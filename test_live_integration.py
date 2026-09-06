"""
Live integration test — runs the InsightEngine against real Supabase data.
"""

import sys
import os
import json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from supabase import create_client
from app.config import settings

print("=" * 70)
print("LIVE INTEGRATION TEST — Insight Engine vs Real Supabase Data")
print("=" * 70)
print()

if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_ROLE_KEY:
    print("ERROR: SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY not set in .env")
    sys.exit(1)

print(f"Supabase URL: {settings.SUPABASE_URL[:40]}...")
print()

sb = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)

# 1. Find all patients (using actual column names)
patients_resp = sb.table("patients").select("id, full_name, gender, date_of_birth").execute()
patients = patients_resp.data

if not patients:
    print("No patients found in the database.")
    sys.exit(0)

print(f"Found {len(patients)} patient(s):")
for p in patients:
    print(f"  - {p.get('full_name', 'Unknown')} (ID: {p['id'][:12]}..., gender: {p.get('gender', 'N/A')})")
print()

# 2. For each patient: show data & run engine
from datetime import datetime, timedelta

for p in patients:
    pid = p["id"]
    pname = p.get("full_name", "Unknown")
    
    print("-" * 70)
    print(f"PATIENT: {pname}")
    print("-" * 70)
    
    # Check vitals
    sixty_days_ago = (datetime.now() - timedelta(days=60)).date().isoformat()
    vitals_resp = sb.table("vitals_daily") \
        .select("*") \
        .eq("patient_id", pid) \
        .gte("date", sixty_days_ago) \
        .order("date") \
        .execute()
    
    vitals = vitals_resp.data
    print(f"  Vitals records (last 60 days): {len(vitals)}")
    
    if vitals:
        metrics_with_data = {}
        for row in vitals:
            for key, val in row.items():
                if key not in ("id", "patient_id", "date", "computed_at", "created_at", "updated_at") and val is not None:
                    if key not in metrics_with_data:
                        metrics_with_data[key] = 0
                    metrics_with_data[key] += 1
        
        print(f"  Metrics with data:")
        for m, count in sorted(metrics_with_data.items()):
            print(f"    {m}: {count} readings")
        
        print(f"  Date range: {vitals[0].get('date', '?')} to {vitals[-1].get('date', '?')}")
        
        # Show latest vitals
        latest = vitals[-1]
        print(f"  Latest vitals ({latest.get('date', '?')}):")
        for key, val in sorted(latest.items()):
            if key not in ("id", "patient_id", "computed_at", "created_at", "updated_at") and val is not None:
                print(f"    {key}: {val}")
    
    # Check labs
    labs_resp = sb.table("lab_results") \
        .select("biomarker_code, biomarker_name, value, flag, measured_at") \
        .eq("patient_id", pid) \
        .order("measured_at", desc=True) \
        .limit(20) \
        .execute()
    print(f"  Lab results: {len(labs_resp.data)}")
    if labs_resp.data:
        for lab in labs_resp.data[:5]:
            print(f"    {lab.get('biomarker_code')}: {lab.get('value')} ({lab.get('flag', 'normal')}) — {lab.get('measured_at', '?')[:10]}")
    
    # Check meds
    try:
        meds_resp = sb.table("medication_logs") \
            .select("*") \
            .eq("patient_id", pid) \
            .gte("scheduled_at", (datetime.now() - timedelta(days=7)).isoformat()) \
            .execute()
        print(f"  Medication logs (7 days): {len(meds_resp.data)}")
    except:
        print("  Medication logs: table not accessible")
    
    print()
    
    # 3. Run the engine
    print("  Running Insight Engine...")
    print()
    
    try:
        from app.services.insights.engine import InsightEngine
        engine = InsightEngine()
        output = engine.evaluate_patient(pid)
        
        if output.calibration_message:
            print(f"  CALIBRATION: {output.calibration_message}")
            print()
        
        # Baseline status
        if output.baseline_status:
            print("  BASELINE STATUS:")
            bs = output.baseline_status
            if "metrics" in bs:
                for metric, info in bs["metrics"].items():
                    status = info.get("status", "unknown")
                    emoji = "[OK]" if status == "established" else "[..]"
                    detail = ""
                    if status == "established":
                        mean_val = info.get("mean", 0)
                        std_val = info.get("std", 0)
                        detail = f" (mean={mean_val:.1f}, std={std_val:.1f})"
                    elif status == "calibrating":
                        detail = f" ({info.get('count', '?')}/{info.get('min_required', '?')} days)"
                    print(f"    {emoji} {metric}: {status}{detail}")
            print()
        
        # Active insights
        if output.active_insights:
            print(f"  >>> ACTIVE INSIGHTS ({len(output.active_insights)}) <<<")
            print()
            for i, insight in enumerate(output.active_insights, 1):
                severity_tag = f"[{insight.severity.value}]"
                print(f"  {i}. {severity_tag} {insight.name}")
                print(f"     {insight.message}")
                if insight.evidence:
                    guideline = insight.evidence.get("guideline", "")
                    instrument = insight.evidence.get("instrument", "")
                    recommendation = insight.evidence.get("recommendation", "")
                    if guideline:
                        print(f"     Guideline: {guideline}")
                    if instrument:
                        print(f"     Instrument: {instrument}")
                    if recommendation:
                        print(f"     Recommendation: {recommendation}")
                    # Print key numeric evidence
                    for ek, ev in insight.evidence.items():
                        if ek not in ("guideline", "instrument", "recommendation", "limitation") and isinstance(ev, (int, float)):
                            print(f"     {ek}: {ev}")
                print()
        else:
            print("  No active insights — all vitals within normal ranges (or calibrating)")
            print()
        
        # Skipped rules
        if output.skipped_rules:
            print(f"  SKIPPED RULES ({len(output.skipped_rules)}):")
            for skip in output.skipped_rules:
                print(f"    - {skip.name}: {skip.skip_reason}")
            print()
        
    except Exception as e:
        print(f"  ENGINE ERROR: {e}")
        import traceback
        traceback.print_exc()
        print()

print("=" * 70)
print("DONE")
print("=" * 70)
