-- 030_add_patient_medications.sql

CREATE TABLE IF NOT EXISTS public.patient_medications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id UUID NOT NULL REFERENCES public.patients(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    dose TEXT,
    frequency TEXT,
    status TEXT NOT NULL DEFAULT 'Active', -- 'Active', 'Discontinued'
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

ALTER TABLE public.patient_medications ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users can manage their own medications" ON public.patient_medications FOR ALL USING (auth.uid() = patient_id);
