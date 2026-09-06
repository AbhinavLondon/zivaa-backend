"""
Full evaluation of Mukesh Patel: Rules, Nudges, and Plans.
"""
import asyncio
import json
from app.services.insights.engine import engine
from app.services.llm_nudge import generate_clinical_nudge
from app.services.llm_plan import build_plan_context, get_fallback_daily_plan, generate_daily_plan
from app.services.ml_pipeline import extract_features
from app.services.insights.data_fetcher import supabase

MUKESH_ID = "44444444-4444-4444-4444-444444444444"

def divider(title):
    print(f"\n{'='*65}")
    print(f"  {title}")
    print(f"{'='*65}\n")


async def main():
    # ═══════════════════════════════════════════════════════════
    # 1. INSIGHTS ENGINE — All 18 rules
    # ═══════════════════════════════════════════════════════════
    divider("1. INSIGHTS ENGINE — RULES EVALUATION")

    output = engine.evaluate_patient(MUKESH_ID)

    total_rules = len(output.active_insights) + len(output.skipped_rules)
    print(f"Total rules evaluated: {total_rules}")
    print(f"Active (triggered): {len(output.active_insights)}")
    print(f"Skipped/inactive: {len(output.skipped_rules)}")
    if output.calibration_message:
        print(f"Calibration: {output.calibration_message}")
    print()

    # Show triggered rules
    print("  TRIGGERED RULES:")
    print(f"  {'Rule Name':<40} {'Severity':<10} {'Category'}")
    print(f"  {'-'*40} {'-'*10} {'-'*15}")
    for result in output.active_insights:
        print(f">>> {result.name:<40} {result.severity.value:<10} {result.category.value}")

    print()
    print("  SKIPPED / NOT TRIGGERED:")
    for result in output.skipped_rules:
        reason = result.skip_reason if result.skip_reason else 'not triggered'
        print(f"    {result.name:<40} ({reason})")

    print()

    # Show active insights detail
    if output.active_insights:
        print("\n  ACTIVE INSIGHT DETAILS:")
        for i, insight in enumerate(output.active_insights, 1):
            print(f"\n  [{i}] {insight.name}")
            print(f"      Severity: {insight.severity.value}")
            print(f"      Category: {insight.category.value}")
            print(f"      Rule ID:  {insight.rule_id}")
            print(f"      Message:  {insight.message}")
            if insight.evidence:
                data_keys = list(insight.evidence.keys())[:6]
                for k in data_keys:
                    v = insight.evidence[k]
                    if isinstance(v, float):
                        v = round(v, 2)
                    print(f"      {k}: {v}")

    # ═══════════════════════════════════════════════════════════
    # 2. CLINICAL NUDGE
    # ═══════════════════════════════════════════════════════════
    divider("2. CLINICAL NUDGE")

    # Get vitals for nudge
    try:
        v_resp = supabase.table("vitals_daily") \
            .select("*") \
            .eq("patient_id", MUKESH_ID) \
            .order("date", desc=True) \
            .limit(1) \
            .execute()

        if v_resp.data:
            vitals_row = v_resp.data[0]
            features = extract_features([{
                "type": "heart_rate",
                "timestamp": vitals_row["date"] + "T08:00:00",
                "values": {"bpm": vitals_row.get("avg_heart_rate", 75)}
            }])

            # Build features dict from vitals
            features["avg_heart_rate"] = vitals_row.get("avg_heart_rate", 75)
            features["bp_systolic"] = vitals_row.get("bp_systolic", 120)
            features["bp_diastolic"] = vitals_row.get("bp_diastolic", 80)
            features["total_steps"] = vitals_row.get("total_steps", 0)
            features["sleep_hours"] = vitals_row.get("sleep_hours", 7)
            features["blood_glucose"] = vitals_row.get("blood_glucose_avg")
            features["oxygen_sat"] = vitals_row.get("oxygen_sat_avg")

            print(f"  Latest vitals used for nudge:")
            for k, v in features.items():
                if v is not None:
                    print(f"    {k}: {v}")

            conditions = ["Type 2 Diabetes Mellitus", "Essential Hypertension"]
            nudge = await generate_clinical_nudge(features, conditions)

            print(f"\n  NUDGE RESPONSE:")
            print(f"    Severity:  {nudge.get('severity', 'N/A')}")
            print(f"    Title:     {nudge.get('title', 'N/A')}")
            print(f"    Message:   {nudge.get('message', 'N/A')}")
            if nudge.get("recommendations"):
                print(f"    Recommendations:")
                for r in nudge["recommendations"]:
                    print(f"      - {r}")
        else:
            print("  No vitals data available for nudge.")
    except Exception as e:
        print(f"  Nudge generation error: {e}")

    # ═══════════════════════════════════════════════════════════
    # 3. DAILY PLAN (Fallback)
    # ═══════════════════════════════════════════════════════════
    divider("3. DAILY PLAN — STRUCTURED FALLBACK")

    ctx = build_plan_context(MUKESH_ID)

    # Show what data was available vs missing
    v = ctx["vitals_today"]
    present = {k: val for k, val in v.items() if val is not None}
    missing = [k for k, val in v.items() if val is None]
    print(f"  Data available today: {len(present)} metrics")
    for k, val in present.items():
        if isinstance(val, float):
            val = round(val, 1)
        print(f"    {k}: {val}")
    print(f"  Missing today: {', '.join(missing)}")
    print()

    fallback = get_fallback_daily_plan(ctx)
    print(f"  Summary: {fallback['summary']}")
    print()
    for slot in ("morning", "afternoon", "evening", "night"):
        tasks = fallback["schedule"][slot]
        print(f"  {slot.upper()} ({len(tasks)} tasks):")
        for t in tasks:
            print(f"    - {t['task']}")
    print()
    hc = fallback.get("health_context", {})
    print(f"  Conditions addressed: {hc.get('conditions_addressed', [])}")
    print(f"  Med adherence rate: {hc.get('med_adherence_rate', 'N/A')}%")

    # ═══════════════════════════════════════════════════════════
    # 4. DAILY PLAN (Gemini LLM)
    # ═══════════════════════════════════════════════════════════
    divider("4. DAILY PLAN — GEMINI LLM")

    llm_plan = await generate_daily_plan(ctx)
    print(f"  Summary: {llm_plan['summary']}")
    print()
    for slot in ("morning", "afternoon", "evening", "night"):
        tasks = llm_plan["schedule"].get(slot, [])
        print(f"  {slot.upper()} ({len(tasks)} tasks):")
        for t in tasks:
            task_text = t.get("task", t) if isinstance(t, dict) else t
            print(f"    - {task_text}")

    alerts = llm_plan.get("active_alerts", [])
    if alerts:
        print(f"\n  Active alerts addressed: {alerts}")

    divider("EVALUATION COMPLETE")

asyncio.run(main())
