import asyncio
import json
from datetime import datetime, timezone
from app.services.insights.data_fetcher import supabase
from app.services.llm_plan import build_plan_context, generate_daily_plan

async def main():
    patient_id = '0c445588-b36c-478f-9be3-2addfc77dc1c'
    print("1. Building rich plan context for patient...")
    ctx = build_plan_context(patient_id)
    patient_name = ctx.get("patient", {}).get("name")
    patient_age = ctx.get("patient", {}).get("age")
    symptoms_count = len(ctx.get("symptoms", []))
    agreed_count = len(ctx.get("agreed_actions", []))
    print(f"   Patient: {patient_name} (Age: {patient_age})")
    print(f"   Decrypted Symptoms: {symptoms_count}")
    print(f"   Agreed Actions: {agreed_count}")

    print("2. Generating daily plan with new schema...")
    plan = await generate_daily_plan(ctx)
    print("   Summary:", plan.get("summary"))
    
    today_date = datetime.now(timezone.utc).date().isoformat()
    payload = {
        "patient_id": patient_id,
        "summary": plan.get("summary", "Your daily health plan"),
        "schedule": plan.get("schedule", {}),
        "health_context": plan.get("health_context", {}),
        "source": "gemini_llm",
        "date": today_date,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    
    print(f"3. Persisting to Supabase daily_plans for date {today_date}...")
    existing = supabase.table("daily_plans").select("id").eq("patient_id", patient_id).eq("date", today_date).execute()
    if existing.data:
        plan_id = existing.data[0]["id"]
        supabase.table("daily_plans").update(payload).eq("id", plan_id).execute()
        print(f"   Successfully updated existing daily_plan row {plan_id}!")
    else:
        res = supabase.table("daily_plans").insert(payload).execute()
        print(f"   Successfully inserted new daily_plan row!")

    print("\n4. Schedule Breakdown:")
    schedule = plan.get("schedule", {})
    for period in ["morning", "afternoon", "evening", "night"]:
        tasks = schedule.get(period, [])
        print(f"\n--- {period.upper()} ({len(tasks)} tasks) ---")
        for i, t in enumerate(tasks):
            action_info = t.get("action", {})
            action_type = action_info.get("type") or action_info.get("action_type")
            cta = action_info.get("cta_label")
            ex_ids = action_info.get("exercise_ids")
            badge = t.get("provenance", {}).get("badge_text") or t.get("provenance", {}).get("badge")
            print(f"  [{i+1}] {t.get('time')}: {t.get('task')} | Cat: {t.get('category')} | Badge: {badge} | CTA: '{cta}' ({action_type}) | ExIDs: {ex_ids}")

if __name__ == "__main__":
    asyncio.run(main())
