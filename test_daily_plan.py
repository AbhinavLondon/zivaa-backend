import sys
import os
import asyncio
import json

# Add user-site packages to sys.path so IDE linter resolves imports
user_site = os.path.expanduser("~\\AppData\\Roaming\\Python\\Python314\\site-packages")
if user_site not in sys.path and os.path.exists(user_site):
    sys.path.insert(0, user_site)

from fastapi.testclient import TestClient
from app.main import app
from app.services.llm_plan import generate_daily_plan

client = TestClient(app)

async def test_service_directly():
    print("\n--- [TEST 1] Calling generate_medgemma_plan Service Directly (With Diabetes) ---")
    from app.services.medgemma_services import generate_medgemma_plan
    plan_context = {
        "patient": {
            "name": "Patient",
            "age": 72,
            "sex": "male",
            "location": "Pune",
            "conditions": ["Type 2 Diabetes"]
        },
        "vitals_today": {
            "heart_rate": 78.0,
            "bp_systolic": 142.0,
            "bp_diastolic": 90.0,
            "sleep_hours": 5.5,
            "steps": 850,
            "blood_glucose": 145.0
        },
        "active_insights": [],
        "lab_alerts": [],
        "med_adherence": {"rate": 90.0, "missed_count": 0}
    }
    
    result = await generate_medgemma_plan(plan_context)
    print(f"Service returned daily plan successfully.")
    print(f"Summary: {result.get('summary')}")
    print(f"Schedule keys: {list(result.get('schedule', {}).keys())}")
    for period, tasks in result.get('schedule', {}).items():
        print(f"  {period.capitalize()}: {len(tasks)} tasks")
        for task in tasks:
            print(f"    - [{ 'x' if task.get('completed') else ' ' }] {task.get('task')}")

def test_api_endpoint():
    print("\n--- [TEST 2] Calling /api/v1/health/daily-plan API Endpoint ---")
    payload = {
        "vitals": {
            "avg_heart_rate": 74.0,
            "bp_systolic": 128.0,
            "bp_diastolic": 82.0,
            "sleep_hours": 7.5,
            "total_steps": 1200.0,
            "glucose_mg_dl": 110.0
        },
        "conditions": ["Type 2 Diabetes"]
    }
    
    response = client.post("/api/v1/health/daily-plan", json=payload)
    assert response.status_code == 200, f"Expected 200, got {response.status_code}. Response: {response.text}"
    
    data = response.json()
    print("API Response received successfully!")
    
    # Extract the plan (testing the medgemma one since it's the fallback here)
    plan_data = data.get("pure_medgemma_plan", {})
    
    print(f"Summary: {plan_data.get('summary')}")
    print("Schedule Periods:")
    schedule = plan_data.get("schedule", {})
    for period in ["morning", "afternoon", "evening", "night"]:
        tasks = schedule.get(period, [])
        print(f"  {period.capitalize()}: {len(tasks)} tasks")
        for task in tasks:
            print(f"    - {task.get('task')}")

if __name__ == "__main__":
    # Run service test
    asyncio.run(test_service_directly())
    # Run API endpoint test
    test_api_endpoint()
    print("\nAll integration tests passed!")
