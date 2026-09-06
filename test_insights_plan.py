"""
Test: Generate daily plans for Ranjit Sharma using the insights-driven system.
Shows both the structured fallback plan and the Gemini LLM plan.
"""
import asyncio
import json
from app.services.llm_plan import build_plan_context, get_fallback_daily_plan, generate_daily_plan

RANJIT_ID = "11111111-1111-1111-1111-111111111111"

def print_plan(plan: dict, title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")
    print(f"\nSummary:\n  {plan['summary']}\n")
    
    schedule = plan.get("schedule", {})
    for slot in ("morning", "afternoon", "evening", "night"):
        tasks = schedule.get(slot, [])
        print(f"  {slot.upper()} ({len(tasks)} tasks):")
        for t in tasks:
            task_text = t.get("task", t) if isinstance(t, dict) else t
            print(f"    - {task_text}")
        print()
    
    hc = plan.get("health_context")
    if hc:
        print(f"  Health Context:")
        print(f"    Conditions addressed: {hc.get('conditions_addressed', [])}")
        print(f"    Insights count: {hc.get('insights_count', hc.get('high_alerts', 0))}")
        print(f"    Lab alerts: {hc.get('lab_alerts_count', 0)}")
        print(f"    Med adherence: {hc.get('med_adherence_rate', 100)}%")
    
    alerts = plan.get("active_alerts", [])
    if alerts:
        print(f"\n  Active Alerts Addressed:")
        for a in alerts:
            print(f"    - {a}")

async def main():
    # Build context
    print("Building plan context for Ranjit...")
    ctx = build_plan_context(RANJIT_ID)
    
    p = ctx["patient"]
    print(f"Patient: {p['name']}, {p['age']}yo {p['sex']}, {p['location']} ({p['region']})")
    print(f"Conditions: {', '.join(p['conditions'])}")
    print(f"Active insights: {len(ctx['active_insights'])}")
    print(f"Lab alerts: {len(ctx['lab_alerts'])}")
    print(f"Med adherence: {ctx['med_adherence']['rate']}%")
    
    # Plan 1: Structured Fallback
    fallback = get_fallback_daily_plan(ctx)
    print_plan(fallback, "PLAN 1: STRUCTURED FALLBACK (No LLM)")
    
    # Plan 2: Gemini LLM
    print("\n\nCalling Gemini API for LLM plan...")
    llm_plan = await generate_daily_plan(ctx)
    print_plan(llm_plan, "PLAN 2: GEMINI LLM-GENERATED")

asyncio.run(main())
