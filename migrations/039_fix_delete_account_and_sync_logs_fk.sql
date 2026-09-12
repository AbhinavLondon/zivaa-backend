-- Migration 039: Fix delete_user_account and sync_logs foreign key constraint
-- Resolves foreign key violation "sync_logs_patient_id_fkey" when deleting an account

-- 1. Ensure sync_logs foreign key cascades on patient deletion
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.table_constraints 
        WHERE constraint_name = 'sync_logs_patient_id_fkey'
    ) THEN
        ALTER TABLE public.sync_logs DROP CONSTRAINT sync_logs_patient_id_fkey;
    END IF;
    
    ALTER TABLE public.sync_logs
        ADD CONSTRAINT sync_logs_patient_id_fkey
        FOREIGN KEY (patient_id)
        REFERENCES public.patients(id)
        ON DELETE CASCADE;
END $$;

-- 2. Ensure coach_chat_logs cascades on patient deletion if FK exists
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.table_constraints 
        WHERE constraint_name = 'coach_chat_logs_patient_id_fkey'
    ) THEN
        ALTER TABLE public.coach_chat_logs DROP CONSTRAINT coach_chat_logs_patient_id_fkey;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.tables 
        WHERE table_schema = 'public' AND table_name = 'coach_chat_logs'
    ) THEN
        ALTER TABLE public.coach_chat_logs
            ADD CONSTRAINT coach_chat_logs_patient_id_fkey
            FOREIGN KEY (patient_id)
            REFERENCES public.patients(id)
            ON DELETE CASCADE;
    END IF;
END $$;

-- 3. Robust delete_user_account() RPC that safely purges all patient data and auth user
CREATE OR REPLACE FUNCTION public.delete_user_account()
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, auth
AS $$
DECLARE
    v_user_id UUID;
BEGIN
    v_user_id := auth.uid();
    IF v_user_id IS NULL THEN
        RAISE EXCEPTION 'Not authenticated';
    END IF;

    -- Explicitly clean up all dependent tables first to prevent any foreign key violation
    DELETE FROM public.sync_logs WHERE patient_id = v_user_id;
    DELETE FROM public.coach_chat_logs WHERE patient_id = v_user_id;
    DELETE FROM public.nudge_alerts WHERE patient_id = v_user_id;
    DELETE FROM public.device_tokens WHERE patient_id = v_user_id;
    DELETE FROM public.vitals_raw WHERE patient_id = v_user_id;
    DELETE FROM public.vitals_daily WHERE patient_id = v_user_id;
    DELETE FROM public.vitals_hourly WHERE patient_id = v_user_id;
    DELETE FROM public.patient_plan_setup WHERE patient_id = v_user_id;
    DELETE FROM public.daily_plans WHERE patient_id = v_user_id;
    DELETE FROM public.patient_checkins WHERE patient_id = v_user_id;
    DELETE FROM public.user_insights WHERE patient_id = v_user_id;
    DELETE FROM public.conditions WHERE patient_id = v_user_id;
    DELETE FROM public.caregivers WHERE patient_id = v_user_id;
    DELETE FROM public.patient_baselines WHERE patient_id = v_user_id;
    DELETE FROM public.patient_longevity_baselines WHERE patient_id = v_user_id;
    DELETE FROM public.patient_longevity_protocols WHERE patient_id = v_user_id;
    DELETE FROM public.symptom_logs WHERE patient_id = v_user_id;
    DELETE FROM public.patient_medications WHERE patient_id = v_user_id;
    DELETE FROM public.daily_morning_briefings WHERE patient_id = v_user_id;

    -- Delete patient profile
    DELETE FROM public.patients WHERE id = v_user_id;

    -- Delete user from Supabase Auth
    DELETE FROM auth.users WHERE id = v_user_id;
END;
$$;

GRANT EXECUTE ON FUNCTION public.delete_user_account() TO authenticated;
