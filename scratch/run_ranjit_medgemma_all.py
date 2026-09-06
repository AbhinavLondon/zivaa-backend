import asyncio
import time
import json
import os
import sys

# Ensure imports work
user_site = os.path.expanduser("~\\AppData\\Roaming\\Python\\Python314\\site-packages")
if user_site not in sys.path and os.path.exists(user_site):
    sys.path.insert(0, user_site)

from app.services.insights.data_fetcher import supabase, fetch_patient_context
from app.services.llm_plan import build_plan_context
from app.services.medgemma_services import (
    generate_medgemma_alerts,
    generate_medgemma_nudge,
    generate_medgemma_plan,
    generate_medgemma_summary
)

async def run():
    print("--- Searching for Ranjit in Supabase ---")
    res = supabase.table("patients").select("*").execute()
    
    if not res.data:
        print("No patients in database.")
        return
        
    patient = None
    for p in res.data:
        name = p.get("first_name", "") + " " + p.get("last_name", "")
        if "Ranjit" in name or "Ranjit" in p.get("preferred_name", ""):
            patient = p
            break
            
    if not patient:
        print("Ranjit not found. Using first patient as fallback.")
        patient = res.data[0]
        
    patient_id = patient["id"]
    patient_name = patient.get("first_name", "Patient")
    print(f"Found {patient_name} (ID: {patient_id})")

    results = {}
    
    # Contexts
    ctx = fetch_patient_context(patient_id)
    plan_context = build_plan_context(patient_id)
    
    # 1. Alerts
    print("Running generate_medgemma_alerts...")
    t0 = time.time()
    alerts = await generate_medgemma_alerts(ctx)
    t1 = time.time()
    results['generate_medgemma_alerts'] = {
        'time_taken_seconds': t1 - t0,
        'output': alerts
    }
    
    # 2. Nudge
    print("Running generate_medgemma_nudge...")
    t0 = time.time()
    nudge = await generate_medgemma_nudge(alerts, patient_name)
    t1 = time.time()
    results['generate_medgemma_nudge'] = {
        'time_taken_seconds': t1 - t0,
        'output': nudge
    }
    
    # 3. Plan
    print("Running generate_medgemma_plan...")
    t0 = time.time()
    plan = await generate_medgemma_plan(plan_context)
    t1 = time.time()
    results['generate_medgemma_plan'] = {
        'time_taken_seconds': t1 - t0,
        'output': plan
    }
    
    # 4. Summary
    print("Running generate_medgemma_summary...")
    t0 = time.time()
    summary = await generate_medgemma_summary(patient_id, patient_name)
    t1 = time.time()
    results['generate_medgemma_summary'] = {
        'time_taken_seconds': t1 - t0,
        'output': summary
    }
    
    with open('scratch/medgemma_ranjit_results_all.json', 'w') as f:
        json.dump(results, f, indent=2)
        
    print("Done. Results saved to scratch/medgemma_ranjit_results_all.json")

if __name__ == "__main__":
    asyncio.run(run())
