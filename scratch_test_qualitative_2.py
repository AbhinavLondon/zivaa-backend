import uuid
import os
from dotenv import load_dotenv

load_dotenv("C:/Users/abhin/Downloads/Zivaa Apps/zivaa-backend/.env")

# Must set before importing fhir to mock background tasks
os.environ["TESTING"] = "true"

from app.api.endpoints.fhir import process_fhir_bundle_internal
from supabase import create_client

url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
supabase = create_client(url, key)

def test_ingestion():
    # Use a real patient_id from the DB to avoid FK errors
    res_pat = supabase.table("patients").select("id").limit(1).execute()
    if not res_pat.data:
        print("No patients found.")
        return
    patient_id = res_pat.data[0]["id"]
    
    mock_bundle = {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": [
            {
                "resource": {
                    "resourceType": "DiagnosticReport",
                    "status": "final",
                    "presentedForm": [{"title": "Test summary"}]
                }
            },
            {
                "resource": {
                    "resourceType": "Observation",
                    "status": "final",
                    "code": {
                        "text": "Urine Bacteria",
                        "coding": [{"code": "UNKNOWN_URINE_BACTERIA"}]
                    },
                    "valueString": "Present"
                }
            },
            {
                "resource": {
                    "resourceType": "Observation",
                    "status": "final",
                    "code": {
                        "text": "Empty Glitch"
                    }
                    # no value, should be discarded
                }
            }
        ]
    }
    
    print("Testing internal ingestion...")
    process_fhir_bundle_internal(patient_id, mock_bundle)
    
    # Check what was inserted
    res = supabase.table("fhir_observations").select("*").eq("patient_id", patient_id).order("created_at", desc=True).limit(2).execute()
    
    print("\nRecent Observations in DB:")
    for obs in res.data:
        print(f"- LOINC: {obs['loinc_code']}, value_numeric: {obs['value_numeric']}, value_string: {obs.get('value_string')}")

if __name__ == "__main__":
    test_ingestion()
