import asyncio
import sys
import os
import json

# Ensure stdout handles unicode
sys.stdout.reconfigure(encoding='utf-8')

# Ensure imports work
user_site = os.path.expanduser("~\\AppData\\Roaming\\Python\\Python314\\site-packages")
if user_site not in sys.path and os.path.exists(user_site):
    sys.path.insert(0, user_site)

# Add current directory to sys.path to find 'app'
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from app.services.insights.data_fetcher import supabase
from app.services.llm_plan import build_plan_context
from app.services.medgemma_services import generate_medgemma_plan
import app.services.medgemma_services as m_services

async def run():
    print("--- Searching for Ranjit in Supabase ---")
    res = supabase.table("patients").select("*").execute()
    
    patient = None
    if res.data:
        for p in res.data:
            name = p.get("first_name", "") + " " + p.get("last_name", "")
            if "Ranjit" in name or "Ranjit" in p.get("preferred_name", ""):
                patient = p
                break
    
    if not patient:
        if res.data:
            print("Ranjit not found. Using first patient as fallback.")
            patient = res.data[0]
        else:
            print("No patients found in DB.")
            return
        
    patient_id = patient["id"]
    print(f"Found {patient.get('first_name')} (ID: {patient_id})")
    
    plan_context = build_plan_context(patient_id)
    
    print("\n================== EXACT INPUT (plan_context) ==================")
    print(json.dumps(plan_context, indent=2, default=str))
    print("==============================================================\n")
    
    print("Running generate_medgemma_plan...")
    
    # Intercept the call to show the exact prompt sent to MedGemma
    original_call = m_services._call_medgemma
    
    async def intercept_call(prompt, **kwargs):
        print("\n================== EXACT LLM PROMPT ==================")
        print(prompt)
        print("======================================================\n")
        return await original_call(prompt, **kwargs)
        
    m_services._call_medgemma = intercept_call
    
    plan = await generate_medgemma_plan(plan_context)
    
    print("\n================== OUTPUT GENERATED ==================")
    print(json.dumps(plan, indent=2))
    print("======================================================\n")

if __name__ == "__main__":
    asyncio.run(run())
