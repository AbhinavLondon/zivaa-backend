import os
from supabase import create_client
from dotenv import load_dotenv
import json

load_dotenv("C:/Users/abhin/Downloads/Zivaa Apps/zivaa-backend/.env")
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
supabase = create_client(url, key)

res = supabase.table("fhir_diagnostic_reports").select("id, summary_explanation, created_at").order("created_at", desc=True).limit(3).execute()
print("Reports:")
print(json.dumps(res.data, indent=2))

for r in res.data:
    obs_res = supabase.table("fhir_observations").select("loinc_code, value_numeric, resource").eq("report_id", r["id"]).execute()
    print(f"\nObservations for {r['id']}:")
    for obs in obs_res.data:
        print(f"  - {obs['loinc_code']}: {obs['value_numeric']}")
