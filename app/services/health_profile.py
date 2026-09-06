import json
from datetime import datetime, date, timedelta
from typing import Any, Optional, Dict
from dataclasses import dataclass, field, asdict

from app.config import settings
from supabase import create_client, Client
from app.services.medgemma_services import generate_medgemma_persona

# ─── Supabase Client ─────────────────────────────────────────────
_sb: Optional[Client] = None

def _get_sb() -> Client:
    global _sb
    if _sb is None:
        _sb = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    return _sb

@dataclass
class HealthPersona:
    three_line_profile: str
    long_term_health: dict
    short_term_health: dict
    preferences: dict

    def to_dict(self) -> dict:
        return asdict(self)

async def generate_health_profile(patient_id: str) -> HealthPersona:
    """
    Generates a holistic Health Persona by feeding raw patient context to MedGemma.
    This replaces the deterministic health profile.
    Checks the cache first to see if a valid persona was generated in the last 30 days.
    """
    sb = _get_sb()
    
    # ── 0. Check Database Cache (30 days) ────────────────────────
    thirty_days_ago = (datetime.now() - timedelta(days=30)).isoformat()
    cached_resp = sb.table("health_personas") \
        .select("*") \
        .eq("patient_id", patient_id) \
        .gte("created_at", thirty_days_ago) \
        .order("created_at", desc=True) \
        .limit(1) \
        .execute()
        
    if cached_resp.data:
        cached = cached_resp.data[0]
        return HealthPersona(
            three_line_profile=cached.get("three_line_profile", ""),
            long_term_health=cached.get("long_term_health", {"good": [], "bad": []}),
            short_term_health=cached.get("short_term_health", {"good": [], "bad": []}),
            preferences=cached.get("preferences", {"likes": [], "dislikes": []})
        )

    # ── 1. Fetch Demographics ────────────────────────────────────
    patient = sb.table("patients").select("*").eq("id", patient_id).single().execute()
    p = patient.data
    
    dob = datetime.strptime(p["date_of_birth"], "%d-%m-%Y").date() if p.get("date_of_birth") else None
    age = (date.today() - dob).days // 365 if dob else None

    # ── 2. Fetch Conditions ──────────────────────────────────────
    conditions_resp = sb.table("conditions").select("*").eq("patient_id", patient_id).execute()
    active_conditions = [
        c["condition_name"]
        for c in conditions_resp.data
        if c.get("status") in ("active", "managed")
    ]

    # ── 3. Fetch Medications & Adherence ─────────────────────────
    meds_resp = sb.table("medications").select("*").eq("patient_id", patient_id).eq("is_active", True).execute()
    med_names = [m["medication_name"] for m in meds_resp.data]

    seven_days_ago = (datetime.now() - timedelta(days=7)).isoformat()
    logs_resp = sb.table("medication_logs").select("*").eq("patient_id", patient_id).gte("scheduled_at", seven_days_ago).execute()
    total_logs = len(logs_resp.data)
    taken = sum(1 for m in logs_resp.data if m.get("status") == "taken")
    adherence_pct = round((taken / total_logs * 100) if total_logs > 0 else 100, 1)

    # ── 4. Fetch Recent Vitals (Last 14 days for LLM context limits) ─────────
    fourteen_days_ago = (date.today() - timedelta(days=14)).isoformat()
    vitals_resp = sb.table("vitals_daily").select("*").eq("patient_id", patient_id).gte("date", fourteen_days_ago).order("date").execute()
    vitals_rows = vitals_resp.data

    # ── 5. Fetch Lab Trends ────────────────────────────
    lab_trends = {}
    try:
        from app.services.lab_history import get_patient_lab_trends
        trends_result = get_patient_lab_trends(patient_id)
        lab_trends = trends_result.get("trend_summary", {})
    except Exception as e:
        print(f"Warning: Lab trend computation failed for {patient_id}: {e}")

    # ── 6. Build Context for LLM ──────────────────────────────────
    context = {
        "demographics": {
            "name": p.get("first_name", "Patient"),
            "age": age,
            "gender": p.get("gender"),
        },
        "conditions": active_conditions,
        "medications": med_names,
        "medication_adherence_7d_pct": adherence_pct,
        "recent_vitals_14d": vitals_rows,
        "lab_trends": lab_trends
    }

    # ── 7. Call MedGemma to generate Persona ──────────────────────
    persona_dict = await generate_medgemma_persona(patient_id, context)
    
    # ── 8. Save to Database ───────────────────────────────────────
    insert_data = {
        "patient_id": patient_id,
        "three_line_profile": persona_dict.get("three_line_profile", ""),
        "long_term_health": persona_dict.get("long_term_health", {"good": [], "bad": []}),
        "short_term_health": persona_dict.get("short_term_health", {"good": [], "bad": []}),
        "preferences": persona_dict.get("preferences", {"likes": [], "dislikes": []})
    }
    sb.table("health_personas").insert(insert_data).execute()

    return HealthPersona(
        three_line_profile=insert_data["three_line_profile"],
        long_term_health=insert_data["long_term_health"],
        short_term_health=insert_data["short_term_health"],
        preferences=insert_data["preferences"]
    )
