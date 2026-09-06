import os
from supabase import create_client
from dotenv import load_dotenv

load_dotenv("C:/Users/abhin/Downloads/Zivaa Apps/zivaa-backend/.env")
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
supabase = create_client(url, key)

# Delete observations with loinc_code = 'UNKNOWN'
res = supabase.table("fhir_observations").delete().eq("loinc_code", "UNKNOWN").execute()
print(f"Deleted {len(res.data)} observations with UNKNOWN loinc_code.")
