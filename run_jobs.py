import asyncio
from app.services.scheduler_jobs import run_nightly_summary, run_nightly_plan

async def main():
    print("Starting manual run of nightly jobs...")
    print("Running nightly summary...")
    await run_nightly_summary()
    print("Running nightly plan...")
    await run_nightly_plan()
    print("Done!")

if __name__ == "__main__":
    asyncio.run(main())
