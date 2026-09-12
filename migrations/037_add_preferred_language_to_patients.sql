-- Migration 037: Add preferred_language column to patients table
ALTER TABLE patients 
ADD COLUMN IF NOT EXISTS preferred_language TEXT DEFAULT 'English';

COMMENT ON COLUMN patients.preferred_language IS 'User preferred UI and communication language (e.g. English, Hindi, Bengali, etc.)';
