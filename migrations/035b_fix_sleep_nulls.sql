-- Migration 035b: Fix sleep columns to be NULL when no sleep session occurs in an hour

-- 1. Remove DEFAULT 0 from sleep columns
ALTER TABLE vitals_hourly ALTER COLUMN sleep_stage_1_hours DROP DEFAULT;
ALTER TABLE vitals_hourly ALTER COLUMN sleep_stage_2_hours DROP DEFAULT;
ALTER TABLE vitals_hourly ALTER COLUMN sleep_stage_3_hours DROP DEFAULT;
ALTER TABLE vitals_hourly ALTER COLUMN sleep_stage_4_hours DROP DEFAULT;
ALTER TABLE vitals_hourly ALTER COLUMN sleep_stage_5_hours DROP DEFAULT;
ALTER TABLE vitals_hourly ALTER COLUMN sleep_stage_6_hours DROP DEFAULT;
ALTER TABLE vitals_hourly ALTER COLUMN sleep_hours DROP DEFAULT;

-- 2. Update existing rows where sleep_hours = 0 to NULL
UPDATE vitals_hourly
SET sleep_stage_1_hours = NULL,
    sleep_stage_2_hours = NULL,
    sleep_stage_3_hours = NULL,
    sleep_stage_4_hours = NULL,
    sleep_stage_5_hours = NULL,
    sleep_stage_6_hours = NULL,
    sleep_hours = NULL
WHERE sleep_hours = 0;

-- 3. Replace recalculate_vitals_hourly function to write NULL for sleep when no session exists
CREATE OR REPLACE FUNCTION recalculate_vitals_hourly(
    p_patient_id UUID DEFAULT NULL,
    p_start_time TIMESTAMPTZ DEFAULT NULL,
    p_end_time TIMESTAMPTZ DEFAULT NULL
)
RETURNS INTEGER AS $$
DECLARE
    rows_affected INTEGER := 0;
BEGIN
    WITH 
    raw_steps AS (
        SELECT 
            v.patient_id,
            date_trunc('hour', v.recorded_at) AS hour_start,
            v.source,
            SUM((v."values" ->> 'count')::numeric) AS source_steps,
            COALESCE(
                (SELECT m.priority_rank FROM metric_source_priority m WHERE m.metric_type = 'StepsRecord' AND m.source = v.source),
                CASE 
                    WHEN v.source LIKE '%\_watch' ESCAPE '\' THEN 5
                    WHEN v.source LIKE '%\_phone' ESCAPE '\' THEN 50
                    ELSE 9999
                END
            ) AS priority_rank
        FROM vitals_raw v
        WHERE v.metric_type = 'StepsRecord'
          AND v.is_outlier = false
          AND (p_patient_id IS NULL OR v.patient_id = p_patient_id)
          AND (p_start_time IS NULL OR v.recorded_at >= p_start_time)
          AND (p_end_time IS NULL OR v.recorded_at <= p_end_time)
          AND (
              CASE 
                  WHEN v."values" ? 'duration_seconds' THEN 
                      (v."values" ->> 'duration_seconds')::numeric <= 3600
                  ELSE 
                      NOT (v.source LIKE '%shealth%')
              END
          )
        GROUP BY v.patient_id, date_trunc('hour', v.recorded_at), v.source
    ),
    ranked_steps AS (
        SELECT 
            rs.patient_id,
            rs.hour_start,
            rs.source,
            rs.source_steps,
            ROW_NUMBER() OVER (
                PARTITION BY rs.patient_id, rs.hour_start
                ORDER BY rs.priority_rank ASC, rs.source_steps DESC
            ) AS rk
        FROM raw_steps rs
    ),
    winning_steps AS (
        SELECT 
            patient_id,
            hour_start,
            source_steps::bigint AS total_steps,
            source
        FROM ranked_steps
        WHERE rk = 1
    ),
    hr_samples AS (
        SELECT 
            v.patient_id,
            date_trunc('hour', ((sample.value ->> 'time')::timestamptz)) AS hour_start,
            ((sample.value ->> 'bpm')::numeric) AS bpm
        FROM vitals_raw v,
             LATERAL jsonb_array_elements((v."values" -> 'samples')) sample(value)
        WHERE v.metric_type = 'HeartRateRecord'
          AND v.is_outlier = false
          AND (p_patient_id IS NULL OR v.patient_id = p_patient_id)
          AND (p_start_time IS NULL OR v.recorded_at >= p_start_time)
          AND (p_end_time IS NULL OR v.recorded_at <= p_end_time)
    ),
    hr_hourly AS (
        SELECT 
            patient_id,
            hour_start,
            ROUND(AVG(bpm), 1) AS avg_heart_rate
        FROM hr_samples
        GROUP BY patient_id, hour_start
    ),
    other_hourly AS (
        SELECT 
            v.patient_id,
            date_trunc('hour', v.recorded_at) AS hour_start,
            SUM(CASE WHEN v.metric_type = 'DistanceRecord' THEN ((v."values" ->> 'distanceMeters')::numeric) ELSE 0 END) AS distance_meters,
            SUM(CASE WHEN v.metric_type = 'ActiveCaloriesBurnedRecord' THEN ((v."values" ->> 'energyKcal')::numeric) ELSE 0 END) AS active_calories
        FROM vitals_raw v
        WHERE v.metric_type IN ('DistanceRecord', 'ActiveCaloriesBurnedRecord')
          AND v.is_outlier = false
          AND (p_patient_id IS NULL OR v.patient_id = p_patient_id)
          AND (p_start_time IS NULL OR v.recorded_at >= p_start_time)
          AND (p_end_time IS NULL OR v.recorded_at <= p_end_time)
        GROUP BY v.patient_id, date_trunc('hour', v.recorded_at)
    ),
    sleep_stages_hourly AS (
        SELECT 
            v.patient_id,
            date_trunc('hour', ((stage.value ->> 'start_time')::timestamptz)) AS hour_start,
            SUM(CASE WHEN (stage.value ->> 'stage')::integer = 1 THEN EXTRACT(epoch FROM (((stage.value ->> 'end_time')::timestamptz) - ((stage.value ->> 'start_time')::timestamptz))) / 3600.0 ELSE 0 END) AS sleep_stage_1_hours,
            SUM(CASE WHEN (stage.value ->> 'stage')::integer = 2 THEN EXTRACT(epoch FROM (((stage.value ->> 'end_time')::timestamptz) - ((stage.value ->> 'start_time')::timestamptz))) / 3600.0 ELSE 0 END) AS sleep_stage_2_hours,
            SUM(CASE WHEN (stage.value ->> 'stage')::integer = 3 THEN EXTRACT(epoch FROM (((stage.value ->> 'end_time')::timestamptz) - ((stage.value ->> 'start_time')::timestamptz))) / 3600.0 ELSE 0 END) AS sleep_stage_3_hours,
            SUM(CASE WHEN (stage.value ->> 'stage')::integer = 4 THEN EXTRACT(epoch FROM (((stage.value ->> 'end_time')::timestamptz) - ((stage.value ->> 'start_time')::timestamptz))) / 3600.0 ELSE 0 END) AS sleep_stage_4_hours,
            SUM(CASE WHEN (stage.value ->> 'stage')::integer = 5 THEN EXTRACT(epoch FROM (((stage.value ->> 'end_time')::timestamptz) - ((stage.value ->> 'start_time')::timestamptz))) / 3600.0 ELSE 0 END) AS sleep_stage_5_hours,
            SUM(CASE WHEN (stage.value ->> 'stage')::integer = 6 THEN EXTRACT(epoch FROM (((stage.value ->> 'end_time')::timestamptz) - ((stage.value ->> 'start_time')::timestamptz))) / 3600.0 ELSE 0 END) AS sleep_stage_6_hours,
            SUM(CASE WHEN (stage.value ->> 'stage')::integer IN (2, 4, 5, 6) THEN EXTRACT(epoch FROM (((stage.value ->> 'end_time')::timestamptz) - ((stage.value ->> 'start_time')::timestamptz))) / 3600.0 ELSE 0 END) AS sleep_hours
        FROM vitals_raw v,
             LATERAL jsonb_array_elements((v."values" -> 'stages')) stage(value)
        WHERE v.metric_type = 'SleepSessionRecord'
          AND v.is_outlier = false
          AND (p_patient_id IS NULL OR v.patient_id = p_patient_id)
          AND (p_start_time IS NULL OR v.recorded_at >= p_start_time)
          AND (p_end_time IS NULL OR v.recorded_at <= p_end_time)
        GROUP BY v.patient_id, date_trunc('hour', ((stage.value ->> 'start_time')::timestamptz))
    ),
    combined_keys AS (
        SELECT patient_id, hour_start FROM winning_steps
        UNION
        SELECT patient_id, hour_start FROM hr_hourly
        UNION
        SELECT patient_id, hour_start FROM other_hourly
        UNION
        SELECT patient_id, hour_start FROM sleep_stages_hourly
    )
    INSERT INTO vitals_hourly (
        patient_id,
        hour_start,
        total_steps,
        distance_meters,
        active_calories,
        avg_heart_rate,
        sleep_stage_1_hours,
        sleep_stage_2_hours,
        sleep_stage_3_hours,
        sleep_stage_4_hours,
        sleep_stage_5_hours,
        sleep_stage_6_hours,
        sleep_hours,
        source,
        updated_at
    )
    SELECT 
        k.patient_id,
        k.hour_start,
        COALESCE(ws.total_steps, 0),
        COALESCE(oth.distance_meters, 0),
        COALESCE(oth.active_calories, 0),
        hr.avg_heart_rate,
        slp.sleep_stage_1_hours,
        slp.sleep_stage_2_hours,
        slp.sleep_stage_3_hours,
        slp.sleep_stage_4_hours,
        slp.sleep_stage_5_hours,
        slp.sleep_stage_6_hours,
        slp.sleep_hours,
        ws.source,
        NOW()
    FROM combined_keys k
    LEFT JOIN winning_steps ws ON k.patient_id = ws.patient_id AND k.hour_start = ws.hour_start
    LEFT JOIN hr_hourly hr ON k.patient_id = hr.patient_id AND k.hour_start = hr.hour_start
    LEFT JOIN other_hourly oth ON k.patient_id = oth.patient_id AND k.hour_start = oth.hour_start
    LEFT JOIN sleep_stages_hourly slp ON k.patient_id = slp.patient_id AND k.hour_start = slp.hour_start
    ON CONFLICT (patient_id, hour_start) DO UPDATE SET
        total_steps = EXCLUDED.total_steps,
        distance_meters = EXCLUDED.distance_meters,
        active_calories = EXCLUDED.active_calories,
        avg_heart_rate = EXCLUDED.avg_heart_rate,
        sleep_stage_1_hours = EXCLUDED.sleep_stage_1_hours,
        sleep_stage_2_hours = EXCLUDED.sleep_stage_2_hours,
        sleep_stage_3_hours = EXCLUDED.sleep_stage_3_hours,
        sleep_stage_4_hours = EXCLUDED.sleep_stage_4_hours,
        sleep_stage_5_hours = EXCLUDED.sleep_stage_5_hours,
        sleep_stage_6_hours = EXCLUDED.sleep_stage_6_hours,
        sleep_hours = EXCLUDED.sleep_hours,
        source = COALESCE(EXCLUDED.source, vitals_hourly.source),
        updated_at = NOW();

    GET DIAGNOSTICS rows_affected = ROW_COUNT;
    RETURN rows_affected;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;
