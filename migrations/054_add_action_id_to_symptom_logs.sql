-- Migration 054: Add action_id to symptom_logs for complete relational audit trail
ALTER TABLE public.symptom_logs 
ADD COLUMN IF NOT EXISTS action_id UUID REFERENCES public.care_plan_actions(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_symptom_logs_action_id 
ON public.symptom_logs(action_id);
