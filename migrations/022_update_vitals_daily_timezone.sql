-- Migration 014: Sleep Stage Percentages
--
-- Developer Notes:
-- This migration enhances the `vitals_daily` view to compute advanced, clinically relevant
-- sleep metrics from granular Health Connect data (`SleepSessionRecord` and its nested stages).
-- 
-- The following metrics are added:
-- 1. `waso_mins` (Wake After Sleep Onset): The total minutes spent awake *strictly between* 
--    falling asleep for the first time and waking up for the final time.
-- 2. `awakenings_count`: The number of times the patient transitioned to an "awake" or 
--    "out of bed" stage during the night.
-- 3. `sleep_latency_mins`: The time it took to fall asleep (difference between getting into 
--    bed and the first actual sleep stage).
-- 4. `sleep_efficiency_pct`: The percentage of time spent in bed actually sleeping. 
--    (Total Sleep Time / Total Time in Bed * 100).
--
-- Note on Stage Integers (Health Connect Standard):
-- 1 = Awake, 2 = Sleeping, 3 = Out of bed, 4 = Light sleep, 5 = Deep sleep, 6 = REM sleep

DROP VIEW IF EXISTS vitals_daily;
CREATE VIEW vitals_daily AS
WITH ranked_sources AS (
    SELECT v.id,
        v.patient_id,
        v.recorded_at,
        v.metric_type,
        v.source,
        v."values",
        v.timezone,
        dense_rank() OVER (
            PARTITION BY v.patient_id, v.metric_type, (date_trunc('day'::text, v.recorded_at AT TIME ZONE COALESCE(v.timezone, 'UTC')))
            ORDER BY COALESCE(
                (SELECT m.priority_rank
                   FROM metric_source_priority m
                  WHERE m.metric_type = v.metric_type AND m.source = v.source),
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
        ranked_sources.timezone,
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
            date_trunc('day'::text, v.recorded_at AT TIME ZONE COALESCE(v.timezone, 'UTC')) AS date,
            v.source,
            SUM((v."values" ->> 'count')::numeric) AS source_total
        FROM vitals_raw v
        WHERE v.metric_type = 'StepsRecord'
          AND v.is_outlier = false
          AND v.source LIKE '%\_phone' ESCAPE '\'
        GROUP BY v.patient_id, date_trunc('day'::text, v.recorded_at AT TIME ZONE COALESCE(v.timezone, 'UTC')), v.source
    ) per_source
    GROUP BY per_source.patient_id, per_source.date
),
hr_samples AS (
    SELECT filtered_raw.patient_id,
        date_trunc('day'::text, ((sample.value ->> 'time'::text))::timestamp with time zone AT TIME ZONE COALESCE(filtered_raw.timezone, 'UTC')) AS date,
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
        date_trunc('day'::text, filtered_raw.recorded_at AT TIME ZONE COALESCE(filtered_raw.timezone, 'UTC')) AS date,
        avg(((filtered_raw."values" ->> 'percentage'::text))::numeric) AS oxygen_sat_avg,
        min(((filtered_raw."values" ->> 'percentage'::text))::numeric) AS oxygen_sat_min
    FROM filtered_raw
    WHERE filtered_raw.metric_type = 'OxygenSaturationRecord'::text
    GROUP BY filtered_raw.patient_id, (date_trunc('day'::text, filtered_raw.recorded_at AT TIME ZONE COALESCE(filtered_raw.timezone, 'UTC')))
),
sleep_stages_raw AS (
    SELECT filtered_raw.patient_id,
        date_trunc('day'::text, ((((stage.value ->> 'end_time'::text))::timestamp with time zone) + interval '12 hours') AT TIME ZONE COALESCE(filtered_raw.timezone, 'UTC')) AS date,
        ((stage.value ->> 'stage'::text))::integer AS stage_type,
        ((stage.value ->> 'start_time'::text))::timestamp with time zone AS start_time,
        ((stage.value ->> 'end_time'::text))::timestamp with time zone AS end_time
    FROM filtered_raw,
        LATERAL jsonb_array_elements((filtered_raw."values" -> 'stages'::text)) stage(value)
    WHERE filtered_raw.metric_type = 'SleepSessionRecord'::text
),
-- Developer Note: We use a gaps-and-islands approach to merge overlapping sleep stages 
-- of the same type. This prevents double-counting if a watch sends duplicate overlapping records.
merged_stage_spans AS (
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
),
-- Calculates total hours spent in each stage type per night
merged_stages AS (
    SELECT patient_id, date, stage_type,
           sum(EXTRACT(epoch FROM (merged_end - merged_start)) / 3600.0) AS duration_hours
    FROM merged_stage_spans
    GROUP BY patient_id, date, stage_type
),
-- Developer Note: Determines the exact timestamps for when the patient first fell asleep 
-- and finally woke up. Stages 2 (Sleeping), 4 (Light), 5 (Deep), and 6 (REM) are sleep stages.
sleep_boundaries AS (
    SELECT patient_id, date,
           MIN(merged_start) FILTER (WHERE stage_type IN (2, 4, 5, 6)) AS sleep_onset,
           MAX(merged_end) FILTER (WHERE stage_type IN (2, 4, 5, 6)) AS final_wakeup
    FROM merged_stage_spans
    GROUP BY patient_id, date
),
-- Computes advanced clinical metrics (WASO and Awakenings Count)
advanced_sleep_metrics AS (
    SELECT ms.patient_id,
           ms.date,
           -- WASO in minutes: Duration of stages 1 (Awake) and 3 (Out of bed) strictly between sleep boundaries
           SUM(EXTRACT(epoch FROM (LEAST(ms.merged_end, b.final_wakeup) - GREATEST(ms.merged_start, b.sleep_onset))) / 60.0) FILTER (
               WHERE ms.stage_type IN (1, 3) 
                 AND ms.merged_end > b.sleep_onset 
                 AND ms.merged_start < b.final_wakeup
           ) AS waso_mins,
           
           -- Awakenings count: Number of times they woke up between sleep boundaries
           COUNT(*) FILTER (
               WHERE ms.stage_type IN (1, 3)
                 AND ms.merged_end > b.sleep_onset 
                 AND ms.merged_start < b.final_wakeup
           ) AS awakenings_count,
           COUNT(*) FILTER (
               WHERE ms.stage_type IN (1, 3)
                 AND ms.merged_end > b.sleep_onset 
                 AND ms.merged_start < b.final_wakeup
                 AND EXTRACT(epoch FROM (ms.merged_end - ms.merged_start)) >= 300
           ) AS awakenings_count_greater_than_5mins,
           
           b.sleep_onset,
           b.final_wakeup
    FROM merged_stage_spans ms
    JOIN sleep_boundaries b ON ms.patient_id = b.patient_id AND ms.date = b.date
    GROUP BY ms.patient_id, ms.date, b.sleep_onset, b.final_wakeup
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
        date_trunc('day'::text, filtered_raw.recorded_at AT TIME ZONE COALESCE(filtered_raw.timezone, 'UTC')) AS date,
        sum(CASE WHEN (filtered_raw.metric_type = 'StepsRecord'::text) THEN ((filtered_raw."values" ->> 'count'::text))::numeric ELSE (0)::numeric END) AS total_steps,
        sum(CASE WHEN (filtered_raw.metric_type = 'DistanceRecord'::text) THEN ((filtered_raw."values" ->> 'distanceMeters'::text))::numeric ELSE (0)::numeric END) AS distance_meters,
        sum(CASE WHEN (filtered_raw.metric_type = 'ActiveCaloriesBurnedRecord'::text) THEN ((filtered_raw."values" ->> 'energyKcal'::text))::numeric ELSE (0)::numeric END) AS active_calories,
        avg(CASE WHEN (filtered_raw.metric_type = 'BodyTemperatureRecord'::text) THEN ((filtered_raw."values" ->> 'temperatureCelsius'::text))::numeric ELSE NULL::numeric END) AS body_temp_avg,
        avg(CASE WHEN (filtered_raw.metric_type = 'RespiratoryRateRecord'::text) THEN ((filtered_raw."values" ->> 'rate'::text))::numeric ELSE NULL::numeric END) AS respiratory_rate_avg,
        sum(CASE WHEN (filtered_raw.metric_type = 'AudioSensorRecord'::text) THEN ((filtered_raw."values" ->> 'cough_count'::text))::numeric ELSE NULL::numeric END) AS cough_count_night,
        sum(CASE WHEN (filtered_raw.metric_type = 'AudioSensorRecord'::text) THEN ((filtered_raw."values" ->> 'snore_events'::text))::numeric ELSE NULL::numeric END) AS snoring_events_count,
        avg(CASE WHEN (filtered_raw.metric_type = 'GyroscopeMobilityRecord'::text) THEN ((filtered_raw."values" ->> 'sit_to_stand_duration'::text))::numeric ELSE NULL::numeric END) AS sit_to_stand_seconds
    FROM filtered_raw
    WHERE (filtered_raw.metric_type = ANY (ARRAY['StepsRecord'::text, 'DistanceRecord'::text, 'ActiveCaloriesBurnedRecord'::text, 'SleepSessionRecord'::text, 'BodyTemperatureRecord'::text, 'RespiratoryRateRecord'::text, 'AudioSensorRecord'::text, 'GyroscopeMobilityRecord'::text]))
    GROUP BY filtered_raw.patient_id, (date_trunc('day'::text, filtered_raw.recorded_at AT TIME ZONE COALESCE(filtered_raw.timezone, 'UTC')))
),
sleep_sessions AS (
    SELECT filtered_raw.patient_id,
        date_trunc('day'::text, ((((filtered_raw."values" ->> 'end_time'::text))::timestamp with time zone) + interval '12 hours') AT TIME ZONE COALESCE(filtered_raw.timezone, 'UTC')) AS date,
        ((filtered_raw."values" ->> 'start_time'::text))::timestamp with time zone AS start_time,
        ((filtered_raw."values" ->> 'end_time'::text))::timestamp with time zone AS end_time
    FROM filtered_raw
    WHERE (filtered_raw.metric_type = 'SleepSessionRecord'::text)
),
merged_sleep AS (
    SELECT s3.patient_id,
        s3.date,
        -- Total time in bed (TIB) in hours
        sum((EXTRACT(epoch FROM (s3.merged_end - s3.merged_start)) / 3600.0)) AS sleep_hours,
        -- The absolute start and end times of the entire session
        min(s3.merged_start) AS session_start,
        max(s3.merged_end) AS session_end
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
sleep_hr_samples AS (
    SELECT s_1.patient_id,
        s_1.date,
        h_1.sample_time,
        h_1.bpm
    FROM sleep_sessions s_1
    JOIN hr_samples h_1 ON (
        s_1.patient_id = h_1.patient_id 
        AND h_1.sample_time >= s_1.start_time 
        AND h_1.sample_time <= s_1.end_time
    )
),
rolling_hr AS (
    SELECT patient_id,
        date,
        bpm,
        avg(bpm) OVER (
            PARTITION BY patient_id, date 
            ORDER BY sample_time 
            RANGE BETWEEN INTERVAL '5 minutes' PRECEDING AND CURRENT ROW
        ) AS roll_avg_5m
    FROM sleep_hr_samples
),
resting_hr AS (
    SELECT patient_id,
        date,
        min(roll_avg_5m) AS resting_heart_rate_calculated,
        max(bpm) AS sleep_max_heart_rate
    FROM rolling_hr
    GROUP BY patient_id, date
),
speed_samples AS (
    SELECT filtered_raw.patient_id,
        date_trunc('day'::text, ((sample.value ->> 'time'::text))::timestamp with time zone AT TIME ZONE COALESCE(filtered_raw.timezone, 'UTC')) AS date,
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
),
hrr_daily AS (
    SELECT filtered_raw.patient_id,
        date_trunc('day'::text, filtered_raw.recorded_at AT TIME ZONE COALESCE(filtered_raw.timezone, 'UTC')) AS date,
        jsonb_agg(jsonb_build_object('bpm', ((filtered_raw."values" ->> 'heart_rate_recovery_bpm'::text))::integer)) AS heart_rate_recovery_calculated
    FROM filtered_raw
    WHERE filtered_raw.metric_type = 'HeartRateRecoveryRecord'::text
    GROUP BY filtered_raw.patient_id, (date_trunc('day'::text, filtered_raw.recorded_at AT TIME ZONE COALESCE(filtered_raw.timezone, 'UTC')))
)
SELECT COALESCE(o.patient_id, h.patient_id, ox.patient_id, s.patient_id, r.patient_id, sp.patient_id, ms.patient_id, spf.patient_id, hrr.patient_id) AS patient_id,
    COALESCE(o.date, h.date, ox.date, s.date, r.date, sp.date, ms.date, spf.date, hrr.date) AS date,
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
    o.sit_to_stand_seconds,
    hrr.heart_rate_recovery_calculated,

    -- --- NEW ADVANCED SLEEP METRICS ---
    -- Must be at the end of the view to satisfy Postgres CREATE OR REPLACE rules
    CASE WHEN s.patient_id IS NOT NULL THEN COALESCE(adv.waso_mins, 0) ELSE NULL END AS waso_mins,
    CASE WHEN s.patient_id IS NOT NULL THEN COALESCE(adv.awakenings_count, 0) ELSE NULL END AS awakenings_count,
    CASE WHEN s.patient_id IS NOT NULL THEN COALESCE(adv.awakenings_count_greater_than_5mins, 0) ELSE NULL END AS awakenings_count_greater_than_5mins,
    -- Sleep Latency: Time between getting into bed and actual sleep onset.
    -- If it's exactly 0, it means the wearable didn't record an 'awake in bed' stage (auto-detected sleep). 
    -- We treat exactly 0 as NULL (missing data) to prevent skewing averages and false positives.
    NULLIF(GREATEST(0, EXTRACT(epoch FROM (adv.sleep_onset - ms.session_start)) / 60.0), 0) AS sleep_latency_mins,
    -- Sleep Efficiency: (Total Time Asleep / Total Time in Bed) * 100
    -- Time Asleep = Sum of stages 2 (General), 4 (Light), 5 (Deep), 6 (REM)
    CASE 
        WHEN ms.sleep_hours > 0 AND s.patient_id IS NOT NULL THEN 
            ((COALESCE(s.sleep_stage_2_hours, 0) + COALESCE(s.sleep_stage_4_hours, 0) + COALESCE(s.sleep_stage_5_hours, 0) + COALESCE(s.sleep_stage_6_hours, 0)) 
            / ms.sleep_hours) * 100.0
        ELSE NULL
    END AS sleep_efficiency_pct,
    
    -- --- SLEEP STAGE PERCENTAGES ---
    CASE WHEN ms.sleep_hours > 0 AND s.patient_id IS NOT NULL THEN (COALESCE(s.sleep_stage_1_hours, 0) / ms.sleep_hours) * 100.0 ELSE NULL END AS sleep_stage_1_pct,
    CASE WHEN ms.sleep_hours > 0 AND s.patient_id IS NOT NULL THEN (COALESCE(s.sleep_stage_2_hours, 0) / ms.sleep_hours) * 100.0 ELSE NULL END AS sleep_stage_2_pct,
    CASE WHEN ms.sleep_hours > 0 AND s.patient_id IS NOT NULL THEN (COALESCE(s.sleep_stage_3_hours, 0) / ms.sleep_hours) * 100.0 ELSE NULL END AS sleep_stage_3_pct,
    CASE WHEN ms.sleep_hours > 0 AND s.patient_id IS NOT NULL THEN (COALESCE(s.sleep_stage_4_hours, 0) / ms.sleep_hours) * 100.0 ELSE NULL END AS sleep_stage_4_pct,
    CASE WHEN ms.sleep_hours > 0 AND s.patient_id IS NOT NULL THEN (COALESCE(s.sleep_stage_5_hours, 0) / ms.sleep_hours) * 100.0 ELSE NULL END AS sleep_stage_5_pct,
    CASE WHEN ms.sleep_hours > 0 AND s.patient_id IS NOT NULL THEN (COALESCE(s.sleep_stage_6_hours, 0) / ms.sleep_hours) * 100.0 ELSE NULL END AS sleep_stage_6_pct
FROM (((((((other_metrics o
    FULL JOIN hr_daily h ON (((o.patient_id = h.patient_id) AND (o.date = h.date))))
    FULL JOIN oxy_daily ox ON (((COALESCE(o.patient_id, h.patient_id) = ox.patient_id) AND (COALESCE(o.date, h.date) = ox.date))))
    FULL JOIN sleep_daily s ON (((COALESCE(o.patient_id, h.patient_id, ox.patient_id) = s.patient_id) AND (COALESCE(o.date, h.date, ox.date) = s.date))))
    FULL JOIN resting_hr r ON (((COALESCE(o.patient_id, h.patient_id, ox.patient_id, s.patient_id) = r.patient_id) AND (COALESCE(o.date, h.date, ox.date, s.date) = r.date))))
    FULL JOIN speed_daily sp ON (((COALESCE(o.patient_id, h.patient_id, ox.patient_id, s.patient_id, r.patient_id) = sp.patient_id) AND (COALESCE(o.date, h.date, ox.date, s.date, r.date) = sp.date))))
    FULL JOIN merged_sleep ms ON (((COALESCE(o.patient_id, h.patient_id, ox.patient_id, s.patient_id, r.patient_id, sp.patient_id) = ms.patient_id) AND (COALESCE(o.date, h.date, ox.date, s.date, r.date, sp.date) = ms.date))))
    FULL JOIN advanced_sleep_metrics adv ON (((COALESCE(o.patient_id, h.patient_id, ox.patient_id, s.patient_id, r.patient_id, sp.patient_id, ms.patient_id) = adv.patient_id) AND (COALESCE(o.date, h.date, ox.date, s.date, r.date, sp.date, ms.date) = adv.date))))
    FULL JOIN steps_phone_fallback spf ON (((COALESCE(o.patient_id, h.patient_id, ox.patient_id, s.patient_id, r.patient_id, sp.patient_id, ms.patient_id, adv.patient_id) = spf.patient_id) AND (COALESCE(o.date, h.date, ox.date, s.date, r.date, sp.date, ms.date, adv.date) = spf.date)))
    FULL JOIN hrr_daily hrr ON (((COALESCE(o.patient_id, h.patient_id, ox.patient_id, s.patient_id, r.patient_id, sp.patient_id, ms.patient_id, adv.patient_id, spf.patient_id) = hrr.patient_id) AND (COALESCE(o.date, h.date, ox.date, s.date, r.date, sp.date, ms.date, adv.date, spf.date) = hrr.date)));
