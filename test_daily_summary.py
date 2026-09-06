"""Quick test of the daily summary with real Supabase data."""
import sys, os, asyncio
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv()

from app.services.daily_summary import generate_daily_summary

async def main():
    pid = "33333333-3333-3333-3333-333333333333"
    
    print("=" * 60)
    print("DAILY SUMMARY TEST")
    print("=" * 60)
    print()
    
    result = await generate_daily_summary(pid, patient_name="Shashank")
    
    print(f"Status: {result['overall_status']}")
    print(f"Insights: {result['insights_count']}")
    print(f"Top concern: {result['top_concern']}")
    print()
    print("SUMMARY:")
    print("-" * 60)
    print(result["summary"])
    print("-" * 60)

asyncio.run(main())
