import asyncio
import os
import sys

from dotenv import load_dotenv
load_dotenv()

from app.services.scheduler_jobs import run_batch_pattern_detection

async def main():
    print("=== Testing run_batch_pattern_detection ===")
    try:
        await run_batch_pattern_detection()
        print("Successfully completed batch pattern detection test.\n")
    except Exception as e:
        print(f"Error in batch pattern detection: {e}\n")

if __name__ == "__main__":
    asyncio.run(main())
