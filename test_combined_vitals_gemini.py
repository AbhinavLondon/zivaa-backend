import os
import httpx
import json
import asyncio
from app.services.ml_pipeline import run_univariate_anomaly_detector, run_multivariate_anomaly_detector
from app.services.llm_nudge import generate_clinical_nudge

# 1. Generate 60 days of combined daily telemetry records
# Baseline (Days 1-55): healthy metrics
# Anomaly (Day 60): RHR = 88 bpm (high), Systolic BP = 154 (high), Steps = 200 (low), Sleep = 5.3 hrs (low)
def generate_combined_vitals_dataset():
    historical_daily = []
    
    # Days 1 to 55: Normal Baseline Profiles
    for day in range(1, 56):
        record = {
            "avg_heart_rate": 68.0 + (day % 3),
            "bp_systolic": 122.0 + (day % 4),
            "bp_diastolic": 78.0 + (day % 2),
            "total_steps": 1600.0 + (day * 10 % 300),
            "sleep_hours": 7.2
        }
        historical_daily.append(record)
        
    # Day 60: Single daily ingestion payload containing a correlation outlier
    new_daily = [{
        "avg_heart_rate": 88.0,
        "bp_systolic": 154.0,
        "bp_diastolic": 98.0,
        "total_steps": 200.0,
        "sleep_hours": 5.3
    }]
    
    return historical_daily, new_daily

async def query_gemini_for_nudge(prompt_text):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: GEMINI_API_KEY environment variable is not set.")
        return None
        
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{"parts": [{"text": prompt_text}]}],
        "generationConfig": {"responseMimeType": "application/json"}
    }
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, headers=headers, json=payload, timeout=20.0)
            if response.status_code == 200:
                response_json = response.json()
                text_content = response_json["candidates"][0]["content"]["parts"][0]["text"]
                try:
                    return json.loads(text_content)
                except Exception as e:
                    print(f"JSON parsing error: {e}")
                    print(f"Raw response was:\n{text_content}")
                    raise e
            else:
                print(f"Gemini API returned status code {response.status_code}: {response.text}")
        except Exception as e:
            import traceback
            print(f"Exception during Gemini query: {type(e).__name__}: {e}")
            traceback.print_exc()
    return None

async def main():
    print("Generating 60-day combined vitals datasets...")
    history, active_day = generate_combined_vitals_dataset()
    
    # Extract historical vectors for 1D checks
    history_hr = [r["avg_heart_rate"] for r in history]
    active_hr = [r["avg_heart_rate"] for r in active_day]
    
    history_bp = [r["bp_systolic"] for r in history]
    active_bp = [r["bp_systolic"] for r in active_day]
    
    # -------------------------------------------------------------
    # CASE 1: Univariate (1D) Outlier Nudge Generation
    # -------------------------------------------------------------
    print("\n--- Running Case 1: Parallel Univariate (1D) Outliers ---")
    hr_result = run_univariate_anomaly_detector(active_hr, history_hr)
    bp_result = run_univariate_anomaly_detector(active_bp, history_bp)
    
    case1_prompt = f"""
    You are an expert conversational clinical guide for Zivaa Eldercare.
    Our **Parallel Univariate (1D) Outlier Models** detected two separate outliers today:
    
    - Heart Rate Outlier: {hr_result['anomaly_detected']} (Current: {hr_result['avg_value']} bpm)
    - Blood Pressure Outlier: {bp_result['anomaly_detected']} (Current: {bp_result['avg_value']} mmHg)
    
    Instructions:
    1. Categorize Risk (LOW, MEDIUM, HIGH). This is HIGH risk.
    2. Write in a warm, comforting, less-clinical tone. Speak in plain English like a reassuring friend, not a cold algorithm.
    3. Exclude dense medical terminology (no jargon).
    4. UNDER THE "why_flagged" SECTION, YOU MUST PROVIDE a simple, non-clinical explanation of why we are flagging this anomaly, highlighting which vitals deviated and by how much compared to their normal baselines. DO NOT include any visual graphs, ASCII graphs, or charts in this section.
    
    Format the response as exact JSON:
    {{
      "risk_level": "LOW | MEDIUM | HIGH",
      "nudge_title": "Warm, human-friendly title",
      "nudge_text": "Empathetic, comforting description in plain conversational English.",
      "why_flagged": "Why we are flagging this (a simple, non-clinical explanation of the independent anomalies compared to their baselines, without any graphs or charts)",
      "action_steps": "What you can do about it (clear, gentle next steps)"
    }}
    """
    
    nudge_case1 = await query_gemini_for_nudge(case1_prompt)
    if nudge_case1:
        print("\n=== AI Generated Nudge (Case 1: Univariate) ===")
        print(json.dumps(nudge_case1, indent=2))
        
    print("\n--- Running Service generate_clinical_nudge for Case 1 ---")
    features_case1 = {
        "avg_heart_rate": hr_result['avg_value'],
        "bp_systolic": bp_result['avg_value'],
        "bp_diastolic": 98.0,
        "sleep_hours": 5.3,
        "total_steps": 200.0,
        "ml_anomaly_detected": True,
        "ml_anomaly_count": 2,
        "hr_spikes": 2
    }
    service_nudge_case1 = await generate_clinical_nudge(features_case1)
    print("=== Service Output (Case 1) ===")
    print(json.dumps(service_nudge_case1, indent=2))
        
    # -------------------------------------------------------------
    # CASE 2: Multivariate (5D) Correlation Outlier Nudge Generation
    # -------------------------------------------------------------
    print("\n--- Running Case 2: Combined Multivariate (5D) Outliers ---")
    features = ["avg_heart_rate", "bp_systolic", "bp_diastolic", "total_steps", "sleep_hours"]
    mv_result = run_multivariate_anomaly_detector(
        new_daily_records=active_day,
        historical_daily_records=history,
        features_to_use=features
    )
    
    case2_prompt = f"""
    You are an expert conversational clinical guide for Zivaa Eldercare.
    Our **Combined Multivariate (5D) Outlier Model** detected a correlation anomaly today:
    
    - Combined Outlier: {mv_result['anomaly_detected']}
    - Context: Today's profile shows: Heart Rate: 88 bpm, Blood Pressure: 154/98 mmHg, Steps: 200, Sleep: 5.3 hrs.
    
    Instructions:
    1. Categorize Risk (LOW, MEDIUM, HIGH). This is HIGH risk.
    2. Write in a warm, comforting, less-clinical tone. Speak in plain English like a reassuring friend, not a cold algorithm.
    3. Exclude dense medical terminology (no jargon).
    4. UNDER THE "why_flagged" SECTION, YOU MUST PROVIDE a simple, non-clinical explanation of why we are flagging this anomaly, highlighting which vitals deviated and by how much compared to their normal baselines. DO NOT include any visual graphs, ASCII graphs, or charts in this section.
    
    Format the response as exact JSON:
    {{
      "risk_level": "LOW | MEDIUM | HIGH",
      "nudge_title": "Warm, human-friendly title",
      "nudge_text": "Empathetic, comforting description in plain conversational English.",
      "why_flagged": "Why we are flagging this (a simple, non-clinical explanation of the correlation anomaly compared to baseline, without any graphs or charts)",
      "action_steps": "What you can do about it (clear, gentle next steps)"
    }}
    """
    
    nudge_case2 = await query_gemini_for_nudge(case2_prompt)
    if nudge_case2:
        print("\n=== AI Generated Nudge (Case 2: Multivariate) ===")
        print(json.dumps(nudge_case2, indent=2))
        
    print("\n--- Running Service generate_clinical_nudge for Case 2 ---")
    features_case2 = {
        "avg_heart_rate": 88.0,
        "bp_systolic": 154.0,
        "bp_diastolic": 98.0,
        "sleep_hours": 5.3,
        "total_steps": 200.0,
        "ml_anomaly_detected": True,
        "ml_anomaly_count": 1,
        "hr_spikes": 1
    }
    service_nudge_case2 = await generate_clinical_nudge(features_case2)
    print("=== Service Output (Case 2) ===")
    print(json.dumps(service_nudge_case2, indent=2))

if __name__ == "__main__":
    asyncio.run(main())
