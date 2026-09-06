import asyncio
from app.services.insights.data_fetcher import supabase

async def main():
    res = supabase.table('vitals_daily').select('*').order('date', desc=True).limit(5).execute()
    for r in res.data:
        print(f"date: {r.get('date')}, sleep_hours: {r.get('sleep_hours')}")

if __name__ == '__main__':
    asyncio.run(main())
