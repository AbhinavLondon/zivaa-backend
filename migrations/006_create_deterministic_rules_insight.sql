CREATE TABLE IF NOT EXISTS public.deterministic_rules_insight (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id UUID NOT NULL,
    rule_id TEXT NOT NULL,
    severity TEXT NOT NULL,
    message TEXT NOT NULL,
    evidence JSONB NOT NULL,
    timestamp TIMESTAMPTZ DEFAULT NOW()
);

-- Enable RLS
ALTER TABLE public.deterministic_rules_insight ENABLE ROW LEVEL SECURITY;
