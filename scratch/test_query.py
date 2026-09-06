import os
import sys
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL:
    print("No SUPABASE_URL found.")
    exit(1)

try:
    supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    response = supabase.table("fhir_observations").select("*").order("created_at", desc=True).limit(5).execute()
    for r in response.data:
        print(f"ID: {r.get('id')}")
        print(f"Patient: {r.get('patient_id')}")
        print(f"LOINC: {r.get('loinc_code')}")
        print(f"Value: {r.get('value_numeric')}")
        print(f"Unit: {r.get('unit')}")
        print(f"Ref Low: {r.get('reference_low')}, Ref High: {r.get('reference_high')}")
        print(f"Explanation: {r.get('patient_explanation')}")
        print(f"Resource: {r.get('resource')}")
        print("-" * 40)
except Exception as e:
    print(f"Error querying: {e}")
