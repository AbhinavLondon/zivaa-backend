-- Migration 047 Rollback: Restore Synchronous Triggers on vitals_raw

DROP TRIGGER IF EXISTS trg_vitals_raw_refresh_insert ON vitals_raw;
CREATE TRIGGER trg_vitals_raw_refresh_insert
AFTER INSERT ON vitals_raw
REFERENCING NEW TABLE AS new_table
FOR EACH STATEMENT
EXECUTE FUNCTION trg_fn_sync_vitals_daily();

DROP TRIGGER IF EXISTS trg_vitals_raw_refresh_update ON vitals_raw;
CREATE TRIGGER trg_vitals_raw_refresh_update
AFTER UPDATE ON vitals_raw
REFERENCING NEW TABLE AS new_table
FOR EACH STATEMENT
EXECUTE FUNCTION trg_fn_sync_vitals_daily();

DROP TRIGGER IF EXISTS trg_vitals_raw_refresh_hourly_insert ON vitals_raw;
CREATE TRIGGER trg_vitals_raw_refresh_hourly_insert
AFTER INSERT ON vitals_raw
REFERENCING NEW TABLE AS new_table
FOR EACH STATEMENT
EXECUTE FUNCTION trg_fn_sync_vitals_hourly();

DROP TRIGGER IF EXISTS trg_vitals_raw_refresh_hourly_update ON vitals_raw;
CREATE TRIGGER trg_vitals_raw_refresh_hourly_update
AFTER UPDATE ON vitals_raw
REFERENCING NEW TABLE AS new_table
FOR EACH STATEMENT
EXECUTE FUNCTION trg_fn_sync_vitals_hourly();
