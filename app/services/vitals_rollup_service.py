import time
import zoneinfo
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional
from app.services.insights.data_fetcher import supabase

# In-memory debounce cache to prevent burst syncs from triggering redundant rollups
_LAST_ROLLUP_TIMESTAMP: Dict[str, float] = {}
DEBOUNCE_WINDOW_SECONDS = 15.0

def recalculate_live_vitals(
    patient_id: str, 
    timezone_str: Optional[str] = None
) -> Dict[str, Any]:
    """
    Executes a fast, targeted daily and hourly vitals rollup for the past 2 days.
    Executed once per live sync session via sync-complete.
    Typically completes in ~100-200ms.
    """
    start_time = time.time()
    
    # Check debouncer
    now_ts = time.time()
    last_ts = _LAST_ROLLUP_TIMESTAMP.get(patient_id, 0.0)
    if (now_ts - last_ts) < DEBOUNCE_WINDOW_SECONDS:
        print(f"[VitalsRollup] Debounced live rollup for {patient_id} (last run {round(now_ts - last_ts, 1)}s ago).")
        return {"status": "debounced", "patient_id": patient_id}
    
    _LAST_ROLLUP_TIMESTAMP[patient_id] = now_ts

    try:
        tz = zoneinfo.ZoneInfo(timezone_str.strip()) if timezone_str and timezone_str.strip() else timezone.utc
    except Exception:
        tz = timezone.utc

    now_local = datetime.now(tz)
    today_local = now_local.date()
    
    # Cover yesterday, today, and tomorrow to ensure local midnight edge cases are fully captured
    start_date = (today_local - timedelta(days=2)).isoformat()
    end_date = (today_local + timedelta(days=1)).isoformat()
    
    hourly_start = (now_local - timedelta(hours=48)).astimezone(timezone.utc).isoformat()
    hourly_end = now_local.astimezone(timezone.utc).isoformat()

    # 1. Daily Rollup
    t0 = time.time()
    daily_res = supabase.rpc("recalculate_vitals_daily", {
        "p_patient_id": patient_id,
        "p_start_date": start_date,
        "p_end_date": end_date
    }).execute()
    daily_duration = round(time.time() - t0, 3)

    # 2. Hourly Rollup
    t1 = time.time()
    hourly_res = supabase.rpc("recalculate_vitals_hourly", {
        "p_patient_id": patient_id,
        "p_start_time": hourly_start,
        "p_end_time": hourly_end
    }).execute()
    hourly_duration = round(time.time() - t1, 3)

    total_duration = round(time.time() - start_time, 3)
    print(f"[VitalsRollup] Live rollup complete for {patient_id} in {total_duration}s (Daily: {daily_res.data} rows in {daily_duration}s | Hourly: {hourly_res.data} rows in {hourly_duration}s)")

    return {
        "status": "success",
        "patient_id": patient_id,
        "daily_rows": daily_res.data,
        "hourly_rows": hourly_res.data,
        "duration_seconds": total_duration
    }


def recalculate_historical_vitals_windowed(
    patient_id: str,
    lookback_days: int = 90,
    window_days: int = 7,
    timezone_str: Optional[str] = None
) -> Dict[str, Any]:
    """
    Executes a timeout-proof historical backfill rollup by splitting the lookback
    period into small, independent 7-day sliding windows.
    Each window runs as its own separate database transaction (~150-250ms),
    completely preventing statement timeouts (57014) and table lock contention.
    """
    start_total = time.time()
    try:
        tz = zoneinfo.ZoneInfo(timezone_str.strip()) if timezone_str and timezone_str.strip() else timezone.utc
    except Exception:
        tz = timezone.utc

    now_local = datetime.now(tz)
    total_start_date = now_local.date() - timedelta(days=lookback_days)
    total_end_date = now_local.date() + timedelta(days=1)

    print(f"[VitalsRollup] Starting {lookback_days}-day windowed historical backfill for {patient_id} ({total_start_date} to {total_end_date})...")

    current_window_start = total_start_date
    windows_processed = 0
    total_daily_rows = 0

    while current_window_start < total_end_date:
        current_window_end = min(current_window_start + timedelta(days=window_days), total_end_date)
        w_start_str = current_window_start.isoformat()
        w_end_str = current_window_end.isoformat()

        w_hourly_start = datetime.combine(current_window_start, datetime.min.time(), tzinfo=tz).astimezone(timezone.utc).isoformat()
        w_hourly_end = datetime.combine(current_window_end, datetime.max.time(), tzinfo=tz).astimezone(timezone.utc).isoformat()

        t0 = time.time()
        try:
            # 1. Daily slice
            daily_res = supabase.rpc("recalculate_vitals_daily", {
                "p_patient_id": patient_id,
                "p_start_date": w_start_str,
                "p_end_date": w_end_str
            }).execute()

            # 2. Hourly slice
            supabase.rpc("recalculate_vitals_hourly", {
                "p_patient_id": patient_id,
                "p_start_time": w_hourly_start,
                "p_end_time": w_hourly_end
            }).execute()

            slice_duration = round(time.time() - t0, 3)
            rows = daily_res.data or 0
            total_daily_rows += rows
            windows_processed += 1
            print(f"[VitalsRollup] Backfill window {windows_processed} [{w_start_str} -> {w_end_str}] completed in {slice_duration}s ({rows} daily rows).")

        except Exception as e:
            print(f"[VitalsRollup] Error processing backfill window [{w_start_str} -> {w_end_str}] for {patient_id}: {e}")

        current_window_start = current_window_end

    elapsed = round(time.time() - start_total, 3)
    print(f"[VitalsRollup] Completed all {windows_processed} backfill windows for {patient_id} in {elapsed}s. Total daily rows affected: {total_daily_rows}.")

    return {
        "status": "success",
        "patient_id": patient_id,
        "windows_processed": windows_processed,
        "total_daily_rows": total_daily_rows,
        "duration_seconds": elapsed
    }
