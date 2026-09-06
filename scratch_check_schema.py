import os
from supabase import create_client
from dotenv import load_dotenv
import json

load_dotenv("C:/Users/abhin/Downloads/Zivaa Apps/zivaa-backend/.env")
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
supabase = create_client(url, key)

res = supabase.table("fhir_observations").select("*").limit(1).execute()
print("Columns:", res.data[0].keys() if res.data else "No data")
