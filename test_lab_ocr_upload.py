import os
import sys
import json
from fastapi.testclient import TestClient

# Ensure app is importable
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app.main import app

client = TestClient(app)

def test_upload():
    report_path = r"c:\Users\abhin\Downloads\Zivaa Apps\zivaa-backend\scratch\user_ocr_lab_report.txt"
    
    print(f"Reading sample report from {report_path}...")
    with open(report_path, "rb") as f:
        file_bytes = f.read()
    
    # Use a dummy UUID
    patient_id = "11111111-1111-1111-1111-111111111111"
    
    print(f"Sending POST request to /api/v1/fhir/Bundle/upload for patient {patient_id}...")
    response = client.post(
        "/api/v1/fhir/Bundle/upload",
        params={"patient_id": patient_id},
        files={"file": ("user_ocr_lab_report.txt", file_bytes, "text/plain")}
    )
    
    print("\nStatus Code:", response.status_code)
    try:
        print("Response JSON:")
        print(json.dumps(response.json(), indent=2))
        
        # Next step in end to end flow: Get the updated lab trends for the patient
        print("\n--- Getting Lab Trends to see if new insights are generated ---")
        trends_resp = client.get(f"/api/v1/health/lab-trends/{patient_id}")
        if trends_resp.status_code == 200:
             print("Lab Trends Response JSON:")
             print(json.dumps(trends_resp.json(), indent=2))
        else:
             print("Lab Trends Error:", trends_resp.text)
             
    except Exception as e:
        print("Response Text:", response.text)

if __name__ == "__main__":
    test_upload()
