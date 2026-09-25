-- Migration 053: Add symptom_id and action_id to symptom_intervention_efficacy for relational closed-loop tracking

ALTER TABLE symptom_intervention_efficacy 
ADD COLUMN IF NOT EXISTS symptom_id UUID REFERENCES patient_symptoms(id) ON DELETE CASCADE,
ADD COLUMN IF NOT EXISTS action_id UUID REFERENCES care_plan_actions(id) ON DELETE SET NULL;
