-- Add a JSONB column to store category-level explanations (summaries)
ALTER TABLE fhir_diagnostic_reports
ADD COLUMN IF NOT EXISTS category_level_explanation JSONB DEFAULT '{}'::jsonb;
