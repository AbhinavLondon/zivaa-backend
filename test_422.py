import httpx
import json

try:
    response = httpx.post('http://localhost:8000/api/v1/fhir/Bundle', params={'patient_id': '123'}, files={'file': ('a.txt', b'test', 'text/plain')})
    print(response.status_code)
    print(json.dumps(response.json(), indent=2))
except Exception as e:
    print("Error:", e)
