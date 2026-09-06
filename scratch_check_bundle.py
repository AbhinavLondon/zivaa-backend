import os
from supabase import create_client
from dotenv import load_dotenv
import json

load_dotenv("C:/Users/abhin/Downloads/Zivaa Apps/zivaa-backend/.env")
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
supabase = create_client(url, key)

res = supabase.table("fhir_diagnostic_reports").select("resource").order("created_at", desc=True).limit(1).execute()
resource = res.data[0]["resource"]

# Check if there are observations in the bundle? No, this is just the diagnostic report resource.
# We need to look at the MedGemma payloads log.
