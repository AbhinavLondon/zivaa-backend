"""Quick test of the daily plan service for Shashank."""
import sys, os, asyncio
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv()

from app.services.insights.data_fetcher import fetch_patient_context
from app.services.llm_plan import generate_daily_plan

async def test_patient_plan(pid: str, name: str, location: str):
    print("=" * 60)
    print(f"DAILY PLAN TEST FOR {name.upper()} ({location})")
    print("=" * 60)
    
    ctx = fetch_patient_context(pid)
    latest_vitals = {}
    mapping = {
        "steps": "total_steps",
        "heart_rate": "avg_heart_rate",
        "sleep_hours": "sleep_hours",
        "sleep_quality": "sleep_quality_score"
    }
    for metric_name, values in ctx.vitals._vitals.items():
        if values:
            db_key = mapping.get(metric_name, metric_name)
            latest_vitals[db_key] = values[-1].value
            
    print(f"Vitals: {latest_vitals}")
    print()
    
    result = await generate_daily_plan(latest_vitals, conditions=[], location=location)
    
    # Print breakfast, lunch, dinner tasks to verify food items
    print("Plan tasks:")
    for period, tasks in result["schedule"].items():
        print(f"  {period.capitalize()}:")
        for t in tasks:
            if "Eat" in t["task"] or "Drink" in t["task"]:
                print(f"    * {t['task']}")
    print()

async def main():
    await test_patient_plan("33333333-3333-3333-3333-333333333333", "Shashank", "Delhi")
    await test_patient_plan("22222222-2222-2222-2222-222222222222", "Neha", "Bengaluru")

asyncio.run(main())
