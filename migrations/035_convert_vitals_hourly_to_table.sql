-- Migration 035: Convert vitals_hourly from dynamic VIEW to indexed physical TABLE
-- Preserves all existing columns: total_steps, distance_meters, active_calories,
-- avg_heart_rate, sleep_stage_1-6_hours, sleep_hours, plus adds source tracking.
-- Implements vendor-agnostic interval filtering to exclude multi-hour/daily rollups.

-- Step 1: Drop old view
DROP VIEW IF EXISTS vitals_hourly CASCADE;

-- Step 2: Create physical table vitals_hourly
CREATE TABLE IF NOT EXISTS vitals_hourly (
    patient_id UUID NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    hour_start TIMESTAMPTZ NOT NULL,
    total_steps BIGINT DEFAULT 0,
    distance_meters NUMERIC DEFAULT 0,
    active_calories NUMERIC DEFAULT 0,
    avg_heart_rate NUMERIC,
    sleep_stage_1_hours NUMERIC,
    sleep_stage_2_hours NUMERIC,
    sleep_stage_3_hours NUMERIC,
    sleep_stage_4_hours NUMERIC,
    sleep_stage_5_hours NUMERIC,
    sleep_stage_6_hours NUMERIC,
    sleep_hours NUMERIC,
    source VARCHAR(255),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT pk_vitals_hourly PRIMARY KEY (patient_id, hour_start)
);

-- Step 3: Indexes
CREATE INDEX IF NOT EXISTS idx_vitals_hourly_patient_hour 
ON vitals_hourly (patient_id, hour_start DESC);

-- Step 4: Row Level Security (RLS)
ALTER TABLE vitals_hourly ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Allow select on vitals_hourly" ON vitals_hourly;
CREATE POLICY "Allow select on vitals_hourly" 
ON vitals_hourly FOR SELECT 
TO authenticated, anon 
USING (true);

DROP POLICY IF EXISTS "Allow service role all on vitals_hourly" ON vitals_hourly;
CREATE POLICY "Allow service role all on vitals_hourly" 
ON vitals_hourly FOR ALL 
TO service_role 
USING (true)
WITH CHECK (true);

-- Step 5: Calculation & Upsert Function
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
    -- 1. Steps Records: Vendor-agnostic duration filter (<= 3600s) + source priority
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
          -- Vendor-agnostic interval filter:
          -- Only include genuine hourly intervals (<= 1 hour)
          -- Exclude 24-hour summary rollups
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
    -- 2. Heart Rate Records
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
    -- 3. Distance & Calories
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
    -- 4. Sleep Stages (Health Connect: 1=Awake, 2=Sleeping, 3=Out of bed, 4=Light, 5=Deep, 6=REM)
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
    -- 5. Combine All Stream Keys
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

-- Step 6: Statement-Level Triggers on vitals_raw
CREATE OR REPLACE FUNCTION trg_fn_sync_vitals_hourly()
RETURNS TRIGGER AS $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN (
        SELECT DISTINCT 
            patient_id, 
            date_trunc('hour', recorded_at) AS v_hour
        FROM new_table
        WHERE is_outlier = false
    ) LOOP
        PERFORM recalculate_vitals_hourly(r.patient_id, r.v_hour - interval '1 hour', r.v_hour + interval '1 hour');
    END LOOP;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

DROP TRIGGER IF EXISTS trg_vitals_raw_refresh_hourly_insert ON vitals_raw;
CREATE TRIGGER trg_vitals_raw_refresh_hourly_insert
AFTER INSERT ON vitals_raw
REFERENCING NEW TABLE AS new_table
FOR EACH STATEMENT
EXECUTE FUNCTION trg_fn_sync_vitals_hourly();

DROP TRIGGER IF EXISTS trg_vitals_raw_refresh_hourly_update ON vitals_raw;
CREATE TRIGGER trg_vitals_raw_refresh_hourly_update
AFTER UPDATE ON vitals_raw
REFERENCING NEW TABLE AS new_table
FOR EACH STATEMENT
EXECUTE FUNCTION trg_fn_sync_vitals_hourly();

-- Step 7: Backfill existing data for all patients (past 30 days)
DO $$
DECLARE
    p_rec RECORD;
BEGIN
    FOR p_rec IN SELECT DISTINCT patient_id FROM vitals_raw LOOP
        PERFORM recalculate_vitals_hourly(p_rec.patient_id, NOW() - interval '30 days', NULL);
    END LOOP;
END $$;
