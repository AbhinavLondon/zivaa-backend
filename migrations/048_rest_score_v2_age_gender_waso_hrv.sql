-- Migration 048: Rest Score 2.0 with Science-Backed Age & Gender Duration Benchmarks, WASO, and HRV RMSSD Personal Baseline Recovery
-- Version: 20260921021000

-- ==============================================================================
-- 1. SCHEMA ENHANCEMENTS ON vitals_daily
-- ==============================================================================
ALTER TABLE vitals_daily 
ADD COLUMN IF NOT EXISTS hrv_rmssd_avg NUMERIC,
ADD COLUMN IF NOT EXISTS hrv_rmssd_min NUMERIC,
ADD COLUMN IF NOT EXISTS hrv_rmssd_max NUMERIC;

-- ==============================================================================
-- 2. DAILY AGGREGATOR FUNCTION (recalculate_vitals_daily)
--    Aggregates HeartRateVariabilityRmssdRecord nocturnal and daily values.
-- ==============================================================================
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
        avg_cadence_spm,
        active_movement_minutes,
        active_hours_count,
        hrv_rmssd_avg,
        hrv_rmssd_min,
        hrv_rmssd_max,
        updated_at
    )
    WITH ranked_sources AS (
         SELECT v.id,
            v.patient_id,
            v.recorded_at,
            v.metric_type,
            v.source,
            v."values",
            COALESCE(v.timezone, p.timezone, 'UTC'::character varying) AS timezone,
            dense_rank() OVER (PARTITION BY v.patient_id, v.metric_type, (date_trunc('day'::text, (v.recorded_at AT TIME ZONE COALESCE(v.timezone, p.timezone, 'UTC'::character varying)))) ORDER BY COALESCE(( SELECT m.priority_rank
                   FROM metric_source_priority m
                  WHERE ((m.metric_type = v.metric_type) AND (m.source = v.source))),
                CASE
                    WHEN (v.source ~~ like_escape('%\_watch'::text, '\'::text)) THEN 5
                    WHEN (v.source ~~ like_escape('%\_phone'::text, '\'::text)) THEN 50
                    ELSE 9999
                END)) AS rk
           FROM vitals_raw v
           LEFT JOIN patients p ON p.id = v.patient_id
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
            (array_agg(filtered_raw.timezone ORDER BY filtered_raw.recorded_at DESC) FILTER (WHERE filtered_raw.timezone IS NOT NULL))[1] AS timezone
           FROM filtered_raw
          GROUP BY filtered_raw.patient_id, date_trunc('day'::text, (filtered_raw.recorded_at AT TIME ZONE COALESCE(filtered_raw.timezone, 'UTC'::character varying)))
        ), granular_steps_ranked AS (
          SELECT v.id,
            v.patient_id,
            v.recorded_at,
            v.source,
            v."values",
            COALESCE(v.timezone, p.timezone, 'UTC'::character varying) AS timezone,
            date_trunc('day'::text, (v.recorded_at AT TIME ZONE COALESCE(v.timezone, p.timezone, 'UTC'::character varying))) AS date,
            ((v."values" ->> 'duration_seconds'::text))::numeric AS duration_seconds,
            ((v."values" ->> 'count'::text))::numeric AS count,
            dense_rank() OVER (
                PARTITION BY v.patient_id, (date_trunc('day'::text, (v.recorded_at AT TIME ZONE COALESCE(v.timezone, p.timezone, 'UTC'::character varying))))
                ORDER BY COALESCE(
                    (SELECT m.priority_rank FROM metric_source_priority m WHERE m.metric_type = 'StepsRecord' AND m.source = v.source),
                    CASE 
                        WHEN v.source LIKE '%\_watch' ESCAPE '\' THEN 5
                        WHEN v.source LIKE '%\_phone' ESCAPE '\' THEN 50
                        ELSE 9999
                    END
                ) ASC
            ) AS rk
          FROM vitals_raw v
          LEFT JOIN patients p ON p.id = v.patient_id
          WHERE v.metric_type = 'StepsRecord'::text
            AND v.is_outlier = false
            AND (p_patient_id IS NULL OR v.patient_id = p_patient_id)
            AND (p_start_date IS NULL OR v.recorded_at >= p_start_date - interval '2 days')
            AND (p_end_date IS NULL OR v.recorded_at <= p_end_date + interval '2 days')
            AND (v."values" ? 'duration_seconds')
            AND ((v."values" ->> 'duration_seconds'::text))::numeric > 0
            AND ((v."values" ->> 'duration_seconds'::text))::numeric <= 600
            AND ((v."values" ->> 'count'::text))::numeric > 0
        ), winning_granular_steps AS (
          SELECT * FROM granular_steps_ranked WHERE rk = 1
        ), active_hours_daily AS (
          SELECT
            sub_h.patient_id,
            sub_h.date,
            count(*)::integer AS active_hours_count
          FROM (
            SELECT
              v.patient_id,
              date_trunc('day'::text, (v.recorded_at AT TIME ZONE COALESCE(v.timezone, p.timezone, 'UTC'::character varying))) AS date,
              EXTRACT(HOUR FROM (v.recorded_at AT TIME ZONE COALESCE(v.timezone, p.timezone, 'UTC'::character varying))) AS h
            FROM vitals_raw v
            LEFT JOIN patients p ON p.id = v.patient_id
            WHERE v.metric_type = 'StepsRecord'::text
              AND v.is_outlier = false
              AND (p_patient_id IS NULL OR v.patient_id = p_patient_id)
              AND (p_start_date IS NULL OR v.recorded_at >= p_start_date - interval '2 days')
              AND (p_end_date IS NULL OR v.recorded_at <= p_end_date + interval '2 days')
              AND (
                CASE 
                  WHEN v."values" ? 'duration_seconds' 
                  THEN ((v."values" ->> 'duration_seconds'::text))::numeric <= 3600
                  ELSE NOT (v.source ~~ like_escape('%shealth%'::text, '\'::text))
                END
              )
              AND EXTRACT(HOUR FROM (v.recorded_at AT TIME ZONE COALESCE(v.timezone, p.timezone, 'UTC'::character varying))) BETWEEN 8 AND 20
            GROUP BY v.patient_id,
                     date_trunc('day'::text, (v.recorded_at AT TIME ZONE COALESCE(v.timezone, p.timezone, 'UTC'::character varying))),
                     EXTRACT(HOUR FROM (v.recorded_at AT TIME ZONE COALESCE(v.timezone, p.timezone, 'UTC'::character varying)))
            HAVING sum(((v."values" ->> 'count'::text))::numeric) >= 150
          ) sub_h
          GROUP BY sub_h.patient_id, sub_h.date
        ), mobility_bouts AS (
          SELECT g.patient_id,
            g.date,
            round(
              (sum(CASE WHEN ((g.count / (g.duration_seconds / 60.0)) BETWEEN 40.0 AND 160.0) AND g.duration_seconds >= 10 AND g.count >= 8 THEN g.duration_seconds ELSE 0 END) / 60.0) +
              (sum(CASE WHEN NOT (((g.count / (g.duration_seconds / 60.0)) BETWEEN 40.0 AND 160.0) AND g.duration_seconds >= 10 AND g.count >= 8) THEN g.count ELSE 0 END) / 75.0),
              1
            ) AS active_movement_minutes,
            CASE 
              WHEN sum(CASE WHEN ((g.count / (g.duration_seconds / 60.0)) BETWEEN 40.0 AND 160.0) AND g.duration_seconds >= 10 AND g.count >= 8 THEN g.duration_seconds ELSE 0 END) >= 30
              THEN round(
                sum(CASE WHEN ((g.count / (g.duration_seconds / 60.0)) BETWEEN 40.0 AND 160.0) AND g.duration_seconds >= 10 AND g.count >= 8 THEN g.count ELSE 0 END) /
                (sum(CASE WHEN ((g.count / (g.duration_seconds / 60.0)) BETWEEN 40.0 AND 160.0) AND g.duration_seconds >= 10 AND g.count >= 8 THEN g.duration_seconds ELSE 0 END) / 60.0)
              )
              ELSE NULL::numeric
            END AS avg_cadence_spm
          FROM winning_granular_steps g
          GROUP BY g.patient_id, g.date
        ), mobility_daily AS (
          SELECT
            COALESCE(mb.patient_id, ah.patient_id) AS patient_id,
            COALESCE(mb.date, ah.date) AS date,
            mb.active_movement_minutes,
            mb.avg_cadence_spm,
            COALESCE(ah.active_hours_count, 0)::integer AS active_hours_count
          FROM mobility_bouts mb
          FULL JOIN active_hours_daily ah ON (mb.patient_id = ah.patient_id AND mb.date = ah.date)
        ), steps_phone_fallback AS (
         SELECT per_source.patient_id,
            per_source.date,
            max(per_source.source_total) AS phone_steps
           FROM ( SELECT v.patient_id,
                    date_trunc('day'::text, (v.recorded_at AT TIME ZONE COALESCE(v.timezone, p.timezone, 'UTC'::character varying))) AS date,
                    v.source,
                    sum(((v."values" ->> 'count'::text))::numeric) AS source_total
                   FROM vitals_raw v
                   LEFT JOIN patients p ON p.id = v.patient_id
                  WHERE ((v.metric_type = 'StepsRecord'::text) AND (v.is_outlier = false) AND (v.source ~~ like_escape('%\_phone'::text, '\'::text))
                    AND (p_patient_id IS NULL OR v.patient_id = p_patient_id)
                    AND (p_start_date IS NULL OR v.recorded_at >= p_start_date - interval '2 days')
                    AND (p_end_date IS NULL OR v.recorded_at <= p_end_date + interval '2 days'))
                  GROUP BY v.patient_id, (date_trunc('day'::text, (v.recorded_at AT TIME ZONE COALESCE(v.timezone, p.timezone, 'UTC'::character varying)))), v.source) per_source
          GROUP BY per_source.patient_id, per_source.date
        ), hr_samples AS (
         SELECT filtered_raw.patient_id,
            date_trunc('day'::text, (((sample.value ->> 'time'::text))::timestamp with time zone AT TIME ZONE COALESCE(filtered_raw.timezone, 'UTC'::character varying))) AS date,
            ((sample.value ->> 'time'::text))::timestamp with time zone AS sample_time,
            ((sample.value ->> 'bpm'::text))::numeric AS bpm,
            filtered_raw.timezone
           FROM filtered_raw,
            LATERAL jsonb_array_elements((filtered_raw."values" -> 'samples'::text)) sample(value)
          WHERE (filtered_raw.metric_type = 'HeartRateRecord'::text)
        ), hr_daily AS (
           SELECT hr_samples.patient_id,
              hr_samples.date,
              avg(hr_samples.bpm) AS avg_heart_rate,
              max(hr_samples.bpm) AS max_heart_rate,
              min(hr_samples.bpm) AS min_heart_rate,
              avg(CASE WHEN extract(hour from (hr_samples.sample_time AT TIME ZONE COALESCE(hr_samples.timezone, 'UTC'::character varying))) BETWEEN 6 AND 11 THEN hr_samples.bpm END) AS hr_avg_morning,
              avg(CASE WHEN extract(hour from (hr_samples.sample_time AT TIME ZONE COALESCE(hr_samples.timezone, 'UTC'::character varying))) BETWEEN 12 AND 17 THEN hr_samples.bpm END) AS hr_avg_afternoon,
              avg(CASE WHEN extract(hour from (hr_samples.sample_time AT TIME ZONE COALESCE(hr_samples.timezone, 'UTC'::character varying))) BETWEEN 18 AND 23 THEN hr_samples.bpm END) AS hr_avg_evening,
              avg(CASE WHEN extract(hour from (hr_samples.sample_time AT TIME ZONE COALESCE(hr_samples.timezone, 'UTC'::character varying))) BETWEEN 0 AND 5 THEN hr_samples.bpm END) AS hr_avg_night
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
        ), sleep_hrv_samples AS (
         SELECT s_1.patient_id,
            s_1.date,
            ((v_1."values" ->> 'rmssdMillis'::text))::numeric AS rmssd
           FROM sleep_sessions s_1
           JOIN filtered_raw v_1 ON (s_1.patient_id = v_1.patient_id 
                                 AND v_1.metric_type = 'HeartRateVariabilityRmssdRecord'::text
                                 AND v_1.recorded_at >= s_1.start_time 
                                 AND v_1.recorded_at <= s_1.end_time)
        ), sleep_hrv_daily AS (
         SELECT sleep_hrv_samples.patient_id,
            sleep_hrv_samples.date,
            round(avg(sleep_hrv_samples.rmssd), 2) AS hrv_rmssd_avg,
            round(min(sleep_hrv_samples.rmssd), 2) AS hrv_rmssd_min,
            round(max(sleep_hrv_samples.rmssd), 2) AS hrv_rmssd_max
           FROM sleep_hrv_samples
          GROUP BY sleep_hrv_samples.patient_id, sleep_hrv_samples.date
        ), all_hrv_daily AS (
         SELECT filtered_raw.patient_id,
            date_trunc('day'::text, (filtered_raw.recorded_at AT TIME ZONE COALESCE(filtered_raw.timezone, 'UTC'::character varying))) AS date,
            round(avg(((filtered_raw."values" ->> 'rmssdMillis'::text))::numeric), 2) AS hrv_rmssd_avg,
            round(min(((filtered_raw."values" ->> 'rmssdMillis'::text))::numeric), 2) AS hrv_rmssd_min,
            round(max(((filtered_raw."values" ->> 'rmssdMillis'::text))::numeric), 2) AS hrv_rmssd_max
           FROM filtered_raw
          WHERE (filtered_raw.metric_type = 'HeartRateVariabilityRmssdRecord'::text)
            AND (filtered_raw."values" ? 'rmssdMillis')
            AND ((filtered_raw."values" ->> 'rmssdMillis'::text))::numeric > 0
          GROUP BY filtered_raw.patient_id, (date_trunc('day'::text, (filtered_raw.recorded_at AT TIME ZONE COALESCE(filtered_raw.timezone, 'UTC'::character varying))))
        ), hrv_daily AS (
         SELECT 
            COALESCE(sh.patient_id, ah.patient_id) AS patient_id,
            COALESCE(sh.date, ah.date) AS date,
            COALESCE(sh.hrv_rmssd_avg, ah.hrv_rmssd_avg) AS hrv_rmssd_avg,
            COALESCE(sh.hrv_rmssd_min, ah.hrv_rmssd_min) AS hrv_rmssd_min,
            COALESCE(sh.hrv_rmssd_max, ah.hrv_rmssd_max) AS hrv_rmssd_max
           FROM sleep_hrv_daily sh
           FULL JOIN all_hrv_daily ah ON (sh.patient_id = ah.patient_id AND sh.date = ah.date)
        )
  SELECT 
    COALESCE(mob.patient_id, sk.patient_id, o.patient_id, h.patient_id, ox.patient_id, s.patient_id, r.patient_id, sp.patient_id, ms.patient_id, spf.patient_id, hrr.patient_id, tz.patient_id, hrv.patient_id) AS patient_id,
    COALESCE(mob.date, sk.date, o.date, h.date, ox.date, s.date, r.date, sp.date, ms.date, spf.date, hrr.date, tz.date, hrv.date) AS date,
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
        WHEN ((ms.sleep_hours > (0)::numeric) AND (s.patient_id IS NOT NULL)) THEN LEAST(100.0, GREATEST(0.0, (((((COALESCE(s.sleep_stage_2_hours, (0)::numeric) + COALESCE(s.sleep_stage_4_hours, (0)::numeric)) + COALESCE(s.sleep_stage_5_hours, (0)::numeric)) + COALESCE(s.sleep_stage_6_hours, (0)::numeric)) / ms.sleep_hours) * 100.0)))
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
    mob.avg_cadence_spm,
    mob.active_movement_minutes,
    mob.active_hours_count,
    hrv.hrv_rmssd_avg,
    hrv.hrv_rmssd_min,
    hrv.hrv_rmssd_max,
    NOW() AS updated_at
   FROM other_metrics o
     FULL JOIN hr_daily h ON (o.patient_id = h.patient_id AND o.date = h.date)
     FULL JOIN oxy_daily ox ON (COALESCE(o.patient_id, h.patient_id) = ox.patient_id AND COALESCE(o.date, h.date) = ox.date)
     FULL JOIN sleep_daily s ON (COALESCE(o.patient_id, h.patient_id, ox.patient_id) = s.patient_id AND COALESCE(o.date, h.date, ox.date) = s.date)
     FULL JOIN resting_hr r ON (COALESCE(o.patient_id, h.patient_id, ox.patient_id, s.patient_id) = r.patient_id AND COALESCE(o.date, h.date, ox.date, s.date) = r.date)
     FULL JOIN speed_daily sp ON (COALESCE(o.patient_id, h.patient_id, ox.patient_id, s.patient_id, r.patient_id) = sp.patient_id AND COALESCE(o.date, h.date, ox.date, s.date, r.date) = sp.date)
     FULL JOIN merged_sleep ms ON (COALESCE(o.patient_id, h.patient_id, ox.patient_id, s.patient_id, r.patient_id, sp.patient_id) = ms.patient_id AND COALESCE(o.date, h.date, ox.date, s.date, r.date, sp.date) = ms.date)
     FULL JOIN advanced_sleep_metrics adv ON (COALESCE(o.patient_id, h.patient_id, ox.patient_id, s.patient_id, r.patient_id, sp.patient_id, ms.patient_id) = adv.patient_id AND COALESCE(o.date, h.date, ox.date, s.date, r.date, sp.date, ms.date) = adv.date)
     FULL JOIN steps_phone_fallback spf ON (COALESCE(o.patient_id, h.patient_id, ox.patient_id, s.patient_id, r.patient_id, sp.patient_id, ms.patient_id, adv.patient_id) = spf.patient_id AND COALESCE(o.date, h.date, ox.date, s.date, r.date, sp.date, ms.date, adv.date) = spf.date)
     FULL JOIN hrr_daily hrr ON (COALESCE(o.patient_id, h.patient_id, ox.patient_id, s.patient_id, r.patient_id, sp.patient_id, ms.patient_id, adv.patient_id, spf.patient_id) = hrr.patient_id AND COALESCE(o.date, h.date, ox.date, s.date, r.date, sp.date, ms.date, adv.date, spf.date) = hrr.date)
     FULL JOIN skin_temp_daily sk ON (COALESCE(o.patient_id, h.patient_id, ox.patient_id, s.patient_id, r.patient_id, sp.patient_id, ms.patient_id, adv.patient_id, spf.patient_id, hrr.patient_id) = sk.patient_id AND COALESCE(o.date, h.date, ox.date, s.date, r.date, sp.date, ms.date, adv.date, spf.date, hrr.date) = sk.date)
     FULL JOIN tz_daily tz ON (COALESCE(sk.patient_id, o.patient_id, h.patient_id, ox.patient_id, s.patient_id, r.patient_id, sp.patient_id, ms.patient_id, adv.patient_id, spf.patient_id, hrr.patient_id) = tz.patient_id AND COALESCE(sk.date, o.date, h.date, ox.date, s.date, r.date, sp.date, ms.date, adv.date, spf.date, hrr.date) = tz.date)
     FULL JOIN mobility_daily mob ON (COALESCE(tz.patient_id, sk.patient_id, o.patient_id, h.patient_id, ox.patient_id, s.patient_id, r.patient_id, sp.patient_id, ms.patient_id, adv.patient_id, spf.patient_id, hrr.patient_id) = mob.patient_id AND COALESCE(tz.date, sk.date, o.date, h.date, ox.date, s.date, r.date, sp.date, ms.date, adv.date, spf.date, hrr.date) = mob.date)
     FULL JOIN hrv_daily hrv ON (COALESCE(mob.patient_id, tz.patient_id, sk.patient_id, o.patient_id, h.patient_id, ox.patient_id, s.patient_id, r.patient_id, sp.patient_id, ms.patient_id, adv.patient_id, spf.patient_id, hrr.patient_id) = hrv.patient_id AND COALESCE(mob.date, tz.date, sk.date, o.date, h.date, ox.date, s.date, r.date, sp.date, ms.date, adv.date, spf.date, hrr.date) = hrv.date)
    WHERE (p_patient_id IS NULL OR COALESCE(mob.patient_id, sk.patient_id, o.patient_id, h.patient_id, ox.patient_id, s.patient_id, r.patient_id, sp.patient_id, ms.patient_id, spf.patient_id, hrr.patient_id, tz.patient_id, hrv.patient_id) = p_patient_id)
      AND (p_start_date IS NULL OR COALESCE(mob.date, sk.date, o.date, h.date, ox.date, s.date, r.date, sp.date, ms.date, spf.date, hrr.date, tz.date, hrv.date) >= p_start_date)
      AND (p_end_date IS NULL OR COALESCE(mob.date, sk.date, o.date, h.date, ox.date, s.date, r.date, sp.date, ms.date, spf.date, hrr.date, tz.date, hrv.date) <= p_end_date)
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
        avg_cadence_spm = EXCLUDED.avg_cadence_spm,
        active_movement_minutes = EXCLUDED.active_movement_minutes,
        active_hours_count = EXCLUDED.active_hours_count,
        hrv_rmssd_avg = EXCLUDED.hrv_rmssd_avg,
        hrv_rmssd_min = EXCLUDED.hrv_rmssd_min,
        hrv_rmssd_max = EXCLUDED.hrv_rmssd_max,
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
    WHERE vd.patient_id = sub.patient_id AND vd.date = sub.date
      AND (vd.sleep_consistency_pct IS DISTINCT FROM sub.consistency_score 
           OR vd.bedtime_variance_mins IS DISTINCT FROM sub.variance_mins);

    RETURN rows_affected;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

GRANT EXECUTE ON FUNCTION recalculate_vitals_daily(UUID, TIMESTAMP WITHOUT TIME ZONE, TIMESTAMP WITHOUT TIME ZONE) TO authenticated, service_role;

-- ==============================================================================
-- 3. REST SCORE 2.0 TRIGGER FUNCTION (trg_fn_update_zivaa_rest_score)
-- ==============================================================================
CREATE OR REPLACE FUNCTION trg_fn_update_zivaa_rest_score()
RETURNS TRIGGER AS $$
DECLARE
    -- Patient demographics
    v_patient RECORD;
    v_age INTEGER;
    v_target_hours NUMERIC := 7.25;
    
    -- Baselines
    v_baseline_rhr NUMERIC := NULL;
    v_baseline_hrv NUMERIC := NULL;
    v_baseline_rr NUMERIC := NULL;
    
    -- Component points
    v_duration_pts NUMERIC := 0;
    v_quality_pts NUMERIC := 0;
    v_waso_pts NUMERIC := 0;
    v_deep_pts NUMERIC := 0;
    v_rem_pts NUMERIC := 0;
    v_vitals_pts NUMERIC := 0;
    v_rhr_pts NUMERIC := 0;
    v_hrv_pts NUMERIC := NULL;
    v_penalty_pts NUMERIC := 0;
    
    -- Current night vitals
    v_curr_rhr NUMERIC;
    v_curr_hrv NUMERIC;
    v_curr_waso NUMERIC;
    v_curr_deep NUMERIC;
    v_curr_rem NUMERIC;
    
    -- Final score
    v_total_score INTEGER := 0;
BEGIN
    -- 1. Safety check for missing/invalid sleep data
    IF NEW.sleep_hours IS NULL OR NEW.sleep_hours <= 0 THEN
        UPDATE zivaa_score 
        SET rest_score = NULL, rest_breakdown = NULL
        WHERE patient_id = NEW.patient_id AND date = NEW.date::date;
        RETURN NEW;
    END IF;

    -- 2. Fetch patient demographics (DOB & Gender)
    SELECT date_of_birth, gender INTO v_patient
    FROM patients
    WHERE id = NEW.patient_id;

    -- Calculate age safely
    IF v_patient.date_of_birth IS NOT NULL THEN
        BEGIN
            IF v_patient.date_of_birth ~ '^\d{2}-\d{2}-\d{4}$' THEN
                v_age := EXTRACT(YEAR FROM age(CURRENT_DATE, to_date(v_patient.date_of_birth, 'DD-MM-YYYY')))::INTEGER;
            ELSIF v_patient.date_of_birth ~ '^\d{4}-\d{2}-\d{2}$' THEN
                v_age := EXTRACT(YEAR FROM age(CURRENT_DATE, to_date(v_patient.date_of_birth, 'YYYY-MM-DD')))::INTEGER;
            END IF;
        EXCEPTION WHEN OTHERS THEN
            v_age := NULL;
        END;
    END IF;

    -- Determine science-backed sleep duration target (NSF / Duke / Cambridge benchmarks)
    IF v_age IS NOT NULL THEN
        IF v_age >= 75 THEN
            IF LOWER(COALESCE(v_patient.gender, '')) = 'female' THEN
                v_target_hours := 7.00;
            ELSE
                v_target_hours := 6.75;
            END IF;
        ELSIF v_age >= 65 THEN
            IF LOWER(COALESCE(v_patient.gender, '')) = 'female' THEN
                v_target_hours := 7.25;
            ELSE
                v_target_hours := 7.00;
            END IF;
        ELSE -- Age < 65
            IF LOWER(COALESCE(v_patient.gender, '')) = 'female' THEN
                v_target_hours := 7.75;
            ELSE
                v_target_hours := 7.50;
            END IF;
        END IF;
    ELSE
        -- Fallback when age is unknown
        IF LOWER(COALESCE(v_patient.gender, '')) = 'female' THEN
            v_target_hours := 7.50;
        ELSE
            v_target_hours := 7.25;
        END IF;
    END IF;

    -- 3. Fetch 14-day rolling baselines for this patient
    SELECT 
        AVG(COALESCE(resting_heart_rate_calculated, hr_avg_night)),
        AVG(hrv_rmssd_avg),
        AVG(respiratory_rate_avg)
    INTO v_baseline_rhr, v_baseline_hrv, v_baseline_rr
    FROM vitals_daily
    WHERE patient_id = NEW.patient_id 
      AND date >= (NEW.date - INTERVAL '14 days')
      AND date < NEW.date;

    -- 4. PILLAR 1: Adaptive Duration Points (Max 35)
    -- Target is v_target_hours; debt threshold is (v_target_hours - 3.0)
    IF NEW.sleep_hours >= v_target_hours THEN
        v_duration_pts := 35.0;
    ELSIF NEW.sleep_hours <= (v_target_hours - 3.0) THEN
        v_duration_pts := 0.0;
    ELSE
        v_duration_pts := 35.0 * ((NEW.sleep_hours - (v_target_hours - 3.0)) / 3.0);
    END IF;

    -- 5. PILLAR 2: Sleep Architecture & WASO Quality (Max 35)
    v_curr_waso := NEW.waso_mins;
    v_curr_deep := COALESCE(NEW.sleep_stage_5_hours, 0);
    v_curr_rem  := COALESCE(NEW.sleep_stage_6_hours, 0);

    IF v_curr_waso IS NOT NULL THEN
        -- Case 2A: WASO is available from device
        -- WASO (Max 15 pts): <= 30 mins -> 15 pts; 30-75 mins -> 15 down to 0; > 75 mins -> 0 pts
        IF v_curr_waso <= 30.0 THEN
            v_waso_pts := 15.0;
        ELSIF v_curr_waso >= 75.0 THEN
            v_waso_pts := 0.0;
        ELSE
            v_waso_pts := 15.0 * (1.0 - ((v_curr_waso - 30.0) / 45.0));
        END IF;

        -- Deep Sleep (Max 10 pts, target >= 1.0 hr)
        v_deep_pts := LEAST(10.0, (v_curr_deep / 1.0) * 10.0);

        -- REM Sleep (Max 10 pts, target >= 1.5 hrs)
        v_rem_pts := LEAST(10.0, (v_curr_rem / 1.5) * 10.0);

        v_quality_pts := v_waso_pts + v_deep_pts + v_rem_pts;
    ELSIF (v_curr_deep > 0 OR v_curr_rem > 0) THEN
        -- Case 2B: Device tracked sleep stages but no discrete WASO
        -- Redistribute 15 WASO pts to Deep (20 pts max) and REM (15 pts max)
        v_deep_pts := LEAST(20.0, (v_curr_deep / 1.0) * 20.0);
        v_rem_pts  := LEAST(15.0, (v_curr_rem / 1.5) * 15.0);
        v_quality_pts := v_deep_pts + v_rem_pts;
    ELSE
        -- Case 2C: Tracker provides total sleep duration only (no stage breakdown)
        -- Safe clinical default: allocate 25 pts so score isn't unfairly penalised
        v_quality_pts := 25.0;
    END IF;

    -- 6. PILLAR 3: Autonomic Recovery & Vitals (Max 30)
    v_curr_rhr := COALESCE(NEW.resting_heart_rate_calculated, NEW.hr_avg_night);
    v_curr_hrv := NEW.hrv_rmssd_avg;

    -- Fallback for RHR baseline if missing
    IF v_baseline_rhr IS NULL OR v_baseline_rhr <= 0 THEN
        v_baseline_rhr := 65.0; -- Safe population reference
    END IF;

    IF v_curr_hrv IS NOT NULL AND v_curr_hrv > 0 THEN
        -- Case 3A: HRV RMSSD is available (15 pts RHR + 15 pts HRV)
        -- 6.1 RHR recovery (15 pts)
        IF v_curr_rhr IS NOT NULL AND v_curr_rhr > 0 THEN
            IF v_curr_rhr <= v_baseline_rhr THEN
                v_rhr_pts := 15.0;
            ELSIF (v_curr_rhr - v_baseline_rhr) >= 6.0 THEN
                v_rhr_pts := 0.0;
            ELSE
                v_rhr_pts := 15.0 - ((v_curr_rhr - v_baseline_rhr) * 2.5);
            END IF;
        ELSE
            v_rhr_pts := 10.0;
        END IF;

        -- 6.2 HRV RMSSD recovery (15 pts)
        -- Score against personal 14-day rolling baseline
        DECLARE
            v_hrv_ref NUMERIC := v_baseline_hrv;
            v_hrv_ratio NUMERIC;
        BEGIN
            IF v_hrv_ref IS NULL OR v_hrv_ref <= 0 THEN
                -- Age-adjusted default reference if no prior baseline
                IF COALESCE(v_age, 50) >= 65 THEN
                    v_hrv_ref := 25.0;
                ELSE
                    v_hrv_ref := 40.0;
                END IF;
            END IF;

            v_hrv_ratio := v_curr_hrv / v_hrv_ref;
            IF v_hrv_ratio >= 1.0 THEN
                v_hrv_pts := 15.0;
            ELSIF v_hrv_ratio <= 0.70 THEN
                v_hrv_pts := 0.0;
            ELSE
                v_hrv_pts := 15.0 * ((v_hrv_ratio - 0.70) / 0.30);
            END IF;
        END;

        v_vitals_pts := v_rhr_pts + v_hrv_pts;
    ELSE
        -- Case 3B: Wearable does NOT support HRV RMSSD
        -- Graceful Fallback: RHR gets all 30 points (no penalty for missing HRV sensor!)
        IF v_curr_rhr IS NOT NULL AND v_curr_rhr > 0 THEN
            IF v_curr_rhr <= v_baseline_rhr THEN
                v_rhr_pts := 30.0;
            ELSIF (v_curr_rhr - v_baseline_rhr) >= 6.0 THEN
                v_rhr_pts := 0.0;
            ELSE
                v_rhr_pts := 30.0 - ((v_curr_rhr - v_baseline_rhr) * 5.0);
            END IF;
        ELSE
            v_rhr_pts := 25.0;
        END IF;
        v_vitals_pts := v_rhr_pts;
        v_hrv_pts := NULL;
    END IF;

    -- 7. PILLAR 4: Stress & Irregularity Penalties (Up to -30)
    -- Skin temperature delta (nocturnal fever or inflammation)
    IF COALESCE(NEW.skin_temperature_delta, 0) > 0.5 THEN 
        v_penalty_pts := v_penalty_pts + 15.0; 
    END IF;
    
    -- Respiratory rate surge above rolling baseline
    IF v_baseline_rr IS NOT NULL AND v_baseline_rr > 0 AND (COALESCE(NEW.respiratory_rate_avg, v_baseline_rr) - v_baseline_rr) > 1.5 THEN 
        v_penalty_pts := v_penalty_pts + 15.0; 
    END IF;

    -- Extreme Hypersomnia (> 10.5 hrs)
    IF NEW.sleep_hours > 10.5 THEN
        v_penalty_pts := v_penalty_pts + LEAST(15.0, (NEW.sleep_hours - 10.5) * 5.0);
    END IF;

    -- 8. Calculate Final Rest Score (Clamped 0 to 100)
    v_total_score := GREATEST(0, LEAST(100, ROUND(v_duration_pts + v_quality_pts + v_vitals_pts - v_penalty_pts)));

    -- 9. Upsert into zivaa_score with backward compatible + enhanced telemetry
    INSERT INTO zivaa_score (patient_id, date, rest_score, rest_breakdown, updated_at)
    VALUES (
        NEW.patient_id, 
        NEW.date::date, 
        v_total_score,
        jsonb_build_object(
            -- Backward compatibility fields
            'duration_pts', ROUND(v_duration_pts), 
            'quality_pts', ROUND(v_quality_pts), 
            'vitals_pts', ROUND(v_vitals_pts), 
            'penalty_pts', ROUND(v_penalty_pts),
            'sleep_hours', ROUND(NEW.sleep_hours, 2),
            'sleep_efficiency_pct', ROUND(COALESCE(NEW.sleep_efficiency_pct, 0), 1),
            'sleep_stage_5_hours', ROUND(COALESCE(NEW.sleep_stage_5_hours, 0), 2),
            'sleep_stage_6_hours', ROUND(COALESCE(NEW.sleep_stage_6_hours, 0), 2),
            'sleep_stage_5_pct', ROUND(COALESCE(NEW.sleep_stage_5_pct, 0), 1),
            'sleep_stage_6_pct', ROUND(COALESCE(NEW.sleep_stage_6_pct, 0), 1),
            'resting_heart_rate', ROUND(COALESCE(v_curr_rhr, 0), 1),
            'skin_temp_delta', NEW.skin_temperature_delta,
            'respiratory_rate', ROUND(COALESCE(NEW.respiratory_rate_avg, 0), 1),
            
            -- Rest Score 2.0 Enhanced Clinical Fields
            'target_sleep_hours', v_target_hours,
            'patient_age', v_age,
            'patient_gender', v_patient.gender,
            'waso_mins', ROUND(COALESCE(v_curr_waso, 0), 1),
            'waso_pts', ROUND(v_waso_pts),
            'deep_pts', ROUND(v_deep_pts),
            'rem_pts', ROUND(v_rem_pts),
            'rhr_pts', ROUND(v_rhr_pts),
            'rhr_baseline', ROUND(COALESCE(v_baseline_rhr, 0), 1),
            'hrv_rmssd', ROUND(COALESCE(v_curr_hrv, 0), 1),
            'hrv_rmssd_baseline', ROUND(COALESCE(v_baseline_hrv, 0), 1),
            'hrv_pts', CASE WHEN v_hrv_pts IS NOT NULL THEN ROUND(v_hrv_pts) ELSE NULL END
        ),
        NOW()
    )
    ON CONFLICT (patient_id, date) DO UPDATE SET
        rest_score = EXCLUDED.rest_score,
        rest_breakdown = EXCLUDED.rest_breakdown,
        updated_at = NOW();

    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

GRANT EXECUTE ON FUNCTION trg_fn_update_zivaa_rest_score() TO authenticated, service_role;

-- ==============================================================================
-- 4. BIND REST SCORE TRIGGER ON vitals_daily
-- ==============================================================================
DROP TRIGGER IF EXISTS trg_vitals_daily_update_rest_score ON vitals_daily;
CREATE TRIGGER trg_vitals_daily_update_rest_score
AFTER INSERT OR UPDATE OF 
    sleep_hours, 
    waso_mins, 
    sleep_efficiency_pct, 
    sleep_stage_5_hours, 
    sleep_stage_6_hours, 
    sleep_stage_5_pct, 
    sleep_stage_6_pct, 
    resting_heart_rate_calculated, 
    hr_avg_night,
    hrv_rmssd_avg,
    respiratory_rate_avg, 
    skin_temperature_delta
ON vitals_daily
FOR EACH ROW EXECUTE FUNCTION trg_fn_update_zivaa_rest_score();

-- ==============================================================================
-- 5. REGISTER MIGRATION
-- ==============================================================================
INSERT INTO supabase_migrations.schema_migrations (version, name, statements)
VALUES ('20260921021000', '048_rest_score_v2_age_gender_waso_hrv', ARRAY['Rest Score 2.0 Migration'])
ON CONFLICT (version) DO NOTHING;
