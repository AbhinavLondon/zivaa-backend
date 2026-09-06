import json
import httpx
from datetime import datetime, timezone

URL = "http://127.0.0.1:8000/api/v1/health/ingest"

# Scenario A: All Vitals Healthy (Low Risk)
healthy_payload = {
    "client_time": datetime.now(timezone.utc).isoformat(),
    "timezone": "Asia/Kolkata",
    "records": [
        {"type": "steps", "timestamp": datetime.now(timezone.utc).isoformat(), "values": {"count": 1650.0}},
        {"type": "heart_rate", "timestamp": datetime.now(timezone.utc).isoformat(), "values": {"bpm": 68.0}},
        {"type": "sleep", "timestamp": datetime.now(timezone.utc).isoformat(), "values": {"duration_minutes": 460.0}},
        {"type": "blood_pressure", "timestamp": datetime.now(timezone.utc).isoformat(), "values": {"systolic": 122.0, "diastolic": 78.0}}
    ]
}

# Scenario B: High Blood Pressure (High Risk Alert)
high_risk_payload = {
    "client_time": datetime.now(timezone.utc).isoformat(),
    "timezone": "Asia/Kolkata",
    "records": [
        {"type": "steps", "timestamp": datetime.now(timezone.utc).isoformat(), "values": {"count": 200.0}},
        {"type": "heart_rate", "timestamp": datetime.now(timezone.utc).isoformat(), "values": {"bpm": 92.0}},
        {"type": "sleep", "timestamp": datetime.now(timezone.utc).isoformat(), "values": {"duration_minutes": 320.0}},
        {"type": "blood_pressure", "timestamp": datetime.now(timezone.utc).isoformat(), "values": {"systolic": 154.0, "diastolic": 98.0}}
    ]
}

def run_test(scenario_name, payload):
    print(f"\n--- Testing Scenario: {scenario_name} ---")
    try:
        response = httpx.post(URL, json=payload, timeout=10.0)
        print(f"Status Code: {response.status_code}")
        print("Response JSON:")
        print(json.dumps(response.json(), indent=2))
    except Exception as e:
        print(f"Failed to connect to backend: {e}")
        print("Make sure your FastAPI server is running with 'uvicorn app.main:app --reload'")

if __name__ == "__main__":
    # Test healthy scenario
    run_test("Healthy Baseline Vitals", healthy_payload)
    
    # Test high risk warning triggers
    run_test("Elevated Vitals Spike", high_risk_payload)
