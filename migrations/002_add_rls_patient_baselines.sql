-- =====================================================
-- Migration: Add RLS policies to patient_baselines
-- 
-- Follows Zivaa Security Blueprint §2 (Supabase RLS):
--   - Patient can read their own baselines
--   - Authorised caregiver with 'vitals' permission can read
--   - Only service_role (backend API) can insert/update/delete
--
-- Data Classification: Tier 4 (System/Derived)
--   Baselines are computed statistical summaries (mean, std, median)
--   derived from Tier 1 vitals. They do not contain raw PHI readings
--   but are scoped to patient_id and must be access-controlled.
--
-- Run via: Supabase SQL Editor or supabase db push
-- =====================================================

-- Step 1: Enable RLS on the table
ALTER TABLE patient_baselines ENABLE ROW LEVEL SECURITY;

-- Step 2: Force RLS even for table owners (prevents bypassing via direct connection)
ALTER TABLE patient_baselines FORCE ROW LEVEL SECURITY;

-- =====================================================
-- POLICY: Patient can read their own baselines
-- Matches blueprint pattern: patients_own_data
-- =====================================================
CREATE POLICY "patient_read_own_baselines"
    ON patient_baselines
    FOR SELECT
    USING (patient_id = auth.uid());

-- =====================================================
-- POLICY: Authorised caregiver can read baselines
-- Requires 'vitals' permission + active consent
-- Uses has_caregiver_access() helper from blueprint §2
-- =====================================================
CREATE POLICY "caregiver_read_baselines"
    ON patient_baselines
    FOR SELECT
    USING (has_caregiver_access(patient_id, 'vitals'));

-- =====================================================
-- POLICY: Only backend service role can INSERT baselines
-- The backend computes baselines during insights evaluation
-- and upserts them via service_role key.
-- =====================================================
CREATE POLICY "service_insert_baselines"
    ON patient_baselines
    FOR INSERT
    WITH CHECK (auth.role() = 'service_role');

-- =====================================================
-- POLICY: Only backend service role can UPDATE baselines
-- Baselines are refreshed daily by the insights engine.
-- =====================================================
CREATE POLICY "service_update_baselines"
    ON patient_baselines
    FOR UPDATE
    USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');

-- =====================================================
-- POLICY: Only backend service role can DELETE baselines
-- Used during patient reset / recalibration.
-- =====================================================
CREATE POLICY "service_delete_baselines"
    ON patient_baselines
    FOR DELETE
    USING (auth.role() = 'service_role');

-- =====================================================
-- VERIFICATION: List all policies on the table
-- Run this after applying to confirm policies are active.
-- =====================================================
-- SELECT policyname, cmd, qual, with_check
-- FROM pg_policies
-- WHERE tablename = 'patient_baselines';
