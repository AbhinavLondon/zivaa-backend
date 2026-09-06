import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

from app.services.scheduler_jobs import run_memory_consolidation

if __name__ == "__main__":
    asyncio.run(run_memory_consolidation())
