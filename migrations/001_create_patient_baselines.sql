-- Supabase Migration: Create patient_baselines table
-- This table persists per-patient, per-metric baseline values
-- so the insights engine has a stable reference point for deviation detection.

CREATE TABLE IF NOT EXISTS patient_baselines (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id UUID NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    metric_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'calibrating' CHECK (status IN ('calibrating', 'established')),
    baseline_mean FLOAT,
    baseline_std FLOAT,
    baseline_median FLOAT,
    data_points_used INT DEFAULT 0,
    calibration_start DATE,
    established_at TIMESTAMPTZ,
    last_refreshed_at TIMESTAMPTZ DEFAULT NOW(),
    last_data_date DATE,
    window_days INT DEFAULT 30,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (patient_id, metric_name)
);

-- Index for fast lookup by patient
CREATE INDEX idx_patient_baselines_patient ON patient_baselines(patient_id);

-- Add comment for documentation
COMMENT ON TABLE patient_baselines IS 'Persisted per-metric baselines for the insight rules engine. Transitions from calibrating → established once minimum data threshold is met.';
