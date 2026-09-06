-- Add effective_datetime to active_clinical_insights to track true clinical date
ALTER TABLE active_clinical_insights ADD COLUMN effective_datetime TIMESTAMPTZ;

-- Backfill existing rows with created_at as a fallback
UPDATE active_clinical_insights SET effective_datetime = created_at WHERE effective_datetime IS NULL;
