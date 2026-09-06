-- Migration 013: Convert why_flagged to JSONB
--
-- Developer Notes:
-- We are upgrading the MedGemma Nudge generator to output a rich structured JSON 
-- object for the "Why We're Nudging You" correlation UI card.
-- This migration converts the plain text column to JSONB safely.

ALTER TABLE nudge_alerts 
ALTER COLUMN why_flagged TYPE jsonb 
USING CASE 
    WHEN why_flagged IS NULL THEN NULL 
    WHEN why_flagged LIKE '{%' OR why_flagged LIKE '[%' THEN why_flagged::jsonb 
    ELSE to_jsonb(why_flagged) 
END;
