"""
Insights-Driven Daily Plan Generation
======================================
Generates personalised daily care plans for elderly patients by combining:

1. Insights Engine output (18 clinical rules, RCV-based lab trends)
2. Patient demographics (name, age, sex, location)
3. Today's vitals with personal baseline deviations
4. Lab trend data (RCV-filtered from EFLM Biological Variation Database)
5. Medication adherence (past 7 days)

The plan is generated either by Gemini (primary) or a structured
composable fallback (when LLM is unavailable).

SECURITY NOTE (re: Zivaa Security Blueprint v1.0):
  - InsightsCache stores Tier 4 (System/Derived) data only — rule IDs,
    severity levels, plain-text messages. No raw Tier 1 PHI (lab values,
    vitals readings) is cached.
  - Cache is process-local (Python dict), not persisted to disk or
    external store. Auto-expires after 1 hour.
  - Cache is keyed by patient_id and accessed only by the service_role
    backend. No new access surface is created.
  - Compliant with: DPDPA 2023 §data minimisation, SPDI Rules 2011,
    Supabase RLS (backend uses service_role key).

CITATIONS:
  - Zivaa Security Blueprint: security_blueprint.md §1 (Data Classification),
    §2 (RLS), §9 (Data Retention)
"""

import sys
import os
# Add user-site packages to sys.path so IDE linter resolves imports
user_site = os.path.expanduser("~\\AppData\\Roaming\\Python\\Python314\\site-packages")
if user_site not in sys.path and os.path.exists(user_site):
    sys.path.insert(0, user_site)

import httpx
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional, Tuple
from app.config import settings


# ═══════════════════════════════════════════════════════════════════
# 1. INSIGHTS CACHE
#    In-memory cache for Insights Engine output (Tier 4 derived data).
#    Avoids re-running 18 rules + Supabase queries on every plan request.
#    TTL: 1 hour. Process-local, not persisted.
# ═══════════════════════════════════════════════════════════════════

class InsightsCache:
    """
    Thread-safe in-memory cache for Insights Engine output.

    Stores Tier 4 (System/Derived) data only:
      - Rule IDs, severity levels, plain-text insight messages
      - Lab trend summaries (direction, clinical_flag)
      - Medication adherence rate

    Does NOT store Tier 1 PHI (raw lab values, BP readings, etc.).

    Security: compliant with Zivaa Security Blueprint §1 (Data
    Classification) — cached data is Tier 4 (derived), not Tier 1 (PHI).
    """

    DEFAULT_TTL_SECONDS = 3600  # 1 hour

    def __init__(self, ttl_seconds: int = DEFAULT_TTL_SECONDS):
        self._cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
        self._ttl = ttl_seconds

    def get(self, patient_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve cached context if it exists and hasn't expired."""
        entry = self._cache.get(patient_id)
        if entry is None:
            return None
        timestamp, data = entry
        if time.time() - timestamp > self._ttl:
            # Expired — remove and return None
            del self._cache[patient_id]
            return None
        return data

    def set(self, patient_id: str, data: Dict[str, Any]) -> None:
        """Cache the plan context for this patient."""
        self._cache[patient_id] = (time.time(), data)

    def invalidate(self, patient_id: str) -> None:
        """Manually invalidate cache for a patient (e.g., after new data)."""
        self._cache.pop(patient_id, None)

    def clear(self) -> None:
        """Clear entire cache."""
        self._cache.clear()


# Global cache instance
_insights_cache = InsightsCache()


# ═══════════════════════════════════════════════════════════════════
# 2. REGION / FOOD MAPPING
# ═══════════════════════════════════════════════════════════════════

def get_region_from_location(location: Optional[str]) -> str:
    """
    Maps Indian city/state names to broad dietary regions.
    Used for region-appropriate food suggestions.
    """
    if not location:
        return "North"
    loc = location.lower()

    south_indicators = [
        "bangalore", "bengaluru", "chennai", "hyderabad", "kochi",
        "kerala", "karnataka", "tamil nadu", "andhra", "telangana",
        "mysore", "coimbatore"
    ]
    west_indicators = [
        "mumbai", "pune", "ahmedabad", "surat", "gujarat",
        "maharashtra", "goa", "nagpur", "rajkot"
    ]
    east_indicators = [
        "kolkata", "bengal", "odisha", "bhubaneswar", "assam",
        "guwahati", "patna", "bihar", "ranchi"
    ]

    if any(ind in loc for ind in south_indicators):
        return "South"
    if any(ind in loc for ind in west_indicators):
        return "West"
    if any(ind in loc for ind in east_indicators):
        return "East"
    return "North"


# Regional food mapping (max 3 words for food item)
REGIONAL_FOODS = {
    "South": {
        "breakfast": "Oats Idli",
        "lunch": "Sambhar Rice",
        "dinner": "Ragi Dosa",
        "iron_breakfast": "Ragi Idli",
        "low_sodium_dinner": "Steamed Idli",
        "low_gi_breakfast": "Oats Upma",
    },
    "North": {
        "breakfast": "Missi Roti",
        "lunch": "Roti Sabzi",
        "dinner": "Moong Dal",
        "iron_breakfast": "Bajra Roti",
        "low_sodium_dinner": "Dal Chawal",
        "low_gi_breakfast": "Besan Chilla",
    },
    "West": {
        "breakfast": "Methi Poha",
        "lunch": "Bajra Roti",
        "dinner": "Kadhi Khichdi",
        "iron_breakfast": "Nachni Roti",
        "low_sodium_dinner": "Plain Khichdi",
        "low_gi_breakfast": "Sprouts Poha",
    },
    "East": {
        "breakfast": "Suji Upma",
        "lunch": "Palak Dal",
        "dinner": "Sattu Paratha",
        "iron_breakfast": "Sattu Drink",
        "low_sodium_dinner": "Moong Khichdi",
        "low_gi_breakfast": "Chana Sattu",
    },
}


# ═══════════════════════════════════════════════════════════════════
# 3. BUILD PLAN CONTEXT (bridge between Insights Engine & Plan)
#    Fetches patient data + runs Insights Engine + extracts lab trends
#    Returns a rich PlanContext dict for prompt construction.
# ═══════════════════════════════════════════════════════════════════

def build_plan_context(patient_id: str, phone_location: str = None) -> Dict[str, Any]:
    """
    Builds the full context needed for daily plan generation by:
    1. Checking the insights cache (Tier 4 derived data, 1h TTL)
    2. If cache miss: running the Insights Engine, fetching patient
       demographics, today's vitals, lab trends, and medication adherence
    3. Returning a structured PlanContext dict

    Returns: dict with keys:
        - patient: {name, age, sex, location, region, conditions}
        - vitals_today: {hr, bp_sys, bp_dia, steps, sleep, glucose, ...}
        - active_insights: [{rule_id, name, severity, message, category}]
        - lab_alerts: [{biomarker, direction, change_pct, rate_alert}]
        - med_adherence: {rate, missed_count}
    """
    # Check cache first
    cached = _insights_cache.get(patient_id)
    if cached is not None:
        return cached

    from app.services.insights.data_fetcher import supabase

    # ── Patient demographics ──
    patient_info = {"id": patient_id, "name": "Patient", "age": None, "sex": None,
                    "location": None, "region": "North", "conditions": []}
    try:
        resp = supabase.table("patients") \
            .select("full_name, date_of_birth, gender, location_city") \
            .eq("id", patient_id) \
            .single() \
            .execute()
        if resp.data:
            patient_info["name"] = resp.data.get("full_name", "Patient")
            patient_info["sex"] = (resp.data.get("gender") or "").lower() or None
            patient_info["location"] = resp.data.get("location_city")
            patient_info["region"] = get_region_from_location(
                patient_info["location"])
            dob = resp.data.get("date_of_birth")
            if dob:
                birth = datetime.strptime(dob, "%Y-%m-%d").date() \
                    if isinstance(dob, str) else dob
                patient_info["age"] = (datetime.now().date() - birth).days // 365
            
            # Fetch Temperature
            target_city = phone_location or patient_info.get("location")
            if target_city:
                from app.utils.weather import get_city_temperature
                patient_info["temperature"] = get_city_temperature(target_city)
                    
    except Exception as e:
        print(f"Warning: Could not fetch patient demographics: {e}")

    # ── Fetch conditions ──
    try:
        cond_resp = supabase.table("conditions") \
            .select("condition_name") \
            .eq("patient_id", patient_id) \
            .execute()
        if cond_resp.data:
            patient_info["conditions"] = [
                c["condition_name"] for c in cond_resp.data
                if c.get("condition_name")
            ]
    except Exception:
        pass  # conditions table may not exist yet

    # ── Vitals History (Last 7 Days) ──
    vitals_today = {}
    vitals_history = []
    try:
        today_str = datetime.now().date().isoformat()
        seven_days_ago_str = (datetime.now().date() - timedelta(days=7)).isoformat()
        v_resp = supabase.table("vitals_daily") \
            .select("*") \
            .eq("patient_id", patient_id) \
            .gte("date", seven_days_ago_str) \
            .order("date", desc=True) \
            .execute()
        
        if v_resp.data:
            vitals_history = v_resp.data
            
            # The most recent row is typically "today" (or yesterday if today isn't logged yet)
            row = v_resp.data[0]
            vitals_today = {
                "avg_heart_rate": row.get("avg_heart_rate"),
                "bp_systolic": row.get("bp_systolic"),
                "bp_diastolic": row.get("bp_diastolic"),
                "steps": row.get("total_steps", 0),
                "sleep_hours": row.get("sleep_hours"),
                "blood_glucose": row.get("blood_glucose_avg"),
                "oxygen_sat": row.get("oxygen_sat_avg"),
                "body_temp": row.get("body_temp_avg"),
                "skin_temp_delta": row.get("skin_temperature_delta"),
                "weight": row.get("weight_kg"),
                "mood_score": row.get("mood_score"),
            }
    except Exception as e:
        print(f"Warning: Could not fetch vitals history: {e}")

    # ── Previous Plan & Recent Meals ──
    previous_plan = {}
    recent_meals = []
    try:
        plan_resp = supabase.table("daily_plans") \
            .select("schedule, date") \
            .eq("patient_id", patient_id) \
            .order("created_at", desc=True) \
            .limit(3) \
            .execute()
        if plan_resp.data:
            previous_plan = plan_resp.data[0].get("schedule", {})
            for row in plan_resp.data:
                schedule = row.get("schedule", {})
                for period in ["morning", "afternoon", "evening", "night"]:
                    tasks = schedule.get(period, [])
                    if isinstance(tasks, list):
                        for t in tasks:
                            category = (t.get("category") or "").lower()
                            task_name = t.get("task", "")
                            if any(kw in category for kw in ["breakfast", "lunch", "dinner", "meal", "snack"]) or \
                               any(kw in task_name.lower() for kw in ["breakfast", "lunch", "dinner"]):
                                recent_meals.append(task_name)
    except Exception as e:
        print(f"Warning: Could not fetch previous plans: {e}")

    # ── Run Insights Engine ──
    active_insights = []
    try:
        from app.services.insights.engine import engine
        output = engine.evaluate_patient(patient_id)
        # Extract Tier 4 derived data only (no raw PHI)
        for insight in output.active_insights:
            active_insights.append({
                "rule_id": insight.rule_id,
                "name": insight.name,
                "severity": insight.severity.value,
                "message": insight.message,
                "category": insight.category.value,
                "is_stale": getattr(insight, 'is_stale', False)
            })
            
        # Also fetch recently resolved_stale insights from DB to pass to LLM coaching
        stale_cutoff = (datetime.now() - timedelta(hours=48)).isoformat()
        stale_resp = supabase.table("active_clinical_insights") \
            .select("rule_id, name, severity, message, category") \
            .eq("patient_id", patient_id) \
            .eq("status", "resolved_stale") \
            .gte("updated_at", stale_cutoff) \
            .execute()
        if stale_resp.data:
            for s in stale_resp.data:
                s["is_stale"] = True
                active_insights.append(s)
        # Fetch historical insights (overdue labs)
        historical_insights = []
        hist_resp = supabase.table("active_clinical_insights") \
            .select("name, message, updated_at") \
            .eq("patient_id", patient_id) \
            .eq("status", "historical") \
            .execute()
        if hist_resp.data:
            historical_insights = hist_resp.data
            
    except Exception as e:
        print(f"Warning: Insights Engine failed: {e}")
        historical_insights = []

    # ── Lab trend alerts (RCV-filtered) ──
    lab_alerts = []
    try:
        from app.services.lab_history import get_patient_lab_trends
        trends = get_patient_lab_trends(patient_id)
        for code, summary in trends.get("trend_summary", {}).items():
            # Only include worsening or needs_attention biomarkers
            flag = summary.get("clinical_flag", "stable")
            if flag in ("worsening", "needs_attention"):
                alert = {
                    "biomarker": summary.get("biomarker_name", code),
                    "direction": summary.get("trend_direction", "unknown"),
                    "change_pct": summary.get("change_percent", 0),
                    "clinical_flag": flag,
                }
                # Include published rate alert if present
                if summary.get("rate_alert"):
                    alert["rate_alert"] = summary["rate_alert"]
                lab_alerts.append(alert)
    except Exception as e:
        print(f"Warning: Lab trend fetch failed: {e}")

    # ── Medication adherence ──
    med_adherence = {"rate": None, "missed_count": 0}
    try:
        seven_days_ago = (datetime.now() - timedelta(days=7)).isoformat()
        meds_resp = supabase.table("medication_logs") \
            .select("status") \
            .eq("patient_id", patient_id) \
            .gte("scheduled_at", seven_days_ago) \
            .execute()
        total = len(meds_resp.data)
        if total > 0:
            taken = sum(1 for m in meds_resp.data if m.get("status") == "taken")
            missed = sum(1 for m in meds_resp.data
                         if m.get("status") in ("missed", "skipped"))
            med_adherence = {
                "rate": round((taken / total) * 100, 1),
                "missed_count": missed,
            }
    except Exception as e:
        print(f"Warning: Medication adherence fetch failed: {e}")

    # ── Task Correlations ──
    correlations = []
    try:
        from app.services.reinforcement import fetch_history_data, calculate_task_correlations
        history_data = fetch_history_data(patient_id)
        correlations = calculate_task_correlations(history_data)
    except Exception as e:
        print(f"Warning: Correlations fetch failed: {e}")

    # ── Patient Setup Preferences ──
    setup_prefs = {}
    try:
        setup_resp = supabase.table("patient_plan_setup") \
            .select("*") \
            .eq("patient_id", patient_id) \
            .order("created_at", desc=True) \
            .execute()
        if setup_resp.data:
            fields = [
                "primary_focus", "wake_time", "movement_level", "steps_goal", 
                "diet_type", "height_inches", "weight_kg", "goal_weight_kg", 
                "health_conditions", "evening_activities", "reminders",
                "target_calories_user_generated", "protein_g_user_generated", 
                "carbs_g_user_generated", "fat_g_user_generated", "diet_preference"
            ]
            for field in fields:
                for row in setup_resp.data:
                    val = row.get(field)
                    if val is not None:
                        # For lists, empty is considered null per user request
                        if isinstance(val, list) and not val:
                            continue
                        # For strings, empty is considered null
                        if isinstance(val, str) and not val.strip():
                            continue
                        setup_prefs[field] = val
                        break
    except Exception as e:
        print(f"Warning: Patient plan setup fetch failed: {e}")

    # ── Fetch patient preferences and symptoms (Domain-Driven Care Model) ──
    preferences = []
    symptoms = []
    try:
        # 1. Fetch permanent preferences
        pref_resp = supabase.table("patient_preferences") \
            .select("*") \
            .eq("patient_id", patient_id) \
            .execute()
        if pref_resp.data:
            preferences.extend(pref_resp.data)
            
        # 2. Fetch active/resolving symptoms
        sym_resp = supabase.table("patient_symptoms") \
            .select("*") \
            .eq("patient_id", patient_id) \
            .in_("status", ["Active", "Resolving"]) \
            .execute()
            
        if sym_resp.data:
            symptoms.extend(sym_resp.data)
            
    except Exception as e:
        print(f"Warning: Could not fetch patient preferences/symptoms for {patient_id}: {e}")

    agreed_actions = []
    suggested_actions = []
    try:
        act_resp = supabase.table("care_plan_actions") \
            .select("*") \
            .eq("patient_id", patient_id) \
            .execute()
        if act_resp.data:
            agreed_actions = [a for a in act_resp.data if a.get("status") == "Agreed"]
            suggested_actions = [a for a in act_resp.data if a.get("status") == "Suggested"]
    except Exception as e:
        print(f"Warning: Could not fetch care plan actions for {patient_id}: {e}")

    # ── Fetch Nutritional Insights ──
    nutritional_insights = []
    try:
        nut_resp = supabase.table("active_nutritional_insights") \
            .select("rule_id, insight_name, severity, context_data, category") \
            .eq("patient_id", patient_id) \
            .eq("status", "active") \
            .execute()
        if nut_resp.data:
            nutritional_insights = nut_resp.data
    except Exception as e:
        print(f"Warning: Nutritional insights fetch failed: {e}")

    # ── Fetch Existing Pre-Planned Schedule (from Weekly Planner) ──
    existing_plan = {}
    try:
        today_str = datetime.now(timezone.utc).date().isoformat()
        plan_resp = supabase.table("daily_plans") \
            .select("schedule") \
            .eq("patient_id", patient_id) \
            .eq("date", today_str) \
            .execute()
        if plan_resp.data and plan_resp.data[0].get("schedule"):
            existing_plan = plan_resp.data[0].get("schedule")
    except Exception as e:
        print(f"Warning: Could not fetch existing pre-planned schedule: {e}")

    # ── Assemble plan context ──
    context = {
        "patient": patient_info,
        "vitals_today": vitals_today,
        "vitals_history": vitals_history,
        "previous_plan": previous_plan,
        "existing_plan": existing_plan,
        "active_insights": active_insights,
        "lab_alerts": lab_alerts,
        "med_adherence": med_adherence,
        "correlations": correlations,
        "setup_prefs": setup_prefs,
        "recent_meals": recent_meals,
        "preferences": preferences,
        "symptoms": symptoms,
        "agreed_actions": agreed_actions,
        "suggested_actions": suggested_actions,
        "historical_insights": historical_insights,
        "nutritional_insights": nutritional_insights,
    }

    # Cache the result (Tier 4 derived data only, 1h TTL)
    _insights_cache.set(patient_id, context)

    return context


# ═══════════════════════════════════════════════════════════════════
# 4. INSIGHTS-TO-CONDITION MAPPER
#    Maps active insight rule_ids to condition categories for
#    the composable fallback template system.
# ═══════════════════════════════════════════════════════════════════

# Maps insight rule IDs → condition template keys
INSIGHT_TO_CONDITION = {
    "prediabetes_progression": "diabetes",
    "glycemic_risk": "diabetes",
    "kidney_decline": "ckd",
    "anemia_detection": "anemia",
    "thyroid_dysfunction": "thyroid",
    "cardiovascular_risk": "cardiovascular",
    "hypertension_escalation": "cardiovascular",
    "respiratory_distress": "respiratory",
    "depression_withdrawal": "mental_health",
    "emotional_wellbeing": "mental_health",
    "sleep_disturbance": "sleep",
}


# ═══════════════════════════════════════════════════════════════════
# 5. COMPOSABLE FALLBACK TEMPLATES
#    Each condition contributes tasks to a daily plan.
#    Multiple conditions can be composed together.
# ═══════════════════════════════════════════════════════════════════

def _get_condition_tasks(
    condition: str, region: str
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Returns condition-specific tasks for each time-of-day slot.
    Food items are region-appropriate.

    Each condition template is designed based on published clinical
    guidelines referenced in the corresponding Tier 3 rule:
      - diabetes: ADA 2024 (glucose checks, post-meal walks, foot care)
      - ckd: KDIGO 2024 (hydration, salt monitoring, BP checks)
      - anemia: WHO 2011 (iron-rich foods, rest periods)
      - thyroid: ATA 2012/2016 (medication timing, energy management)
      - cardiovascular: ACC/AHA 2018 (BP checks, low sodium, light cardio)
    """
    foods = REGIONAL_FOODS.get(region, REGIONAL_FOODS["North"])

    templates = {
        "diabetes": {
            "morning": [
                {"task": "Check blood sugar", "time": "7:30 AM", "completed": False, "category": "Vitals", "details": "Monitor your fasting blood sugar level."},
                {"task": f"Eat {foods['low_gi_breakfast']}", "time": "8:30 AM", "completed": False, "category": "Diet", "details": "Have a low glycemic index breakfast to stabilize sugar levels."},
            ],
            "afternoon": [
                {"task": "Post-meal short walk", "time": "1:30 PM", "completed": False, "category": "Activity", "details": "A 10-minute walk helps prevent post-meal sugar spikes."},
            ],
            "evening": [
                {"task": "Check evening glucose", "time": "7:00 PM", "completed": False, "category": "Vitals", "details": "Monitor your sugar level before dinner."},
            ],
            "night": [
                {"task": "Diabetic foot check", "time": "9:30 PM", "completed": False, "category": "Hygiene", "details": "Inspect your feet for any cuts or sores."},
            ],
        },
        "ckd": {
            "morning": [
                {"task": "Drink warm water", "time": "7:00 AM", "completed": False, "category": "Diet", "details": "Hydrate gently in the morning."},
            ],
            "afternoon": [
                {"task": "Monitor salt intake", "time": "1:00 PM", "completed": False, "category": "Diet", "details": "Ensure your lunch is low in sodium for kidney health."},
            ],
            "evening": [
                {"task": "Check blood pressure", "time": "6:30 PM", "completed": False, "category": "Vitals", "details": "Keep an eye on your blood pressure as it affects kidney function."},
            ],
            "night": [
                {"task": "Track fluid intake", "time": "9:00 PM", "completed": False, "category": "Diet", "details": "Review your fluid intake to stay within daily limits."},
            ],
        },
        "anemia": {
            "morning": [
                {"task": f"Eat {foods['iron_breakfast']}", "time": "8:30 AM", "completed": False, "category": "Diet", "details": "An iron-rich breakfast helps combat anemia fatigue."},
            ],
            "afternoon": [
                {"task": "Take short rest", "time": "2:30 PM", "completed": False, "category": "Sleep", "details": "Rest to recover energy levels."},
            ],
            "evening": [],
            "night": [],
        },
        "thyroid": {
            "morning": [
                {"task": "Take thyroid medication", "time": "7:00 AM", "completed": False, "category": "Medication", "details": "Take on an empty stomach for best absorption."},
                {"task": "Wait before eating", "time": "7:30 AM", "completed": False, "category": "Diet", "details": "Wait 30-60 minutes after medication before having breakfast."},
            ],
            "afternoon": [],
            "evening": [],
            "night": [],
        },
        "cardiovascular": {
            "morning": [
                {"task": "Check blood pressure", "time": "8:00 AM", "completed": False, "category": "Vitals", "details": "Morning check to ensure blood pressure is stable."},
            ],
            "afternoon": [
                {"task": "Take gentle walk", "time": "2:00 PM", "completed": False, "category": "Activity", "details": "Keep your heart healthy with some light movement."},
            ],
            "evening": [
                {"task": f"Eat {foods['low_sodium_dinner']}", "time": "7:30 PM", "completed": False, "category": "Diet", "details": "A low-sodium dinner reduces strain on your heart."},
            ],
            "night": [],
        },
        "respiratory": {
            "morning": [
                {"task": "Do breathing exercises", "time": "8:00 AM", "completed": False, "category": "Activity", "details": "Strengthen your lungs with morning breathing exercises."},
            ],
            "afternoon": [],
            "evening": [],
            "night": [
                {"task": "Elevate head pillow", "time": "9:30 PM", "completed": False, "category": "Sleep", "details": "Sleep with your head elevated for easier breathing."},
            ],
        },
        "mental_health": {
            "morning": [],
            "afternoon": [
                {"task": "Call friend or family", "time": "3:00 PM", "completed": False, "category": "Social", "details": "Connect with a loved one for a quick chat."},
            ],
            "evening": [
                {"task": "Enjoy calm hobby", "time": "7:00 PM", "completed": False, "category": "Mindfulness", "details": "Spend time on a relaxing activity."},
            ],
            "night": [],
        },
        "sleep": {
            "morning": [],
            "afternoon": [],
            "evening": [
                {"task": "Dim lights early", "time": "8:00 PM", "completed": False, "category": "Sleep", "details": "Help your body prepare for rest."},
            ],
            "night": [
                {"task": "Prepare dark bedroom", "time": "9:30 PM", "completed": False, "category": "Sleep", "details": "Ensure your room is dark and quiet."},
            ],
        },
    }

    return templates.get(condition, {
        "morning": [], "afternoon": [], "evening": [], "night": []
    })


def get_fallback_daily_plan(plan_context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Structured clinical fallback plan when LLM is unavailable.

    Uses a composable template system:
    1. Maps active insights → condition keys
    2. Merges tasks from all relevant conditions
    3. Adds universal senior care tasks
    4. Applies vitals-based adjustments
    5. Caps at 4 tasks per time slot (most important first)

    This replaces the old single diabetes/generic split with a system
    that adapts to any combination of conditions.
    """
    patient = plan_context.get("patient", {})
    vitals = plan_context.get("vitals_today", {})
    insights = plan_context.get("active_insights", [])
    lab_alerts = plan_context.get("lab_alerts", [])
    med_adherence = plan_context.get("med_adherence", {})

    region = patient.get("region", "North")
    name = patient.get("name", "Patient").split()[0]  # First name only
    foods = REGIONAL_FOODS.get(region, REGIONAL_FOODS["North"])

    # ── Determine active conditions from insights ──
    active_conditions = set()
    for insight in insights:
        condition = INSIGHT_TO_CONDITION.get(insight.get("rule_id"))
        if condition:
            active_conditions.add(condition)

    # Also check from patient conditions list
    for cond in patient.get("conditions", []):
        cond_lower = cond.lower()
        if "diabet" in cond_lower:
            active_conditions.add("diabetes")
        elif "kidney" in cond_lower or "ckd" in cond_lower or "renal" in cond_lower:
            active_conditions.add("ckd")
        elif "thyroid" in cond_lower:
            active_conditions.add("thyroid")
        elif "anemia" in cond_lower or "anaemia" in cond_lower:
            active_conditions.add("anemia")
        elif "hypertens" in cond_lower or "cardiac" in cond_lower:
            active_conditions.add("cardiovascular")

    # ── Build universal base schedule ──
    schedule = {
        "morning": [
            {"task": "Drink warm water", "time": "7:00 AM", "completed": False, "category": "Diet", "details": "Start your day with a glass of warm water for digestion."},
            {"task": f"Eat {foods['breakfast']}", "time": "8:30 AM", "completed": False, "category": "Diet", "details": "Have a nutritious breakfast to energize your morning."},
            {"task": "Do morning stretches", "time": "9:00 AM", "completed": False, "category": "Activity", "details": "Stretch lightly to improve joint mobility and blood flow."},
        ],
        "afternoon": [
            {"task": f"Eat {foods['lunch']}", "time": "1:00 PM", "completed": False, "category": "Diet", "details": "Enjoy a balanced lunch for steady afternoon energy."},
            {"task": "Drink glass water", "time": "3:00 PM", "completed": False, "category": "Diet", "details": "Stay hydrated throughout the day."},
        ],
        "evening": [
            {"task": f"Eat {foods['dinner']}", "time": "7:30 PM", "completed": False, "category": "Diet", "details": "Have a light, easy-to-digest dinner."},
        ],
        "night": [
            {"task": "Take bedtime medications", "time": "9:45 PM", "completed": False, "category": "Medication", "details": "Take any prescribed night-time medications."},
            {"task": "Prepare dark bedroom", "time": "10:00 PM", "completed": False, "category": "Sleep", "details": "Dim the lights and ensure your bedroom is quiet for restful sleep."},
        ],
    }

    # ── Compose condition-specific tasks ──
    # Dedup by task text (before time stamp). Also treat all "eat ..."
    # tasks in the same slot as the same category to prevent duplicate
    # dinner entries when multiple conditions suggest different foods.
    seen_tasks = set()        # Global dedup
    slot_has_meal = set()     # Track which slots already have an "eat" task

    for slot in schedule:
        for task in schedule[slot]:
            task_key = task["task"].split("|")[0].strip().lower()
            seen_tasks.add(task_key)
            if task_key.startswith("eat "):
                slot_has_meal.add(slot)

    for condition in active_conditions:
        cond_tasks = _get_condition_tasks(condition, region)
        for slot in ("morning", "afternoon", "evening", "night"):
            for task in cond_tasks.get(slot, []):
                task_key = task["task"].split("|")[0].strip().lower()
                # Skip duplicate meal tasks (same slot already has food)
                if task_key.startswith("eat ") and slot in slot_has_meal:
                    continue
                if task_key not in seen_tasks:
                    schedule[slot].append(task)
                    seen_tasks.add(task_key)
                    if task_key.startswith("eat "):
                        slot_has_meal.add(slot)

    # ── Medication adherence adjustment ──
    if med_adherence.get("rate", 100) < 80:
        med_task = {"task": "Set medication reminder", "time": "9:00 AM", "completed": False, "category": "Medication", "details": "Set an alarm to ensure you don't miss any doses today."}
        task_key = "set medication reminder"
        if task_key not in seen_tasks:
            schedule["morning"].insert(0, med_task)
            seen_tasks.add(task_key)

    # ── Vitals-based adjustments ──
    steps = vitals.get("steps", 0) or 0
    bp_sys = vitals.get("bp_systolic", 120) or 120
    hr = vitals.get("avg_heart_rate", 72) or 72

    if steps < 1000 and not (bp_sys > 150 or hr > 90):
        task = {"task": "Walk around house", "time": "4:00 PM", "completed": False, "category": "Activity", "details": "Take a short walk to keep your circulation healthy."}
        if "walk around house" not in seen_tasks:
            schedule["afternoon"].append(task)

    if bp_sys > 140 or hr > 85:
        task = {"task": "Do deep breathing", "time": "8:00 PM", "completed": False, "category": "Mindfulness", "details": "Practice deep breathing to help lower your blood pressure and heart rate."}
        if "do deep breathing" not in seen_tasks:
            schedule["evening"].append(task)

    # ── Cap each slot at 4 tasks ──
    for slot in schedule:
        schedule[slot] = schedule[slot][:4]

    # ── Build summary ──
    high_insights = [i for i in insights if i.get("severity") == "HIGH"]
    medium_insights = [i for i in insights if i.get("severity") == "MEDIUM"]

    summary_parts = [f"Today's plan for {name} focuses on"]
    if active_conditions:
        focus_areas = []
        if "diabetes" in active_conditions:
            focus_areas.append("blood sugar management")
        if "ckd" in active_conditions:
            focus_areas.append("kidney care and hydration")
        if "anemia" in active_conditions:
            focus_areas.append("iron-rich nutrition and rest")
        if "thyroid" in active_conditions:
            focus_areas.append("thyroid medication timing")
        if "cardiovascular" in active_conditions:
            focus_areas.append("heart health")
        if not focus_areas:
            focus_areas.append("overall wellness")
        summary_parts.append(", ".join(focus_areas) + ".")
    else:
        summary_parts.append("steady energy, hydration, and gentle movement.")

    if high_insights:
        summary_parts.append(
            f" We noticed {len(high_insights)} important health "
            f"alert{'s' if len(high_insights) > 1 else ''} that today's "
            f"plan addresses."
        )

    sleep = vitals.get("sleep_hours")
    if sleep and sleep < 6.0:
        summary_parts.append(
            " Since sleep was short last night, let's keep things gentle."
        )

    if med_adherence.get("rate", 100) < 80:
        summary_parts.append(
            " Some medications were missed recently — medication reminders "
            "have been added."
        )

    summary = " ".join(summary_parts)

    return {
        "summary": summary,
        "schedule": schedule,
        "health_context": {
            "conditions_addressed": list(active_conditions),
            "high_alerts": len(high_insights),
            "medium_alerts": len(medium_insights),
            "lab_alerts_count": len(lab_alerts),
            "med_adherence_rate": med_adherence.get("rate"),
        },
        "active_alerts": [i.get("name", "") for i in insights[:5]],
    }


# ═══════════════════════════════════════════════════════════════════
# 6. LLM PROMPT CONSTRUCTION & DAILY PLAN GENERATION
# ═══════════════════════════════════════════════════════════════════

def _build_insights_prompt_section(insights: List[Dict]) -> str:
    """Format active insights for the LLM prompt."""
    if not insights:
        return "No active health alerts today."

    lines = []
    for i in insights:
        severity = i.get("severity", "LOW")
        name = i.get("name", "Unknown")
        msg = i.get("message", "")
        # Truncate long messages
        if len(msg) > 200:
            msg = msg[:200] + "..."
        lines.append(f"  - [{severity}] {name}: {msg}")
    return "\n".join(lines)


def _build_lab_alerts_prompt_section(lab_alerts: List[Dict]) -> str:
    """Format lab trend alerts for the LLM prompt."""
    if not lab_alerts:
        return "No lab trends requiring attention."

    lines = []
    for alert in lab_alerts:
        name = alert.get("biomarker", "Unknown")
        direction = alert.get("direction", "unknown")
        change = alert.get("change_pct", 0)
        line = f"  - {name}: {direction} ({change:+.1f}%)"
        if alert.get("rate_alert"):
            label = alert["rate_alert"].get("label", "")
            line += f" — {label}"
        lines.append(line)
    return "\n".join(lines)


async def generate_daily_plan(
    plan_context: Dict[str, Any],
    # Legacy params for backward compatibility
    vitals: Optional[Dict[str, float]] = None,
    conditions: Optional[List[str]] = None,
    location: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Generates a personalised daily plan using Gemini, grounded in the
    patient's Insights Engine output, lab trends, and vitals.

    Args:
        plan_context: Rich context from build_plan_context(patient_id).
                      Contains patient info, vitals, insights, lab alerts,
                      and medication adherence.
        vitals: (Legacy) Raw vitals dict — used only for backward compat.
        conditions: (Legacy) Conditions list — used only for backward compat.
        location: (Legacy) Location string — used only for backward compat.

    Returns:
        Dict with 'summary', 'schedule', optional 'health_context',
        optional 'active_alerts'.
    """
    patient = plan_context.get("patient", {})
    vitals_today = plan_context.get("vitals_today", {})
    insights = plan_context.get("active_insights", [])
    lab_alerts = plan_context.get("lab_alerts", [])
    med_adherence = plan_context.get("med_adherence", {})
    preferences = plan_context.get("preferences", [])
    symptoms = plan_context.get("symptoms", [])
    agreed_actions = plan_context.get("agreed_actions", [])
    suggested_actions = plan_context.get("suggested_actions", [])
    historical_insights = plan_context.get("historical_insights", [])

    patient_name = patient.get("name", "Patient")
    patient_age = patient.get("age", 72)
    patient_sex = patient.get("sex", "")
    patient_location = patient.get("location", location or "India")
    patient_conditions = patient.get("conditions", conditions or [])

    # Vitals with defaults
    hr = vitals_today.get("avg_heart_rate") or (vitals or {}).get("avg_heart_rate", 72)
    bp_sys = vitals_today.get("bp_systolic") or (vitals or {}).get("bp_systolic", 120)
    bp_dia = vitals_today.get("bp_diastolic") or (vitals or {}).get("bp_diastolic", 80)
    sleep = vitals_today.get("sleep_hours") or (vitals or {}).get("sleep_hours", 7)
    steps = vitals_today.get("steps") or (vitals or {}).get("total_steps", 0)
    bg = (vitals_today.get("blood_glucose")
          or (vitals or {}).get("glucose_mg_dl")
          or (vitals or {}).get("blood_glucose"))
    bg_str = f"{bg} mg/dL" if bg else "Not recorded"

    # Format insights and lab alerts for the prompt
    insights_section = _build_insights_prompt_section(insights)
    lab_section = _build_lab_alerts_prompt_section(lab_alerts)
    
    overdue_labs_section = "None"
    if historical_insights:
        overdue_labs_section = "\n".join([f"- {h.get('name')}: {h.get('message')}" for h in historical_insights])

    # Condition-specific instructions for the LLM
    condition_instructions = []
    active_conditions = set()
    for insight in insights:
        cond = INSIGHT_TO_CONDITION.get(insight.get("rule_id"))
        if cond:
            active_conditions.add(cond)

    if "diabetes" in active_conditions:
        condition_instructions.append(
            "- Include glucose monitoring tasks and carbohydrate-controlled meals."
        )
    if "ckd" in active_conditions:
        condition_instructions.append(
            "- Include hydration reminders, salt monitoring, and BP checks."
        )
    if "anemia" in active_conditions:
        condition_instructions.append(
            "- Include iron-rich food suggestions and rest periods."
        )
    if "thyroid" in active_conditions:
        condition_instructions.append(
            "- Include thyroid medication timing (30 min before breakfast)."
        )
    if "cardiovascular" in active_conditions:
        condition_instructions.append(
            "- Include BP checks, low-sodium meals, and gentle cardiac exercise."
        )

    rate = med_adherence.get('rate')
    rate = 100 if rate is None else rate
    missed_count = med_adherence.get('missed_count')
    missed_count = 0 if missed_count is None else missed_count

    med_section = (
        f"Adherence: {rate:.0f}% over past 7 days. "
        f"Missed doses: {missed_count}."
    )
    if rate < 80:
        med_section += " IMPORTANT: Medication adherence is low. Include prominent medication reminders."

    condition_instructions_str = "\n".join(condition_instructions) if condition_instructions else "- No specific condition-based adjustments needed."

    mem_lines = []
    if preferences:
        mem_lines.extend([f"- (Preference: {p.get('domain', 'General')}) {p.get('constraint_text', '')}" for p in preferences])
    if symptoms:
        mem_lines.extend([f"- (Symptom) {s.get('name', '')} (Severity: {s.get('severity', '')}, Status: {s.get('status', '')})" for s in symptoms])
        
    if mem_lines:
        memory_bullet = "\n".join(mem_lines)
    else:
        memory_bullet = "No recent conversational context."
        
    action_lines = []
    if agreed_actions:
        action_lines.append("[AGREED ACTIONS]")
        action_lines.extend([f"- {a.get('description', '')}" for a in agreed_actions])
    if suggested_actions:
        action_lines.append("\n[SUGGESTED ACTIONS]")
        action_lines.extend([f"- {a.get('description', '')}" for a in suggested_actions])
    actions_bullet = "\n".join(action_lines) if action_lines else "No specific coach actions recorded."

    prompt = f"""
    You are a caring and expert conversational clinical guide for Zivaa Eldercare.
    Create a personalized daily plan (morning, afternoon, evening, night) for:

    PATIENT: {patient_name}, {patient_age}-year-old {patient_sex or 'patient'}
    LOCATION: {patient_location}
    CONDITIONS: {", ".join(patient_conditions) if patient_conditions else "None specified"}

    TODAY'S VITALS:
    - Heart Rate: {hr} bpm
    - Blood Pressure: {bp_sys}/{bp_dia} mmHg
    - Sleep: {sleep} hours
    - Steps: {steps}
    - Blood Glucose: {bg_str}

    ACTIVE HEALTH ALERTS (from clinical rules engine):
{insights_section}

    LAB TRENDS REQUIRING ATTENTION:
{lab_section}

    OVERDUE LABS TO SCHEDULE (Historical):
{overdue_labs_section}

    MEDICATION STATUS:
    {med_section}

    KNOWN PATIENT CONTEXT & RECENT MEMORIES (from chat):
{memory_bullet}

    CARE PLAN ACTIONS (from Coach):
{actions_bullet}

    CONDITION-SPECIFIC INSTRUCTIONS:
{condition_instructions_str}

    GENERAL INSTRUCTIONS:
    1. Write in a warm, comforting tone. Speak like a reassuring family nurse.
    2. No medical jargon. No graphs, charts, or ASCII art.
    3. CRITICAL: You MUST generate 2-3 tasks for the morning, 1-2 for afternoon, 1-2 for evening, and 1-2 for night. No more than 4 per period.
    4. CRITICAL: If there are OVERDUE LABS TO SCHEDULE, include exactly one task to "Book lab test" or "Schedule blood test" in the morning or afternoon.
    5. CRITICAL: You MUST explicitly schedule the 'AGREED' care plan actions into the daily schedule. You should also evaluate the 'SUGGESTED' actions and schedule them if they directly help with the patient's ACTIVE SYMPTOMS.
    6. CRITICAL: Keep distinct activities (like meals, hygiene, self-care, exercise, and medical tasks) as SEPARATE tasks. Do NOT merge unrelated activities together (e.g., do not combine breakfast and self-care).
    7. CRITICAL: The task string should be 4 words maximum. The specific time should be in the 'time' field.
    8. CRITICAL: Food items MUST be specific, healthy Indian recipes suited for {patient_location or 'India'}.
    9. The plan MUST address the active health alerts listed above.
    10. CRITICAL: Provide a canonical 'category' (e.g. 'Activity', 'Diet', 'Medication') and 'details' (1-2 sentences explaining why and how to do it) for every task.

    Format as exact JSON:
    {{
      "summary": "Warm daily overview addressing the health alerts.",
      "schedule": {{
        "morning": [{{ "task": "Gentle Stretches", "time": "7:30 AM", "completed": false, "category": "Activity", "details": "Start your day with 10 minutes of gentle stretching to improve circulation." }}],
        "afternoon": [{{ "task": "Healthy Lunch", "time": "1:00 PM", "completed": false, "category": "Diet", "details": "Enjoy a nutritious meal to keep your energy levels steady." }}],
        "evening": [{{ "task": "Evening Walk", "time": "7:00 PM", "completed": false, "category": "Activity", "details": "A 15-minute walk will help you digest dinner and relax." }}],
        "night": [{{ "task": "Read a Book", "time": "9:30 PM", "completed": false, "category": "Mindfulness", "details": "Read a few chapters of a book to wind down before sleep." }}]
      }}
    }}
    """

    # ── Call Gemini API ──
    if settings.GEMINI_API_KEY != "your-api-key-here":
        try:
            from app.services.plan_schema import get_gemini_schema
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"gemini-2.5-flash:generateContent"
                f"?key={settings.GEMINI_API_KEY}"
            )
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    headers={"Content-Type": "application/json"},
                    json={
                        "contents": [{"parts": [{"text": prompt}]}],
                        "generationConfig": {
                            "responseMimeType": "application/json",
                            "responseSchema": get_gemini_schema()
                        },
                    },
                    timeout=20.0,
                )
                if response.status_code == 200:
                    response_json = response.json()
                    text_content = (
                        response_json["candidates"][0]
                        ["content"]["parts"][0]["text"]
                    )
                    result = json.loads(text_content)
                    
                    # ── Pydantic Validation ──
                    from app.services.plan_schema import DailyPlanResponse
                    validated = DailyPlanResponse.model_validate(result).model_dump()

                    # Attach health context for transparency
                    validated["health_context"] = {
                        "conditions_addressed": list(active_conditions),
                        "insights_count": len(insights),
                        "lab_alerts_count": len(lab_alerts),
                        "med_adherence_rate": med_adherence.get("rate"),
                    }
                    validated["active_alerts"] = [
                        i.get("name", "") for i in insights[:5]
                    ]
                    return validated
                else:
                    print(
                        f"Daily plan LLM error: {response.status_code}, "
                        f"{response.text}"
                    )
        except Exception as e:
            print(f"Daily plan LLM exception: {repr(e)}")

    # ── Fallback: composable structured plan ──
    return get_fallback_daily_plan(plan_context)


# ═══════════════════════════════════════════════════════════════════
# 7. LEGACY COMPATIBILITY
#    For callers that still pass (vitals, conditions, location)
#    instead of a plan_context dict.
# ═══════════════════════════════════════════════════════════════════

async def generate_daily_plan_legacy(
    features: Dict[str, Any],
    conditions: List[str],
    location: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Legacy wrapper for backward compatibility.
    Constructs a minimal plan_context from raw vitals/conditions.
    """
    region = get_region_from_location(location)
    plan_context = {
        "patient": {
            "name": "Patient",
            "age": None,
            "sex": None,
            "location": location,
            "region": region,
            "conditions": conditions,
        },
        "vitals_today": {
            "avg_heart_rate": features.get("avg_heart_rate"),
            "bp_systolic": features.get("bp_systolic"),
            "bp_diastolic": features.get("bp_diastolic"),
            "steps": features.get("total_steps", 0),
            "sleep_hours": features.get("sleep_hours"),
            "blood_glucose": (
                features.get("glucose_mg_dl")
                or features.get("blood_glucose")
                or features.get("avg_blood_glucose")
            ),
        },
        "active_insights": [],
        "lab_alerts": [],
        "med_adherence": {"rate": 100.0, "missed_count": 0},
    }
    return await generate_daily_plan(plan_context)
