import os
import sys
import json
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from app.main import app

client = TestClient(app)

def test_insights():
    patient_id = "11111111-1111-1111-1111-111111111111"
    
    print("\n--- Getting Patient Insights ---")
    resp = client.get(f"/api/v1/health/insights/{patient_id}")
    if resp.status_code == 200:
        data = resp.json()
        print(json.dumps(data, indent=2))
        
        # Look for nudges
        print("\n--- Generating Daily Summary ---")
        summary_resp = client.get(f"/api/v1/health/daily-summary/{patient_id}")
        if summary_resp.status_code == 200:
             print(json.dumps(summary_resp.json(), indent=2))
    else:
        print("Insights Error:", resp.text)

if __name__ == "__main__":
    test_insights()
