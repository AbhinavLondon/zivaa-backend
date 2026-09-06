-- Migration: Add outlier tracking to vitals_raw and set up aggregation trigger

-- 1. Add new columns to vitals_raw
ALTER TABLE vitals_raw
ADD COLUMN IF NOT EXISTS is_outlier BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS cleaned_values JSONB;

-- 2. Create the aggregation function
CREATE OR REPLACE FUNCTION aggregate_vitals_daily()
RETURNS TRIGGER AS $$
DECLARE
    target_date DATE;
    avg_hr NUMERIC;
BEGIN
    -- Only process non-outliers
    IF NEW.is_outlier = TRUE THEN
        RETURN NEW;
    END IF;

    target_date := DATE(NEW.recorded_at);

    -- Calculate averages for heart rate for this patient on this day
    SELECT AVG((cleaned_values->>'bpm')::NUMERIC)
    INTO avg_hr
    FROM vitals_raw
    WHERE patient_id = NEW.patient_id
      AND DATE(recorded_at) = target_date
      AND metric_type = 'heart_rate'
      AND is_outlier = FALSE;

    -- Upsert into vitals_daily
    INSERT INTO vitals_daily (patient_id, date, avg_heart_rate)
    VALUES (NEW.patient_id, target_date, avg_hr)
    ON CONFLICT (patient_id, date)
    DO UPDATE SET
        avg_heart_rate = EXCLUDED.avg_heart_rate;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 3. Attach the trigger to vitals_raw
DROP TRIGGER IF EXISTS trigger_aggregate_vitals_daily ON vitals_raw;
CREATE TRIGGER trigger_aggregate_vitals_daily
AFTER INSERT ON vitals_raw
FOR EACH ROW
EXECUTE FUNCTION aggregate_vitals_daily();
