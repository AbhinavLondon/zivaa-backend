"""Test of the yesterday-metrics getter function."""
import sys, os, asyncio
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv()

from app.services.yesterday_metrics import get_yesterday_metrics

async def test_metrics(pid: str, name: str):
    print("=" * 60)
    print(f"YESTERDAY METRICS FOR {name.upper()}")
    print("=" * 60)
    
    result = await get_yesterday_metrics(pid)
    
    print(f"Date: {result['date']}")
    print(f"Steps: {result['steps']}")
    print(f"Sleep Hours: {result['sleep_hours']}")
    print(f"Mood Score: {result['mood_score']}")
    print(f"Walking Cadence: {result.get('avg_cadence_spm')} spm")
    print(f"Active Movement: {result.get('active_movement_minutes')} mins")
    print(f"Active Daytime Hours: {result.get('active_hours_count')}/12")
    print()

async def main():
    await test_metrics("0c445588-b36c-478f-9be3-2addfc77dc1c", "Active Patient")

asyncio.run(main())
