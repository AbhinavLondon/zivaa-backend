import asyncio
import json
from app.services.insights.data_fetcher import supabase, fetch_patient_context
from app.services.medgemma_services import (
    generate_medgemma_alerts, 
    generate_medgemma_nudge,
    generate_medgemma_plan,
    generate_medgemma_summary
)
from app.services.llm_plan import build_plan_context, generate_daily_plan
from app.services.daily_summary import generate_daily_summary
from app.services.insights.engine import InsightEngine

async def run():
    print("--- Searching for Ranjit in Supabase ---")
    res = supabase.table("patients").select("*").execute()
    
    if not res.data:
        print("Could not find any patients in the database.")
        return
        
    print("Available patients:", [p.get("first_name", p.get("id")) for p in res.data])
    
    # Try to find Ranjit
    patient = None
    for p in res.data:
        name = p.get("first_name", "") + " " + p.get("last_name", "")
        if "Ranjit" in name or "Ranjit" in p.get("preferred_name", ""):
            patient = p
            break
            
    if not patient:
        patient = res.data[0] # Just use the first one if we can't find him
        
    patient_id = patient["id"]
    patient_name = patient.get("first_name", "Patient")
    
    print(f"Found {patient_name} (ID: {patient_id})")
    print("\n--- 1. Fetching Context & Running Diagnostics ---")
    
    ctx = fetch_patient_context(patient_id)
    plan_context = build_plan_context(patient_id)
    
    from app.config import settings
    
    # Run Rules Engine
    engine = InsightEngine()
    rules_output = engine.evaluate_patient(patient_id, ctx)
    rules_alerts = rules_output.active_insights
    
    print(f"Rules Engine generated {len(rules_alerts)} alerts:")
    for a in rules_alerts:
        print(f"  - {a.name}: {a.message}")
    
    medgemma_alerts_list = []
    if settings.ENABLE_MEDGEMMA_PIPELINE:
        # Run MedGemma Diagnostics
        medgemma_alerts_dict = await generate_medgemma_alerts(ctx)
        medgemma_alerts_list = medgemma_alerts_dict.get("active_insights", [])
        print(f"\nMedGemma Diagnostics generated {len(medgemma_alerts_list)} alerts:")
        for a in medgemma_alerts_list:
            print(f"  - {a.get('name')}: {a.get('message')}")
    else:
        print("\nMedGemma Diagnostics skipped (ENABLE_MEDGEMMA_PIPELINE=False).")
    
    print("\n--- 2. Generating Daily Plans ---")
    
    # Gemini Plan (Deterministic)
    gemini_plan = await generate_daily_plan(plan_context)
    
    print("\n[DETERMINISTIC / GEMINI PLAN]")
    print(json.dumps(gemini_plan, indent=2))
    
    if settings.ENABLE_MEDGEMMA_PIPELINE:
        # MedGemma Plan
        medgemma_plan_ctx = {**plan_context, "active_insights": medgemma_alerts_list}
        medgemma_plan = await generate_medgemma_plan(medgemma_plan_ctx)
        
        print("\n[PURE MEDGEMMA PLAN]")
        print(json.dumps(medgemma_plan, indent=2))
    else:
        print("\n[PURE MEDGEMMA PLAN] Skipped.")
    
    print("\n--- 3. Generating Morning Summaries ---")
    
    gemini_summary_res = await generate_daily_summary(patient_id, patient_name)
    print("\n[DETERMINISTIC / RULES ENGINE SUMMARY]")
    print(json.dumps(gemini_summary_res, indent=2))
    
    if settings.ENABLE_MEDGEMMA_PIPELINE:
        medgemma_summary_res = await generate_medgemma_summary(patient_id, patient_name)
        print("\n[PURE MEDGEMMA SUMMARY]")
        print(json.dumps(medgemma_summary_res, indent=2))
    else:
        print("\n[PURE MEDGEMMA SUMMARY] Skipped.")
        
    print("\n--- 4. Generating Nudge ---")
    try:
        nudge_res = await generate_medgemma_nudge(rules_alerts, patient_name)
        print("\n[MEDGEMMA NUDGE]")
        print(json.dumps(nudge_res, indent=2))
    except Exception as e:
        print(f"\n[MEDGEMMA NUDGE] Error: {e}")

if __name__ == "__main__":
    import sys
    import os
    user_site = os.path.expanduser("~\\AppData\\Roaming\\Python\\Python314\\site-packages")
    if user_site not in sys.path and os.path.exists(user_site):
        sys.path.insert(0, user_site)
        
    asyncio.run(run())
