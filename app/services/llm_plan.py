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

import asyncio
import httpx
import json
import re
import time
import uuid
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

    def get(self, patient_id: str, today_str: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Retrieve cached context if it exists, hasn't expired, and matches today's date."""
        entry = self._cache.get(patient_id)
        if entry is None:
            return None
        timestamp, data = entry
        if time.time() - timestamp > self._ttl:
            del self._cache[patient_id]
            return None
        if today_str and data.get("_plan_date") and data.get("_plan_date") != today_str:
            del self._cache[patient_id]
            return None
        return data

    def set(self, patient_id: str, data: Dict[str, Any], today_str: Optional[str] = None) -> None:
        """Cache the plan context for this patient."""
        if today_str:
            data["_plan_date"] = today_str
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
# 1B. ANATOMICAL ALIASES & EXERCISE CATALOG
# ═══════════════════════════════════════════════════════════════════

ANATOMICAL_ALIASES: Dict[str, str] = {
    # Lower Back
    "lumbar": "Lower Back",
    "lower back": "Lower Back",
    "low back": "Lower Back",
    "spine": "Lower Back",
    "spinal": "Lower Back",
    "sciatica": "Lower Back",
    "sciatic": "Lower Back",
    "sacrum": "Lower Back",
    "back pain": "Lower Back",
    "back": "Lower Back",
    
    # Shoulders / Neck
    "cervical": "Shoulders / Neck",
    "neck": "Shoulders / Neck",
    "trapezius": "Shoulders / Neck",
    "trap": "Shoulders / Neck",
    "traps": "Shoulders / Neck",
    "shoulder": "Shoulders / Neck",
    "shoulders": "Shoulders / Neck",
    "rotator cuff": "Shoulders / Neck",
    "rotator": "Shoulders / Neck",
    "scapula": "Shoulders / Neck",
    "upper back": "Shoulders / Neck",
    
    # Knees / Legs
    "knee": "Knees / Legs",
    "knees": "Knees / Legs",
    "patella": "Knees / Legs",
    "patellar": "Knees / Legs",
    "quadriceps": "Knees / Legs",
    "quad": "Knees / Legs",
    "quads": "Knees / Legs",
    "hamstring": "Knees / Legs",
    "hamstrings": "Knees / Legs",
    "calf": "Knees / Legs",
    "calves": "Knees / Legs",
    "leg": "Knees / Legs",
    "legs": "Knees / Legs",
    "thigh": "Knees / Legs",
    
    # Ankles / Feet
    "ankle": "Ankles / Feet",
    "ankles": "Ankles / Feet",
    "foot": "Ankles / Feet",
    "feet": "Ankles / Feet",
    "plantar": "Ankles / Feet",
    "heel": "Ankles / Feet",
    "toe": "Ankles / Feet",
    "toes": "Ankles / Feet",
    
    # Wrists / Hands
    "wrist": "Wrists / Hands",
    "wrists": "Wrists / Hands",
    "hand": "Wrists / Hands",
    "hands": "Wrists / Hands",
    "finger": "Wrists / Hands",
    "fingers": "Wrists / Hands",
    "grip": "Wrists / Hands",
    "carpal": "Wrists / Hands",
    
    # Hip
    "hip": "Hip",
    "hips": "Hip",
    "glute": "Hip",
    "glutes": "Hip",
    "pelvis": "Hip",
    "pelvic": "Hip",
    "groin": "Hip",
    
    # Core
    "core": "Core",
    "abdominal": "Core",
    "abdomen": "Core",
    "abs": "Core",
    "belly": "Core",
    
    # Full Body / Balance
    "balance": "Full Body / Balance",
    "stability": "Full Body / Balance",
    "fall prevention": "Full Body / Balance",
    "gait": "Full Body / Balance",
    "full body": "Full Body / Balance",
    "posture": "Full Body / Balance",
}


class ExerciseCatalog:
    """
    Cached access to zivaa_exercise_repository to ground daily exercise
    recommendations in verified clinical senior movements.
    """
    _cached_exercises: Optional[List[Dict[str, Any]]] = None
    _cached_timestamp: float = 0.0
    TTL: float = 86400.0  # 24 hours

    @classmethod
    def get_exercises(cls) -> List[Dict[str, Any]]:
        if cls._cached_exercises is not None and (time.time() - cls._cached_timestamp < cls.TTL):
            return cls._cached_exercises
        try:
            from app.services.insights.data_fetcher import supabase
            res = supabase.table("zivaa_exercise_repository") \
                .select("id, exercise_name, body_part, type, duration_seconds, benefits, equipment_needed, difficulty") \
                .execute()
            cls._cached_exercises = res.data or []
            cls._cached_timestamp = time.time()
        except Exception as e:
            print(f"Warning: Failed to fetch exercise repository: {e}")
            cls._cached_exercises = []
        return cls._cached_exercises

    @classmethod
    def get_available_body_parts(cls) -> List[str]:
        exercises = cls.get_exercises()
        parts = {e.get("body_part") for e in exercises if e.get("body_part")}
        return sorted(list(parts))

    @classmethod
    def resolve_body_part_from_text(cls, text: str) -> Optional[str]:
        if not text:
            return None
        text_lower = text.lower()
        
        # 1. Check direct catalog body parts first (longest names first)
        available = sorted(cls.get_available_body_parts(), key=lambda x: len(x), reverse=True)
        for bp in available:
            pattern = rf"\b{re.escape(bp.lower())}\b"
            if re.search(pattern, text_lower):
                return bp
                
        # 2. Check clinical and anatomical aliases (longest phrases first)
        sorted_aliases = sorted(ANATOMICAL_ALIASES.keys(), key=lambda x: len(x), reverse=True)
        for alias in sorted_aliases:
            pattern = rf"\b{re.escape(alias)}\b"
            if re.search(pattern, text_lower):
                return ANATOMICAL_ALIASES[alias]
                
        return None

    @classmethod
    def find_exercises(
        cls, 
        body_part: Optional[str] = None, 
        exercise_type: Optional[str] = None, 
        difficulty: Optional[str] = "beginner", 
        limit: int = 3
    ) -> List[Dict[str, Any]]:
        exercises = cls.get_exercises()
        if not exercises:
            return []
        matches = []
        for ex in exercises:
            bp = (ex.get("body_part") or "").lower()
            et = (ex.get("type") or "").lower()
            diff = (ex.get("difficulty") or "").lower()
            
            # Enforce difficulty safety if specified
            if difficulty and diff and diff != difficulty.lower():
                continue

            if body_part and body_part.lower() in bp:
                matches.append(ex)
            elif exercise_type and exercise_type.lower() in et:
                matches.append(ex)
        if not matches:
            matches = [
                ex for ex in exercises 
                if (not difficulty or (ex.get("difficulty") or "").lower() == difficulty.lower()) 
                and ("balance" in (ex.get("body_part") or "").lower() or "mobility" in (ex.get("type") or "").lower() or "stretch" in (ex.get("type") or "").lower())
            ]
        return matches[:limit]

    @classmethod
    def match_exercises_for_text(
        cls, 
        text: str, 
        target_body_part: Optional[str] = None, 
        difficulty: Optional[str] = "beginner", 
        limit: int = 2
    ) -> List[Dict[str, Any]]:
        exercises = cls.get_exercises()
        if not exercises:
            return []
            
        # 1. Determine target body part
        bp = target_body_part or cls.resolve_body_part_from_text(text)
        if bp:
            matched = cls.find_exercises(body_part=bp, difficulty=difficulty, limit=limit)
            if matched:
                return matched

        # 2. Search exercise name, benefits, or type matching
        clean_words = set(re.findall(r'\b[a-zA-Z]{4,}\b', text.lower()))
        stop_words = {"with", "this", "that", "from", "your", "have", "more", "some", "time", "done", "will", "make"}
        search_words = clean_words - stop_words

        scored: List[Tuple[int, Dict[str, Any]]] = []
        for ex in exercises:
            diff = (ex.get("difficulty") or "").lower()
            if difficulty and diff and diff != difficulty.lower():
                continue
            name_lower = (ex.get("exercise_name") or "").lower()
            benefits_lower = (ex.get("benefits") or "").lower()
            ex_type_lower = (ex.get("type") or "").lower()
            
            score = 0
            for w in search_words:
                if w in name_lower:
                    score += 4
                if w in benefits_lower:
                    score += 2
                if w in ex_type_lower:
                    score += 3
            if score > 0:
                scored.append((score, ex))
                
        if scored:
            scored.sort(key=lambda x: x[0], reverse=True)
            return [x[1] for x in scored[:limit]]

        # 3. Safe fallback to gentle senior mobility/balance
        return cls.find_exercises(exercise_type="mobility", difficulty=difficulty, limit=limit)


def resolve_task_action(act: Dict[str, Any], default_mobility_ids: List[str]) -> Dict[str, Any]:
    """
    Intelligently resolves the UI TaskAction payload for an agreed care action.
    Prioritizes pre-structured metadata, then classifies intent cleanly with
    errand and clinical guardrails.
    """
    desc = act.get("description", "")
    desc_lower = desc.lower()
    operational_type = act.get("action_type", "habit")
    
    # Check if pre-structured metadata exists (e.g. from upstream memory_summarizer)
    meta = act.get("action_metadata") or {}
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except Exception:
            meta = {}
            
    if meta.get("ui_action_type") or meta.get("action_type"):
        ui_type = meta.get("ui_action_type") or meta.get("action_type")
        cta = meta.get("cta_label") or ("Start Routine" if ui_type == "FOLLOW_EXERCISE" else ("Ask Zivaa" if ui_type == "COACH_CHAT" else "Done"))
        payload: Dict[str, Any] = {
            "action_type": ui_type,
            "type": ui_type,
            "cta_label": cta,
        }
        if ui_type == "FOLLOW_EXERCISE":
            payload["exercise_ids"] = meta.get("exercise_ids") or default_mobility_ids
            payload["routine_title"] = meta.get("routine_title") or desc
        if meta.get("target"):
            payload["target"] = meta["target"]
        if meta.get("prefilled_prompt"):
            payload["prefilled_prompt"] = meta["prefilled_prompt"]
        return payload

    # 1. Guardrail against Errands / One-off Tasks
    # If it's a one-off errand (buy medication, see doctor, pick up supplies), it's CHECKBOX_ONLY, even if it contains "walk"!
    is_errand = (operational_type == "one_off") or any(kw in desc_lower for kw in [
        "pharmacy", "chemist", "doctor", "appointment", "clinic", "hospital",
        "buy ", "purchase", "pick up", "order ", "refill"
    ])
    if is_errand:
        return {
            "action_type": "CHECKBOX_ONLY",
            "type": "CHECKBOX_ONLY",
            "cta_label": "Done"
        }

    # 2. Vitals Logging Intent
    is_bp = any(kw in desc_lower for kw in ["blood pressure", "bp ", "bp reading", "systolic", "diastolic", "check bp", "log bp"])
    if is_bp:
        return {
            "action_type": "LOG_VITALS",
            "type": "LOG_VITALS",
            "target": "blood_pressure",
            "cta_label": "Record BP"
        }
        
    is_glucose = any(kw in desc_lower for kw in ["glucose", "blood sugar", "sugar reading", "fasting sugar", "postprandial", "check sugar", "log sugar"])
    if is_glucose:
        return {
            "action_type": "LOG_VITALS",
            "type": "LOG_VITALS",
            "target": "glucose",
            "cta_label": "Log Sugar"
        }

    # 3. Nutrition Intent
    is_meal = any(kw in desc_lower for kw in [
        "snap meal", "log meal", "food photo", "photo of meal", "meal photo",
        "photo of food", "snap food", "log food", "track food", "log lunch",
        "log dinner", "log breakfast", "track lunch", "track dinner", "track breakfast"
    ]) or (("photo" in desc_lower or "snap" in desc_lower or "log" in desc_lower or "track" in desc_lower) and any(m in desc_lower for m in ["meal", "breakfast", "lunch", "dinner", "food", "snack"]))
    if is_meal:
        return {
            "action_type": "LOG_MEAL",
            "type": "LOG_MEAL",
            "target": "nutrition",
            "cta_label": "Snap Meal"
        }

    # 4. Coach Chat Intent
    is_coach = any(kw in desc_lower for kw in ["ask zivaa", "ask coach", "check in with zivaa", "chat with zivaa", "discuss with zivaa", "message zivaa", "talk to zivaa"])
    if is_coach:
        return {
            "action_type": "COACH_CHAT",
            "type": "COACH_CHAT",
            "cta_label": "Ask Zivaa",
            "prefilled_prompt": f"I want to follow up on: {desc}"
        }

    # 5. Exercise / Movement Intent
    # Look for movement keywords OR anatomical targets
    target_bp = act.get("target_body_part") or ExerciseCatalog.resolve_body_part_from_text(desc)
    is_exercise_keyword = any(kw in desc_lower for kw in [
        "exercise", "stretch", "workout", "routine", "squat", "mobility", 
        "yoga", "walk", "walking", "stroll", "strengthening", "reps", "flexibility"
    ])
    
    if target_bp or is_exercise_keyword:
        matched = ExerciseCatalog.match_exercises_for_text(
            text=desc,
            target_body_part=target_bp,
            difficulty="Beginner",
            limit=2
        )
        ex_ids = [str(e["id"]) for e in matched] if matched else default_mobility_ids
        return {
            "action_type": "FOLLOW_EXERCISE",
            "type": "FOLLOW_EXERCISE",
            "cta_label": "Start Routine",
            "exercise_ids": ex_ids,
            "routine_title": desc
        }

    # 6. Default Fallback
    return {
        "action_type": "CHECKBOX_ONLY",
        "type": "CHECKBOX_ONLY",
        "cta_label": "Done"
    }


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

async def build_plan_context(
    patient_id: str, 
    phone_location: Optional[str] = None,
    phone_timezone: Optional[str] = None
) -> Dict[str, Any]:
    """
    Builds the full context needed for daily plan generation concurrently.
    Consolidates 17 sequential blocking queries down to parallel async tasks.
    Guarantees strict today's date checking and patient-local timezone consistency.
    """
    import zoneinfo
    from app.services.insights.data_fetcher import get_async_supabase
    from app.services.reinforcement import align_history_data, calculate_task_correlations
    from app.services.lab_history import get_patient_lab_trends
    from app.utils.crypto import decrypt_text
    from app.utils.weather import get_city_temperature_async

    client = await get_async_supabase()

    now_utc = datetime.now(timezone.utc)
    # Query 16 days back to safely cover 14 local days across all timezones
    fourteen_days_cutoff_str = (now_utc.date() - timedelta(days=16)).isoformat()
    seven_days_cutoff_str = (now_utc.date() - timedelta(days=9)).isoformat()
    now_iso = now_utc.isoformat()

    # ── 1. Consolidated Native Async Task Definitions ──

    async def _fetch_patient() -> Dict[str, Any]:
        p_info = {
            "id": patient_id, "name": "Patient", "age": None, "sex": None,
            "location": None, "region": "North", "conditions": [],
            "timezone": None
        }
        try:
            resp = await client.table("patients") \
                .select("full_name, date_of_birth, gender, location_city, timezone") \
                .eq("id", patient_id) \
                .single() \
                .execute()
            if resp.data:
                p_info["name"] = resp.data.get("full_name", "Patient")
                p_info["sex"] = (resp.data.get("gender") or "").lower() or None
                p_info["location"] = resp.data.get("location_city")
                p_info["timezone"] = resp.data.get("timezone")
                p_info["region"] = get_region_from_location(p_info["location"])
                p_info["_raw_dob"] = resp.data.get("date_of_birth")
        except Exception as e:
            print(f"Warning: Could not fetch patient demographics: {e}")
        return p_info

    async def _fetch_conditions() -> List[str]:
        try:
            cond_resp = await client.table("conditions") \
                .select("condition_name") \
                .eq("patient_id", patient_id) \
                .execute()
            if cond_resp.data:
                return [
                    c["condition_name"] for c in cond_resp.data if c.get("condition_name")
                ]
        except Exception as e:
            print(f"Warning: Could not fetch conditions: {e}")
        return []

    async def _fetch_vitals_14d() -> List[Dict[str, Any]]:
        try:
            v_resp = await client.table("vitals_daily") \
                .select("*") \
                .eq("patient_id", patient_id) \
                .gte("date", fourteen_days_cutoff_str) \
                .order("date", desc=True) \
                .execute()
            return v_resp.data or []
        except Exception as e:
            print(f"Warning: Could not fetch vitals history: {e}")
            return []

    async def _fetch_plans_14d() -> List[Dict[str, Any]]:
        try:
            plan_resp = await client.table("daily_plans") \
                .select("date, schedule, created_at") \
                .eq("patient_id", patient_id) \
                .gte("date", fourteen_days_cutoff_str) \
                .order("created_at", desc=True) \
                .execute()
            return plan_resp.data or []
        except Exception as e:
            print(f"Warning: Could not fetch daily plans: {e}")
            return []

    async def _fetch_insights() -> List[Dict[str, Any]]:
        try:
            insights_resp = await client.table("active_clinical_insights") \
                .select("rule_id, name, severity, message, category, status, updated_at") \
                .eq("patient_id", patient_id) \
                .in_("status", ["active", "resolved_stale", "historical"]) \
                .execute()
            return insights_resp.data or []
        except Exception as e:
            print(f"Warning: Could not fetch active clinical insights: {e}")
            return []

    async def _fetch_lab_trends() -> List[Dict[str, Any]]:
        alerts = []
        try:
            trends = await asyncio.to_thread(get_patient_lab_trends, patient_id)
            for code, summary in trends.get("trend_summary", {}).items():
                flag = summary.get("clinical_flag", "stable")
                if flag in ("worsening", "needs_attention"):
                    alert = {
                        "biomarker": summary.get("biomarker_name", code),
                        "direction": summary.get("trend_direction", "unknown"),
                        "change_pct": summary.get("change_percent", 0),
                        "clinical_flag": flag,
                    }
                    if summary.get("rate_alert"):
                        alert["rate_alert"] = summary["rate_alert"]
                    alerts.append(alert)
        except Exception as e:
            print(f"Warning: Lab trend fetch failed: {e}")
        return alerts

    async def _fetch_meds() -> Dict[str, Any]:
        med_adh = {"rate": None, "missed_count": 0}
        try:
            meds_resp = await client.table("medication_logs") \
                .select("status, scheduled_at") \
                .eq("patient_id", patient_id) \
                .gte("scheduled_at", seven_days_cutoff_str) \
                .lte("scheduled_at", now_iso) \
                .execute()
            rows = meds_resp.data or []
            total = len(rows)
            if total > 0:
                taken = sum(1 for m in rows if m.get("status") == "taken")
                missed = sum(1 for m in rows if m.get("status") in ("missed", "skipped"))
                med_adh = {
                    "rate": round((taken / total) * 100, 1),
                    "missed_count": missed,
                }
        except Exception as e:
            print(f"Warning: Medication adherence fetch failed: {e}")
        return med_adh

    async def _fetch_setup() -> Dict[str, Any]:
        s_prefs = {}
        try:
            setup_resp = await client.table("patient_plan_setup") \
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
                            if isinstance(val, list) and not val:
                                continue
                            if isinstance(val, str) and not val.strip():
                                continue
                            s_prefs[field] = val
                            break
        except Exception as e:
            print(f"Warning: Patient plan setup fetch failed: {e}")
        return s_prefs

    async def _fetch_nutritional() -> List[Dict[str, Any]]:
        try:
            nut_resp = await client.table("active_nutritional_insights") \
                .select("rule_id, insight_name, severity, context_data, category") \
                .eq("patient_id", patient_id) \
                .eq("status", "active") \
                .execute()
            return nut_resp.data or []
        except Exception as e:
            print(f"Warning: Nutritional insights fetch failed: {e}")
            return []

    async def _fetch_preferences() -> List[Dict[str, Any]]:
        try:
            pref_resp = await client.table("patient_preferences") \
                .select("*") \
                .eq("patient_id", patient_id) \
                .execute()
            return pref_resp.data or []
        except Exception as e:
            print(f"Warning: Could not fetch patient preferences: {e}")
            return []

    async def _fetch_symptoms() -> List[Dict[str, Any]]:
        syms = []
        try:
            sym_resp = await client.table("patient_symptoms") \
                .select("*") \
                .eq("patient_id", patient_id) \
                .in_("status", ["Active", "Resolving"]) \
                .execute()
            if sym_resp.data:
                for s in sym_resp.data:
                    try:
                        if s.get("name"):
                            s["name"] = decrypt_text(s["name"])
                    except Exception:
                        pass
                syms.extend(sym_resp.data)
        except Exception as e:
            print(f"Warning: Could not fetch patient symptoms: {e}")
        return syms

    async def _fetch_actions() -> List[Dict[str, Any]]:
        try:
            act_resp = await client.table("care_plan_actions") \
                .select("*") \
                .eq("patient_id", patient_id) \
                .execute()
            return act_resp.data or []
        except Exception as e:
            print(f"Warning: Could not fetch care plan actions: {e}")
            return []

    # ── 2. Run All Independent Database Queries in Parallel ──
    results = await asyncio.gather(
        _fetch_patient(),
        _fetch_conditions(),
        _fetch_vitals_14d(),
        _fetch_plans_14d(),
        _fetch_insights(),
        _fetch_lab_trends(),
        _fetch_meds(),
        _fetch_setup(),
        _fetch_nutritional(),
        _fetch_preferences(),
        _fetch_symptoms(),
        _fetch_actions(),
    )

    patient_info = results[0]
    patient_info["conditions"] = results[1]
    vitals_rows = results[2]
    plan_rows = results[3]
    insights_rows = results[4]
    lab_alerts = results[5]
    med_adherence = results[6]
    setup_prefs = results[7]
    nutritional_insights = results[8]
    preferences = results[9]
    symptoms = results[10]
    raw_actions = results[11]

    # ── 3. Resolve Patient Local Timezone & Date Boundaries ──
    pt_tz_str = phone_timezone or patient_info.get("timezone") or "Asia/Kolkata"
    try:
        patient_tz = zoneinfo.ZoneInfo(pt_tz_str)
    except Exception:
        try:
            patient_tz = zoneinfo.ZoneInfo("Asia/Kolkata")
            pt_tz_str = "Asia/Kolkata"
        except Exception:
            patient_tz = timezone.utc
            pt_tz_str = "UTC"

    patient_info["timezone"] = pt_tz_str
    now_local = datetime.now(patient_tz)
    today_str = now_local.date().isoformat()
    yesterday_str = (now_local.date() - timedelta(days=1)).isoformat()
    current_weekday = now_local.strftime("%A").lower()

    # Check cache with verified patient today_str
    cached = _insights_cache.get(patient_id, today_str=today_str)
    if cached is not None:
        return cached

    # Calculate age accurately in patient local time
    dob = patient_info.pop("_raw_dob", None)
    if dob:
        birth = None
        if isinstance(dob, str):
            for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%m-%d-%Y", "%d/%m/%Y", "%Y/%m/%d"):
                try:
                    birth = datetime.strptime(dob, fmt).date()
                    break
                except ValueError:
                    continue
        else:
            birth = dob
        if birth:
            patient_info["age"] = (now_local.date() - birth).days // 365

    # ── 4. Filter Care Actions with Local Current Weekday ──
    agreed_actions = []
    suggested_actions = []
    for a in raw_actions:
        st = a.get("status")
        if st == "Agreed":
            cadence = (a.get("cadence") or "daily").lower()
            if cadence.startswith("weekly_"):
                target_day = cadence.replace("weekly_", "")
                if target_day != current_weekday:
                    continue
            agreed_actions.append(a)
        elif st == "Suggested":
            suggested_actions.append(a)

    # ── 5. Resolve Location & Fetch Weather (Async with 30m in-memory cache) ──
    target_city = phone_location or patient_info.get("location")
    if not target_city and pt_tz_str and "/" in pt_tz_str:
        inferred_city = pt_tz_str.split("/")[-1].replace("_", " ")
        if inferred_city.lower() != "utc":
            target_city = inferred_city
    if not target_city:
        target_city = "Delhi"

    # Ensure patient_info["location"] and region are populated
    if not patient_info.get("location"):
        patient_info["location"] = target_city
        patient_info["region"] = get_region_from_location(target_city)

    patient_info["temperature"] = await get_city_temperature_async(target_city)

    # ── 6. In-Memory Slicing & Parsing (Zero Additional Database Queries) ──

    def _norm_d(d_val: Any) -> str:
        if not d_val:
            return ""
        return str(d_val)[:10]

    # A. Vitals today & history: strictly verify today's date
    vitals_today = {}
    today_vitals_row = next((r for r in vitals_rows if _norm_d(r.get("date")) == today_str), None)
    if today_vitals_row:
        vitals_today = {
            "avg_heart_rate": today_vitals_row.get("avg_heart_rate"),
            "bp_systolic": today_vitals_row.get("bp_systolic"),
            "bp_diastolic": today_vitals_row.get("bp_diastolic"),
            "steps": today_vitals_row.get("total_steps", 0),
            "sleep_hours": today_vitals_row.get("sleep_hours"),
            "blood_glucose": today_vitals_row.get("blood_glucose_avg"),
            "oxygen_sat": today_vitals_row.get("oxygen_sat_avg"),
            "body_temp": today_vitals_row.get("body_temp_avg"),
            "skin_temp_delta": today_vitals_row.get("skin_temperature_delta"),
            "weight": today_vitals_row.get("weight_kg"),
            "mood_score": today_vitals_row.get("mood_score"),
            "avg_cadence_spm": today_vitals_row.get("avg_cadence_spm"),
            "active_movement_minutes": today_vitals_row.get("active_movement_minutes"),
            "active_hours_count": today_vitals_row.get("active_hours_count"),
        }

    # vitals_history contains completed preceding days strictly before today
    vitals_history = [r for r in vitals_rows if _norm_d(r.get("date")) < today_str][:7]
    if not vitals_history and vitals_rows:
        vitals_history = vitals_rows[:7]

    # B. Daily plans slicing: existing_plan, previous_plan, recent_meals
    existing_plan = {}
    previous_plan = {}
    recent_meals = []

    for r in plan_rows:
        r_date = _norm_d(r.get("date"))
        schedule = r.get("schedule")
        if not schedule:
            continue
        if r_date == today_str and not existing_plan:
            existing_plan = schedule
        elif r_date == yesterday_str and not previous_plan:
            previous_plan = schedule

    # If no plan specifically for yesterday, pick the latest plan strictly before today
    if not previous_plan:
        for r in plan_rows:
            r_date = _norm_d(r.get("date"))
            if r_date < today_str and r.get("schedule"):
                previous_plan = r.get("schedule")
                break

    # Recent meals should strictly come from prior days (not today) to ensure dietary variety
    prior_plans = [r for r in plan_rows if _norm_d(r.get("date")) < today_str]
    for row in prior_plans[:3]:
        schedule = row.get("schedule", {})
        if isinstance(schedule, dict):
            for period in ["morning", "afternoon", "evening", "night"]:
                tasks = schedule.get(period, [])
                if isinstance(tasks, list):
                    for t in tasks:
                        category = (t.get("category") or "").lower()
                        task_name = t.get("task", "")
                        if any(kw in category for kw in ["breakfast", "lunch", "dinner", "meal", "snack"]) or \
                           any(kw in task_name.lower() for kw in ["breakfast", "lunch", "dinner"]):
                            recent_meals.append(task_name)

    # C. Task Correlations (Calculated in-memory from pre-fetched 14-day data)
    correlations = []
    try:
        plans_by_date = {_norm_d(r.get("date")): r.get("schedule", {}) for r in plan_rows if r.get("date")}
        vitals_by_date = {_norm_d(r.get("date")): r for r in vitals_rows if r.get("date")}
        aligned_data = align_history_data(plans_by_date, vitals_by_date)
        correlations = calculate_task_correlations(aligned_data)
    except Exception as e:
        print(f"Warning: Correlations calculation failed: {e}")

    # D. Clinical Insights Partitioning
    active_insights = []
    historical_insights = []
    stale_cutoff = (now_utc - timedelta(hours=48)).isoformat()

    for item in insights_rows:
        st = item.get("status")
        if st == "active":
            active_insights.append({
                "rule_id": item.get("rule_id", ""),
                "name": item.get("name", "Alert"),
                "severity": item.get("severity", "LOW"),
                "message": item.get("message", ""),
                "category": item.get("category", "General"),
                "is_stale": False
            })
        elif st == "resolved_stale":
            updated_at = item.get("updated_at") or ""
            if updated_at >= stale_cutoff:
                active_insights.append({
                    "rule_id": item.get("rule_id", ""),
                    "name": item.get("name", "Alert"),
                    "severity": item.get("severity", "LOW"),
                    "message": item.get("message", ""),
                    "category": item.get("category", "General"),
                    "is_stale": True
                })
        elif st == "historical":
            historical_insights.append({
                "name": item.get("name", "Alert"),
                "message": item.get("message", ""),
                "updated_at": item.get("updated_at")
            })

    # ── 7. Assemble Structured Context ──
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

    _insights_cache.set(patient_id, context, today_str=today_str)
    return context


def build_plan_context_sync(
    patient_id: str, 
    phone_location: Optional[str] = None,
    phone_timezone: Optional[str] = None
) -> Dict[str, Any]:
    """Synchronous wrapper for offline test scripts and synchronous callers."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(asyncio.run, build_plan_context(patient_id, phone_location, phone_timezone))
            return future.result()
    else:
        return asyncio.run(build_plan_context(patient_id, phone_location, phone_timezone))


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
    mobility_exercises = [str(e["id"]) for e in ExerciseCatalog.find_exercises(exercise_type="mobility", limit=2)] or ["53", "55"]
    schedule = {
        "morning": [
            {"task": "Drink warm water", "time": "7:00 AM", "completed": False, "category": "Diet", "details": "Start your day with a glass of warm water for digestion.", "action": {"action_type": "CHECKBOX_ONLY", "type": "CHECKBOX_ONLY", "cta_label": "Done"}},
            {"task": f"Eat {foods['breakfast']}", "time": "8:30 AM", "completed": False, "category": "Diet", "details": "Have a nutritious breakfast to energize your morning.", "action": {"action_type": "LOG_MEAL", "type": "LOG_MEAL", "target": "nutrition", "cta_label": "Log Meal"}},
            {"task": "Morning Mobility Routine", "time": "9:00 AM", "completed": False, "category": "Activity", "details": "Stretch lightly to improve joint mobility and blood flow.", "action": {"action_type": "FOLLOW_EXERCISE", "type": "FOLLOW_EXERCISE", "target": "routine", "routine_title": "Morning Mobility Routine", "cta_label": "Start Routine", "exercise_ids": mobility_exercises}},
        ],
        "afternoon": [
            {"task": f"Eat {foods['lunch']}", "time": "1:00 PM", "completed": False, "category": "Diet", "details": "Enjoy a balanced lunch for steady afternoon energy.", "action": {"action_type": "LOG_MEAL", "type": "LOG_MEAL", "target": "nutrition", "cta_label": "Log Meal"}},
            {"task": "Drink glass water", "time": "3:00 PM", "completed": False, "category": "Diet", "details": "Stay hydrated throughout the day.", "action": {"action_type": "CHECKBOX_ONLY", "type": "CHECKBOX_ONLY", "cta_label": "Done"}},
        ],
        "evening": [
            {"task": f"Eat {foods['dinner']}", "time": "7:30 PM", "completed": False, "category": "Diet", "details": "Have a light, easy-to-digest dinner.", "action": {"action_type": "LOG_MEAL", "type": "LOG_MEAL", "target": "nutrition", "cta_label": "Log Meal"}},
        ],
        "night": [
            {"task": "Take bedtime medications", "time": "9:45 PM", "completed": False, "category": "Medication", "details": "Take any prescribed night-time medications.", "action": {"action_type": "CHECKBOX_ONLY", "type": "CHECKBOX_ONLY", "cta_label": "Taken"}},
            {"task": "Prepare dark bedroom", "time": "10:00 PM", "completed": False, "category": "Sleep", "details": "Dim the lights and ensure your bedroom is quiet for restful sleep.", "action": {"action_type": "CHECKBOX_ONLY", "type": "CHECKBOX_ONLY", "cta_label": "Done"}},
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
    med_rate = med_adherence.get("rate") if med_adherence.get("rate") is not None else 100
    if med_rate < 80:
        med_task = {"task": "Set medication reminder", "time": "9:00 AM", "completed": False, "category": "Medication", "details": "Set an alarm to ensure you don't miss any doses today."}
        task_key = "set medication reminder"
        if task_key not in seen_tasks:
            schedule["morning"].insert(0, med_task)
            seen_tasks.add(task_key)

    # ── Vitals-based adjustments ──
    steps = vitals.get("steps", 0) or 0
    bp_sys = vitals.get("bp_systolic", 120) or 120
    hr = vitals.get("avg_heart_rate", 72) or 72
    active_hours = vitals.get("active_hours_count")
    active_mins = vitals.get("active_movement_minutes")

    if steps < 1000 and not (bp_sys > 150 or hr > 90):
        task = {"task": "Walk around house", "time": "4:00 PM", "completed": False, "category": "Activity", "details": "Take a short walk to keep your circulation healthy."}
        if "walk around house" not in seen_tasks:
            schedule["afternoon"].append(task)

    # If prolonged sitting detected (< 4 daytime active hours or < 20 active movement minutes)
    if (active_hours is not None and active_hours < 4) or (active_mins is not None and active_mins < 20):
        task = {"task": "Gentle circulation stroll", "time": "2:30 PM", "completed": False, "category": "Activity", "details": "A brief 5-minute stroll to break up prolonged sitting and keep joints supple."}
        if "gentle circulation stroll" not in seen_tasks:
            schedule["afternoon"].append(task)

    if bp_sys > 140 or hr > 85:
        task = {"task": "Do deep breathing", "time": "8:00 PM", "completed": False, "category": "Mindfulness", "details": "Practice deep breathing to help lower your blood pressure and heart rate."}
        if "do deep breathing" not in seen_tasks:
            schedule["evening"].append(task)

    # ── Compose agreed coach actions into schedule ──
    agreed_coach_actions = plan_context.get("agreed_actions", [])
    for act in agreed_coach_actions:
        desc = act.get("description", "")
        act_id = str(act.get("id", ""))
        act_type = act.get("action_type", "habit")
        badge = "HABIT" if act_type == "habit" else ("ERRAND" if act_type == "one_off" else "COACH AGREED")
        action_payload = resolve_task_action(act, default_mobility_ids=mobility_exercises)
            
        target_slot = "morning" if len(schedule["morning"]) < 3 else ("afternoon" if len(schedule["afternoon"]) < 2 else "evening")
        schedule[target_slot].append({
            "id": act_id or str(uuid.uuid4()),
            "task": desc[:25],
            "time": "10:30 AM" if target_slot == "morning" else "3:30 PM",
            "completed": False,
            "category": "Coach",
            "details": f"Agreed with Coach Zivaa: {desc}",
            "tier": "coach",
            "anchor_type": act_type,
            "anchor_id": act_id,
            "provenance": {"source": "coach", "badge": badge, "badge_text": badge, "reason": "Agreed during your conversation with Coach Zivaa"},
            "action": action_payload
        })


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

    if med_rate < 80:
        summary_parts.append(
            " Some medications were missed recently — medication reminders "
            "have been added."
        )

    summary = " ".join(summary_parts)

    from app.services.plan_schema import DailyPlanResponse
    return DailyPlanResponse.model_validate({
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
    }).model_dump()


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

    cadence = vitals_today.get("avg_cadence_spm") or (vitals or {}).get("avg_cadence_spm")
    cadence_str = f"{round(cadence)} spm (Target: 80+ spm for brisk walking)" if cadence else "Not recorded"

    active_mins = vitals_today.get("active_movement_minutes") or (vitals or {}).get("active_movement_minutes")
    active_mins_str = f"{round(active_mins)} mins (Daily target: 30+ mins)" if active_mins else "Not recorded"

    active_hours = vitals_today.get("active_hours_count") or (vitals or {}).get("active_hours_count")
    active_hours_str = f"{int(active_hours)}/12 daytime hours active (Target: >=6/12)" if active_hours is not None else "Not recorded"

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

    # Format sample exercises from repository for LLM grounding
    available_exercises = ExerciseCatalog.get_exercises()
    sample_ex_lines = []
    if available_exercises:
        by_bp = {}
        for ex in available_exercises:
            bp = ex.get("body_part", "General")
            if bp not in by_bp and len(by_bp) < 8:
                by_bp[bp] = ex
        for bp, ex in by_bp.items():
            sample_ex_lines.append(f"- [ID: {ex.get('id')}] {ex.get('exercise_name')} ({bp} / {ex.get('type')})")
    exercise_sample_str = "\n".join(sample_ex_lines) if sample_ex_lines else "Repository available."

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
    - Walking Cadence: {cadence_str}
    - Active Moving Time: {active_mins_str}
    - Movement Regularity: {active_hours_str}

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

    EXERCISE REPOSITORY EXAMPLES:
{exercise_sample_str}

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
    11. CRITICAL EXERCISE GROUNDING: When scheduling physical activity, stretching, or movement:
        - Pick real exercises from the repository above.
        - Set 'action': {{ 'type': 'FOLLOW_EXERCISE', 'cta_label': 'Follow Exercises', 'exercise_ids': ['<id1>', '<id2>'] }}.
    12. CRITICAL CTA MAPPING:
        - For Vitals (BP / Glucose): set 'action': {{ 'type': 'LOG_VITALS', 'target': 'blood_pressure' or 'glucose', 'cta_label': 'Record BP' or 'Log Sugar' }}.
        - For Meals / Nutrition: set 'action': {{ 'type': 'LOG_MEAL', 'target': 'nutrition', 'cta_label': 'Snap Meal' }}.
        - For Coach / Symptom Check: set 'action': {{ 'type': 'COACH_CHAT', 'cta_label': 'Ask Zivaa', 'prefilled_prompt': '...' }}.
        - For routine / water / lights: set 'action': {{ 'type': 'CHECKBOX_ONLY', 'cta_label': 'Done' }}.
    13. CRITICAL PROVENANCE:
        - If task addresses an active health alert, set 'tier': 'clinical', 'provenance': {{ 'badge': 'NEW', 'reason': '...' }}.
        - If task comes from Agreed Coach Actions, set 'tier': 'coach', 'anchor_id': '<action_id>', 'provenance': {{ 'badge': 'COACH AGREED' or 'HABIT', 'reason': 'Agreed with Coach Zivaa' }}.


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
                    timeout=60.0,
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
            "avg_cadence_spm": features.get("avg_cadence_spm"),
            "active_movement_minutes": features.get("active_movement_minutes"),
            "active_hours_count": features.get("active_hours_count"),
        },
        "active_insights": [],
        "lab_alerts": [],
        "med_adherence": {"rate": 100.0, "missed_count": 0},
    }
    return await generate_daily_plan(plan_context)
