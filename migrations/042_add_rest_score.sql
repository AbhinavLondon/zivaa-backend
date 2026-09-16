-- Migration 042: Add Rest Score

-- 1. Schema Update
ALTER TABLE zivaa_score 
ADD COLUMN IF NOT EXISTS rest_score INTEGER CHECK (rest_score >= 0 AND rest_score <= 100),
ADD COLUMN IF NOT EXISTS rest_breakdown JSONB;

-- 2. Trigger Function
CREATE OR REPLACE FUNCTION trg_fn_update_zivaa_rest_score()
RETURNS TRIGGER AS $$
DECLARE
    v_baseline_rhr NUMERIC := 0;
    v_baseline_rr NUMERIC := 0;
    v_duration_pts NUMERIC := 0;
    v_quality_pts NUMERIC := 0;
    v_vitals_pts NUMERIC := 0;
    v_penalty_pts NUMERIC := 0;
    v_total_score INTEGER := 0;
BEGIN
    -- 1. Fetch 14-day rolling baselines for this patient
    SELECT AVG(resting_heart_rate_calculated), AVG(respiratory_rate_avg)
    INTO v_baseline_rhr, v_baseline_rr
    FROM vitals_daily
    WHERE patient_id = NEW.patient_id 
      AND date >= (NEW.date - INTERVAL '14 days')
      AND date < NEW.date;

    -- 1.5. Safety check for missing data
    IF NEW.sleep_hours IS NULL OR NEW.sleep_hours <= 0 THEN
        -- No sleep tracked, so a Rest Score cannot be accurately calculated.
        -- Update the record to null out the rest score instead of giving a 0.
        UPDATE zivaa_score 
        SET rest_score = NULL, rest_breakdown = NULL
        WHERE patient_id = NEW.patient_id AND date = NEW.date;
        RETURN NEW;
    END IF;

    -- 2. Duration Points (Max 40)
    v_duration_pts := LEAST((COALESCE(NEW.sleep_hours, 0) / 8.0) * 40.0, 40.0);

    -- 3. Quality Points (Max 30)
    -- Target 1.5 hours of Deep (Stage 5) and 1.5 hours of REM (Stage 6)
    v_quality_pts := (COALESCE(NEW.sleep_efficiency_pct, 0) / 100.0 * 10.0) 
                   + LEAST((COALESCE(NEW.sleep_stage_5_hours, 0) / 1.5) * 10.0, 10.0)
                   + LEAST((COALESCE(NEW.sleep_stage_6_hours, 0) / 1.5) * 10.0, 10.0);

    -- 4. Vitals Points (Max 30)
    IF v_baseline_rhr IS NOT NULL AND v_baseline_rhr > 0 THEN
        v_vitals_pts := GREATEST(0.0, 30.0 - (GREATEST(0.0, COALESCE(NEW.resting_heart_rate_calculated, v_baseline_rhr) - v_baseline_rhr) * 3.0));
    ELSE
        v_vitals_pts := 30.0;
    END IF;

    -- 5. Stress Penalties
    IF COALESCE(NEW.skin_temperature_delta, 0) > 0.5 THEN 
        v_penalty_pts := v_penalty_pts + 15.0; 
    END IF;
    
    IF v_baseline_rr IS NOT NULL AND v_baseline_rr > 0 AND (COALESCE(NEW.respiratory_rate_avg, v_baseline_rr) - v_baseline_rr) > 1.5 THEN 
        v_penalty_pts := v_penalty_pts + 15.0; 
    END IF;

    -- 6. Calculate Final Score
    v_total_score := GREATEST(0, LEAST(100, ROUND(v_duration_pts + v_quality_pts + v_vitals_pts - v_penalty_pts)));

    -- 7. Upsert into zivaa_score
    INSERT INTO zivaa_score (patient_id, date, rest_score, rest_breakdown, updated_at)
    VALUES (
        NEW.patient_id, NEW.date, v_total_score,
        jsonb_build_object(
            'duration_pts', ROUND(v_duration_pts), 
            'quality_pts', ROUND(v_quality_pts), 
            'vitals_pts', ROUND(v_vitals_pts), 
            'penalty_pts', ROUND(v_penalty_pts),
            'sleep_hours', NEW.sleep_hours,
            'sleep_efficiency_pct', NEW.sleep_efficiency_pct,
            'sleep_stage_5_pct', NEW.sleep_stage_5_pct,
            'sleep_stage_6_pct', NEW.sleep_stage_6_pct,
            'resting_heart_rate', NEW.resting_heart_rate_calculated,
            'skin_temp_delta', NEW.skin_temperature_delta,
            'respiratory_rate', NEW.respiratory_rate_avg
        ),
        NOW()
    )
    ON CONFLICT (patient_id, date) DO UPDATE SET
        rest_score = EXCLUDED.rest_score,
        rest_breakdown = EXCLUDED.rest_breakdown,
        updated_at = NOW();

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 3. Bind the trigger
DROP TRIGGER IF EXISTS trg_vitals_daily_update_rest_score ON vitals_daily;
CREATE TRIGGER trg_vitals_daily_update_rest_score
AFTER INSERT OR UPDATE OF sleep_hours, sleep_efficiency_pct, sleep_stage_5_pct, sleep_stage_6_pct, resting_heart_rate_calculated, respiratory_rate_avg, skin_temperature_delta
ON vitals_daily
FOR EACH ROW EXECUTE FUNCTION trg_fn_update_zivaa_rest_score();

-- 4. Backfill historical scores
DO $$
DECLARE
    r RECORD;
    v_baseline_rhr NUMERIC;
    v_baseline_rr NUMERIC;
    v_duration_pts NUMERIC;
    v_quality_pts NUMERIC;
    v_vitals_pts NUMERIC;
    v_penalty_pts NUMERIC;
    v_total_score INTEGER;
BEGIN
    FOR r IN SELECT * FROM vitals_daily LOOP
        SELECT AVG(resting_heart_rate_calculated), AVG(respiratory_rate_avg)
        INTO v_baseline_rhr, v_baseline_rr
        FROM vitals_daily
        WHERE patient_id = r.patient_id 
          AND date >= (r.date - INTERVAL '14 days')
          AND date < r.date;

        -- 1.5. Safety check for missing data
        IF r.sleep_hours IS NULL OR r.sleep_hours <= 0 THEN
            UPDATE zivaa_score 
            SET rest_score = NULL, rest_breakdown = NULL
            WHERE patient_id = r.patient_id AND date = r.date;
            CONTINUE;
        END IF;

        v_duration_pts := LEAST((COALESCE(r.sleep_hours, 0) / 8.0) * 40.0, 40.0);
        v_quality_pts := (COALESCE(r.sleep_efficiency_pct, 0) / 100.0 * 10.0) 
                       + LEAST((COALESCE(r.sleep_stage_5_hours, 0) / 1.5) * 10.0, 10.0)
                       + LEAST((COALESCE(r.sleep_stage_6_hours, 0) / 1.5) * 10.0, 10.0);
        
        IF v_baseline_rhr IS NOT NULL AND v_baseline_rhr > 0 THEN
            v_vitals_pts := GREATEST(0.0, 30.0 - (GREATEST(0.0, COALESCE(r.resting_heart_rate_calculated, v_baseline_rhr) - v_baseline_rhr) * 3.0));
        ELSE
            v_vitals_pts := 30.0;
        END IF;

        v_penalty_pts := 0;
        IF COALESCE(r.skin_temperature_delta, 0) > 0.5 THEN 
            v_penalty_pts := v_penalty_pts + 15.0; 
        END IF;
        
        IF v_baseline_rr IS NOT NULL AND v_baseline_rr > 0 AND (COALESCE(r.respiratory_rate_avg, v_baseline_rr) - v_baseline_rr) > 1.5 THEN 
            v_penalty_pts := v_penalty_pts + 15.0; 
        END IF;

        v_total_score := GREATEST(0, LEAST(100, ROUND(v_duration_pts + v_quality_pts + v_vitals_pts - v_penalty_pts)));

        INSERT INTO zivaa_score (patient_id, date, rest_score, rest_breakdown, updated_at)
        VALUES (
            r.patient_id, r.date, v_total_score,
            jsonb_build_object(
                'duration_pts', ROUND(v_duration_pts), 
                'quality_pts', ROUND(v_quality_pts), 
                'vitals_pts', ROUND(v_vitals_pts), 
                'penalty_pts', ROUND(v_penalty_pts),
                'sleep_hours', r.sleep_hours,
                'sleep_efficiency_pct', r.sleep_efficiency_pct,
                'sleep_stage_5_hours', r.sleep_stage_5_hours,
                'sleep_stage_6_hours', r.sleep_stage_6_hours,
                'resting_heart_rate', r.resting_heart_rate_calculated,
                'skin_temp_delta', r.skin_temperature_delta,
                'respiratory_rate', r.respiratory_rate_avg
            ),
            NOW()
        )
        ON CONFLICT (patient_id, date) DO UPDATE SET
            rest_score = EXCLUDED.rest_score,
            rest_breakdown = EXCLUDED.rest_breakdown,
            updated_at = NOW();
    END LOOP;
END;
$$;
