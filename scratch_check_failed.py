import os
from supabase import create_client
from dotenv import load_dotenv
import json

load_dotenv("C:/Users/abhin/Downloads/Zivaa Apps/zivaa-backend/.env")
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
supabase = create_client(url, key)

obs_res = supabase.table("fhir_observations").select("resource").eq("report_id", "0de566d7-61af-4a25-b6ce-93db421c3d16").execute()
print(json.dumps(obs_res.data, indent=2))
