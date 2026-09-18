-- Migration: 043_care_plan_action_types.sql
-- Description: Adds action_type and cadence to care_plan_actions for intelligent lifecycle and decay management

ALTER TABLE public.care_plan_actions 
ADD COLUMN IF NOT EXISTS action_type TEXT DEFAULT 'habit', -- 'symptom_relief', 'one_off', 'habit', 'periodic'
ADD COLUMN IF NOT EXISTS cadence TEXT DEFAULT 'daily';     -- 'daily', 'weekly_sunday', 'weekly_wednesday', 'once'

COMMENT ON COLUMN public.care_plan_actions.action_type IS 'Operational classification: symptom_relief, one_off, habit, periodic';
COMMENT ON COLUMN public.care_plan_actions.cadence IS 'Recurrence schedule: daily, weekly_sunday, etc., or once for errands';
