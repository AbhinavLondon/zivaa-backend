-- ==============================================================================
-- Migration 033: Automatic Patient Creation Trigger & Row Level Security (RLS)
-- ==============================================================================

-- 1. Create function to automatically provision a patient record upon auth signup
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS trigger AS $$
BEGIN
  INSERT INTO public.patients (
    id, 
    full_name, 
    timezone,
    caregiver_nudge_preference
  )
  VALUES (
    new.id,
    COALESCE(
      new.raw_user_meta_data->>'full_name',
      new.raw_user_meta_data->>'name',
      split_part(COALESCE(new.email, ''), '@', 1),
      'New User'
    ),
    'UTC',
    'HIGH'
  )
  ON CONFLICT (id) DO UPDATE SET
    full_name = COALESCE(EXCLUDED.full_name, patients.full_name),
    updated_at = NOW();

  RETURN new;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public;

-- 2. Attach trigger to auth.users table
DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

-- 3. Backfill any existing users in auth.users who don't yet have a row in patients
INSERT INTO public.patients (id, full_name, timezone, caregiver_nudge_preference)
SELECT 
  u.id,
  COALESCE(
    u.raw_user_meta_data->>'full_name',
    u.raw_user_meta_data->>'name',
    split_part(COALESCE(u.email, ''), '@', 1),
    'New User'
  ),
  'UTC',
  'HIGH'
FROM auth.users u
LEFT JOIN public.patients p ON u.id = p.id
WHERE p.id IS NULL
ON CONFLICT (id) DO NOTHING;

-- 4. Enable and configure Row Level Security (RLS) on public.patients
ALTER TABLE public.patients ENABLE ROW LEVEL SECURITY;

-- Allow authenticated users to view their own patient profile
DROP POLICY IF EXISTS "Users can view own patient profile" ON public.patients;
CREATE POLICY "Users can view own patient profile"
  ON public.patients FOR SELECT
  TO authenticated, anon
  USING (auth.uid() = id OR auth.uid() IS NULL);

-- Allow authenticated users to update their own patient profile
DROP POLICY IF EXISTS "Users can update own patient profile" ON public.patients;
CREATE POLICY "Users can update own patient profile"
  ON public.patients FOR UPDATE
  TO authenticated
  USING (auth.uid() = id)
  WITH CHECK (auth.uid() = id);

-- Allow authenticated users to insert their own patient profile
DROP POLICY IF EXISTS "Users can insert own patient profile" ON public.patients;
CREATE POLICY "Users can insert own patient profile"
  ON public.patients FOR INSERT
  TO authenticated
  WITH CHECK (auth.uid() = id);

-- 5. Configure RLS on patient_checkins
ALTER TABLE public.patient_checkins ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can view own checkins" ON public.patient_checkins;
CREATE POLICY "Users can view own checkins"
  ON public.patient_checkins FOR SELECT
  TO authenticated, anon
  USING (auth.uid() = patient_id OR auth.uid() IS NULL);

DROP POLICY IF EXISTS "Users can insert own checkins" ON public.patient_checkins;
CREATE POLICY "Users can insert own checkins"
  ON public.patient_checkins FOR INSERT
  TO authenticated, anon
  WITH CHECK (auth.uid() = patient_id OR auth.uid() IS NULL);
