import json
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List
from pydantic import BaseModel, Field

# Lazy imports to avoid circular dependency if needed, but we will import at the top
from app.services.insights.data_fetcher import fetch_patient_context
from app.services.insights.data_fetcher import supabase
from app.services.medgemma_services import _call_medgemma, _clean_json
from app.services.macro_calculator import calculate_daily_macros

# Pydantic Schemas for 7-Day Plan
class TaskItem(BaseModel):
    task: str = Field(..., description="A specific and descriptive task action, not more than 1 short sentence.")
    time: str = Field(..., description="Time of the task, e.g., '7:30 AM'")
    completed: bool = Field(default=False)
    category: str = Field(..., description="Canonical 1-2 word category, e.g. 'Walking', 'Breakfast'")
    details: str = Field(..., description="One sentence explaining the why/how. Must include macro breakdown for meals.")

class DailySchedule(BaseModel):
    morning: List[TaskItem]
    afternoon: List[TaskItem]
    evening: List[TaskItem]
    night: List[TaskItem]

class DayPlan(BaseModel):
    day_of_week: str = Field(..., description="Day of the week (e.g. 'Monday')")
    summary: str = Field(..., description="A 1-2 sentence explanation of why this plan was generated for the user on this day, taking into account their nutritional goals and preferences.")
    schedule: DailySchedule

class WeeklyPlanResponse(BaseModel):
    days: List[DayPlan]

def get_weekly_gemini_schema():
    return WeeklyPlanResponse.model_json_schema()

WEEKLY_PLAN_PROMPT = """You are MedGemma, a caring clinical guide for eldercare support.
Create a comprehensive 7-DAY LIFESTYLE AND MEAL PLAN (Sunday to Saturday) for:

PATIENT: {patient_name}, {patient_age}-year-old {patient_sex}
LOCATION: {location_str}
CONDITIONS: {patient_conditions}

PATIENT PREFERENCES (Crucial for plan setup):
{setup_str}

NUTRITIONAL TARGETS (Daily Averages):
  - {macro_targets_str}

KNOWN PATIENT PREFERENCES (From Memory):
{memory_str}

RECENT REPORTED SYMPTOMS (From recent chat logs):
{symptom_str}

CARE PLAN ACTIONS (from Coach):
{actions_bullet}

ACTIVE NUTRITIONAL INSIGHTS:
{nut_insights_str}

HISTORICAL SUCCESS CORRELATIONS (What works for this person):
{corr_str}

INSTRUCTIONS:
1. Generate a complete 7-day schedule (Sunday through Saturday).
2. Focus on MAJOR ACTIVITIES (like grocery shopping, meal prep, exercise blocks). 
3. Do not prescribe specific recipes for meals. Instead, suggest high-level activities (e.g., 'Grocery shopping for lean proteins', 'Meal prep Sundays') and incorporate active nutritional nudges.
4. CRITICAL: Do not provide exact macro counts for meals.
5. Generate 2-3 tasks for the morning, 2-3 for afternoon, 2-3 for evening, and 2-3 for night per day.
6. CRITICAL: Ensure that all 'AGREED' care plan actions are explicitly scheduled across the week. For 'SUGGESTED' actions, schedule them on days that align with alleviating the patient's active symptoms.
7. CRITICAL: Keep distinct activities (like meals, hygiene, self-care, exercise, and medical tasks) as SEPARATE tasks. Do NOT merge unrelated activities together (e.g., do not combine breakfast and self-care).
8. For each day, write a 1-2 sentence 'summary' explaining why this plan was tailored for the user on this specific day.
9. Format the output strictly as JSON matching the provided schema, containing an array of 7 days.

EXPECTED JSON SCHEMA:
{schema_str}
"""

async def generate_weekly_plan(patient_id: str):
    print(f"Generating weekly plan for {patient_id}...")
    
    try:
        ctx = fetch_patient_context(patient_id)
        
        patient_name = "Patient"
        patient_res = supabase.table("patients").select("full_name").eq("id", patient_id).execute()
        if patient_res.data:
            patient_name = patient_res.data[0].get("full_name", "Patient")
            
        location_str = ctx.location_city or "Unknown"
        conditions_str = ", ".join(ctx.patient_conditions) if ctx.patient_conditions else "None specified"
        
        setup_lines = []
        if ctx.setup_prefs:
            if ctx.setup_prefs.get("primary_focus"): setup_lines.append(f"Primary Focus: {ctx.setup_prefs.get('primary_focus')}")
            if ctx.setup_prefs.get("wake_time"): setup_lines.append(f"Wake Time: {ctx.setup_prefs.get('wake_time')}")
            if ctx.setup_prefs.get("movement_level"): setup_lines.append(f"Movement Level: {ctx.setup_prefs.get('movement_level')}")
            if ctx.setup_prefs.get("steps_goal"): setup_lines.append(f"Steps Goal: {ctx.setup_prefs.get('steps_goal')} steps")
            if ctx.setup_prefs.get("diet_type"): setup_lines.append(f"Diet Type: {ctx.setup_prefs.get('diet_type')}")
            hc = ctx.setup_prefs.get("health_conditions")
            if hc: setup_lines.append(f"Health Conditions: {', '.join(hc) if isinstance(hc, list) else hc}")
            ea = ctx.setup_prefs.get("evening_activities")
            if ea: setup_lines.append(f"Evening Activities: {', '.join(ea) if isinstance(ea, list) else ea}")
        setup_str = "\n".join([f"  - {line}" for line in setup_lines]) if setup_lines else "  - No specific preferences provided."
        
        if ctx.setup_prefs and ctx.setup_prefs.get("target_calories_user_generated"):
            cals = ctx.setup_prefs.get("target_calories_user_generated")
            p = ctx.setup_prefs.get("protein_g_user_generated", 0)
            c = ctx.setup_prefs.get("carbs_g_user_generated", 0)
            f = ctx.setup_prefs.get("fat_g_user_generated", 0)
            macro_targets_str = f"Total Calories: {cals} kcal (Protein: {p}g, Carbs: {c}g, Fat: {f}g)"
        else:
            macro_targets_str = calculate_daily_macros(ctx.patient, ctx.setup_prefs)
            
        pref_lines = []
        symptom_lines = []
        action_lines = []
        preferences = getattr(ctx, "preferences", [])
        symptoms = getattr(ctx, "symptoms", [])
        agreed_actions = getattr(ctx, "agreed_actions", [])
        suggested_actions = getattr(ctx, "suggested_actions", [])
        for pref in preferences:
            pref_lines.append(f"  - {pref.get('constraint_text')}")
        for sym in symptoms:
            symptom_lines.append(f"  - {sym.get('name')} (Status: {sym.get('status')})")
            
        if agreed_actions:
            action_lines.append("[AGREED ACTIONS]")
            action_lines.extend([f"- {a.get('description', '')}" for a in agreed_actions])
        if suggested_actions:
            action_lines.append("\n[SUGGESTED ACTIONS]")
            action_lines.extend([f"- {a.get('description', '')}" for a in suggested_actions])
                
        memory_str = "\n".join(pref_lines) if pref_lines else "  - No specific preferences recorded."
        symptom_str = "\n".join(symptom_lines) if symptom_lines else "  - No recent symptoms reported."
        actions_bullet = "\n".join(action_lines) if action_lines else "  - No specific coach actions recorded."
        
        corr_str = "  - No clear statistical correlations established yet."
        
        # Fetch nutritional insights
        nut_lines = []
        try:
            nut_resp = supabase.table("active_nutritional_insights") \
                .select("insight_name, context_data") \
                .eq("patient_id", patient_id) \
                .eq("status", "active") \
                .execute()
            if nut_resp.data:
                for n in nut_resp.data:
                    nut_lines.append(f"  - {n.get('insight_name')}: {n.get('context_data')}")
        except Exception as e:
            print(f"Warning: Failed to fetch nutritional insights for weekly plan: {e}")
        nut_insights_str = "\n".join(nut_lines) if nut_lines else "  - None active."
        
    except Exception as e:
        print(f"Failed to fetch context for weekly plan: {e}")
        return False
        
    try:
        schema_dict = get_weekly_gemini_schema()
        schema_str = json.dumps(schema_dict, indent=2)
    except Exception as e:
        schema_str = "{}"
        
    prompt = WEEKLY_PLAN_PROMPT.format(
        patient_name=patient_name,
        patient_age=ctx.patient_age or 70,
        patient_sex=ctx.patient_sex or "patient",
        location_str=location_str,
        patient_conditions=conditions_str,
        setup_str=setup_str,
        macro_targets_str=macro_targets_str,
        memory_str=memory_str,
        symptom_str=symptom_str,
        actions_bullet=actions_bullet,
        nut_insights_str=nut_insights_str,
        corr_str=corr_str,
        schema_str=schema_str
    )
    
    try:
        res = await _call_medgemma(prompt, json_mode=True, prefill=False, response_schema=None)
        result = _clean_json(res)
        validated_plan = WeeklyPlanResponse.model_validate(result).model_dump()
        
        today = datetime.now(timezone.utc).date()
        days_until_sunday = (6 - today.weekday()) % 7
        next_sunday = today + timedelta(days=days_until_sunday)
        
        day_name_to_offset = {
            "Sunday": 0,
            "Monday": 1,
            "Tuesday": 2,
            "Wednesday": 3,
            "Thursday": 4,
            "Friday": 5,
            "Saturday": 6
        }
        
        for day_plan in validated_plan.get("days", []):
            day_name = day_plan.get("day_of_week", "")
            offset = day_name_to_offset.get(day_name)
            if offset is not None:
                target_date = (next_sunday + timedelta(days=offset)).isoformat()
                
                payload = {
                    "patient_id": patient_id,
                    "date": target_date,
                    "schedule": day_plan.get("schedule", {}),
                    "summary": day_plan.get("summary", f"Your logistical plan for {day_name}"),
                    "health_context": {"is_preplanned": True}
                }
                
                supabase.table("daily_plans").delete().eq("patient_id", patient_id).eq("date", target_date).execute()
                supabase.table("daily_plans").insert(payload).execute()
                
        print(f"Successfully generated weekly plan for {patient_id}")
        return True
        
    except Exception as e:
        print(f"Weekly plan generation failed for {patient_id}: {e}")
        return False
