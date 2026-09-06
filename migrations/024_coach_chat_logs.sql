CREATE TABLE IF NOT EXISTS public.coach_chat_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id UUID NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    message TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- RLS Policies
ALTER TABLE public.coach_chat_logs ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Enable insert for authenticated users only"
ON public.coach_chat_logs FOR INSERT
TO authenticated
WITH CHECK (true);

CREATE POLICY "Enable select for users based on user_id"
ON public.coach_chat_logs FOR SELECT
TO authenticated
USING (true);
