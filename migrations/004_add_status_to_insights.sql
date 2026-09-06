-- Migration 004: Add status tracking to insights
ALTER TABLE active_clinical_insights 
ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'active';
