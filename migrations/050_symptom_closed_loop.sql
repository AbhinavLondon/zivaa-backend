-- Migration: 050_symptom_closed_loop.sql
-- Description: Adds clinical ontology, anatomical target, SLAs, unified progression logs, and intervention efficacy learning for closed-loop symptom management.

-- 1. Enhance patient_symptoms with clinical ontology, anatomical target, and SLAs
ALTER TABLE public.patient_symptoms
ADD COLUMN IF NOT EXISTS canonical_key TEXT NULL,                -- e.g. 'MSK_LUMBAR_STRAIN'
ADD COLUMN IF NOT EXISTS snomed_code TEXT NULL,                  -- e.g. '279039007'
ADD COLUMN IF NOT EXISTS anatomical_site TEXT NULL,              -- e.g. 'Lower Back', 'Right Knee'
ADD COLUMN IF NOT EXISTS symptom_category TEXT DEFAULT 'MUSCULOSKELETAL', 
ADD COLUMN IF NOT EXISTS expected_resolution_days INT DEFAULT 7,
ADD COLUMN IF NOT EXISTS max_self_care_days INT DEFAULT 14,      -- Clinical stop-loss SLA
ADD COLUMN IF NOT EXISTS checkin_cadence_days INT DEFAULT 3,
ADD COLUMN IF NOT EXISTS trajectory_status TEXT DEFAULT 'IMPROVING', -- 'IMPROVING', 'STAGNANT', 'DETERIORATING', 'ESCALATED'
ADD COLUMN IF NOT EXISTS episode_count INT DEFAULT 1,
ADD COLUMN IF NOT EXISTS red_flag_screened BOOLEAN DEFAULT TRUE;

-- Index for rapid lookup by patient and body part
CREATE INDEX IF NOT EXISTS idx_patient_symptoms_patient_anatomical 
ON public.patient_symptoms(patient_id, anatomical_site) WHERE status IN ('Active', 'Resolving');

-- 2. Enhance symptom_logs as the Unified Clinical Progression Ledger
ALTER TABLE public.symptom_logs
ADD COLUMN IF NOT EXISTS task_id UUID NULL,                      -- Optional FK if logged via UI task completion
ADD COLUMN IF NOT EXISTS source TEXT DEFAULT 'coach_chat',       -- 'daily_plan_ui', 'coach_chat', 'scheduler_checkin'
ADD COLUMN IF NOT EXISTS micro_feedback TEXT NULL,               -- 'better', 'same', 'worse'
ADD COLUMN IF NOT EXISTS severity_score INT NULL;                -- Standardized 0-10 integer scale

CREATE INDEX IF NOT EXISTS idx_symptom_logs_symptom_time 
ON public.symptom_logs(symptom_id, created_at DESC);

-- 3. Patient Intervention Efficacy Learning Table
-- Tracks what non-pharma remedies work or fail for this specific patient's body
CREATE TABLE IF NOT EXISTS public.symptom_intervention_efficacy (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id UUID NOT NULL REFERENCES public.patients(id) ON DELETE CASCADE,
    canonical_key TEXT NOT NULL,                                 -- e.g. 'MSK_KNEE_OA_FLARE'
    symptom_name TEXT NOT NULL,                                  -- e.g. 'Right Knee Pain'
    action_description TEXT NOT NULL,                            -- e.g. 'Warm mustard oil compress'
    positive_relief_count INT DEFAULT 0,
    neutral_relief_count INT DEFAULT 0,
    negative_relief_count INT DEFAULT 0,
    efficacy_ratio FLOAT GENERATED ALWAYS AS (
        CASE WHEN (positive_relief_count + negative_relief_count + neutral_relief_count) = 0 THEN 0.5
        ELSE (positive_relief_count::FLOAT / (positive_relief_count + negative_relief_count + neutral_relief_count)::FLOAT) END
    ) STORED,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL,
    UNIQUE(patient_id, canonical_key, action_description)
);

CREATE INDEX IF NOT EXISTS idx_symptom_efficacy_lookup 
ON public.symptom_intervention_efficacy(patient_id, canonical_key);

-- 4. Enable RLS
ALTER TABLE public.symptom_intervention_efficacy ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies 
        WHERE tablename = 'symptom_intervention_efficacy' 
        AND policyname = 'Users can manage their own symptom efficacy'
    ) THEN
        CREATE POLICY "Users can manage their own symptom efficacy" 
        ON public.symptom_intervention_efficacy FOR ALL USING (auth.uid() = patient_id);
    END IF;
END $$;
