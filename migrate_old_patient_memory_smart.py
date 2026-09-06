import os
import json
import httpx
import asyncio
import traceback
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not SUPABASE_URL or not SUPABASE_KEY or not GEMINI_API_KEY:
    print("Credentials not found in .env")
    exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

async def ask_gemini_to_map(symptoms, actions):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key={GEMINI_API_KEY}"
    
    prompt = """
You are an intelligent clinical assistant. Your task is to map health actions to their root cause symptoms or lifestyle factors.

Here are the patient's facts (symptoms and lifestyle):
{symptoms_json}

Here are the recommended/agreed actions:
{actions_json}

For each action, identify which fact it most logically corresponds to based on semantic meaning. 
If an action does not strongly relate to any fact, map its fact_id to null.

Return a JSON object in exactly this format, and nothing else (no markdown blocks):
{{
  "mappings": [
    {{"action_id": "uuid-here", "fact_id": "uuid-here-or-null"}}
  ]
}}
"""
    symptoms_cleaned = [{"id": s["id"], "fact": s["fact"], "category": s["category"]} for s in symptoms]
    actions_cleaned = [{"id": a["id"], "fact": a["fact"], "category": a["category"]} for a in actions]
    
    formatted_prompt = prompt.format(
        symptoms_json=json.dumps(symptoms_cleaned, indent=2),
        actions_json=json.dumps(actions_cleaned, indent=2)
    )
    
    payload = {
        "contents": [{"role": "user", "parts": [{"text": formatted_prompt}]}],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json"
        }
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload, timeout=120.0)
        response.raise_for_status()
        data = response.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        
        try:
            return json.loads(text.strip())
        except Exception as e:
            print("RAW GEMINI RESPONSE:")
            print(text)
            raise e

async def run():
    print("Fetching patient memories...")
    res = supabase.table("patient_memory").select("*").in_("category", ["symptom", "lifestyle", "agreed_action", "suggested_action"]).execute()
    
    memories = res.data or []
    
    by_patient = {}
    for m in memories:
        pid = m["patient_id"]
        if pid not in by_patient:
            by_patient[pid] = {"facts": [], "actions": []}
        
        if m["category"] in ["symptom", "lifestyle"]:
            by_patient[pid]["facts"].append(m)
        else:
            by_patient[pid]["actions"].append(m)
            
    for pid, data in by_patient.items():
        facts = data["facts"]
        actions = data["actions"]
        
        if not facts or not actions:
            print(f"Skipping patient {pid} due to missing facts or actions.")
            continue
            
        print(f"Mapping {len(actions)} actions to {len(facts)} facts for patient {pid}...")
        
        try:
            result = await ask_gemini_to_map(facts, actions)
            mappings = result.get("mappings", [])
            
            updates_made = 0
            clears_made = 0
            for mapping in mappings:
                action_id = mapping.get("action_id")
                fact_id = mapping.get("fact_id")
                
                if action_id and fact_id:
                    # Update DB with intelligent mapping
                    supabase.table("patient_memory").update({"linked_symptom_id": fact_id}).eq("id", action_id).execute()
                    updates_made += 1
                elif action_id and not fact_id:
                    # Clear it if it was previously wrongly mapped by the naive script
                    supabase.table("patient_memory").update({"linked_symptom_id": None}).eq("id", action_id).execute()
                    clears_made += 1
            
            print(f"Successfully mapped {updates_made} actions and cleared {clears_made} unrelated actions for patient {pid}.")
        except Exception as e:
            print(f"Error mapping for patient {pid}: {e}")
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(run())
