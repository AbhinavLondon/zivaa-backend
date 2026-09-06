import asyncio
from app.services.insights.data_fetcher import supabase

async def main():
    res = supabase.table('vitals_raw').select('metric_type, recorded_at, source').order('recorded_at', desc=True).limit(50).execute()
    print('Recent vitals_raw records:')
    for r in res.data:
        print(f"{r['metric_type']} - {r['recorded_at']} - {r['source']}")

if __name__ == '__main__':
    asyncio.run(main())
