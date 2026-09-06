-- Create the device_tokens table to store FCM tokens for push notifications
CREATE TABLE IF NOT EXISTS public.device_tokens (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    patient_id UUID NOT NULL REFERENCES public.patients(id) ON DELETE CASCADE,
    fcm_token TEXT NOT NULL UNIQUE,
    last_updated TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Index for fast lookup by patient_id
CREATE INDEX IF NOT EXISTS idx_device_tokens_patient_id ON public.device_tokens(patient_id);

-- Enable RLS
ALTER TABLE public.device_tokens ENABLE ROW LEVEL SECURITY;

-- Create policies for access (authenticated users can only see/modify their own tokens)
CREATE POLICY "Users can view own device tokens" 
    ON public.device_tokens FOR SELECT 
    USING (auth.uid() = patient_id);

CREATE POLICY "Users can insert own device tokens" 
    ON public.device_tokens FOR INSERT 
    WITH CHECK (auth.uid() = patient_id);

CREATE POLICY "Users can update own device tokens" 
    ON public.device_tokens FOR UPDATE 
    USING (auth.uid() = patient_id);

CREATE POLICY "Users can delete own device tokens" 
    ON public.device_tokens FOR DELETE 
    USING (auth.uid() = patient_id);
