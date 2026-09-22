-- Migration 049: Add Heart Health Score with RHR, HRV RMSSD, Circadian Dipping, and Dynamic Range
-- Version: 20260921233000

-- ==============================================================================
-- 1. SCHEMA ENHANCEMENT ON zivaa_score
-- ==============================================================================
ALTER TABLE zivaa_score 
ADD COLUMN IF NOT EXISTS heart_score INTEGER CHECK (heart_score >= 0 AND heart_score <= 100),
ADD COLUMN IF NOT EXISTS heart_breakdown JSONB;

-- ==============================================================================
-- 2. CALCULATION CORE FUNCTION (calculate_zivaa_heart_score)
-- ==============================================================================
CREATE OR REPLACE FUNCTION calculate_zivaa_heart_score(p_row vitals_daily)
RETURNS VOID AS $$
DECLARE
    -- Patient demographics
    v_patient RECORD;
    v_age INTEGER := 65;
    
    -- Baselines (14-day rolling)
    v_baseline_rhr NUMERIC := NULL;
    v_baseline_hrv NUMERIC := NULL;
    
    -- Vitals inputs
    v_curr_rhr NUMERIC;
    v_curr_hrv NUMERIC;
    v_day_hr NUMERIC;
    v_night_hr NUMERIC;
    v_dipping_ratio NUMERIC := NULL;
    v_hr_min NUMERIC;
    v_hr_max NUMERIC;
    v_hr_span NUMERIC := 0;
    
    -- Pillar points
    v_rhr_pts NUMERIC := 0;
    v_hrv_pts NUMERIC := NULL;
    v_dipping_pts NUMERIC := 0;
    v_range_pts NUMERIC := 0;
    v_penalty_pts NUMERIC := 0;
    
    -- Final score
    v_total_score INTEGER := 0;
    v_valid_day_count INTEGER := 0;
BEGIN
    -- 1. Safety check for heart rate data presence
    v_curr_rhr := COALESCE(p_row.resting_heart_rate_calculated, p_row.hr_avg_night);
    v_hr_min := p_row.min_heart_rate;
    v_hr_max := p_row.max_heart_rate;

    IF p_row.avg_heart_rate IS NULL AND v_curr_rhr IS NULL AND v_hr_min IS NULL THEN
        UPDATE zivaa_score 
        SET heart_score = NULL, heart_breakdown = NULL
        WHERE patient_id = p_row.patient_id AND date = p_row.date::date;
        RETURN;
    END IF;

    -- 2. Fetch patient demographics (DOB)
    SELECT date_of_birth, gender INTO v_patient
    FROM patients
    WHERE id = p_row.patient_id;

    IF v_patient.date_of_birth IS NOT NULL THEN
        BEGIN
            IF v_patient.date_of_birth ~ '^\d{2}-\d{2}-\d{4}$' THEN
                v_age := EXTRACT(YEAR FROM age(CURRENT_DATE, to_date(v_patient.date_of_birth, 'DD-MM-YYYY')))::INTEGER;
            ELSIF v_patient.date_of_birth ~ '^\d{4}-\d{2}-\d{2}$' THEN
                v_age := EXTRACT(YEAR FROM age(CURRENT_DATE, to_date(v_patient.date_of_birth, 'YYYY-MM-DD')))::INTEGER;
            END IF;
        EXCEPTION WHEN OTHERS THEN
            v_age := 65;
        END;
    END IF;
    IF v_age IS NULL OR v_age <= 0 THEN
        v_age := 65;
    END IF;

    -- 3. Fetch 14-day rolling baselines for RHR and HRV
    SELECT 
        AVG(COALESCE(resting_heart_rate_calculated, hr_avg_night)),
        AVG(hrv_rmssd_avg)
    INTO v_baseline_rhr, v_baseline_hrv
    FROM vitals_daily
    WHERE patient_id = p_row.patient_id 
      AND date >= (p_row.date - INTERVAL '14 days')
      AND date < p_row.date;

    IF v_baseline_rhr IS NULL OR v_baseline_rhr <= 0 THEN
        v_baseline_rhr := 65.0; -- Safe geriatric population reference
    END IF;

    -- 4. PILLAR 1: Resting Heart Rate Stability (30 Points Max)
    IF v_curr_rhr IS NOT NULL AND v_curr_rhr > 0 THEN
        IF v_curr_rhr <= v_baseline_rhr THEN
            v_rhr_pts := 30.0;
        ELSIF (v_curr_rhr - v_baseline_rhr) >= 8.0 THEN
            v_rhr_pts := 0.0;
        ELSE
            v_rhr_pts := 30.0 - ((v_curr_rhr - v_baseline_rhr) * 3.75);
        END IF;
    ELSE
        v_rhr_pts := 22.0;
    END IF;

    -- 5. PILLAR 2: Autonomic Tone / HRV RMSSD (25 Points Max with Sensor Fallback)
    v_curr_hrv := p_row.hrv_rmssd_avg;
    IF v_curr_hrv IS NOT NULL AND v_curr_hrv > 0 THEN
        DECLARE
            v_hrv_ref NUMERIC := v_baseline_hrv;
            v_hrv_ratio NUMERIC;
        BEGIN
            IF v_hrv_ref IS NULL OR v_hrv_ref <= 0 THEN
                IF v_age >= 65 THEN
                    v_hrv_ref := 25.0;
                ELSE
                    v_hrv_ref := 40.0;
                END IF;
            END IF;

            v_hrv_ratio := v_curr_hrv / v_hrv_ref;
            IF v_hrv_ratio >= 1.0 THEN
                v_hrv_pts := 25.0;
            ELSIF v_hrv_ratio <= 0.70 THEN
                v_hrv_pts := 0.0;
            ELSE
                v_hrv_pts := 25.0 * ((v_hrv_ratio - 0.70) / 0.30);
            END IF;
        END;
    ELSE
        -- Fallback: When wearable does not track HRV, gracefully redistribute 25 pts
        -- RHR gets +15 pts (45 max), Circadian Dipping gets +10 pts (35 max)
        v_hrv_pts := NULL;
        v_rhr_pts := v_rhr_pts * (45.0 / 30.0);
    END IF;

    -- 6. PILLAR 3: Circadian Rhythm & Nocturnal Dipping (25 Points Max)
    -- Calculate daytime average HR from morning, afternoon, evening segments
    v_valid_day_count := 0;
    v_day_hr := 0;
    IF p_row.hr_avg_morning IS NOT NULL AND p_row.hr_avg_morning > 0 THEN
        v_day_hr := v_day_hr + p_row.hr_avg_morning;
        v_valid_day_count := v_valid_day_count + 1;
    END IF;
    IF p_row.hr_avg_afternoon IS NOT NULL AND p_row.hr_avg_afternoon > 0 THEN
        v_day_hr := v_day_hr + p_row.hr_avg_afternoon;
        v_valid_day_count := v_valid_day_count + 1;
    END IF;
    IF p_row.hr_avg_evening IS NOT NULL AND p_row.hr_avg_evening > 0 THEN
        v_day_hr := v_day_hr + p_row.hr_avg_evening;
        v_valid_day_count := v_valid_day_count + 1;
    END IF;

    IF v_valid_day_count > 0 THEN
        v_day_hr := v_day_hr / v_valid_day_count;
    ELSE
        v_day_hr := COALESCE(p_row.avg_heart_rate, v_curr_rhr);
    END IF;

    v_night_hr := COALESCE(p_row.hr_avg_night, v_curr_rhr);

    IF v_day_hr IS NOT NULL AND v_day_hr > 30 AND v_night_hr IS NOT NULL AND v_night_hr > 30 THEN
        v_dipping_ratio := (v_day_hr - v_night_hr) / v_day_hr;
        
        -- Normal Dipper: 10% to 22% nocturnal drop
        IF v_dipping_ratio >= 0.10 AND v_dipping_ratio <= 0.22 THEN
            v_dipping_pts := 25.0;
        -- Mild Dipper: 5% to 10% drop
        ELSIF v_dipping_ratio >= 0.05 AND v_dipping_ratio < 0.10 THEN
            v_dipping_pts := 18.0;
        -- Non-Dipper: 0% to 5% drop
        ELSIF v_dipping_ratio >= 0.0 AND v_dipping_ratio < 0.05 THEN
            v_dipping_pts := 8.0;
        -- Reverse Dipper: night HR higher than daytime HR (autonomic / BP risk)
        ELSIF v_dipping_ratio < 0.0 THEN
            v_dipping_pts := 2.0;
        -- Extreme Dipper: > 22% drop (excessive bradycardia)
        ELSE
            v_dipping_pts := 16.0;
        END IF;
    ELSE
        v_dipping_pts := 18.0; -- Neutral fallback
    END IF;

    -- Adjust dipping weight if HRV is absent
    IF v_curr_hrv IS NULL THEN
        v_dipping_pts := v_dipping_pts * (35.0 / 25.0);
    END IF;

    -- 7. PILLAR 4: Cardiovascular Flexibility & Range (20 Points Max)
    IF v_hr_min IS NOT NULL AND v_hr_max IS NOT NULL AND v_hr_max >= v_hr_min THEN
        v_hr_span := v_hr_max - v_hr_min;
        
        -- Optimal Senior Flexibility: 35 to 65 bpm span
        IF v_hr_span >= 35.0 AND v_hr_span <= 65.0 THEN
            v_range_pts := 20.0;
        -- Mildly restricted (25-34) or active sports span (66-75)
        ELSIF (v_hr_span >= 25.0 AND v_hr_span < 35.0) OR (v_hr_span > 65.0 AND v_hr_span <= 75.0) THEN
            v_range_pts := 15.0;
        -- Chronotropic blunting / stiffness (18-24)
        ELSIF v_hr_span >= 18.0 AND v_hr_span < 25.0 THEN
            v_range_pts := 8.0;
        -- Severe cardiac rigidity (< 18 bpm span)
        ELSIF v_hr_span < 18.0 AND v_hr_span > 0.0 THEN
            v_range_pts := 3.0;
        -- Excessive unprovoked volatility (> 75 bpm)
        ELSE
            v_range_pts := 10.0;
        END IF;
    ELSE
        v_range_pts := 14.0;
    END IF;

    -- 8. SAFETY DEDUCTIONS & PENALTIES (Up to -20 Points)
    -- Extreme nocturnal tachycardia
    IF COALESCE(p_row.sleep_max_heart_rate, 0) > 105.0 THEN
        v_penalty_pts := v_penalty_pts + 10.0;
    END IF;

    -- Concurrent nocturnal hypoxia
    IF COALESCE(p_row.oxygen_sat_min, 100.0) < 90.0 THEN
        v_penalty_pts := v_penalty_pts + 10.0;
    END IF;

    -- Unprovoked peak exceeding safe age ceiling
    IF v_hr_max IS NOT NULL AND v_hr_max > ((220 - v_age) * 0.90) THEN
        v_penalty_pts := v_penalty_pts + 8.0;
    END IF;

    -- 9. Final Score Calculation (Clamped 0 to 100)
    v_total_score := GREATEST(0, LEAST(100, ROUND(
        v_rhr_pts + COALESCE(v_hrv_pts, 0.0) + v_dipping_pts + v_range_pts - v_penalty_pts
    )));

    -- 10. Atomically Upsert into zivaa_score
    INSERT INTO zivaa_score (patient_id, date, heart_score, heart_breakdown, updated_at)
    VALUES (
        p_row.patient_id, 
        p_row.date::date, 
        v_total_score,
        jsonb_build_object(
            'heart_score', v_total_score,
            'rhr_pts', ROUND(v_rhr_pts),
            'hrv_pts', CASE WHEN v_hrv_pts IS NOT NULL THEN ROUND(v_hrv_pts) ELSE NULL END,
            'dipping_pts', ROUND(v_dipping_pts),
            'range_pts', ROUND(v_range_pts),
            'penalty_pts', ROUND(v_penalty_pts),
            'resting_heart_rate', ROUND(COALESCE(v_curr_rhr, 0), 1),
            'rhr_baseline', ROUND(COALESCE(v_baseline_rhr, 0), 1),
            'hrv_rmssd', ROUND(COALESCE(v_curr_hrv, 0), 1),
            'hrv_rmssd_baseline', ROUND(COALESCE(v_baseline_hrv, 0), 1),
            'min_heart_rate', ROUND(COALESCE(v_hr_min, 0), 1),
            'max_heart_rate', ROUND(COALESCE(v_hr_max, 0), 1),
            'avg_heart_rate', ROUND(COALESCE(p_row.avg_heart_rate, 0), 1),
            'hr_span', ROUND(COALESCE(v_hr_span, 0), 1),
            'dipping_ratio_pct', ROUND(COALESCE(v_dipping_ratio * 100.0, 0), 1),
            'day_avg_hr', ROUND(COALESCE(v_day_hr, 0), 1),
            'night_avg_hr', ROUND(COALESCE(v_night_hr, 0), 1),
            'patient_age', v_age
        ),
        NOW()
    )
    ON CONFLICT (patient_id, date) DO UPDATE SET
        heart_score = EXCLUDED.heart_score,
        heart_breakdown = EXCLUDED.heart_breakdown,
        updated_at = NOW();
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

GRANT EXECUTE ON FUNCTION calculate_zivaa_heart_score(vitals_daily) TO authenticated, service_role;

-- ==============================================================================
-- 3. BIND HEART SCORE TRIGGER FUNCTION (trg_fn_update_zivaa_heart_score)
-- ==============================================================================
CREATE OR REPLACE FUNCTION trg_fn_update_zivaa_heart_score()
RETURNS TRIGGER AS $$
BEGIN
    PERFORM calculate_zivaa_heart_score(NEW);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

GRANT EXECUTE ON FUNCTION trg_fn_update_zivaa_heart_score() TO authenticated, service_role;

-- Bind Trigger on vitals_daily
DROP TRIGGER IF EXISTS trg_vitals_daily_update_heart_score ON vitals_daily;
CREATE TRIGGER trg_vitals_daily_update_heart_score
AFTER INSERT OR UPDATE OF 
    avg_heart_rate,
    min_heart_rate,
    max_heart_rate,
    resting_heart_rate_calculated,
    hr_avg_morning,
    hr_avg_afternoon,
    hr_avg_evening,
    hr_avg_night,
    hrv_rmssd_avg,
    sleep_max_heart_rate,
    oxygen_sat_min
ON vitals_daily
FOR EACH ROW EXECUTE FUNCTION trg_fn_update_zivaa_heart_score();

-- ==============================================================================
-- 4. BACKFILL HISTORICAL HEART SCORES
-- ==============================================================================
DO $$
DECLARE
    r vitals_daily%ROWTYPE;
BEGIN
    FOR r IN SELECT * FROM vitals_daily WHERE avg_heart_rate IS NOT NULL OR resting_heart_rate_calculated IS NOT NULL LOOP
        PERFORM calculate_zivaa_heart_score(r);
    END LOOP;
END;
$$;

-- ==============================================================================
-- 5. REGISTER MIGRATION (Safe idempotent check)
-- ==============================================================================
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables 
        WHERE table_schema = 'supabase_migrations' AND table_name = 'schema_migrations'
    ) THEN
        INSERT INTO supabase_migrations.schema_migrations (version, name, statements)
        VALUES ('20260921233000', '049_add_heart_health_score', ARRAY['Heart Health Score Migration'])
        ON CONFLICT (version) DO NOTHING;
    END IF;
END;
$$;
