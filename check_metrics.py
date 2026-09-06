import asyncio
from app.services.insights.data_fetcher import supabase

async def main():
    res = supabase.table('vitals_raw').select('*').order('recorded_at', desc=True).limit(20).execute()
    for r in res.data:
        print(f"type: {r.get('metric_type')}, time: {r.get('recorded_at')}, source: {r.get('source')}")

if __name__ == '__main__':
    asyncio.run(main())
