import asyncio
from app.services.insights.engine import engine
from app.services.llm_nudge import generate_clinical_nudge
from app.services.insights.data_fetcher import supabase

async def test():
    # Fetch Ranjit's UUID dynamically
    resp = supabase.table("patients").select("id").eq("full_name", "Ranjit Sharma").execute()
    if not resp.data:
        print("Error: Could not find patient 'Ranjit Sharma' in the database.")
        return
        
    patient_id = resp.data[0]["id"]
    print(f"Running Engine for Ranjit Sharma (ID: {patient_id})")
    
    try:
        # Run rules engine
        output = engine.evaluate_patient(patient_id)
        
        print(f"\n{'='*60}")
        print(f" TRIGGERED INSIGHTS ({len(output.active_insights)})")
        print(f"{'='*60}")
        for i in output.active_insights:
            print(f"  [{i.severity.value}] {i.name}")
            print(f"       {i.message}")
            print(f"       Evidence: {i.evidence}")
            print()
        
        print(f"{'='*60}")
        print(f" SKIPPED RULES ({len(output.skipped_rules)})")
        print(f"{'='*60}")
        for s in output.skipped_rules:
            print(f"  [SKIP] {s.name}")
            print(f"       Reason: {s.skip_reason}")
            print()
            
        print(f"{'='*60}")
        print(f" LLM NUDGE")
        print(f"{'='*60}")
        nudge = await generate_clinical_nudge(output.active_insights, patient_name="Ranjit")
        import json
        print(json.dumps(nudge, indent=2))
        
    except Exception as e:
        import traceback
        print(f"Error during test: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test())
