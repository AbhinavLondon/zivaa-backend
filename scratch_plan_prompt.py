import asyncio
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app.services.medgemma_services as mg_services
from app.services.llm_plan import build_plan_context

async def main():
    original_call = mg_services._call_medgemma

    async def mock_call(prompt, **kwargs):
        print("-------------------- PROMPT START --------------------")
        print(prompt)
        print("-------------------- PROMPT END --------------------")
        sys.exit(0) # Exit early after printing

    mg_services._call_medgemma = mock_call

    try:
        plan_ctx = build_plan_context("0c445588-b36c-478f-9be3-2addfc77dc1c")
        await mg_services.generate_medgemma_plan(plan_ctx)
    except SystemExit:
        pass

if __name__ == "__main__":
    asyncio.run(main())
