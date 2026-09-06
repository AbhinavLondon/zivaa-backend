import os
from supabase import create_client
from dotenv import load_dotenv
import json

load_dotenv("C:/Users/abhin/Downloads/Zivaa Apps/zivaa-backend/.env")
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
supabase = create_client(url, key)

res = supabase.table("fhir_observations").select("*").eq("report_id", "c9fe9663-ad35-48d7-96ca-f750e463a656").execute()
print(f"Observations for c9fe9663-ad35-48d7-96ca-f750e463a656: {len(res.data)}")
print(json.dumps(res.data, indent=2))
