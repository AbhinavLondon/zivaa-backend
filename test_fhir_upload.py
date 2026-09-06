import os
import sys
from fastapi.testclient import TestClient

# Ensure app is importable
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app.main import app

client = TestClient(app)

def test_upload():
    report_path = r"C:\Users\abhin\.gemini\antigravity-ide\brain\88e4c53f-bb4f-4cbc-871b-b3e75d757287\scratch\sample_lab_report.txt"
    
    print(f"Reading sample report from {report_path}...")
    with open(report_path, "rb") as f:
        file_bytes = f.read()
    
    # Use a dummy UUID
    patient_id = "11111111-1111-1111-1111-111111111111"
    
    print(f"Sending POST request to /api/v1/fhir/Bundle for patient {patient_id}...")
    response = client.post(
        "/api/v1/fhir/Bundle",
        params={"patient_id": patient_id},
        files={"file": ("sample_lab_report.txt", file_bytes, "text/plain")}
    )
    
    print("\nStatus Code:", response.status_code)
    try:
        import json
        print("Response JSON:")
        print(json.dumps(response.json(), indent=2))
    except Exception as e:
        print("Response Text:", response.text)

if __name__ == "__main__":
    test_upload()
