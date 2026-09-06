import os
from supabase import create_client
from dotenv import load_dotenv
import json

load_dotenv("C:/Users/abhin/Downloads/Zivaa Apps/zivaa-backend/.env")
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
supabase = create_client(url, key)

res = supabase.table("fhir_diagnostic_reports").select("*").order("created_at", desc=True).limit(1).execute()
print(json.dumps(res.data, indent=2))
