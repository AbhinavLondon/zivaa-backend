-- ==============================================================================
-- MIGRATION 051: FIX REST BREAKDOWN NULL TELEMETRY
-- ==============================================================================
-- Description:
-- Prevents coalescing missing telemetry (sleep stages, WASO, nocturnal RHR, HRV)
-- to 0.0 in rest_breakdown JSONB. When a sensor does not record readings, the 
-- field is stored as NULL so client apps display "No data" rather than "0 bpm", 
-- "0m", or triggering false "Attention" status badges.
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
        IF v_curr_waso <= 30.0 THEN
            v_waso_pts := 15.0;
        ELSIF v_curr_waso >= 75.0 THEN
            v_waso_pts := 0.0;
        ELSE
            v_waso_pts := 15.0 * (1.0 - ((v_curr_waso - 30.0) / 45.0));
        END IF;

        v_deep_pts := LEAST(10.0, (v_curr_deep / 1.0) * 10.0);
        v_rem_pts  := LEAST(10.0, (v_curr_rem / 1.5) * 10.0);
        v_quality_pts := v_waso_pts + v_deep_pts + v_rem_pts;
    ELSIF (v_curr_deep > 0 OR v_curr_rem > 0) THEN
        -- Case 2B: Device tracked sleep stages but no discrete WASO
        v_deep_pts := LEAST(20.0, (v_curr_deep / 1.0) * 20.0);
        v_rem_pts  := LEAST(15.0, (v_curr_rem / 1.5) * 15.0);
        v_quality_pts := v_deep_pts + v_rem_pts;
    ELSE
        -- Case 2C: Tracker provides total sleep duration only (no stage breakdown)
        v_quality_pts := 25.0;
    END IF;

    -- 6. PILLAR 3: Autonomic Recovery & Vitals (Max 30)
    v_curr_rhr := COALESCE(NEW.resting_heart_rate_calculated, NEW.hr_avg_night);
    v_curr_hrv := NEW.hrv_rmssd_avg;

    IF v_baseline_rhr IS NULL OR v_baseline_rhr <= 0 THEN
        v_baseline_rhr := 65.0;
    END IF;

    IF v_curr_hrv IS NOT NULL AND v_curr_hrv > 0 THEN
        -- Case 3A: HRV RMSSD is available (15 pts RHR + 15 pts HRV)
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

        DECLARE
            v_hrv_ref NUMERIC := v_baseline_hrv;
            v_hrv_ratio NUMERIC;
        BEGIN
            IF v_hrv_ref IS NULL OR v_hrv_ref <= 0 THEN
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
    IF COALESCE(NEW.skin_temperature_delta, 0) > 0.5 THEN 
        v_penalty_pts := v_penalty_pts + 15.0; 
    END IF;
    
    IF v_baseline_rr IS NOT NULL AND v_baseline_rr > 0 AND (COALESCE(NEW.respiratory_rate_avg, v_baseline_rr) - v_baseline_rr) > 1.5 THEN 
        v_penalty_pts := v_penalty_pts + 15.0; 
    END IF;

    IF NEW.sleep_hours > 10.5 THEN
        v_penalty_pts := v_penalty_pts + LEAST(15.0, (NEW.sleep_hours - 10.5) * 5.0);
    END IF;

    -- 8. Calculate Final Rest Score (Clamped 0 to 100)
    v_total_score := GREATEST(0, LEAST(100, ROUND(v_duration_pts + v_quality_pts + v_vitals_pts - v_penalty_pts)));

    -- 9. Upsert into zivaa_score with null-safe telemetry
    INSERT INTO zivaa_score (patient_id, date, rest_score, rest_breakdown, updated_at)
    VALUES (
        NEW.patient_id, 
        NEW.date::date, 
        v_total_score,
        jsonb_build_object(
            'duration_pts', ROUND(v_duration_pts), 
            'quality_pts', ROUND(v_quality_pts), 
            'vitals_pts', ROUND(v_vitals_pts), 
            'penalty_pts', ROUND(v_penalty_pts),
            'sleep_hours', ROUND(NEW.sleep_hours, 2),
            'sleep_efficiency_pct', CASE WHEN NEW.sleep_efficiency_pct IS NOT NULL THEN ROUND(NEW.sleep_efficiency_pct, 1) ELSE NULL END,
            'sleep_stage_5_hours', CASE WHEN NEW.sleep_stage_5_hours IS NOT NULL THEN ROUND(NEW.sleep_stage_5_hours, 2) ELSE NULL END,
            'sleep_stage_6_hours', CASE WHEN NEW.sleep_stage_6_hours IS NOT NULL THEN ROUND(NEW.sleep_stage_6_hours, 2) ELSE NULL END,
            'sleep_stage_5_pct', CASE WHEN NEW.sleep_stage_5_pct IS NOT NULL THEN ROUND(NEW.sleep_stage_5_pct, 1) ELSE NULL END,
            'sleep_stage_6_pct', CASE WHEN NEW.sleep_stage_6_pct IS NOT NULL THEN ROUND(NEW.sleep_stage_6_pct, 1) ELSE NULL END,
            'resting_heart_rate', CASE WHEN v_curr_rhr IS NOT NULL AND v_curr_rhr > 0 THEN ROUND(v_curr_rhr, 1) ELSE NULL END,
            'skin_temp_delta', NEW.skin_temperature_delta,
            'respiratory_rate', CASE WHEN NEW.respiratory_rate_avg IS NOT NULL AND NEW.respiratory_rate_avg > 0 THEN ROUND(NEW.respiratory_rate_avg, 1) ELSE NULL END,
            
            -- Rest Score 2.0 Enhanced Clinical Fields
            'target_sleep_hours', v_target_hours,
            'patient_age', v_age,
            'patient_gender', v_patient.gender,
            'waso_mins', CASE WHEN v_curr_waso IS NOT NULL THEN ROUND(v_curr_waso, 1) ELSE NULL END,
            'waso_pts', CASE WHEN v_curr_waso IS NOT NULL THEN ROUND(v_waso_pts) ELSE NULL END,
            'deep_pts', CASE WHEN NEW.sleep_stage_5_hours IS NOT NULL AND NEW.sleep_stage_5_hours > 0 THEN ROUND(v_deep_pts) ELSE NULL END,
            'rem_pts', CASE WHEN NEW.sleep_stage_6_hours IS NOT NULL AND NEW.sleep_stage_6_hours > 0 THEN ROUND(v_rem_pts) ELSE NULL END,
            'rhr_pts', CASE WHEN v_curr_rhr IS NOT NULL AND v_curr_rhr > 0 THEN ROUND(v_rhr_pts) ELSE NULL END,
            'rhr_baseline', CASE WHEN v_baseline_rhr IS NOT NULL AND v_baseline_rhr > 0 THEN ROUND(v_baseline_rhr, 1) ELSE NULL END,
            'hrv_rmssd', CASE WHEN v_curr_hrv IS NOT NULL AND v_curr_hrv > 0 THEN ROUND(v_curr_hrv, 1) ELSE NULL END,
            'hrv_rmssd_baseline', CASE WHEN v_baseline_hrv IS NOT NULL AND v_baseline_hrv > 0 THEN ROUND(v_baseline_hrv, 1) ELSE NULL END,
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
