import urllib.request
import json

patient_id = "0c445588-b36c-478f-9be3-2addfc77dc1c"
url = "http://127.0.0.1:8000/api/v1/health/daily-plan"
payload = json.dumps({"patient_id": patient_id}).encode('utf-8')
req = urllib.request.Request(url, data=payload, headers={'Content-Type': 'application/json'})

try:
    with urllib.request.urlopen(req) as response:
        data = json.loads(response.read().decode('utf-8'))
        print(json.dumps(data, indent=2))
except Exception as e:
    print("Error:", e)
    if hasattr(e, 'read'):
        print(e.read().decode('utf-8'))
