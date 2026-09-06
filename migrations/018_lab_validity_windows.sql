-- Table for storing biomarker clinical validity windows
CREATE TABLE IF NOT EXISTS public.lab_validity_windows (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    loinc_code TEXT UNIQUE NOT NULL,
    biomarker_name TEXT NOT NULL,
    category TEXT NOT NULL,
    validity_days INTEGER NOT NULL,
    source TEXT,
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Enable RLS
ALTER TABLE public.lab_validity_windows ENABLE ROW LEVEL SECURITY;

-- Allow read access for authenticated users
CREATE POLICY "Enable read access for authenticated users" 
    ON public.lab_validity_windows 
    FOR SELECT 
    TO authenticated 
    USING (true);

-- Allow all access for service role
CREATE POLICY "Enable all access for service role" 
    ON public.lab_validity_windows 
    FOR ALL 
    TO service_role 
    USING (true)
    WITH CHECK (true);
