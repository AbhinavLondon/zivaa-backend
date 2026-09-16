import os
import requests
from dotenv import load_dotenv

load_dotenv('c:/Users/abhin/Downloads/Zivaa Apps/zivaa-backend/.env')

supabase_url = os.getenv('SUPABASE_URL')
supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')

headers = {
    'apikey': supabase_key,
    'Authorization': f'Bearer {supabase_key}'
}

# Query vitals_daily for patient 0c445588-b36c-478f-9be3-2addfc77dc1c around 2026-09-13
url = f"{supabase_url}/rest/v1/vitals_daily?patient_id=eq.0c445588-b36c-478f-9be3-2addfc77dc1c&date=gte.2026-09-12T00:00:00&date=lte.2026-09-14T23:59:59&select=*"
res = requests.get(url, headers=headers)
print("VITALS_DAILY:")
print(res.json())

# Also query vitals_raw for StepsRecord on 2026-09-13
raw_url = f"{supabase_url}/rest/v1/vitals_raw?patient_id=eq.0c445588-b36c-478f-9be3-2addfc77dc1c&metric_type=eq.StepsRecord&recorded_at=gte.2026-09-12T23:00:00Z&recorded_at=lte.2026-09-13T23:59:59Z&select=id,source,recorded_at,timezone,values,is_outlier"
raw_res = requests.get(raw_url, headers=headers)
raw_data = raw_res.json()
print(f"\nVITALS_RAW count: {len(raw_data)}")
sources = {}
for r in raw_data:
    s = r.get('source')
    sources[s] = sources.get(s, 0) + 1
print("Sources distribution:", sources)
for r in raw_data[:5]:
    print("Sample raw record:", r)
for r in raw_data:
    if 'shealth' in r.get('source', ''):
        print("sHealth record:", r)
