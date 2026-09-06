import os
import httpx
import json
import numpy as np
from sklearn.ensemble import IsolationForest
from datetime import datetime, timedelta, timezone

# 1. Generate 30 days of synthetic resting heart rate data
# Baseline (Days 1-25): healthy resting heart rate around 66-72 bpm
# Anomaly (Days 26-30): steady drift upwards to 89 bpm (resting tachycardia spike)
def generate_30_day_data():
    data = []
    base_time = datetime.now(timezone.utc) - timedelta(days=30)
    
    # Days 1 to 25: Normal Baseline
    for day in range(1, 26):
        timestamp = base_time + timedelta(days=day)
        # Normal fluctuation between 66 and 71
        bpm = 68.0 + (day % 3) - (day % 2)
        data.append({"day": day, "timestamp": timestamp.isoformat(), "bpm": bpm})
        
    # Days 26 to 30: Anomalous Drift (Spike)
    anomaly_values = [81.0, 84.0, 86.0, 87.0, 89.0]
    for idx, bpm in enumerate(anomaly_values):
        day = 26 + idx
        timestamp = base_time + timedelta(days=day)
        data.append({"day": day, "timestamp": timestamp.isoformat(), "bpm": bpm})
        
    return data

# 2. Analyze the time-series data using Machine Learning (Isolation Forest)
def detect_anomalies_ml(data):
    # Reshape heart rates into a 2D array for scikit-learn
    heart_rates = np.array([r["bpm"] for r in data]).reshape(-1, 1)
    
    # Isolation Forest: Unsupervised Outlier Detection
    # contamination represents the expected percentage of outlier data points
    model = IsolationForest(contamination=0.17, random_state=42)
    model.fit(heart_rates)
    
    # Predict outliers: 1 = normal, -1 = anomaly
    predictions = model.predict(heart_rates)
    
    anomalies = []
    normal_values = []
    
    for idx, pred in enumerate(predictions):
        record = data[idx]
        if pred == -1:
            anomalies.append(record)
        else:
            normal_values.append(record["bpm"])
            
    avg_baseline = sum(normal_values) / len(normal_values) if normal_values else 68.0
    
    return {
        "baseline_average": round(avg_baseline, 1),
        "anomalies_detected": anomalies,
        "is_anomaly_found": len(anomalies) > 0,
        "anomaly_count": len(anomalies)
    }

# 3. Request Gemini to analyze the anomaly and write a nudge
async def query_gemini_for_nudge(metrics):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: GEMINI_API_KEY environment variable is not set. Cannot run AI analysis.")
        return None
        
    anomalous_days_str = ", ".join([f"Day {r['day']}: {r['bpm']} bpm" for r in metrics['anomalies_detected']])
    
    prompt = f"""
    You are an expert AI clinical coordinator for Zivaa Eldercare.
    We performed a 30-day time-series anomaly detection on a 72-year-old senior's resting heart rate (RHR) using an **Isolation Forest Machine Learning Outlier Model**:
    
    - Model Fit: Isolation Forest (Contamination=0.17)
    - Learned Baseline RHR (Normal days): {metrics['baseline_average']} bpm
    - Detected Anomalies: {metrics['anomaly_count']} outlier days flagged.
    - Outlier Details: [{anomalous_days_str}]
    
    Tasks:
    1. Determine the appropriate Risk Level (LOW, MEDIUM, HIGH). A cluster of resting heart rates rising up to 89 bpm is classified as HIGH risk resting tachycardia.
    2. Write an empathetic, plain-language notification (nudge) for the patient's family caregiver (Aarav).
    3. State that the **Zivaa Machine Learning Engine** detected this anomaly trend.
    4. Suggest practical, gentle next steps (e.g., check hydration, check for a low-grade fever, consult their doctor).
    
    Format the response as exact JSON:
    {{
      "risk_level": "LOW | MEDIUM | HIGH",
      "nudge_title": "Actionable, clear title",
      "nudge_text": "Empathetic description mentioning Zivaa ML Outlier detection and next steps"
    }}
    """

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json"}
    }
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, headers=headers, json=payload, timeout=12.0)
            if response.status_code == 200:
                response_json = response.json()
                text_content = response_json["candidates"][0]["content"]["parts"][0]["text"]
                return json.loads(text_content)
            else:
                print(f"API Error ({response.status_code}): {response.text}")
        except Exception as e:
            print(f"Failed to query Gemini API: {e}")
    return None

async def main():
    print("Generating 30-day resting heart rate time-series dataset...")
    data = generate_30_day_data()
    
    print("\nRunning Isolation Forest ML Outlier Analysis...")
    analysis = detect_anomalies_ml(data)
    
    print(f"-> Learned Baseline RHR (Inliers): {analysis['baseline_average']} bpm")
    print(f"-> Anomalies Detected: {analysis['is_anomaly_found']}")
    print(f"-> Total Outlier Days Flagged: {analysis['anomaly_count']}")
    for record in analysis['anomalies_detected']:
        print(f"   * Day {record['day']}: {record['bpm']} bpm (Flagged as Anomaly)")
        
    if analysis['is_anomaly_found']:
        print("\n[ALERT] ML anomaly detected. Triggering Google Gemini Nudge Engine...")
        nudge = await query_gemini_for_nudge(analysis)
        
        if nudge:
            print("\n=== AI Generated Caregiver Nudge ===")
            print(json.dumps(nudge, indent=2))
        else:
            print("Failed to generate AI nudge.")
    else:
        print("\nNo anomaly detected. Vitals steady.")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
