"""Quick test of the clinical nudge service for Neha."""
import sys, os, asyncio
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv()

from app.services.insights.data_fetcher import fetch_patient_context
from app.services.insights.engine import InsightEngine
from app.services.llm_nudge import generate_clinical_nudge

async def main():
    pid = "33333333-3333-3333-3333-333333333333"
    
    print("=" * 60)
    print("CLINICAL NUDGE TEST FOR SHASHANK")
    print("=" * 60)
    print()
    
    ctx = fetch_patient_context(pid)
    engine = InsightEngine()
    output = engine.evaluate_patient(pid, ctx)
    
    print(f"Active Insights: {[i.name for i in output.active_insights]}")
    print()
    
    result = await generate_clinical_nudge(output.active_insights, patient_name="Shashank")
    
    import json
    print(json.dumps(result, indent=2))

asyncio.run(main())
