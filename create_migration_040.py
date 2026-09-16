import sys

with open('migrations/036_add_sleep_consistency_to_vitals_daily.sql', 'r', encoding='utf-8') as f:
    text = f.read()

header = """-- Migration 040: Add mobility KPIs (avg_cadence_spm, active_movement_minutes, active_hours_count) to vitals_daily
--
-- Adds:
-- 1. avg_cadence_spm (NUMERIC): Average walking cadence (steps/min) across sustained walking bouts
-- 2. active_movement_minutes (NUMERIC): Total duration (in minutes) of active walking bouts
-- 3. active_hours_count (INTEGER): Number of daytime waking hours (8 AM - 8 PM) with >= 150 steps
--
-- All changes are additive and preserve all existing columns.

-- Step 1: Add new mobility columns to vitals_daily table
ALTER TABLE vitals_daily 
ADD COLUMN IF NOT EXISTS avg_cadence_spm NUMERIC,
ADD COLUMN IF NOT EXISTS active_movement_minutes NUMERIC,
ADD COLUMN IF NOT EXISTS active_hours_count INTEGER;
"""

old_header_end = text.find('-- Step 2: Replace recalculate_vitals_daily')
body = text[old_header_end:]

insert_target = '        final_wakeup_time,\n        timezone,\n        updated_at'
insert_repl = '        final_wakeup_time,\n        timezone,\n        avg_cadence_spm,\n        active_movement_minutes,\n        active_hours_count,\n        updated_at'
assert insert_target in body, 'insert_target not found'
body = body.replace(insert_target, insert_repl, 1)

tz_target = "        ), steps_phone_fallback AS ("
mobility_cte = """        ), mobility_daily AS (
          SELECT v.patient_id,
            date_trunc('day'::text, (v.recorded_at AT TIME ZONE COALESCE(v.timezone, 'UTC'::character varying))) AS date,
            round(sum(
                CASE 
                    WHEN (v."values" ? 'duration_seconds') 
                         AND ((v."values" ->> 'duration_seconds'::text))::numeric > 0 
                         AND ((v."values" ->> 'duration_seconds'::text))::numeric <= 600
                    THEN ((v."values" ->> 'duration_seconds'::text))::numeric / 60.0
                    ELSE 0::numeric
                END
            ), 1) AS active_movement_minutes,
            CASE 
                WHEN sum(
                    CASE 
                        WHEN (v."values" ? 'duration_seconds') 
                             AND ((v."values" ->> 'duration_seconds'::text))::numeric >= 15
                             AND ((v."values" ->> 'duration_seconds'::text))::numeric <= 600
                             AND ((v."values" ->> 'count'::text))::numeric >= 10
                        THEN ((v."values" ->> 'duration_seconds'::text))::numeric
                        ELSE 0::numeric
                    END
                ) >= 30
                THEN round(
                    sum(
                        CASE 
                            WHEN (v."values" ? 'duration_seconds') 
                                 AND ((v."values" ->> 'duration_seconds'::text))::numeric >= 15
                                 AND ((v."values" ->> 'duration_seconds'::text))::numeric <= 600
                                 AND ((v."values" ->> 'count'::text))::numeric >= 10
                            THEN ((v."values" ->> 'count'::text))::numeric
                            ELSE 0::numeric
                        END
                    ) / 
                    (sum(
                        CASE 
                            WHEN (v."values" ? 'duration_seconds') 
                                 AND ((v."values" ->> 'duration_seconds'::text))::numeric >= 15
                                 AND ((v."values" ->> 'duration_seconds'::text))::numeric <= 600
                                 AND ((v."values" ->> 'count'::text))::numeric >= 10
                            THEN ((v."values" ->> 'duration_seconds'::text))::numeric / 60.0
                            ELSE 0::numeric
                        END
                    ))
                )
                ELSE NULL::numeric
            END AS avg_cadence_spm,
            (
                SELECT count(DISTINCT sub_h.h)
                FROM (
                    SELECT EXTRACT(HOUR FROM (v2.recorded_at AT TIME ZONE COALESCE(v2.timezone, 'UTC'::character varying))) AS h
                    FROM filtered_raw v2
                    WHERE v2.patient_id = v.patient_id
                      AND date_trunc('day'::text, (v2.recorded_at AT TIME ZONE COALESCE(v2.timezone, 'UTC'::character varying))) = 
                          date_trunc('day'::text, (v.recorded_at AT TIME ZONE COALESCE(v.timezone, 'UTC'::character varying)))
                      AND v2.metric_type = 'StepsRecord'::text
                      AND (
                          CASE 
                              WHEN v2."values" ? 'duration_seconds' 
                              THEN ((v2."values" ->> 'duration_seconds'::text))::numeric <= 3600
                              ELSE NOT (v2.source ~~ like_escape('%shealth%'::text, '\\'::text))
                          END
                      )
                      AND EXTRACT(HOUR FROM (v2.recorded_at AT TIME ZONE COALESCE(v2.timezone, 'UTC'::character varying))) BETWEEN 8 AND 20
                    GROUP BY EXTRACT(HOUR FROM (v2.recorded_at AT TIME ZONE COALESCE(v2.timezone, 'UTC'::character varying)))
                    HAVING sum(((v2."values" ->> 'count'::text))::numeric) >= 150
                ) sub_h
            ) AS active_hours_count
          FROM filtered_raw v
          WHERE v.metric_type = 'StepsRecord'::text
          GROUP BY v.patient_id, (date_trunc('day'::text, (v.recorded_at AT TIME ZONE COALESCE(v.timezone, 'UTC'::character varying))))
        ), steps_phone_fallback AS ("""

assert tz_target in body, 'tz_target not found'
body = body.replace(tz_target, mobility_cte, 1)

select_target = """    COALESCE(adv.final_wakeup, ms.session_end) AS final_wakeup_time,
    COALESCE(tz.timezone, ms.timezone) AS timezone,
    NOW() AS updated_at"""
select_repl = """    COALESCE(adv.final_wakeup, ms.session_end) AS final_wakeup_time,
    COALESCE(tz.timezone, ms.timezone) AS timezone,
    mob.avg_cadence_spm,
    mob.active_movement_minutes,
    mob.active_hours_count,
    NOW() AS updated_at"""
assert select_target in body, 'select_target not found'
body = body.replace(select_target, select_repl, 1)

join_target = """     FULL JOIN tz_daily tz ON (COALESCE(sk.patient_id, o.patient_id, h.patient_id, ox.patient_id, s.patient_id, r.patient_id, sp.patient_id, ms.patient_id, adv.patient_id, spf.patient_id, hrr.patient_id) = tz.patient_id AND COALESCE(sk.date, o.date, h.date, ox.date, s.date, r.date, sp.date, ms.date, adv.date, spf.date, hrr.date) = tz.date))"""
join_repl = """     FULL JOIN tz_daily tz ON (COALESCE(sk.patient_id, o.patient_id, h.patient_id, ox.patient_id, s.patient_id, r.patient_id, sp.patient_id, ms.patient_id, adv.patient_id, spf.patient_id, hrr.patient_id) = tz.patient_id AND COALESCE(sk.date, o.date, h.date, ox.date, s.date, r.date, sp.date, ms.date, adv.date, spf.date, hrr.date) = tz.date))
     FULL JOIN mobility_daily mob ON (COALESCE(tz.patient_id, sk.patient_id, o.patient_id, h.patient_id, ox.patient_id, s.patient_id, r.patient_id, sp.patient_id, ms.patient_id, adv.patient_id, spf.patient_id, hrr.patient_id) = mob.patient_id AND COALESCE(tz.date, sk.date, o.date, h.date, ox.date, s.date, r.date, sp.date, ms.date, adv.date, spf.date, hrr.date) = mob.date)"""
assert join_target in body, 'join_target not found'
body = body.replace(join_target, join_repl, 1)

where_target = "COALESCE(sk.patient_id, o.patient_id, h.patient_id, ox.patient_id, s.patient_id, r.patient_id, sp.patient_id, ms.patient_id, spf.patient_id, hrr.patient_id, tz.patient_id)"
where_repl = "COALESCE(mob.patient_id, sk.patient_id, o.patient_id, h.patient_id, ox.patient_id, s.patient_id, r.patient_id, sp.patient_id, ms.patient_id, spf.patient_id, hrr.patient_id, tz.patient_id)"
body = body.replace(where_target, where_repl)

where_date_target = "COALESCE(sk.date, o.date, h.date, ox.date, s.date, r.date, sp.date, ms.date, spf.date, hrr.date, tz.date)"
where_date_repl = "COALESCE(mob.date, sk.date, o.date, h.date, ox.date, s.date, r.date, sp.date, ms.date, spf.date, hrr.date, tz.date)"
body = body.replace(where_date_target, where_date_repl)

conflict_target = """        timezone = COALESCE(EXCLUDED.timezone, vitals_daily.timezone),
        updated_at = NOW();"""
conflict_repl = """        timezone = COALESCE(EXCLUDED.timezone, vitals_daily.timezone),
        avg_cadence_spm = EXCLUDED.avg_cadence_spm,
        active_movement_minutes = EXCLUDED.active_movement_minutes,
        active_hours_count = EXCLUDED.active_hours_count,
        updated_at = NOW();"""
assert conflict_target in body, 'conflict_target not found'
body = body.replace(conflict_target, conflict_repl, 1)

full_sql = header + "\n" + body
with open('migrations/040_add_mobility_kpis_to_vitals_daily.sql', 'w', encoding='utf-8') as f:
    f.write(full_sql)

print('Successfully generated migrations/040_add_mobility_kpis_to_vitals_daily.sql')
