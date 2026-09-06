-- Migration 014: Convert action_steps to JSONB
--
-- Developer Notes:
-- We are upgrading the Nudge CTA system to support structured, dynamically
-- generated UI cards for recommendations.
-- This migration converts the plain text column to JSONB safely.

ALTER TABLE nudge_alerts 
ALTER COLUMN action_steps TYPE jsonb 
USING CASE 
    WHEN action_steps IS NULL THEN NULL 
    WHEN action_steps LIKE '{%' OR action_steps LIKE '[%' THEN action_steps::jsonb 
    ELSE to_jsonb(action_steps) 
END;
