import json
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

from app.services.insights.data_fetcher import supabase
from app.services.medgemma_services import _call_medgemma, _clean_json
from app.services.macro_calculator import calculate_daily_macros
from app.services.plan_schema import TaskItem, DailySchedule
from app.services.llm_plan import build_plan_context, enrich_and_escalate_schedule
from app.services.clinical_taxonomy.catalog import get_symptom_relief_badge
from app.services.multilingual import get_patient_language, get_proactive_language_directive

class DayPlan(BaseModel):
    day_of_week: str = Field(..., description="Day of the week (e.g. 'Monday')")
    summary: str = Field(..., description="A 1-2 sentence explanation of why this plan was generated for the user on this day.")
    schedule: DailySchedule

class WeeklyPlanResponse(BaseModel):
    days: List[DayPlan]

def get_weekly_gemini_schema():
    return WeeklyPlanResponse.model_json_schema()

WEEKLY_PLAN_PROMPT = """You are MedGemma, a caring clinical guide and personal health companion for eldercare support.
Create a comprehensive 7-DAY LIFESTYLE AND CARE PLAN (Sunday through Saturday) for:

PATIENT: {patient_name}, {patient_age}-year-old {patient_sex}
LOCATION: {location_str}
CONDITIONS: {patient_conditions}

PATIENT PREFERENCES (Crucial for plan setup):
{setup_str}

USER CHAT PREFERENCES (Crucial requests made by the patient to the AI Coach):
{memory_str}

RECENT REPORTED SYMPTOMS (From recent chat logs):
{symptom_str}

CARE PLAN ACTIONS (from Coach):
{actions_bullet}

ACTIVE PRESCRIPTIONS & MEDICATION STATUS:
{med_section}

RECENT VITALS TREND & MORNING READINGS:
{vitals_trend_str}

ACTIVE CLINICAL ALERTS & LAB TRENDS:
{clinical_alerts_str}

NUTRITIONAL FOCUS & CONTEXT:
  - Daily Nutritional Baseline: {macro_targets_str}
  - Active Nutritional Insights: {nut_insights_str}

HISTORICAL SUCCESS CORRELATIONS (What works for this person):
{corr_str}

INSTRUCTIONS:
1. Tone & Senior Empathy: Speak with warmth, dignity, and reassurance, like an experienced clinical nurse. Frame tasks as empowering micro-rituals, not clinical chores.
2. Cognitive Budget & Daypart Allocation (Anchor-Driven Priority Tiering):
   - Generate a complete 7-day schedule (Sunday through Saturday).
   - For EACH DAY, generate strictly 4 to 6 high-impact tasks total across the 4 dayparts (morning, afternoon, evening, night).
   - Do NOT generate artificial filler tasks (such as "Relax", "Sit quietly", "Mindful breathing" unless clinically indicated). Lean dayparts with 0 to 1 tasks (e.g. in afternoon or night) are natural and encouraged.
   - In the 'task' property, provide a specific, atomic action (max 4-6 words).
   - In the 'time' property, provide the exact time (e.g. '8:00 AM', '1:00 PM', '6:30 PM', '9:30 PM').
   - For each day, write a 1-2 sentence 'summary' explaining why this plan was tailored for the user on this specific day.
3. Priority Tiering Structure (Each Day):
   - Tier 1 (Clinical Foundations - Mandatory): Active prescribed medications placed consistently at their designated time slots and timing instructions (e.g., before food, with food, bedtime). Acute vitals check if alerted, or overdue lab reminders.
   - Tier 2 (Coach Actions & Symptom Relief - Targeted & Actionable): Distribute all 'AGREED' coach actions across the week. Actively evaluate and schedule 'SUGGESTED' coach actions on days where they directly help alleviate active symptoms or target recent vitals trends. When addressing a symptom, set 'anchor_type': 'symptom', 'anchor_id': exact SYMPTOM ID, and under 'provenance' set 'badge': exact Relief Badge (e.g. 'FOR KNEE RELIEF', 'FOR BLOOD SUGAR BALANCE'). Prioritize remedies marked 'PROVEN EFFECTIVE' and NEVER use 'CONTRAINDICATED / AVOID'.
   - Tier 3 (Supporting Micro-Habits - Lean & Non-Prescriptive): Exactly 1 small nutrition micro-habit per day (e.g. adding roasted seeds or curd for protein, warm water before meals—no full meal prescriptions/macro counts) + exactly 1 evening wind-down routine.
4. Dynamic Vitals & Clinical Adaptation:
   - Adjust weekly schedule intensity based on RECENT VITALS TREND & CLINICAL ALERTS:
     * Elevated BP / BP Spike: Favor gentle stretching, seated joint mobility, or rest days over strenuous walking; include calming breathing.
     * Sleep Deficits (<6 hours): Lighten morning physical intensity, include quiet afternoon pauses, and schedule earlier evening wind-down.
     * Blood Glucose Elevation: Pair meals with a 10-minute post-meal stroll (shatapadi) and enforce low-glycemic/fiber micro-habits.
     * Elevated Resting Heart Rate: Add relaxing breathwork (e.g. physiological sigh).
5. Weekly Logistics & Major Anchor Routines:
   - Balance daily habits with weekly routines (e.g. weekend grocery replenishment for healthy produce, gentle mid-week mobility reviews, family social connections).
6. Activity Separation: Keep distinct activities (meals, hygiene, mobility/stretching, medications, self-care) as SEPARATE tasks. Do not merge unrelated activities together.
7. Interactive Mobile Action Binding:
   - Attach an intuitive 'action' object where relevant:
     * Vitals check -> type: 'LOG_VITALS', target: 'blood_pressure' or 'glucose', cta_label: 'Record BP' or 'Log Sugar'
     * Nutrition micro-habit -> type: 'LOG_MEAL', target: 'nutrition', cta_label: 'Snap Meal'
     * Mobility routine or walk -> type: 'FOLLOW_EXERCISE', target: 'routine', cta_label: 'Start Routine'
     * Coach check-in or reflection -> type: 'COACH_CHAT', cta_label: 'Ask Zivaa'
     * Personal routine or medication -> type: 'CHECKBOX_ONLY', cta_label: 'Done'
8. Strict JSON Output:
   - Output exact JSON only matching the schema below, containing an array of 7 days. Do not wrap in markdown code blocks, do not add introductory greetings or "Thinking Process" text.
9. {language_directive}

EXPECTED JSON SCHEMA:
{schema_str}
"""

async def generate_weekly_plan(patient_id: str) -> bool:
    print(f"Generating weekly plan for {patient_id}...")
    
    try:
        plan_context = await build_plan_context(patient_id)
        patient = plan_context.get("patient", {})
        patient_name = patient.get("name", "Patient")
        patient_age = patient.get("age", 70)
        patient_sex = patient.get("sex") or "patient"
        location_str = patient.get("location") or "India"
        if patient.get("temperature"):
            location_str += f" (Current Temp: {patient['temperature']}°C)"
        conditions_str = ", ".join(patient.get("conditions", [])) if patient.get("conditions") else "None specified"
        pref_lang = patient.get("preferred_language") or get_patient_language(patient_id)
        
        setup_prefs = plan_context.get("setup_prefs", {})
        setup_lines = []
        if setup_prefs:
            if setup_prefs.get("primary_focus"): setup_lines.append(f"Primary Focus: {setup_prefs.get('primary_focus')}")
            if setup_prefs.get("wake_time"): setup_lines.append(f"Wake Time: {setup_prefs.get('wake_time')}")
            if setup_prefs.get("movement_level"): setup_lines.append(f"Movement Level: {setup_prefs.get('movement_level')}")
            if setup_prefs.get("steps_goal"): setup_lines.append(f"Steps Goal: {setup_prefs.get('steps_goal')} steps")
            if setup_prefs.get("diet_type"): setup_lines.append(f"Diet Type: {setup_prefs.get('diet_type')}")
            hc = setup_prefs.get("health_conditions")
            if hc: setup_lines.append(f"Health Conditions: {', '.join(hc) if isinstance(hc, list) else hc}")
            ea = setup_prefs.get("evening_activities")
            if ea: setup_lines.append(f"Evening Activities: {', '.join(ea) if isinstance(ea, list) else ea}")
        setup_str = "\n".join([f"  - {line}" for line in setup_lines]) if setup_lines else "  - No specific preferences provided."
        
        if setup_prefs.get("target_calories_user_generated"):
            cals = setup_prefs.get("target_calories_user_generated")
            p = setup_prefs.get("protein_g_user_generated", 0)
            c = setup_prefs.get("carbs_g_user_generated", 0)
            f = setup_prefs.get("fat_g_user_generated", 0)
            macro_targets_str = f"Total Calories: {cals} kcal (Protein: {p}g, Carbs: {c}g, Fat: {f}g)"
        else:
            macro_targets_str = calculate_daily_macros(patient, setup_prefs)
            
        preferences = plan_context.get("preferences", [])
        pref_lines = [f"  - {p.get('constraint_text')}" for p in preferences if p.get("constraint_text")]
        memory_str = "\n".join(pref_lines) if pref_lines else "  - No specific preferences recorded."

        symptoms_clinical = plan_context.get("symptoms_clinical") or plan_context.get("symptoms", [])
        symptom_lines = []
        for sym in symptoms_clinical:
            sym_id = sym.get("id") or "active"
            site = sym.get("anatomical_site") or "General"
            relief_badge = sym.get("relief_badge") or get_symptom_relief_badge(sym)
            line = f"  - [SYMPTOM ID: {sym_id}] {sym.get('name')} (Relief Badge: {relief_badge}, Site: {site}, Status: {sym.get('status', 'Active')}, Severity: {sym.get('severity', 'Mild')})"
            if sym.get("proven_effective"):
                line += f"\n    * PROVEN EFFECTIVE FOR THIS PERSON: {', '.join(sym['proven_effective'])}"
            elif sym.get("guideline_modalities"):
                line += f"\n    * CLINICAL GUIDELINE STARTER MODALITIES: {', '.join(sym['guideline_modalities'])}"
            if sym.get("contraindicated"):
                line += f"\n    * CONTRAINDICATED / AVOID: {', '.join(sym['contraindicated'])}"
            symptom_lines.append(line)
        symptom_str = "\n".join(symptom_lines) if symptom_lines else "  - No recent symptoms reported."

        agreed_actions = plan_context.get("agreed_actions", [])
        suggested_actions = plan_context.get("suggested_actions", [])
        action_lines = []
        if agreed_actions:
            action_lines.append("[AGREED ACTIONS]")
            action_lines.extend([f"- {a.get('description', '')}" for a in agreed_actions])
        if suggested_actions:
            action_lines.append("\n[SUGGESTED ACTIONS]")
            action_lines.extend([f"- {a.get('description', '')}" for a in suggested_actions])
        actions_bullet = "\n".join(action_lines) if action_lines else "  - No specific coach actions recorded."

        # Active Prescriptions
        active_medications = plan_context.get("active_medications", [])
        med_lines = []
        if active_medications:
            for m in active_medications:
                m_name = m.get("medication_name", "Prescription")
                m_dose = m.get("dosage", "")
                m_timing = (m.get("timing_instruction") or "").replace("_", " ")
                m_freq = (m.get("frequency") or "").replace("_", " ")
                slots = m.get("time_slots") or []
                times = ", ".join([s.get("time", "") for s in slots if isinstance(s, dict) and s.get("time")])
                time_info = f" at {times}" if times else ""
                timing_info = f" ({m_timing})" if m_timing else ""
                med_lines.append(f"  - {m_name} {m_dose}{time_info}{timing_info} [{m_freq}]".strip())
            meds_prescribed_str = "\n".join(med_lines)
        else:
            meds_prescribed_str = "  - No active prescriptions recorded."
        med_adherence = plan_context.get("med_adherence", {})
        rate = med_adherence.get('rate')
        rate = rate if rate is not None else 100
        med_section = f"Past 7-Day Adherence: {rate:.0f}%\nActive Prescriptions to Schedule:\n{meds_prescribed_str}"

        # Vitals History & Today
        vitals_history = plan_context.get("vitals_history", [])
        history_lines = []
        excluded_keys = {"id", "patient_id", "created_at", "updated_at", "date"}
        for v in vitals_history[:7]:
            date = v.get("date", "Unknown")
            metrics = []
            if v.get("bp_systolic") is not None and v.get("bp_diastolic") is not None:
                metrics.append(f"BP {v['bp_systolic']}/{v['bp_diastolic']}")
            for key, val in v.items():
                if key in excluded_keys or val is None:
                    continue
                if key in {"bp_systolic", "bp_diastolic"} and "BP " + str(v.get("bp_systolic")) + "/" + str(v.get("bp_diastolic")) in metrics:
                    continue
                human_key = key.replace("_", " ").title()
                if key == "sleep_hours":
                    metrics.append(f"{human_key} {val}h")
                elif key == "mood_score":
                    metrics.append(f"{human_key} {val}/10")
                elif key == "avg_cadence_spm":
                    metrics.append(f"Walking Cadence {round(val)} spm")
                elif key == "active_movement_minutes":
                    metrics.append(f"Active Movement {round(val)}m")
                elif key == "total_steps":
                    metrics.append(f"Steps {int(val)}")
                else:
                    metrics.append(f"{human_key} {val}")
            metrics_str = ", ".join(metrics) if metrics else "No metrics recorded"
            history_lines.append(f"  - {date}: {metrics_str}")
        history_str = "\n".join(history_lines) if history_lines else "  - No history available."

        vitals_today = plan_context.get("vitals_today", {})
        today_metrics = []
        if vitals_today:
            if vitals_today.get("bp_systolic") is not None and vitals_today.get("bp_diastolic") is not None:
                today_metrics.append(f"BP {vitals_today['bp_systolic']}/{vitals_today['bp_diastolic']}")
            if vitals_today.get("sleep_hours") is not None:
                today_metrics.append(f"Sleep {vitals_today['sleep_hours']}h")
            if vitals_today.get("blood_glucose") is not None:
                today_metrics.append(f"Blood Glucose {vitals_today['blood_glucose']} mg/dL")
            if vitals_today.get("avg_heart_rate") is not None:
                today_metrics.append(f"Heart Rate {vitals_today['avg_heart_rate']} bpm")
            if vitals_today.get("steps") is not None:
                today_metrics.append(f"Steps {vitals_today['steps']}")
            if vitals_today.get("oxygen_sat") is not None:
                today_metrics.append(f"SpO2 {vitals_today['oxygen_sat']}%")
            if vitals_today.get("mood_score") is not None:
                today_metrics.append(f"Mood {vitals_today['mood_score']}/10")
        today_vitals_str = ", ".join(today_metrics) if today_metrics else "No morning readings yet"
        vitals_trend_str = f"  - Today's Immediate Readings: {today_vitals_str}\n  - Past 7-Day Trend:\n{history_str}"

        # Clinical Alerts & Labs
        active_insights = plan_context.get("active_insights", [])
        insights_lines = [f"  - {i.get('name')}: {i.get('message')}" for i in active_insights]
        lab_alerts = plan_context.get("lab_alerts", [])
        lab_lines = [f"  - Lab Alert: {l.get('biomarker')} {l.get('direction')} ({l.get('change_pct'):+.1f}%)" for l in lab_alerts]
        all_alerts = insights_lines + lab_lines
        clinical_alerts_str = "\n".join(all_alerts) if all_alerts else "  - No acute alerts."

        # Nutritional Insights
        nutritional_insights = plan_context.get("nutritional_insights", [])
        nut_lines = [f"  - {n.get('insight_name')}: {n.get('context_data')}" for n in nutritional_insights]
        nut_insights_str = "\n".join(nut_lines) if nut_lines else "  - None active."

        # Correlations
        correlations = plan_context.get("correlations", [])
        corr_lines = [f"  - {c.get('task_category', 'Task')} highly correlates with improved {c.get('metric', 'health')} (r={c.get('correlation', 0):.2f})" for c in correlations[:3]]
        corr_str = "\n".join(corr_lines) if corr_lines else "  - No clear statistical correlations established yet."

        language_directive = get_proactive_language_directive(pref_lang, content_type="plan")
        
        schema_dict = get_weekly_gemini_schema()
        schema_str = json.dumps(schema_dict, indent=2)
        
        prompt = WEEKLY_PLAN_PROMPT.format(
            patient_name=patient_name,
            patient_age=patient_age,
            patient_sex=patient_sex,
            location_str=location_str,
            patient_conditions=conditions_str,
            setup_str=setup_str,
            macro_targets_str=macro_targets_str,
            memory_str=memory_str,
            symptom_str=symptom_str,
            actions_bullet=actions_bullet,
            med_section=med_section,
            vitals_trend_str=vitals_trend_str,
            clinical_alerts_str=clinical_alerts_str,
            nut_insights_str=nut_insights_str,
            corr_str=corr_str,
            language_directive=language_directive,
            schema_str=schema_str
        )
        
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
                
                # Enrich and escalate each day's schedule with closed-loop bindings & relief badges!
                raw_sched = day_plan.get("schedule", {})
                enriched_sched = enrich_and_escalate_schedule(raw_sched, plan_context, target_day=day_name.lower())
                
                payload = {
                    "patient_id": patient_id,
                    "date": target_date,
                    "schedule": enriched_sched,
                    "summary": day_plan.get("summary", f"Your logistical plan for {day_name}"),
                    "health_context": {"is_preplanned": True}
                }
                
                supabase.table("daily_plans").delete().eq("patient_id", patient_id).eq("date", target_date).execute()
                supabase.table("daily_plans").insert(payload).execute()
                
        print(f"Successfully generated and enriched weekly plan for {patient_id}")
        return True
        
    except Exception as e:
        print(f"Weekly plan generation failed for {patient_id}: {e}")
        return False
