-- 029_add_symptom_logs.sql

CREATE TABLE IF NOT EXISTS public.symptom_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    symptom_id UUID NOT NULL REFERENCES public.patient_symptoms(id) ON DELETE CASCADE,
    patient_id UUID NOT NULL REFERENCES public.patients(id) ON DELETE CASCADE,
    severity TEXT NOT NULL,
    status TEXT NOT NULL,
    note TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

ALTER TABLE public.symptom_logs ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users can manage their own symptom logs" ON public.symptom_logs FOR ALL USING (auth.uid() = patient_id);
