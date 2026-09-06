-- Migration 008: Noon-to-Noon Sleep Aggregation and Stage Overlap Prevention
-- Problem: Sleep records were grouped by `recorded_at`, which caused midnight-crossing sleep sessions to be split into two days.
--          Additionally, while total `sleep_hours` prevented double-counting using a gaps-and-islands approach, individual
--          `sleep_stages` (Light, Deep, etc.) simply summed up raw records, causing double-counting when overlapping data existed.
-- Fix:     1. Redefine sleep "date" for both sessions and stages as `end_time - 12 hours` (Noon-to-Noon window).
--          2. Introduce `merged_stages` CTE to perform the exact same gaps-and-islands overlap merging on EACH `stage_type` before pivoting.

CREATE OR REPLACE VIEW vitals_daily AS
WITH ranked_sources AS (
    SELECT v.id,
        v.patient_id,
        v.recorded_at,
        v.metric_type,
        v.source,
        v."values",
        dense_rank() OVER (
            PARTITION BY v.patient_id, v.metric_type, (date_trunc('day'::text, v.recorded_at))
            ORDER BY COALESCE(
                (SELECT m.priority_rank
                   FROM metric_source_priority m
                  WHERE m.metric_type = v.metric_type AND m.source = v.source),
                -- Wildcard fallback for unrecognised sources based on device suffix
                CASE
                    WHEN v.source LIKE '%\_watch' ESCAPE '\' THEN 5
                    WHEN v.source LIKE '%\_phone' ESCAPE '\' THEN 50
                    ELSE 9999
                END)
        ) AS rk
    FROM vitals_raw v
    WHERE v.is_outlier = false
),
filtered_raw AS (
    SELECT DISTINCT ON (ranked_sources.patient_id, ranked_sources.metric_type, ranked_sources.recorded_at, ranked_sources.source)
        ranked_sources.id,
        ranked_sources.patient_id,
        ranked_sources.recorded_at,
        ranked_sources.metric_type,
        ranked_sources.source,
        ranked_sources."values",
        ranked_sources.rk
    FROM ranked_sources
    WHERE ranked_sources.rk = 1
    ORDER BY ranked_sources.patient_id, ranked_sources.metric_type, ranked_sources.recorded_at, ranked_sources.source, ranked_sources.id DESC
),
steps_phone_fallback AS (
    SELECT
        per_source.patient_id,
        per_source.date,
        MAX(per_source.source_total) AS phone_steps
    FROM (
        SELECT
            v.patient_id,
            date_trunc('day'::text, v.recorded_at) AS date,
            v.source,
            SUM((v."values" ->> 'count')::numeric) AS source_total
        FROM vitals_raw v
        WHERE v.metric_type = 'StepsRecord'
          AND v.is_outlier = false
          AND v.source LIKE '%\_phone' ESCAPE '\'
        GROUP BY v.patient_id, date_trunc('day'::text, v.recorded_at), v.source
    ) per_source
    GROUP BY per_source.patient_id, per_source.date
),
hr_samples AS (
    SELECT filtered_raw.patient_id,
        date_trunc('day'::text, ((sample.value ->> 'time'::text))::timestamp with time zone) AS date,
        ((sample.value ->> 'time'::text))::timestamp with time zone AS sample_time,
        ((sample.value ->> 'bpm'::text))::numeric AS bpm
    FROM filtered_raw,
        LATERAL jsonb_array_elements((filtered_raw."values" -> 'samples'::text)) sample(value)
    WHERE filtered_raw.metric_type = 'HeartRateRecord'::text
),
hr_daily AS (
    SELECT hr_samples.patient_id,
        hr_samples.date,
        avg(hr_samples.bpm) AS avg_heart_rate,
        max(hr_samples.bpm) AS max_heart_rate,
        min(hr_samples.bpm) AS min_heart_rate
    FROM hr_samples
    GROUP BY hr_samples.patient_id, hr_samples.date
),
oxy_daily AS (
    SELECT filtered_raw.patient_id,
        date_trunc('day'::text, filtered_raw.recorded_at) AS date,
        avg(((filtered_raw."values" ->> 'percentage'::text))::numeric) AS oxygen_sat_avg,
        min(((filtered_raw."values" ->> 'percentage'::text))::numeric) AS oxygen_sat_min
    FROM filtered_raw
    WHERE filtered_raw.metric_type = 'OxygenSaturationRecord'::text
    GROUP BY filtered_raw.patient_id, (date_trunc('day'::text, filtered_raw.recorded_at))
),
sleep_stages_raw AS (
    SELECT filtered_raw.patient_id,
        date_trunc('day'::text, ((((stage.value ->> 'end_time'::text))::timestamp with time zone) + interval '12 hours')) AS date,
        ((stage.value ->> 'stage'::text))::integer AS stage_type,
        ((stage.value ->> 'start_time'::text))::timestamp with time zone AS start_time,
        ((stage.value ->> 'end_time'::text))::timestamp with time zone AS end_time
    FROM filtered_raw,
        LATERAL jsonb_array_elements((filtered_raw."values" -> 'stages'::text)) stage(value)
    WHERE filtered_raw.metric_type = 'SleepSessionRecord'::text
),
merged_stages AS (
    SELECT s3.patient_id,
        s3.date,
        s3.stage_type,
        sum((EXTRACT(epoch FROM (s3.merged_end - s3.merged_start)) / 3600.0)) AS duration_hours
    FROM (
        SELECT s2.patient_id, s2.date, s2.stage_type, s2.grp,
            min(s2.start_time) AS merged_start,
            max(s2.end_time) AS merged_end
        FROM (
            SELECT s1.patient_id, s1.date, s1.stage_type, s1.start_time, s1.end_time,
                sum(CASE WHEN ((s1.prev_max_end IS NULL) OR (s1.start_time > s1.prev_max_end)) THEN 1 ELSE 0 END)
                    OVER (PARTITION BY s1.patient_id, s1.date, s1.stage_type ORDER BY s1.start_time, s1.end_time) AS grp
            FROM (
                SELECT ss.patient_id, ss.date, ss.stage_type, ss.start_time, ss.end_time,
                    max(ss.end_time) OVER (
                        PARTITION BY ss.patient_id, ss.date, ss.stage_type
                        ORDER BY ss.start_time, ss.end_time
                        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                    ) AS prev_max_end
                FROM sleep_stages_raw ss
            ) s1
        ) s2
        GROUP BY s2.patient_id, s2.date, s2.stage_type, s2.grp
    ) s3
    GROUP BY s3.patient_id, s3.date, s3.stage_type
),
sleep_daily AS (
    SELECT merged_stages.patient_id,
        merged_stages.date,
        sum(CASE WHEN (merged_stages.stage_type = 1) THEN merged_stages.duration_hours ELSE (0)::numeric END) AS sleep_stage_1_hours,
        sum(CASE WHEN (merged_stages.stage_type = 2) THEN merged_stages.duration_hours ELSE (0)::numeric END) AS sleep_stage_2_hours,
        sum(CASE WHEN (merged_stages.stage_type = 3) THEN merged_stages.duration_hours ELSE (0)::numeric END) AS sleep_stage_3_hours,
        sum(CASE WHEN (merged_stages.stage_type = 4) THEN merged_stages.duration_hours ELSE (0)::numeric END) AS sleep_stage_4_hours,
        sum(CASE WHEN (merged_stages.stage_type = 5) THEN merged_stages.duration_hours ELSE (0)::numeric END) AS sleep_stage_5_hours,
        sum(CASE WHEN (merged_stages.stage_type = 6) THEN merged_stages.duration_hours ELSE (0)::numeric END) AS sleep_stage_6_hours
    FROM merged_stages
    GROUP BY merged_stages.patient_id, merged_stages.date
),
other_metrics AS (
    SELECT filtered_raw.patient_id,
        date_trunc('day'::text, filtered_raw.recorded_at) AS date,
        sum(CASE WHEN (filtered_raw.metric_type = 'StepsRecord'::text) THEN ((filtered_raw."values" ->> 'count'::text))::numeric ELSE (0)::numeric END) AS total_steps,
        sum(CASE WHEN (filtered_raw.metric_type = 'DistanceRecord'::text) THEN ((filtered_raw."values" ->> 'distanceMeters'::text))::numeric ELSE (0)::numeric END) AS distance_meters,
        sum(CASE WHEN (filtered_raw.metric_type = 'ActiveCaloriesBurnedRecord'::text) THEN ((filtered_raw."values" ->> 'energyKcal'::text))::numeric ELSE (0)::numeric END) AS active_calories,
        avg(CASE WHEN (filtered_raw.metric_type = 'BodyTemperatureRecord'::text) THEN ((filtered_raw."values" ->> 'temperatureCelsius'::text))::numeric ELSE NULL::numeric END) AS body_temp_avg,
        avg(CASE WHEN (filtered_raw.metric_type = 'RespiratoryRateRecord'::text) THEN ((filtered_raw."values" ->> 'rate'::text))::numeric ELSE NULL::numeric END) AS respiratory_rate_avg,
        sum(CASE WHEN (filtered_raw.metric_type = 'AudioSensorRecord'::text) THEN ((filtered_raw."values" ->> 'cough_count'::text))::numeric ELSE (0)::numeric END) AS cough_count_night,
        sum(CASE WHEN (filtered_raw.metric_type = 'AudioSensorRecord'::text) THEN ((filtered_raw."values" ->> 'snore_events'::text))::numeric ELSE (0)::numeric END) AS snoring_events_count,
        avg(CASE WHEN (filtered_raw.metric_type = 'GyroscopeMobilityRecord'::text) THEN ((filtered_raw."values" ->> 'sit_to_stand_duration'::text))::numeric ELSE NULL::numeric END) AS sit_to_stand_seconds
    FROM filtered_raw
    WHERE (filtered_raw.metric_type = ANY (ARRAY['StepsRecord'::text, 'DistanceRecord'::text, 'ActiveCaloriesBurnedRecord'::text, 'SleepSessionRecord'::text, 'BodyTemperatureRecord'::text, 'RespiratoryRateRecord'::text, 'AudioSensorRecord'::text, 'GyroscopeMobilityRecord'::text]))
    GROUP BY filtered_raw.patient_id, (date_trunc('day'::text, filtered_raw.recorded_at))
),
sleep_sessions AS (
    SELECT filtered_raw.patient_id,
        date_trunc('day'::text, ((((filtered_raw."values" ->> 'end_time'::text))::timestamp with time zone) + interval '12 hours')) AS date,
        ((filtered_raw."values" ->> 'start_time'::text))::timestamp with time zone AS start_time,
        ((filtered_raw."values" ->> 'end_time'::text))::timestamp with time zone AS end_time
    FROM filtered_raw
    WHERE (filtered_raw.metric_type = 'SleepSessionRecord'::text)
),
merged_sleep AS (
    SELECT s3.patient_id,
        s3.date,
        sum((EXTRACT(epoch FROM (s3.merged_end - s3.merged_start)) / 3600.0)) AS sleep_hours
    FROM (
        SELECT s2.patient_id, s2.date, s2.grp,
            min(s2.start_time) AS merged_start,
            max(s2.end_time) AS merged_end
        FROM (
            SELECT s1.patient_id, s1.date, s1.start_time, s1.end_time,
                sum(CASE WHEN ((s1.prev_max_end IS NULL) OR (s1.start_time > s1.prev_max_end)) THEN 1 ELSE 0 END)
                    OVER (PARTITION BY s1.patient_id, s1.date ORDER BY s1.start_time, s1.end_time) AS grp
            FROM (
                SELECT sleep_sessions.patient_id, sleep_sessions.date,
                    sleep_sessions.start_time, sleep_sessions.end_time,
                    max(sleep_sessions.end_time) OVER (
                        PARTITION BY sleep_sessions.patient_id, sleep_sessions.date
                        ORDER BY sleep_sessions.start_time, sleep_sessions.end_time
                        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                    ) AS prev_max_end
                FROM sleep_sessions
            ) s1
        ) s2
        GROUP BY s2.patient_id, s2.date, s2.grp
    ) s3
    GROUP BY s3.patient_id, s3.date
),
resting_hr AS (
    SELECT s_1.patient_id,
        s_1.date,
        avg(h_1.bpm) AS resting_heart_rate_calculated,
        max(h_1.bpm) AS sleep_max_heart_rate
    FROM (sleep_sessions s_1
        JOIN hr_samples h_1 ON (((s_1.patient_id = h_1.patient_id) AND (h_1.sample_time >= s_1.start_time) AND (h_1.sample_time <= s_1.end_time))))
    GROUP BY s_1.patient_id, s_1.date
),
speed_samples AS (
    SELECT filtered_raw.patient_id,
        date_trunc('day'::text, ((sample.value ->> 'time'::text))::timestamp with time zone) AS date,
        ((sample.value ->> 'speedMetersPerSec'::text))::numeric AS speed
    FROM filtered_raw,
        LATERAL jsonb_array_elements((filtered_raw."values" -> 'samples'::text)) sample(value)
    WHERE (filtered_raw.metric_type = 'SpeedRecord'::text)
),
speed_daily AS (
    SELECT speed_samples.patient_id,
        speed_samples.date,
        avg(speed_samples.speed) AS avg_speed
    FROM speed_samples
    GROUP BY speed_samples.patient_id, speed_samples.date
)
SELECT COALESCE(o.patient_id, h.patient_id, ox.patient_id, s.patient_id, r.patient_id, sp.patient_id, ms.patient_id, spf.patient_id) AS patient_id,
    COALESCE(o.date, h.date, ox.date, s.date, r.date, sp.date, ms.date, spf.date) AS date,
    h.avg_heart_rate,
    h.max_heart_rate,
    h.min_heart_rate,
    GREATEST(COALESCE(o.total_steps, (0)::numeric), COALESCE(spf.phone_steps, (0)::numeric)) AS total_steps,
    COALESCE(o.distance_meters, (0)::numeric) AS distance_meters,
    COALESCE(o.active_calories, (0)::numeric) AS active_calories,
    ms.sleep_hours,
    ox.oxygen_sat_avg,
    ox.oxygen_sat_min,
    s.sleep_stage_1_hours,
    s.sleep_stage_2_hours,
    s.sleep_stage_3_hours,
    s.sleep_stage_4_hours,
    s.sleep_stage_5_hours,
    s.sleep_stage_6_hours,
    r.resting_heart_rate_calculated,
    r.sleep_max_heart_rate,
    o.body_temp_avg,
    o.respiratory_rate_avg,
    sp.avg_speed,
    o.cough_count_night,
    o.snoring_events_count,
    o.sit_to_stand_seconds
FROM ((((((other_metrics o
    FULL JOIN hr_daily h ON (((o.patient_id = h.patient_id) AND (o.date = h.date))))
    FULL JOIN oxy_daily ox ON (((COALESCE(o.patient_id, h.patient_id) = ox.patient_id) AND (COALESCE(o.date, h.date) = ox.date))))
    FULL JOIN sleep_daily s ON (((COALESCE(o.patient_id, h.patient_id, ox.patient_id) = s.patient_id) AND (COALESCE(o.date, h.date, ox.date) = s.date))))
    FULL JOIN resting_hr r ON (((COALESCE(o.patient_id, h.patient_id, ox.patient_id, s.patient_id) = r.patient_id) AND (COALESCE(o.date, h.date, ox.date, s.date) = r.date))))
    FULL JOIN speed_daily sp ON (((COALESCE(o.patient_id, h.patient_id, ox.patient_id, s.patient_id, r.patient_id) = sp.patient_id) AND (COALESCE(o.date, h.date, ox.date, s.date, r.date) = sp.date))))
    FULL JOIN merged_sleep ms ON (((COALESCE(o.patient_id, h.patient_id, ox.patient_id, s.patient_id, r.patient_id, sp.patient_id) = ms.patient_id) AND (COALESCE(o.date, h.date, ox.date, s.date, r.date, sp.date) = ms.date))))
    FULL JOIN steps_phone_fallback spf ON (((COALESCE(o.patient_id, h.patient_id, ox.patient_id, s.patient_id, r.patient_id, sp.patient_id, ms.patient_id) = spf.patient_id) AND (COALESCE(o.date, h.date, ox.date, s.date, r.date, sp.date, ms.date) = spf.date)));
