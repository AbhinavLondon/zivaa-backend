-- Migration 032: Add session_id to coach_chat_logs
ALTER TABLE public.coach_chat_logs 
ADD COLUMN IF NOT EXISTS session_id UUID;

CREATE INDEX IF NOT EXISTS idx_coach_chat_logs_session_id 
ON public.coach_chat_logs(session_id);

CREATE INDEX IF NOT EXISTS idx_coach_chat_logs_patient_session 
ON public.coach_chat_logs(patient_id, session_id, created_at);
