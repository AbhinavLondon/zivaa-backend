import asyncio
import json
import httpx
import os
import sys

# Ensure imports work
user_site = os.path.expanduser("~\\AppData\\Roaming\\Python\\Python314\\site-packages")
if user_site not in sys.path and os.path.exists(user_site):
    sys.path.insert(0, user_site)

from app.services.insights.data_fetcher import supabase, fetch_patient_context
from app.services.medgemma_services import format_patient_chart_prompt
from app.services.llm_plan import build_plan_context
from app.config import settings
from app.services.insights.engine import InsightEngine
from app.services.medgemma_services import _normalize_insights

async def count_tokens(text: str) -> int:
    api_key = settings.GEMINI_API_KEY
    if not api_key or api_key == "your-api-key-here":
        # Rough estimate: 1 token ~= 4 chars
        return len(text) // 4
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:countTokens?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": text}]}]
    }
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, timeout=10.0)
            if resp.status_code == 200:
                return resp.json().get("totalTokens", len(text) // 4)
            else:
                return len(text) // 4
    except Exception:
        return len(text) // 4

def build_vertex_payload(prompt: str, json_mode: bool = False, prefill: bool = True) -> dict:
    if json_mode and prefill:
        formatted_prompt = f"<start_of_turn>user\n{prompt}<end_of_turn>\n<start_of_turn>model\nOutput:\n{{"
    else:
        formatted_prompt = f"<start_of_turn>user\n{prompt}<end_of_turn>\n<start_of_turn>model\nOutput:\n"
    return {
        "instances": [
            {
                "prompt": formatted_prompt,
                "max_tokens": 2048,
                "temperature": 0.2
            }
        ],
        "parameters": {
            "max_tokens": 2048,
            "temperature": 0.2
        }
    }

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
        print("Ranjit not found. Using first patient as fallback (just like run_ranjit).")
        patient = res.data[0]
        
    patient_id = patient["id"]
    patient_name = patient.get("first_name", "Patient")
    print(f"Found {patient_name} (ID: {patient_id})")
    
    ctx = fetch_patient_context(patient_id)
    plan_context = build_plan_context(patient_id)
    
    # 1. MedGemma Alerts
    chart_text = format_patient_chart_prompt(ctx)
    alerts_prompt = f"""You are MedGemma, an advanced clinical reasoning AI model.
Review the following patient clinical chart:

{chart_text}

Your task is to review all metrics, baselines, trends, and lab history, and identify any active health concerns or risk flags across these clinical domains:
- Cardiovascular (hypertension, rate flags, arrhythmia)
- Metabolic (diabetes progression, glycaemic risk, HbA1c worsening)
- Renal (kidney decline, eGFR drop, albuminuria)
- Respiratory (hypoxia, respiratory rate changes)
- Hematology / Nutritional Status (anemia, vitamin/iron deficiencies)
- Thyroid & Endocrine
- Mental Wellbeing (depression logs, sleep quality)
- General Health

For each active concern you identify:
1. Assess the severity (LOW, MEDIUM, HIGH) using standard clinical practice guidelines (e.g. ADA for HbA1c, AHA for blood pressure, KDIGO for kidney function).
2. Map it to one of these category values: CARDIAC, METABOLIC, RENAL, RESPIRATORY, HEMATOLOGY, THYROID, NUTRITION, MENTAL_HEALTH, GENERAL.
3. Assign a short, descriptive rule_id in snake_case (e.g., 'hypertension_escalation', 'prediabetes_progression').
4. Write a concise, supportive message explaining the concern. Reference specific values and guideline thresholds where appropriate.
5. Populate the evidence dictionary with the exact metrics and values that triggered this alert (e.g. {{"bp_systolic": 142, "bp_diastolic": 91}}).

Return your findings in a strict JSON format with this exact structure:
{{
  "active_insights": [
    {{
      "rule_id": "short_snake_case_id",
      "name": "Human-friendly alert name",
      "severity": "LOW | MEDIUM | HIGH",
      "category": "CARDIAC | METABOLIC | RENAL | RESPIRATORY | HEMATOLOGY | THYROID | NUTRITION | MENTAL_HEALTH | GENERAL",
      "message": "Clinical explanation with guideline citations",
      "evidence": {{
        "bp_systolic": 142.0,
        "bp_diastolic": 91.0
      }}
    }}
  ]
}}

Ensure that the output contains ONLY the JSON payload. DO NOT include any markdown wraps (no backticks), greetings, summary notes, or any "Thinking Process" / reasoning text. Start your response immediately with the opening brace '{{' and end with the closing brace '}}'. If no concerns are found, return an empty list under "active_insights".
"""
    alerts_payload = build_vertex_payload(alerts_prompt, json_mode=True, prefill=False)
    
    # Generate the artifact JSON containing the payloads
    results = {
        "patient": patient_name,
        "payloads": {
            "generate_medgemma_alerts": {
                "payload": alerts_payload,
                "estimated_tokens": await count_tokens(alerts_prompt)
            }
        }
    }
    
    # We will output this to a file
    with open('medgemma_payloads_ranjit.json', 'w') as f:
        json.dump(results, f, indent=2)
        
    print(f"Token count for alerts prompt: {results['payloads']['generate_medgemma_alerts']['estimated_tokens']}")
    print("Payloads saved to medgemma_payloads_ranjit.json")

if __name__ == "__main__":
    asyncio.run(run())
