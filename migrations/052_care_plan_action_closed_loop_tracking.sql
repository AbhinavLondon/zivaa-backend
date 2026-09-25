-- Migration 052: Add last_completed_at and completed_count to care_plan_actions for Closed-Loop Tracking

ALTER TABLE care_plan_actions 
ADD COLUMN IF NOT EXISTS last_completed_at TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS completed_count INT DEFAULT 0;
