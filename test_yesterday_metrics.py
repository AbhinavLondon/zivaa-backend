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
    print()

async def main():
    # Neha (ID: 22222222-2222-2222-2222-222222222222)
    await test_metrics("22222222-2222-2222-2222-222222222222", "Neha")
    # Shashank (ID: 33333333-3333-3333-3333-333333333333)
    await test_metrics("33333333-3333-3333-3333-333333333333", "Shashank")

asyncio.run(main())
