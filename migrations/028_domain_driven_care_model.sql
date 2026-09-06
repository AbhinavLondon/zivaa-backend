-- 028_domain_driven_care_model.sql

-- 1. Create patient_preferences table
CREATE TABLE IF NOT EXISTS public.patient_preferences (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id UUID NOT NULL REFERENCES public.patients(id) ON DELETE CASCADE,
    domain TEXT NOT NULL DEFAULT 'General', -- e.g., 'Clinical', 'Dietary', 'Logistical', 'Communication', 'Activity'
    constraint_text TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- Enable RLS for patient_preferences
ALTER TABLE public.patient_preferences ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users can manage their own preferences" ON public.patient_preferences FOR ALL USING (auth.uid() = patient_id);
-- (Optional: Add caregiver access policy if applicable in your project)

-- 2. Create patient_symptoms table
CREATE TABLE IF NOT EXISTS public.patient_symptoms (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id UUID NOT NULL REFERENCES public.patients(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Active', -- 'Active', 'Resolving', 'Resolved', 'Chronic'
    severity TEXT NOT NULL DEFAULT 'Mild', -- 'Mild', 'Moderate', 'Severe'
    follow_up_cadence_days INTEGER DEFAULT 3,
    last_followed_up_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL,
    resolved_at TIMESTAMP WITH TIME ZONE
);

-- Enable RLS for patient_symptoms
ALTER TABLE public.patient_symptoms ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users can manage their own symptoms" ON public.patient_symptoms FOR ALL USING (auth.uid() = patient_id);

-- 3. Create care_plan_actions table
CREATE TABLE IF NOT EXISTS public.care_plan_actions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id UUID NOT NULL REFERENCES public.patients(id) ON DELETE CASCADE,
    symptom_id UUID REFERENCES public.patient_symptoms(id) ON DELETE SET NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Suggested', -- 'Suggested', 'Agreed', 'Abandoned'
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- Enable RLS for care_plan_actions
ALTER TABLE public.care_plan_actions ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users can manage their own care actions" ON public.care_plan_actions FOR ALL USING (auth.uid() = patient_id);

-- 4. Migrate existing data from patient_memory
-- Migrate preferences
INSERT INTO public.patient_preferences (id, patient_id, domain, constraint_text, created_at)
SELECT id, patient_id, 'General', fact, created_at
FROM public.patient_memory
WHERE category = 'preference'
ON CONFLICT (id) DO NOTHING;

-- Migrate symptoms (and lifestyle into symptoms for now)
INSERT INTO public.patient_symptoms (id, patient_id, name, status, last_followed_up_at, created_at)
SELECT id, patient_id, fact, COALESCE(status, 'Active'), last_followed_up_at, created_at
FROM public.patient_memory
WHERE category IN ('symptom', 'lifestyle')
ON CONFLICT (id) DO NOTHING;

-- Migrate actions (agreed_action, suggested_action)
INSERT INTO public.care_plan_actions (id, patient_id, symptom_id, description, status, created_at)
SELECT id, patient_id, linked_symptom_id, fact, 
    CASE WHEN category = 'agreed_action' THEN 'Agreed' ELSE 'Suggested' END,
    created_at
FROM public.patient_memory
WHERE category IN ('agreed_action', 'suggested_action')
ON CONFLICT (id) DO NOTHING;

-- We intentionally DO NOT drop public.patient_memory yet, to prevent breaking the live app
-- until the Python backend and Android frontend have fully transitioned.
