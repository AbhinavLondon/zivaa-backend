-- Migration 036: Add sleep consistency and sleep onset/wakeup times to vitals_daily
--
-- This migration enhances the physical vitals_daily table by adding:
-- 1. `sleep_onset_time` (TIMESTAMPTZ): Exact timestamp the patient fell asleep
-- 2. `final_wakeup_time` (TIMESTAMPTZ): Exact timestamp the patient woke up
-- 3. `timezone` (VARCHAR): Local timezone of the patient for the day
-- 4. `bedtime_variance_mins` (NUMERIC): 7-day rolling standard deviation of bedtime in minutes
-- 5. `sleep_consistency_pct` (NUMERIC): 0-100 score indicating circadian bedtime regularity
--
-- All changes are strictly additive and preserve all 43 existing metrics.

-- Step 1: Add new columns to vitals_daily table
ALTER TABLE vitals_daily 
ADD COLUMN IF NOT EXISTS sleep_onset_time TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS final_wakeup_time TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS timezone VARCHAR,
ADD COLUMN IF NOT EXISTS bedtime_variance_mins NUMERIC,
ADD COLUMN IF NOT EXISTS sleep_consistency_pct NUMERIC;

-- Step 2: Replace recalculate_vitals_daily with updated calculation & upsert
CREATE OR REPLACE FUNCTION recalculate_vitals_daily(
    p_patient_id UUID DEFAULT NULL,
    p_start_date TIMESTAMP WITHOUT TIME ZONE DEFAULT NULL,
    p_end_date TIMESTAMP WITHOUT TIME ZONE DEFAULT NULL
)
RETURNS INTEGER AS $$
DECLARE
    rows_affected INTEGER := 0;
BEGIN
    -- 1. Main Upsert of daily aggregated metrics
    INSERT INTO vitals_daily (
        patient_id,
        date,
        avg_heart_rate,
        max_heart_rate,
        min_heart_rate,
        hr_avg_morning,
        hr_avg_afternoon,
        hr_avg_evening,
        hr_avg_night,
        total_steps,
        distance_meters,
        active_calories,
        sleep_hours,
        oxygen_sat_avg,
        oxygen_sat_min,
        sleep_stage_1_hours,
        sleep_stage_2_hours,
        sleep_stage_3_hours,
        sleep_stage_4_hours,
        sleep_stage_5_hours,
        sleep_stage_6_hours,
        resting_heart_rate_calculated,
        sleep_max_heart_rate,
        body_temp_avg,
        respiratory_rate_avg,
        avg_speed,
        cough_count_night,
        snoring_events_count,
        sit_to_stand_seconds,
        skin_temperature_delta,
        heart_rate_recovery_calculated,
        waso_mins,
        awakenings_count,
        awakenings_count_greater_than_5mins,
        sleep_latency_mins,
        sleep_efficiency_pct,
        sleep_stage_1_pct,
        sleep_stage_2_pct,
        sleep_stage_3_pct,
        sleep_stage_4_pct,
        sleep_stage_5_pct,
        sleep_stage_6_pct,
        sleep_onset_time,
        final_wakeup_time,
        timezone,
        updated_at
    )
    WITH ranked_sources AS (
         SELECT v.id,
            v.patient_id,
            v.recorded_at,
            v.metric_type,
            v.source,
            v."values",
            v.timezone,
            dense_rank() OVER (PARTITION BY v.patient_id, v.metric_type, (date_trunc('day'::text, (v.recorded_at AT TIME ZONE COALESCE(v.timezone, 'UTC'::character varying)))) ORDER BY COALESCE(( SELECT m.priority_rank
                   FROM metric_source_priority m
                  WHERE ((m.metric_type = v.metric_type) AND (m.source = v.source))),
                CASE
                    WHEN (v.source ~~ like_escape('%\_watch'::text, '\'::text)) THEN 5
                    WHEN (v.source ~~ like_escape('%\_phone'::text, '\'::text)) THEN 50
                    ELSE 9999
                END)) AS rk
           FROM vitals_raw v
          WHERE (v.is_outlier = false)
          AND (p_patient_id IS NULL OR v.patient_id = p_patient_id)
          AND (p_start_date IS NULL OR v.recorded_at >= p_start_date - interval '2 days')
          AND (p_end_date IS NULL OR v.recorded_at <= p_end_date + interval '2 days')
        ), filtered_raw AS (
         SELECT DISTINCT ON (ranked_sources.patient_id, ranked_sources.metric_type, ranked_sources.recorded_at, ranked_sources.source) ranked_sources.id,
            ranked_sources.patient_id,
            ranked_sources.recorded_at,
            ranked_sources.metric_type,
            ranked_sources.source,
            ranked_sources."values",
            ranked_sources.timezone,
            ranked_sources.rk
           FROM ranked_sources
          WHERE (ranked_sources.rk = 1)
          ORDER BY ranked_sources.patient_id, ranked_sources.metric_type, ranked_sources.recorded_at, ranked_sources.source, ranked_sources.id DESC
        ), tz_daily AS (
         SELECT filtered_raw.patient_id,
            date_trunc('day'::text, (filtered_raw.recorded_at AT TIME ZONE COALESCE(filtered_raw.timezone, 'UTC'::character varying))) AS date,
            (array_agg(filtered_raw.timezone) FILTER (WHERE filtered_raw.timezone IS NOT NULL))[1] AS timezone
           FROM filtered_raw
          GROUP BY filtered_raw.patient_id, date_trunc('day'::text, (filtered_raw.recorded_at AT TIME ZONE COALESCE(filtered_raw.timezone, 'UTC'::character varying)))
        ), steps_phone_fallback AS (
         SELECT per_source.patient_id,
            per_source.date,
            max(per_source.source_total) AS phone_steps
           FROM ( SELECT v.patient_id,
                    date_trunc('day'::text, (v.recorded_at AT TIME ZONE COALESCE(v.timezone, 'UTC'::character varying))) AS date,
                    v.source,
                    sum(((v."values" ->> 'count'::text))::numeric) AS source_total
                   FROM vitals_raw v
                  WHERE ((v.metric_type = 'StepsRecord'::text) AND (v.is_outlier = false) AND (v.source ~~ like_escape('%\_phone'::text, '\'::text)))
                  GROUP BY v.patient_id, (date_trunc('day'::text, (v.recorded_at AT TIME ZONE COALESCE(v.timezone, 'UTC'::character varying)))), v.source) per_source
          GROUP BY per_source.patient_id, per_source.date
        ), hr_samples AS (
         SELECT filtered_raw.patient_id,
            date_trunc('day'::text, (((sample.value ->> 'time'::text))::timestamp with time zone AT TIME ZONE COALESCE(filtered_raw.timezone, 'UTC'::character varying))) AS date,
            ((sample.value ->> 'time'::text))::timestamp with time zone AS sample_time,
            ((sample.value ->> 'bpm'::text))::numeric AS bpm
           FROM filtered_raw,
            LATERAL jsonb_array_elements((filtered_raw."values" -> 'samples'::text)) sample(value)
          WHERE (filtered_raw.metric_type = 'HeartRateRecord'::text)
        ), hr_daily AS (
           SELECT hr_samples.patient_id,
              hr_samples.date,
              avg(hr_samples.bpm) AS avg_heart_rate,
              max(hr_samples.bpm) AS max_heart_rate,
              min(hr_samples.bpm) AS min_heart_rate,
              avg(CASE WHEN extract(hour from hr_samples.sample_time) BETWEEN 6 AND 11 THEN hr_samples.bpm END) AS hr_avg_morning,
              avg(CASE WHEN extract(hour from hr_samples.sample_time) BETWEEN 12 AND 17 THEN hr_samples.bpm END) AS hr_avg_afternoon,
              avg(CASE WHEN extract(hour from hr_samples.sample_time) BETWEEN 18 AND 23 THEN hr_samples.bpm END) AS hr_avg_evening,
              avg(CASE WHEN extract(hour from hr_samples.sample_time) BETWEEN 0 AND 5 THEN hr_samples.bpm END) AS hr_avg_night
             FROM hr_samples
            GROUP BY hr_samples.patient_id, hr_samples.date
        ), oxy_daily AS (
         SELECT filtered_raw.patient_id,
            date_trunc('day'::text, (filtered_raw.recorded_at AT TIME ZONE COALESCE(filtered_raw.timezone, 'UTC'::character varying))) AS date,
            avg(((filtered_raw."values" ->> 'percentage'::text))::numeric) AS oxygen_sat_avg,
            min(((filtered_raw."values" ->> 'percentage'::text))::numeric) AS oxygen_sat_min
           FROM filtered_raw
          WHERE (filtered_raw.metric_type = 'OxygenSaturationRecord'::text)
          GROUP BY filtered_raw.patient_id, (date_trunc('day'::text, (filtered_raw.recorded_at AT TIME ZONE COALESCE(filtered_raw.timezone, 'UTC'::character varying))))
        ), sleep_stages_raw AS (
         SELECT filtered_raw.patient_id,
            date_trunc('day'::text, ((((stage.value ->> 'end_time'::text))::timestamp with time zone + '12:00:00'::interval) AT TIME ZONE COALESCE(filtered_raw.timezone, 'UTC'::character varying))) AS date,
            ((stage.value ->> 'stage'::text))::integer AS stage_type,
            ((stage.value ->> 'start_time'::text))::timestamp with time zone AS start_time,
            ((stage.value ->> 'end_time'::text))::timestamp with time zone AS end_time
           FROM filtered_raw,
            LATERAL jsonb_array_elements((filtered_raw."values" -> 'stages'::text)) stage(value)
          WHERE (filtered_raw.metric_type = 'SleepSessionRecord'::text)
        ), merged_stage_spans AS (
         SELECT s2.patient_id,
            s2.date,
            s2.stage_type,
            s2.grp,
            min(s2.start_time) AS merged_start,
            max(s2.end_time) AS merged_end
           FROM ( SELECT s1.patient_id,
                    s1.date,
                    s1.stage_type,
                    s1.start_time,
                    s1.end_time,
                    sum(
                        CASE
                            WHEN ((s1.prev_max_end IS NULL) OR (s1.start_time > s1.prev_max_end)) THEN 1
                            ELSE 0
                        END) OVER (PARTITION BY s1.patient_id, s1.date, s1.stage_type ORDER BY s1.start_time, s1.end_time) AS grp
                   FROM ( SELECT ss.patient_id,
                            ss.date,
                            ss.stage_type,
                            ss.start_time,
                            ss.end_time,
                            max(ss.end_time) OVER (PARTITION BY ss.patient_id, ss.date, ss.stage_type ORDER BY ss.start_time, ss.end_time ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS prev_max_end
                           FROM sleep_stages_raw ss) s1) s2
          GROUP BY s2.patient_id, s2.date, s2.stage_type, s2.grp
        ), merged_stages AS (
         SELECT merged_stage_spans.patient_id,
            merged_stage_spans.date,
            merged_stage_spans.stage_type,
            sum((EXTRACT(epoch FROM (merged_stage_spans.merged_end - merged_stage_spans.merged_start)) / 3600.0)) AS duration_hours
           FROM merged_stage_spans
          GROUP BY merged_stage_spans.patient_id, merged_stage_spans.date, merged_stage_spans.stage_type
        ), sleep_boundaries AS (
         SELECT merged_stage_spans.patient_id,
            merged_stage_spans.date,
            min(merged_stage_spans.merged_start) FILTER (WHERE (merged_stage_spans.stage_type = ANY (ARRAY[2, 4, 5, 6]))) AS sleep_onset,
            max(merged_stage_spans.merged_end) FILTER (WHERE (merged_stage_spans.stage_type = ANY (ARRAY[2, 4, 5, 6]))) AS final_wakeup
           FROM merged_stage_spans
          GROUP BY merged_stage_spans.patient_id, merged_stage_spans.date
        ), advanced_sleep_metrics AS (
         SELECT ms_1.patient_id,
            ms_1.date,
            sum((EXTRACT(epoch FROM (LEAST(ms_1.merged_end, b.final_wakeup) - GREATEST(ms_1.merged_start, b.sleep_onset))) / 60.0)) FILTER (WHERE ((ms_1.stage_type = ANY (ARRAY[1, 3])) AND (ms_1.merged_end > b.sleep_onset) AND (ms_1.merged_start < b.final_wakeup))) AS waso_mins,
            count(*) FILTER (WHERE ((ms_1.stage_type = ANY (ARRAY[1, 3])) AND (ms_1.merged_end > b.sleep_onset) AND (ms_1.merged_start < b.final_wakeup))) AS awakenings_count,
            count(*) FILTER (WHERE ((ms_1.stage_type = ANY (ARRAY[1, 3])) AND (ms_1.merged_end > b.sleep_onset) AND (ms_1.merged_start < b.final_wakeup) AND (EXTRACT(epoch FROM (ms_1.merged_end - ms_1.merged_start)) >= (300)::numeric))) AS awakenings_count_greater_than_5mins,
            b.sleep_onset,
            b.final_wakeup
           FROM (merged_stage_spans ms_1
             JOIN sleep_boundaries b ON (((ms_1.patient_id = b.patient_id) AND (ms_1.date = b.date))))
          GROUP BY ms_1.patient_id, ms_1.date, b.sleep_onset, b.final_wakeup
        ), sleep_daily AS (
         SELECT merged_stages.patient_id,
            merged_stages.date,
            sum(
                CASE
                    WHEN (merged_stages.stage_type = 1) THEN merged_stages.duration_hours
                    ELSE (0)::numeric
                END) AS sleep_stage_1_hours,
            sum(
                CASE
                    WHEN (merged_stages.stage_type = 2) THEN merged_stages.duration_hours
                    ELSE (0)::numeric
                END) AS sleep_stage_2_hours,
            sum(
                CASE
                    WHEN (merged_stages.stage_type = 3) THEN merged_stages.duration_hours
                    ELSE (0)::numeric
                END) AS sleep_stage_3_hours,
            sum(
                CASE
                    WHEN (merged_stages.stage_type = 4) THEN merged_stages.duration_hours
                    ELSE (0)::numeric
                END) AS sleep_stage_4_hours,
            sum(
                CASE
                    WHEN (merged_stages.stage_type = 5) THEN merged_stages.duration_hours
                    ELSE (0)::numeric
                END) AS sleep_stage_5_hours,
            sum(
                CASE
                    WHEN (merged_stages.stage_type = 6) THEN merged_stages.duration_hours
                    ELSE (0)::numeric
                END) AS sleep_stage_6_hours
           FROM merged_stages
          GROUP BY merged_stages.patient_id, merged_stages.date
        ), other_metrics AS (
         SELECT filtered_raw.patient_id,
            date_trunc('day'::text, (filtered_raw.recorded_at AT TIME ZONE COALESCE(filtered_raw.timezone, 'UTC'::character varying))) AS date,
            sum(
                CASE
                    WHEN (filtered_raw.metric_type = 'StepsRecord'::text) THEN ((filtered_raw."values" ->> 'count'::text))::numeric
                    ELSE (0)::numeric
                END) AS total_steps,
            sum(
                CASE
                    WHEN (filtered_raw.metric_type = 'DistanceRecord'::text) THEN ((filtered_raw."values" ->> 'distanceMeters'::text))::numeric
                    ELSE (0)::numeric
                END) AS distance_meters,
            sum(
                CASE
                    WHEN (filtered_raw.metric_type = 'ActiveCaloriesBurnedRecord'::text) THEN ((filtered_raw."values" ->> 'energyKcal'::text))::numeric
                    ELSE (0)::numeric
                END) AS active_calories,
            avg(
                CASE
                    WHEN (filtered_raw.metric_type = 'BodyTemperatureRecord'::text) THEN ((filtered_raw."values" ->> 'temperatureCelsius'::text))::numeric
                    ELSE NULL::numeric
                END) AS body_temp_avg,
            avg(
                CASE
                    WHEN (filtered_raw.metric_type = 'RespiratoryRateRecord'::text) THEN ((filtered_raw."values" ->> 'rate'::text))::numeric
                    ELSE NULL::numeric
                END) AS respiratory_rate_avg,
            sum(
                CASE
                    WHEN (filtered_raw.metric_type = 'AudioSensorRecord'::text) THEN ((filtered_raw."values" ->> 'cough_count'::text))::numeric
                    ELSE NULL::numeric
                END) AS cough_count_night,
            sum(
                CASE
                    WHEN (filtered_raw.metric_type = 'AudioSensorRecord'::text) THEN ((filtered_raw."values" ->> 'snore_events'::text))::numeric
                    ELSE NULL::numeric
                END) AS snoring_events_count,
            avg(
                CASE
                    WHEN (filtered_raw.metric_type = 'GyroscopeMobilityRecord'::text) THEN ((filtered_raw."values" ->> 'sit_to_stand_duration'::text))::numeric
                    ELSE NULL::numeric
                END) AS sit_to_stand_seconds
           FROM filtered_raw
          WHERE (filtered_raw.metric_type = ANY (ARRAY['StepsRecord'::text, 'DistanceRecord'::text, 'ActiveCaloriesBurnedRecord'::text, 'SleepSessionRecord'::text, 'BodyTemperatureRecord'::text, 'RespiratoryRateRecord'::text, 'AudioSensorRecord'::text, 'GyroscopeMobilityRecord'::text]))
          GROUP BY filtered_raw.patient_id, (date_trunc('day'::text, (filtered_raw.recorded_at AT TIME ZONE COALESCE(filtered_raw.timezone, 'UTC'::character varying))))
        ), sleep_sessions AS (
         SELECT filtered_raw.patient_id,
            date_trunc('day'::text, ((((filtered_raw."values" ->> 'end_time'::text))::timestamp with time zone + '12:00:00'::interval) AT TIME ZONE COALESCE(filtered_raw.timezone, 'UTC'::character varying))) AS date,
            ((filtered_raw."values" ->> 'start_time'::text))::timestamp with time zone AS start_time,
            ((filtered_raw."values" ->> 'end_time'::text))::timestamp with time zone AS end_time,
            filtered_raw.timezone
           FROM filtered_raw
          WHERE (filtered_raw.metric_type = 'SleepSessionRecord'::text)
        ), merged_sleep AS (
         SELECT s3.patient_id,
            s3.date,
            sum((EXTRACT(epoch FROM (s3.merged_end - s3.merged_start)) / 3600.0)) AS sleep_hours,
            min(s3.merged_start) AS session_start,
            max(s3.merged_end) AS session_end,
            max(s3.timezone) AS timezone
           FROM ( SELECT s2.patient_id,
                    s2.date,
                    s2.grp,
                    min(s2.start_time) AS merged_start,
                    max(s2.end_time) AS merged_end,
                    max(s2.timezone) AS timezone
                   FROM ( SELECT s1.patient_id,
                            s1.date,
                            s1.start_time,
                            s1.end_time,
                            s1.timezone,
                            sum(
                                CASE
                                    WHEN ((s1.prev_max_end IS NULL) OR (s1.start_time > s1.prev_max_end)) THEN 1
                                    ELSE 0
                                END) OVER (PARTITION BY s1.patient_id, s1.date ORDER BY s1.start_time, s1.end_time) AS grp
                           FROM ( SELECT sleep_sessions.patient_id,
                                    sleep_sessions.date,
                                    sleep_sessions.start_time,
                                    sleep_sessions.end_time,
                                    sleep_sessions.timezone,
                                    max(sleep_sessions.end_time) OVER (PARTITION BY sleep_sessions.patient_id, sleep_sessions.date ORDER BY sleep_sessions.start_time, sleep_sessions.end_time ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS prev_max_end
                                   FROM sleep_sessions) s1) s2
                  GROUP BY s2.patient_id, s2.date, s2.grp) s3
          GROUP BY s3.patient_id, s3.date
        ), sleep_hr_samples AS (
         SELECT s_1.patient_id,
            s_1.date,
            h_1.sample_time,
            h_1.bpm
           FROM (sleep_sessions s_1
             JOIN hr_samples h_1 ON (((s_1.patient_id = h_1.patient_id) AND (h_1.sample_time >= s_1.start_time) AND (h_1.sample_time <= s_1.end_time))))
        ), rolling_hr AS (
         SELECT sleep_hr_samples.patient_id,
            sleep_hr_samples.date,
            sleep_hr_samples.bpm,
            avg(sleep_hr_samples.bpm) OVER (PARTITION BY sleep_hr_samples.patient_id, sleep_hr_samples.date ORDER BY sleep_hr_samples.sample_time RANGE BETWEEN '00:05:00'::interval PRECEDING AND CURRENT ROW) AS roll_avg_5m
           FROM sleep_hr_samples
        ), resting_hr AS (
         SELECT rolling_hr.patient_id,
            rolling_hr.date,
            min(rolling_hr.roll_avg_5m) AS resting_heart_rate_calculated,
            max(rolling_hr.bpm) AS sleep_max_heart_rate
           FROM rolling_hr
          GROUP BY rolling_hr.patient_id, rolling_hr.date
        ), speed_samples AS (
         SELECT filtered_raw.patient_id,
            date_trunc('day'::text, (((sample.value ->> 'time'::text))::timestamp with time zone AT TIME ZONE COALESCE(filtered_raw.timezone, 'UTC'::character varying))) AS date,
            ((sample.value ->> 'speedMetersPerSec'::text))::numeric AS speed
           FROM filtered_raw,
            LATERAL jsonb_array_elements((filtered_raw."values" -> 'samples'::text)) sample(value)
          WHERE (filtered_raw.metric_type = 'SpeedRecord'::text)
        ), speed_daily AS (
         SELECT speed_samples.patient_id,
            speed_samples.date,
            avg(speed_samples.speed) AS avg_speed
           FROM speed_samples
          GROUP BY speed_samples.patient_id, speed_samples.date
        ), hrr_daily AS (
         SELECT filtered_raw.patient_id,
            date_trunc('day'::text, (filtered_raw.recorded_at AT TIME ZONE COALESCE(filtered_raw.timezone, 'UTC'::character varying))) AS date,
            jsonb_agg(jsonb_build_object('bpm', ((filtered_raw."values" ->> 'heart_rate_recovery_bpm'::text))::integer)) AS heart_rate_recovery_calculated
           FROM filtered_raw
          WHERE (filtered_raw.metric_type = 'HeartRateRecoveryRecord'::text)
          GROUP BY filtered_raw.patient_id, (date_trunc('day'::text, (filtered_raw.recorded_at AT TIME ZONE COALESCE(filtered_raw.timezone, 'UTC'::character varying))))
        ), skin_temp_samples AS (
         SELECT filtered_raw.patient_id,
            date_trunc('day'::text, (((delta.value ->> 'time'::text))::timestamp with time zone AT TIME ZONE COALESCE(filtered_raw.timezone, 'UTC'::character varying))) AS date,
            ((delta.value ->> 'deltaCelsius'::text))::numeric AS delta_celsius
           FROM filtered_raw,
            LATERAL jsonb_array_elements((filtered_raw."values" -> 'deltas'::text)) delta(value)
          WHERE (filtered_raw.metric_type = 'SkinTemperatureRecord'::text)
        ), skin_temp_daily AS (
         SELECT skin_temp_samples.patient_id,
            skin_temp_samples.date,
            avg(skin_temp_samples.delta_celsius) AS skin_temperature_delta
           FROM skin_temp_samples
          GROUP BY skin_temp_samples.patient_id, skin_temp_samples.date
        )
  SELECT 
    COALESCE(sk.patient_id, o.patient_id, h.patient_id, ox.patient_id, s.patient_id, r.patient_id, sp.patient_id, ms.patient_id, spf.patient_id, hrr.patient_id, tz.patient_id) AS patient_id,
    COALESCE(sk.date, o.date, h.date, ox.date, s.date, r.date, sp.date, ms.date, spf.date, hrr.date, tz.date) AS date,
    h.avg_heart_rate,
    h.max_heart_rate,
    h.min_heart_rate,
    h.hr_avg_morning,
    h.hr_avg_afternoon,
    h.hr_avg_evening,
    h.hr_avg_night,
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
    sk.skin_temperature_delta,
    hrr.heart_rate_recovery_calculated,
    CASE
        WHEN (s.patient_id IS NOT NULL) THEN COALESCE(adv.waso_mins, (0)::numeric)
        ELSE NULL::numeric
    END AS waso_mins,
    CASE
        WHEN (s.patient_id IS NOT NULL) THEN COALESCE(adv.awakenings_count, (0)::bigint)
        ELSE NULL::bigint
    END AS awakenings_count,
    CASE
        WHEN (s.patient_id IS NOT NULL) THEN COALESCE(adv.awakenings_count_greater_than_5mins, (0)::bigint)
        ELSE NULL::bigint
    END AS awakenings_count_greater_than_5mins,
    NULLIF(GREATEST((0)::numeric, (EXTRACT(epoch FROM (adv.sleep_onset - ms.session_start)) / 60.0)), (0)::numeric) AS sleep_latency_mins,
    CASE
        WHEN ((ms.sleep_hours > (0)::numeric) AND (s.patient_id IS NOT NULL)) THEN (((((COALESCE(s.sleep_stage_2_hours, (0)::numeric) + COALESCE(s.sleep_stage_4_hours, (0)::numeric)) + COALESCE(s.sleep_stage_5_hours, (0)::numeric)) + COALESCE(s.sleep_stage_6_hours, (0)::numeric)) / ms.sleep_hours) * 100.0)
        ELSE NULL::numeric
    END AS sleep_efficiency_pct,
    CASE
        WHEN ((ms.sleep_hours > (0)::numeric) AND (s.patient_id IS NOT NULL)) THEN ((COALESCE(s.sleep_stage_1_hours, (0)::numeric) / ms.sleep_hours) * 100.0)
        ELSE NULL::numeric
    END AS sleep_stage_1_pct,
    CASE
        WHEN ((ms.sleep_hours > (0)::numeric) AND (s.patient_id IS NOT NULL)) THEN ((COALESCE(s.sleep_stage_2_hours, (0)::numeric) / ms.sleep_hours) * 100.0)
        ELSE NULL::numeric
    END AS sleep_stage_2_pct,
    CASE
        WHEN ((ms.sleep_hours > (0)::numeric) AND (s.patient_id IS NOT NULL)) THEN ((COALESCE(s.sleep_stage_3_hours, (0)::numeric) / ms.sleep_hours) * 100.0)
        ELSE NULL::numeric
    END AS sleep_stage_3_pct,
    CASE
        WHEN ((ms.sleep_hours > (0)::numeric) AND (s.patient_id IS NOT NULL)) THEN ((COALESCE(s.sleep_stage_4_hours, (0)::numeric) / ms.sleep_hours) * 100.0)
        ELSE NULL::numeric
    END AS sleep_stage_4_pct,
    CASE
        WHEN ((ms.sleep_hours > (0)::numeric) AND (s.patient_id IS NOT NULL)) THEN ((COALESCE(s.sleep_stage_5_hours, (0)::numeric) / ms.sleep_hours) * 100.0)
        ELSE NULL::numeric
    END AS sleep_stage_5_pct,
    CASE
        WHEN ((ms.sleep_hours > (0)::numeric) AND (s.patient_id IS NOT NULL)) THEN ((COALESCE(s.sleep_stage_6_hours, (0)::numeric) / ms.sleep_hours) * 100.0)
        ELSE NULL::numeric
    END AS sleep_stage_6_pct,
    COALESCE(adv.sleep_onset, ms.session_start) AS sleep_onset_time,
    COALESCE(adv.final_wakeup, ms.session_end) AS final_wakeup_time,
    COALESCE(tz.timezone, ms.timezone) AS timezone,
    NOW() AS updated_at
   FROM ((((((((((other_metrics o
     FULL JOIN hr_daily h ON (((o.patient_id = h.patient_id) AND (o.date = h.date))))
     FULL JOIN oxy_daily ox ON (((COALESCE(o.patient_id, h.patient_id) = ox.patient_id) AND (COALESCE(o.date, h.date) = ox.date))))
     FULL JOIN sleep_daily s ON (((COALESCE(o.patient_id, h.patient_id, ox.patient_id) = s.patient_id) AND (COALESCE(o.date, h.date, ox.date) = s.date))))
     FULL JOIN resting_hr r ON (((COALESCE(o.patient_id, h.patient_id, ox.patient_id, s.patient_id) = r.patient_id) AND (COALESCE(o.date, h.date, ox.date, s.date) = r.date))))
     FULL JOIN speed_daily sp ON (((COALESCE(o.patient_id, h.patient_id, ox.patient_id, s.patient_id, r.patient_id) = sp.patient_id) AND (COALESCE(o.date, h.date, ox.date, s.date, r.date) = sp.date))))
     FULL JOIN merged_sleep ms ON (((COALESCE(o.patient_id, h.patient_id, ox.patient_id, s.patient_id, r.patient_id, sp.patient_id) = ms.patient_id) AND (COALESCE(o.date, h.date, ox.date, s.date, r.date, sp.date) = ms.date))))
     FULL JOIN advanced_sleep_metrics adv ON (((COALESCE(o.patient_id, h.patient_id, ox.patient_id, s.patient_id, r.patient_id, sp.patient_id, ms.patient_id) = adv.patient_id) AND (COALESCE(o.date, h.date, ox.date, s.date, r.date, sp.date, ms.date) = adv.date))))
     FULL JOIN steps_phone_fallback spf ON (((COALESCE(o.patient_id, h.patient_id, ox.patient_id, s.patient_id, r.patient_id, sp.patient_id, ms.patient_id, adv.patient_id) = spf.patient_id) AND (COALESCE(o.date, h.date, ox.date, s.date, r.date, sp.date, ms.date, adv.date) = spf.date))))
     FULL JOIN hrr_daily hrr ON (((COALESCE(o.patient_id, h.patient_id, ox.patient_id, s.patient_id, r.patient_id, sp.patient_id, ms.patient_id, adv.patient_id, spf.patient_id) = hrr.patient_id) AND (COALESCE(o.date, h.date, ox.date, s.date, r.date, sp.date, ms.date, adv.date, spf.date) = hrr.date))))
     FULL JOIN skin_temp_daily sk ON (COALESCE(o.patient_id, h.patient_id, ox.patient_id, s.patient_id, r.patient_id, sp.patient_id, ms.patient_id, adv.patient_id, spf.patient_id, hrr.patient_id) = sk.patient_id AND COALESCE(o.date, h.date, ox.date, s.date, r.date, sp.date, ms.date, adv.date, spf.date, hrr.date) = sk.date))
     FULL JOIN tz_daily tz ON (COALESCE(sk.patient_id, o.patient_id, h.patient_id, ox.patient_id, s.patient_id, r.patient_id, sp.patient_id, ms.patient_id, adv.patient_id, spf.patient_id, hrr.patient_id) = tz.patient_id AND COALESCE(sk.date, o.date, h.date, ox.date, s.date, r.date, sp.date, ms.date, adv.date, spf.date, hrr.date) = tz.date))
    WHERE (p_patient_id IS NULL OR COALESCE(sk.patient_id, o.patient_id, h.patient_id, ox.patient_id, s.patient_id, r.patient_id, sp.patient_id, ms.patient_id, spf.patient_id, hrr.patient_id, tz.patient_id) = p_patient_id)
      AND (p_start_date IS NULL OR COALESCE(sk.date, o.date, h.date, ox.date, s.date, r.date, sp.date, ms.date, spf.date, hrr.date, tz.date) >= p_start_date)
      AND (p_end_date IS NULL OR COALESCE(sk.date, o.date, h.date, ox.date, s.date, r.date, sp.date, ms.date, spf.date, hrr.date, tz.date) <= p_end_date)
    ON CONFLICT (patient_id, date) DO UPDATE SET
        avg_heart_rate = EXCLUDED.avg_heart_rate,
        max_heart_rate = EXCLUDED.max_heart_rate,
        min_heart_rate = EXCLUDED.min_heart_rate,
        hr_avg_morning = EXCLUDED.hr_avg_morning,
        hr_avg_afternoon = EXCLUDED.hr_avg_afternoon,
        hr_avg_evening = EXCLUDED.hr_avg_evening,
        hr_avg_night = EXCLUDED.hr_avg_night,
        total_steps = EXCLUDED.total_steps,
        distance_meters = EXCLUDED.distance_meters,
        active_calories = EXCLUDED.active_calories,
        sleep_hours = EXCLUDED.sleep_hours,
        oxygen_sat_avg = EXCLUDED.oxygen_sat_avg,
        oxygen_sat_min = EXCLUDED.oxygen_sat_min,
        sleep_stage_1_hours = EXCLUDED.sleep_stage_1_hours,
        sleep_stage_2_hours = EXCLUDED.sleep_stage_2_hours,
        sleep_stage_3_hours = EXCLUDED.sleep_stage_3_hours,
        sleep_stage_4_hours = EXCLUDED.sleep_stage_4_hours,
        sleep_stage_5_hours = EXCLUDED.sleep_stage_5_hours,
        sleep_stage_6_hours = EXCLUDED.sleep_stage_6_hours,
        resting_heart_rate_calculated = EXCLUDED.resting_heart_rate_calculated,
        sleep_max_heart_rate = EXCLUDED.sleep_max_heart_rate,
        body_temp_avg = EXCLUDED.body_temp_avg,
        respiratory_rate_avg = EXCLUDED.respiratory_rate_avg,
        avg_speed = EXCLUDED.avg_speed,
        cough_count_night = EXCLUDED.cough_count_night,
        snoring_events_count = EXCLUDED.snoring_events_count,
        sit_to_stand_seconds = EXCLUDED.sit_to_stand_seconds,
        skin_temperature_delta = EXCLUDED.skin_temperature_delta,
        heart_rate_recovery_calculated = EXCLUDED.heart_rate_recovery_calculated,
        waso_mins = EXCLUDED.waso_mins,
        awakenings_count = EXCLUDED.awakenings_count,
        awakenings_count_greater_than_5mins = EXCLUDED.awakenings_count_greater_than_5mins,
        sleep_latency_mins = EXCLUDED.sleep_latency_mins,
        sleep_efficiency_pct = EXCLUDED.sleep_efficiency_pct,
        sleep_stage_1_pct = EXCLUDED.sleep_stage_1_pct,
        sleep_stage_2_pct = EXCLUDED.sleep_stage_2_pct,
        sleep_stage_3_pct = EXCLUDED.sleep_stage_3_pct,
        sleep_stage_4_pct = EXCLUDED.sleep_stage_4_pct,
        sleep_stage_5_pct = EXCLUDED.sleep_stage_5_pct,
        sleep_stage_6_pct = EXCLUDED.sleep_stage_6_pct,
        sleep_onset_time = EXCLUDED.sleep_onset_time,
        final_wakeup_time = EXCLUDED.final_wakeup_time,
        timezone = COALESCE(EXCLUDED.timezone, vitals_daily.timezone),
        updated_at = NOW();

    GET DIAGNOSTICS rows_affected = ROW_COUNT;

    -- 2. Compute rolling 7-day bedtime variance and sleep consistency score
    UPDATE vitals_daily vd
    SET 
        sleep_consistency_pct = sub.consistency_score,
        bedtime_variance_mins = sub.variance_mins
    FROM (
        SELECT 
            v1.patient_id,
            v1.date,
            calc.var_mins AS variance_mins,
            CASE 
                WHEN calc.sleep_count >= 2 THEN
                    GREATEST(0, LEAST(100, ROUND(100.0 - (calc.var_mins * 0.75), 1)))
                ELSE NULL
            END AS consistency_score
        FROM vitals_daily v1
        CROSS JOIN LATERAL (
            SELECT 
                COUNT(v2.sleep_onset_time) AS sleep_count,
                ROUND(STDDEV(
                    CASE 
                        WHEN EXTRACT(HOUR FROM v2.sleep_onset_time AT TIME ZONE COALESCE(v2.timezone, 'UTC')) >= 12 
                        THEN (EXTRACT(HOUR FROM v2.sleep_onset_time AT TIME ZONE COALESCE(v2.timezone, 'UTC')) - 18) * 60 
                             + EXTRACT(MINUTE FROM v2.sleep_onset_time AT TIME ZONE COALESCE(v2.timezone, 'UTC'))
                        ELSE (EXTRACT(HOUR FROM v2.sleep_onset_time AT TIME ZONE COALESCE(v2.timezone, 'UTC')) + 6) * 60 
                             + EXTRACT(MINUTE FROM v2.sleep_onset_time AT TIME ZONE COALESCE(v2.timezone, 'UTC'))
                    END
                )::numeric, 1) AS var_mins
            FROM vitals_daily v2
            WHERE v2.patient_id = v1.patient_id
              AND v2.date BETWEEN (v1.date - interval '6 days') AND v1.date
              AND v2.sleep_onset_time IS NOT NULL
        ) calc
        WHERE (p_patient_id IS NULL OR v1.patient_id = p_patient_id)
          AND (p_start_date IS NULL OR v1.date >= p_start_date)
          AND (p_end_date IS NULL OR v1.date <= (p_end_date + interval '6 days'))
    ) sub
    WHERE vd.patient_id = sub.patient_id AND vd.date = sub.date;

    RETURN rows_affected;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Step 3: Backfill sleep metrics & consistency across all existing vitals_daily rows
DO $$
DECLARE
    p_rec RECORD;
BEGIN
    FOR p_rec IN SELECT DISTINCT patient_id FROM vitals_raw LOOP
        PERFORM recalculate_vitals_daily(p_rec.patient_id, NULL, NULL);
    END LOOP;
END $$;
