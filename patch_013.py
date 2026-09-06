import re

with open('migrations/012_advanced_sleep_metrics.sql', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Update header
content = content.replace('-- Migration 012: Advanced Sleep Metrics (Efficiency, Latency, WASO, Awakenings)', '-- Migration 013: Fix Heart Rate Calculations (Resting HR & Heart Rate Recovery)')

# 2. Replace resting_hr block with sleep_hr_samples, rolling_hr, resting_hr
old_resting_hr = '''resting_hr AS (
    SELECT s_1.patient_id,
        s_1.date,
        avg(h_1.bpm) AS heart_rate_recovery_calculated,
        max(h_1.bpm) AS sleep_max_heart_rate
    FROM (sleep_sessions s_1
        JOIN hr_samples h_1 ON (((s_1.patient_id = h_1.patient_id) AND (h_1.sample_time >= s_1.start_time) AND (h_1.sample_time <= s_1.end_time))))
    GROUP BY s_1.patient_id, s_1.date
),'''

new_resting_hr = '''sleep_hr_samples AS (
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
),'''

content = content.replace(old_resting_hr, new_resting_hr)

# 3. Add hrr_daily before the SELECT
old_speed_daily = '''speed_daily AS (
    SELECT speed_samples.patient_id,
        speed_samples.date,
        avg(speed_samples.speed) AS avg_speed
    FROM speed_samples
    GROUP BY speed_samples.patient_id, speed_samples.date
)
SELECT'''

new_hrr_daily = '''speed_daily AS (
    SELECT speed_samples.patient_id,
        speed_samples.date,
        avg(speed_samples.speed) AS avg_speed
    FROM speed_samples
    GROUP BY speed_samples.patient_id, speed_samples.date
),
hrr_daily AS (
    SELECT filtered_raw.patient_id,
        date_trunc('day'::text, filtered_raw.recorded_at) AS date,
        jsonb_agg(jsonb_build_object('bpm', ((filtered_raw."values" ->> 'heart_rate_recovery_bpm'::text))::integer)) AS heart_rate_recovery_calculated
    FROM filtered_raw
    WHERE filtered_raw.metric_type = 'HeartRateRecoveryRecord'::text
    GROUP BY filtered_raw.patient_id, (date_trunc('day'::text, filtered_raw.recorded_at))
)
SELECT'''

content = content.replace(old_speed_daily, new_hrr_daily)

# 4. Fix SELECT list: patient_id
old_select_patient = 'SELECT COALESCE(o.patient_id, h.patient_id, ox.patient_id, s.patient_id, r.patient_id, sp.patient_id, ms.patient_id, spf.patient_id) AS patient_id,'
new_select_patient = 'SELECT COALESCE(o.patient_id, h.patient_id, ox.patient_id, s.patient_id, r.patient_id, sp.patient_id, ms.patient_id, spf.patient_id, hrr.patient_id) AS patient_id,'
content = content.replace(old_select_patient, new_select_patient)

# 5. Fix SELECT list: date
old_select_date = '    COALESCE(o.date, h.date, ox.date, s.date, r.date, sp.date, ms.date, spf.date) AS date,'
new_select_date = '    COALESCE(o.date, h.date, ox.date, s.date, r.date, sp.date, ms.date, spf.date, hrr.date) AS date,'
content = content.replace(old_select_date, new_select_date)

# 6. Fix SELECT list: r.heart_rate_recovery_calculated -> r.resting_heart_rate_calculated
content = content.replace('    r.heart_rate_recovery_calculated,', '    r.resting_heart_rate_calculated,')

# 7. Add hrr.heart_rate_recovery_calculated to SELECT list
old_select_end = '''    o.snoring_events_count,
    o.sit_to_stand_seconds,

    -- --- NEW ADVANCED SLEEP METRICS ---'''
new_select_end = '''    o.snoring_events_count,
    o.sit_to_stand_seconds,
    hrr.heart_rate_recovery_calculated,

    -- --- NEW ADVANCED SLEEP METRICS ---'''
content = content.replace(old_select_end, new_select_end)

# 8. Fix the final JOIN
old_join = '''    FULL JOIN steps_phone_fallback spf ON (((COALESCE(o.patient_id, h.patient_id, ox.patient_id, s.patient_id, r.patient_id, sp.patient_id, ms.patient_id, adv.patient_id) = spf.patient_id) AND (COALESCE(o.date, h.date, ox.date, s.date, r.date, sp.date, ms.date, adv.date) = spf.date)));'''
new_join = '''    FULL JOIN steps_phone_fallback spf ON (((COALESCE(o.patient_id, h.patient_id, ox.patient_id, s.patient_id, r.patient_id, sp.patient_id, ms.patient_id, adv.patient_id) = spf.patient_id) AND (COALESCE(o.date, h.date, ox.date, s.date, r.date, sp.date, ms.date, adv.date) = spf.date)))
    FULL JOIN hrr_daily hrr ON (((COALESCE(o.patient_id, h.patient_id, ox.patient_id, s.patient_id, r.patient_id, sp.patient_id, ms.patient_id, adv.patient_id, spf.patient_id) = hrr.patient_id) AND (COALESCE(o.date, h.date, ox.date, s.date, r.date, sp.date, ms.date, adv.date, spf.date) = hrr.date)));'''
content = content.replace(old_join, new_join)

with open('migrations/013_fix_hr_calculations.sql', 'w', encoding='utf-8') as f:
    f.write(content)
