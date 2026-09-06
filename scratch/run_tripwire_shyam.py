import asyncio
import json
import os
import sys

# Ensure app path is in path
sys.path.append(r"c:\Users\abhin\Downloads\Zivaa Apps\zivaa-backend")

from app.services.insights.data_fetcher import supabase
from app.services.tripwire import run_tripwire_evaluation

async def run():
    print("--- Searching for Shyam in Supabase ---")
    res = supabase.table("patients").select("*").execute()
    
    if not res.data:
        print("Could not find any patients in the database.")
        return
        
    patient = None
    for p in res.data:
        name = p.get("first_name", "") + " " + p.get("last_name", "")
        if "Shyam" in name or "Shyam" in p.get("preferred_name", ""):
            patient = p
            break
            
    if not patient:
        print("Could not find Shyam by name. Falling back to the first available patient.")
        patient = res.data[0]
        
    patient_id = patient["id"]
    patient_name = patient.get("first_name", "Patient")
    
    print(f"Found {patient_name} (ID: {patient_id})")
    print(f"\n--- Running Tripwire Evaluation for {patient_name} ---")
    
    await run_tripwire_evaluation(patient_id)
    print("Tripwire evaluation complete.")

if __name__ == "__main__":
    asyncio.run(run())
