import asyncio
import sys
import os

sys.path.insert(0, os.path.abspath('zivaa-backend'))

from app.services.scheduler_jobs import run_morning_generation_pipeline

async def main():
    await run_morning_generation_pipeline("0c445588-b36c-478f-9be3-2addfc77dc1c")

if __name__ == "__main__":
    asyncio.run(main())
