import os
from supabase import create_client
from dotenv import load_dotenv

load_dotenv("C:/Users/abhin/Downloads/Zivaa Apps/zivaa-backend/.env")
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
supabase = create_client(url, key)

res = supabase.table("fhir_observations").select("*").order("created_at", desc=True).limit(5).execute()
import json
print(json.dumps(res.data, indent=2))
