import time
import urllib.request
import json
from dotenv import dotenv_values

env = dotenv_values('c:/Users/abhin/Downloads/Zivaa Apps/zivaa-backend/.env')
url = f"{env['SUPABASE_URL']}/rest/v1"
key = env['SUPABASE_SERVICE_ROLE_KEY']
pid = '0c445588-b36c-478f-9be3-2addfc77dc1c'

headers = {
    'apikey': key,
    'Authorization': f'Bearer {key}'
}

# 1. Check vitals_daily query speed and results
test_url = f"{url}/vitals_daily?patient_id=eq.{pid}&order=date.desc&limit=7"
print(f"Querying: {test_url}...")

t0 = time.time()
try:
    req = urllib.request.Request(test_url, headers=headers)
    with urllib.request.urlopen(req) as resp:
        duration_ms = (time.time() - t0) * 1000
        data = json.loads(resp.read().decode('utf-8'))
        print(f"STATUS: {resp.status} in {duration_ms:.1f}ms")
        print(f"Returned {len(data)} records")
        if data:
            latest = data[0]
            print(f"Latest date: {latest.get('date')}")
            print(f"Steps: {latest.get('total_steps')}")
            print(f"Sleep Hours: {latest.get('sleep_hours')}")
            print(f"Avg HR: {latest.get('avg_heart_rate')}")
            print(f"Sleep Efficiency: {latest.get('sleep_efficiency_pct')}")
            print(f"Awakenings: {latest.get('awakenings_count')}")
            print("SUCCESS: vitals_daily returned immediately without timeout!")
except urllib.error.HTTPError as e:
    duration_ms = (time.time() - t0) * 1000
    print(f"FAILED with HTTP {e.code} after {duration_ms:.1f}ms: {e.read().decode('utf-8')}")
except Exception as e:
    duration_ms = (time.time() - t0) * 1000
    print(f"ERROR after {duration_ms:.1f}ms: {e}")
