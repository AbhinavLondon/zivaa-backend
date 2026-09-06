import asyncio
import os
from dotenv import load_dotenv

# Load env vars
load_dotenv()

from app.services.reinforcement import fetch_history_data, calculate_task_correlations, generate_reinforcement_message
from app.services.insights.data_fetcher import supabase

async def test_engine():
    print("--- Searching for Ranjit in Supabase ---")
    res = supabase.table("patients").select("*").execute()
    
    if not res.data:
        print("Could not find any patients in the database.")
        return
        
    # Find Ranjit
    ranjit = next((p for p in res.data if "Ranjit" in p.get("full_name", "")), None)
    if not ranjit:
        print("Could not find Ranjit in the database.")
        return
        
    patient_id = ranjit["id"]
    print(f"Found Ranjit: {patient_id}")
    
    print("\nFetching history data (14 days)...")
    data = fetch_history_data(patient_id, days=14)
    if not data:
        print("No history data found for Ranjit.")
        return
        
    print(f"Fetched {len(data)} days of data.")
    
    print("\nTesting deterministic statistics:")
    correlations = calculate_task_correlations(data)
    
    if not correlations:
        print("No deterministic correlations found (meaningful >5% improvement on tasks completed at least twice).")
    else:
        for c in correlations:
            print(f"Task: {c['task']}, Metric: {c['metric']}")
            print(f"  Avg with task: {c['task_avg']}")
            print(f"  Avg without task: {c['baseline_avg']}")
            print(f"  Improvement: {c['improvement_pct']}%")
            
    print("\nTesting LLM Generation:")
    result = await generate_reinforcement_message(patient_id, data, correlations)
    if result:
        print(f"Generated Reinforcement Message: {result.get('message')}")
    else:
        print("No message generated.")

if __name__ == "__main__":
    asyncio.run(test_engine())
