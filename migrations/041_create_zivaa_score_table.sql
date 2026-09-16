-- Migration 041: Create zivaa_score table and automatic trigger on vitals_daily
--
-- Developer Notes:
-- 1. Creates `zivaa_score` table to store proprietary product/longevity scores (e.g. mobility_score)
--    without polluting `vitals_daily` (preserving pure clinical biomarkers for MedGemma).
-- 2. Adds trigger `trg_vitals_daily_update_zivaa_score` on `vitals_daily` that automatically calculates
--    and upserts `mobility_score` whenever new mobility KPIs arrive.
-- 3. Backfills all historical dates from existing `vitals_daily` rows.

-- Step 1: Create zivaa_score Table
CREATE TABLE IF NOT EXISTS zivaa_score (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id UUID NOT NULL,
    date DATE NOT NULL,
    mobility_score INTEGER CHECK (mobility_score >= 0 AND mobility_score <= 100),
    mobility_breakdown JSONB, -- {"volume": 38, "cadence": 18, "active_time": 20, "regularity": 16}
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT zivaa_score_patient_date_unique UNIQUE (patient_id, date)
);

-- Step 2: Index for efficient patient date lookups
CREATE INDEX IF NOT EXISTS idx_zivaa_score_patient_date ON zivaa_score (patient_id, date DESC);

-- Step 3: Row Level Security (RLS)
ALTER TABLE zivaa_score ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Allow select on zivaa_score" ON zivaa_score;
CREATE POLICY "Allow select on zivaa_score" 
ON zivaa_score FOR SELECT 
TO authenticated, anon 
USING (true);

DROP POLICY IF EXISTS "Allow service role all on zivaa_score" ON zivaa_score;
CREATE POLICY "Allow service role all on zivaa_score" 
ON zivaa_score FOR ALL 
TO service_role 
USING (true)
WITH CHECK (true);

DROP POLICY IF EXISTS "Allow insert update on zivaa_score" ON zivaa_score;
CREATE POLICY "Allow insert update on zivaa_score"
ON zivaa_score FOR ALL
TO authenticated, anon
USING (true)
WITH CHECK (true);

-- Step 4: Auto-Calculation Trigger Function
CREATE OR REPLACE FUNCTION trg_fn_update_zivaa_mobility_score()
RETURNS TRIGGER AS $$
DECLARE
    v_steps NUMERIC := COALESCE(NEW.total_steps, 0);
    v_cadence NUMERIC := COALESCE(NEW.avg_cadence_spm, 0);
    v_mins NUMERIC := COALESCE(NEW.active_movement_minutes, 0);
    v_hours NUMERIC := COALESCE(NEW.active_hours_count, 0);
    v_volume_score NUMERIC := 0;
    v_cadence_score NUMERIC := 0;
    v_active_time_score NUMERIC := 0;
    v_regularity_score NUMERIC := 0;
    v_total_score INTEGER := 0;
BEGIN
    -- 1. Step Volume (40% Weight: 0 to 40 pts, benchmark: 7,000 steps or personal goal)
    v_volume_score := LEAST(40.0, (v_steps / 7000.0) * 40.0);

    -- 2. Walking Cadence (20% Weight: 0 to 20 pts)
    IF v_cadence >= 85 THEN v_cadence_score := 20;
    ELSIF v_cadence >= 70 THEN v_cadence_score := 15;
    ELSIF v_cadence >= 50 THEN v_cadence_score := 10;
    ELSIF v_cadence >= 30 THEN v_cadence_score := 5;
    ELSE v_cadence_score := 2;
    END IF;

    -- 3. Active Moving Time (20% Weight: 0 to 20 pts, target: 30 mins)
    IF v_mins >= 30 THEN v_active_time_score := 20;
    ELSIF v_mins >= 20 THEN v_active_time_score := 15;
    ELSIF v_mins >= 10 THEN v_active_time_score := 10;
    ELSIF v_mins >= 1 THEN v_active_time_score := 5;
    ELSE v_active_time_score := 0;
    END IF;

    -- 4. Movement Regularity (20% Weight: 0 to 20 pts, target: 8 daytime active hours)
    IF v_hours >= 8 THEN v_regularity_score := 20;
    ELSIF v_hours >= 6 THEN v_regularity_score := 15;
    ELSIF v_hours >= 4 THEN v_regularity_score := 10;
    ELSIF v_hours >= 2 THEN v_regularity_score := 5;
    ELSE v_regularity_score := 2;
    END IF;

    v_total_score := ROUND(v_volume_score + v_cadence_score + v_active_time_score + v_regularity_score);
    v_total_score := GREATEST(0, LEAST(100, v_total_score));

    -- Atomically upsert into zivaa_score
    INSERT INTO zivaa_score (patient_id, date, mobility_score, mobility_breakdown, updated_at)
    VALUES (
        NEW.patient_id,
        NEW.date,
        v_total_score,
        jsonb_build_object(
            'volume', ROUND(v_volume_score),
            'cadence', ROUND(v_cadence_score),
            'active_time', ROUND(v_active_time_score),
            'regularity', ROUND(v_regularity_score)
        ),
        NOW()
    )
    ON CONFLICT (patient_id, date) DO UPDATE SET
        mobility_score = EXCLUDED.mobility_score,
        mobility_breakdown = EXCLUDED.mobility_breakdown,
        updated_at = NOW();

    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Step 5: Attach Trigger to vitals_daily
DROP TRIGGER IF EXISTS trg_vitals_daily_update_zivaa_score ON vitals_daily;
CREATE TRIGGER trg_vitals_daily_update_zivaa_score
AFTER INSERT OR UPDATE OF total_steps, avg_cadence_spm, active_movement_minutes, active_hours_count
ON vitals_daily
FOR EACH ROW
EXECUTE FUNCTION trg_fn_update_zivaa_mobility_score();

-- Step 6: Backfill historical scores from vitals_daily
DO $$
DECLARE
    r RECORD;
    v_volume_score NUMERIC;
    v_cadence_score NUMERIC;
    v_active_time_score NUMERIC;
    v_regularity_score NUMERIC;
    v_total_score INTEGER;
    v_steps NUMERIC;
    v_cadence NUMERIC;
    v_mins NUMERIC;
    v_hours NUMERIC;
BEGIN
    FOR r IN SELECT patient_id, date, total_steps, avg_cadence_spm, active_movement_minutes, active_hours_count FROM vitals_daily LOOP
        v_steps := COALESCE(r.total_steps, 0);
        v_cadence := COALESCE(r.avg_cadence_spm, 0);
        v_mins := COALESCE(r.active_movement_minutes, 0);
        v_hours := COALESCE(r.active_hours_count, 0);

        v_volume_score := LEAST(40.0, (v_steps / 7000.0) * 40.0);

        IF v_cadence >= 85 THEN v_cadence_score := 20;
        ELSIF v_cadence >= 70 THEN v_cadence_score := 15;
        ELSIF v_cadence >= 50 THEN v_cadence_score := 10;
        ELSIF v_cadence >= 30 THEN v_cadence_score := 5;
        ELSE v_cadence_score := 2;
        END IF;

        IF v_mins >= 30 THEN v_active_time_score := 20;
        ELSIF v_mins >= 20 THEN v_active_time_score := 15;
        ELSIF v_mins >= 10 THEN v_active_time_score := 10;
        ELSIF v_mins >= 1 THEN v_active_time_score := 5;
        ELSE v_active_time_score := 0;
        END IF;

        IF v_hours >= 8 THEN v_regularity_score := 20;
        ELSIF v_hours >= 6 THEN v_regularity_score := 15;
        ELSIF v_hours >= 4 THEN v_regularity_score := 10;
        ELSIF v_hours >= 2 THEN v_regularity_score := 5;
        ELSE v_regularity_score := 2;
        END IF;

        v_total_score := ROUND(v_volume_score + v_cadence_score + v_active_time_score + v_regularity_score);
        v_total_score := GREATEST(0, LEAST(100, v_total_score));

        INSERT INTO zivaa_score (patient_id, date, mobility_score, mobility_breakdown, updated_at)
        VALUES (
            r.patient_id,
            r.date,
            v_total_score,
            jsonb_build_object(
                'volume', ROUND(v_volume_score),
                'cadence', ROUND(v_cadence_score),
                'active_time', ROUND(v_active_time_score),
                'regularity', ROUND(v_regularity_score)
            ),
            NOW()
        )
        ON CONFLICT (patient_id, date) DO UPDATE SET
            mobility_score = EXCLUDED.mobility_score,
            mobility_breakdown = EXCLUDED.mobility_breakdown,
            updated_at = NOW();
    END LOOP;
END $$;
