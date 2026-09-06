"""Test script for lab history comparison service and API endpoint."""
import sys, os
# Add user-site packages to sys.path so IDE linter resolves imports
user_site = os.path.expanduser("~\\AppData\\Roaming\\Python\\Python314\\site-packages")
if user_site not in sys.path and os.path.exists(user_site):
    sys.path.insert(0, user_site)

from fastapi.testclient import TestClient
from app.main import app
from app.services.lab_history import get_patient_lab_history

client = TestClient(app)

# Patient ID for Ranjit Sharma (Papa) who has seeded clinical baseline and lab reports
PATIENT_ID = "11111111-1111-1111-1111-111111111111"

def test_service_directly():
    print("=" * 70)
    print("TESTING LAB HISTORY SERVICE DIRECTLY")
    print("=" * 70)
    
    result = get_patient_lab_history(PATIENT_ID)
    print(f"Patient ID: {result['patient_id']}")
    print(f"Available Biomarkers for comparison: {[b['code'] for b in result['available_biomarkers']]}")
    
    comp_data = result["comparison_data"]
    print(f"Grouped biomarkers in comparison: {list(comp_data.keys())}")
    for code, details in comp_data.items():
        print(f"\nBiomarker: {details['name']} ({code}) in {details['unit']}")
        print(f"  Reference Range: {details['reference_low']} - {details['reference_high']}")
        print(f"  Measurements over time:")
        for entry in details["history"]:
            print(f"    - {entry['measured_at']}: {entry['value']} ({entry['flag']})")
    print()

def test_api_endpoint():
    print("=" * 70)
    print("TESTING LAB HISTORY API ENDPOINT")
    print("=" * 70)
    
    # 1. Fetch all biomarkers
    response = client.get(f"/api/v1/health/lab-history/{PATIENT_ID}")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}. Response: {response.text}"
    data = response.json()
    print("All biomarkers fetched successfully.")
    print(f"Available: {[b['code'] for b in data['available_biomarkers']]}")
    print(f"Comparison keys: {list(data['comparison_data'].keys())}")
    
    # 2. Fetch specific filtered biomarkers (e.g. HBA1C and TSH)
    response_filtered = client.get(
        f"/api/v1/health/lab-history/{PATIENT_ID}?biomarker=HBA1C&biomarker=TSH"
    )
    assert response_filtered.status_code == 200, f"Expected 200, got {response_filtered.status_code}"
    data_filtered = response_filtered.json()
    print("\nFiltered biomarkers fetched successfully (HBA1C & TSH).")
    print(f"Available (should still show all): {[b['code'] for b in data_filtered['available_biomarkers']]}")
    print(f"Comparison keys (should only show HBA1C, TSH): {list(data_filtered['comparison_data'].keys())}")
    print()

if __name__ == "__main__":
    test_service_directly()
    test_api_endpoint()
    print("All lab history tests completed successfully!")
