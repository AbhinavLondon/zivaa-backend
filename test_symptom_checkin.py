import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

from app.services.scheduler_jobs import run_symptom_checkins

if __name__ == "__main__":
    asyncio.run(run_symptom_checkins())
