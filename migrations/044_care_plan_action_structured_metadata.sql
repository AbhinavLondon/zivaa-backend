-- Migration: 044_care_plan_action_structured_metadata.sql
-- Description: Adds target_body_part and action_metadata to care_plan_actions for upstream structured clinical capture

ALTER TABLE public.care_plan_actions 
ADD COLUMN IF NOT EXISTS target_body_part TEXT NULL,
ADD COLUMN IF NOT EXISTS action_metadata JSONB DEFAULT '{}'::jsonb;

COMMENT ON COLUMN public.care_plan_actions.target_body_part IS 'Clinical/anatomical target: e.g., Knees / Legs, Lower Back, Shoulders / Neck';
COMMENT ON COLUMN public.care_plan_actions.action_metadata IS 'Structured action payload: ui_action_type (FOLLOW_EXERCISE, LOG_VITALS, etc.), exercise_ids, cta_label, target_metric';
