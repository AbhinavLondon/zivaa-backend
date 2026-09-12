-- Migration 038: Add smoking_status and alcohol_status to patient_plan_setup
ALTER TABLE patient_plan_setup 
ADD COLUMN IF NOT EXISTS smoking_status TEXT DEFAULT 'Non-smoker',
ADD COLUMN IF NOT EXISTS alcohol_status TEXT DEFAULT 'Never / Teetotaler';

COMMENT ON COLUMN patient_plan_setup.smoking_status IS 'Senior self-reported tobacco/smoking status (e.g. Non-smoker, Former smoker, Occasional, Regular)';
COMMENT ON COLUMN patient_plan_setup.alcohol_status IS 'Senior self-reported alcohol consumption frequency (e.g. Never / Teetotaler, Occasional, Moderate, Regular)';
