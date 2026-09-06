import sys
import os
# Add user-site packages to sys.path so IDE linter resolves imports
user_site = os.path.expanduser("~\\AppData\\Roaming\\Python\\Python314\\site-packages")
if user_site not in sys.path and os.path.exists(user_site):
    sys.path.insert(0, user_site)

import httpx
import json
from datetime import datetime, timedelta, timezone
from app.services.ml_pipeline import extract_features as run_ml_pipeline
from app.services.llm_nudge import generate_clinical_nudge

# Mock pydantic classes for script compatibility
class MockRecord:
    def __init__(self, metric_type, timestamp, values):
        self.type = metric_type
        self.timestamp = timestamp
        self.values = values

def generate_60_day_data():
    historical_heart_rates = []
    base_time = datetime.now(timezone.utc) - timedelta(days=60)
    
    # Days 1 to 55: Normal Baseline
    for day in range(1, 56):
        # Fluctuate normally around 68.0 bpm
        bpm = 68.0 + (day % 3) - (day % 2)
        historical_heart_rates.append(bpm)
        
    # Days 56 to 60: New Incoming Telemetry (with outlier drift)
    new_records = []
    anomaly_values = [81.0, 84.0, 86.0, 87.0, 89.0]
    for idx, bpm in enumerate(anomaly_values):
        day = 56 + idx
        timestamp = (base_time + timedelta(days=day)).isoformat()
        # Mock steps and blood pressure along with heart rate
        new_records.append(MockRecord("heart_rate", timestamp, {"bpm": bpm}))
        new_records.append(MockRecord("steps", timestamp, {"count": 250.0}))
        new_records.append(MockRecord("blood_pressure", timestamp, {"systolic": 142.0, "diastolic": 88.0}))
        
    return historical_heart_rates, new_records

async def main():
    print("Generating 60-day resting heart rate time-series dataset...")
    historical_hr, new_records = generate_60_day_data()
    
    print(f"-> Historical baseline points: {len(historical_hr)} days")
    print(f"-> Newly synced points: {len(new_records) // 3} days (Steps, HR, BP)")
    
    print("\nRunning Production Isolation Forest Pipeline...")
    # Executing the exact same function that the FastAPI server routes call in production
    features = run_ml_pipeline(new_records, historical_heart_rates=historical_hr)
    
    print("\n=== Pipeline Extracted Features ===")
    print(json.dumps(features, indent=2))
    
    if features["ml_anomaly_detected"]:
        print("\n[ALERT] Production ML model flagged active anomalies. Querying Gemini 3.5...")
        nudge = await generate_clinical_nudge(features)
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
