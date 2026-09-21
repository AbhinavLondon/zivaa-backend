-- Migration 047: Decouple Vitals Ingestion Pipeline & Windowed Aggregation (Option A)
--
-- Architectural Changes:
-- 1. Drops synchronous statement-level triggers on `vitals_raw`
--    (trg_vitals_raw_refresh_insert, trg_vitals_raw_refresh_update,
--     trg_vitals_raw_refresh_hourly_insert, trg_vitals_raw_refresh_hourly_update)
--    This eliminates HTTP 500 errors, statement timeouts (57014), and index lock timeouts (55P03)
--    during batch vitals upload from Android Health Connect.
-- 2. Preserves `recalculate_vitals_daily` and `recalculate_vitals_hourly` as independent RPC functions.
-- 3. Grants execute permissions to authenticated and service_role.
-- 4. Creates helper function `recalculate_vitals_windowed` for timeout-proof 7-day sliding window backfills.

-- Step 1: Drop statement-level triggers on vitals_raw
DROP TRIGGER IF EXISTS trg_vitals_raw_refresh_insert ON vitals_raw;
DROP TRIGGER IF EXISTS trg_vitals_raw_refresh_update ON vitals_raw;
DROP TRIGGER IF EXISTS trg_vitals_raw_refresh_hourly_insert ON vitals_raw;
DROP TRIGGER IF EXISTS trg_vitals_raw_refresh_hourly_update ON vitals_raw;

-- Step 2: Grant execute permissions on RPC calculation functions
GRANT EXECUTE ON FUNCTION recalculate_vitals_daily(UUID, TIMESTAMP WITHOUT TIME ZONE, TIMESTAMP WITHOUT TIME ZONE) TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION recalculate_vitals_hourly(UUID, TIMESTAMPTZ, TIMESTAMPTZ) TO authenticated, service_role;

-- Step 3: Helper function for server-side sliding window historical rollups
CREATE OR REPLACE FUNCTION recalculate_vitals_windowed(
    p_patient_id UUID,
    p_start_date TIMESTAMP WITHOUT TIME ZONE,
    p_end_date TIMESTAMP WITHOUT TIME ZONE,
    p_window_days INTEGER DEFAULT 7
)
RETURNS TABLE (
    window_start TIMESTAMP WITHOUT TIME ZONE,
    window_end TIMESTAMP WITHOUT TIME ZONE,
    rows_affected INTEGER
) AS $$
DECLARE
    curr_start TIMESTAMP WITHOUT TIME ZONE := p_start_date;
    curr_end TIMESTAMP WITHOUT TIME ZONE;
    affected INTEGER;
BEGIN
    WHILE curr_start < p_end_date LOOP
        curr_end := LEAST(curr_start + (p_window_days || ' days')::INTERVAL, p_end_date);
        
        -- Execute single-window daily rollup (~150ms)
        affected := recalculate_vitals_daily(p_patient_id, curr_start, curr_end);
        
        -- Execute single-window hourly rollup
        PERFORM recalculate_vitals_hourly(
            p_patient_id, 
            curr_start AT TIME ZONE 'UTC', 
            curr_end AT TIME ZONE 'UTC'
        );
        
        window_start := curr_start;
        window_end := curr_end;
        rows_affected := affected;
        RETURN NEXT;
        
        curr_start := curr_end;
    END LOOP;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

GRANT EXECUTE ON FUNCTION recalculate_vitals_windowed(UUID, TIMESTAMP WITHOUT TIME ZONE, TIMESTAMP WITHOUT TIME ZONE, INTEGER) TO authenticated, service_role;
