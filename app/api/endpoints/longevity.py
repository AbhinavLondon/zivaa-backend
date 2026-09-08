import uuid
from fastapi import APIRouter, HTTPException, BackgroundTasks, Body
from app.utils.crypto import encrypt_text, decrypt_text
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from app.services.insights.data_fetcher import supabase
from app.services.longevity_engine import generate_weekly_strategy

router = APIRouter()

def normalize_protocol(p: dict, idx: int = 0) -> dict:
    title = p.get("title") or p.get("baseline_target") or "Daily Protocol"
    category = p.get("category") or "General"
    description = p.get("description") or p.get("why_it_matters") or ""
    reasoning = p.get("reasoning") or p.get("why_it_matters") or ""
    
    # Attempt decryption if encrypted
    for k in ["title", "description", "reasoning", "modification_note"]:
        val = p.get(k)
        if val and isinstance(val, str) and val.startswith("gAAAA"):
            try:
                p[k] = decrypt_text(val)
            except Exception:
                pass
                
    protocol_id = p.get("id")
    if not protocol_id or not isinstance(protocol_id, str) or protocol_id.startswith("String"):
        protocol_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{title}-{category}-{idx}"))
        
    p["id"] = protocol_id
    p["title"] = p.get("title") or title
    p["category"] = category
    p["description"] = p.get("description") or description
    p["reasoning"] = p.get("reasoning") or reasoning
    p["is_modified_today"] = bool(p.get("is_modified_today", False))
    p["is_new_from_coach"] = bool(p.get("is_new_from_coach", False))
    p["modification_note"] = p.get("modification_note")
    return p

@router.get("/protocols/{patient_id}")
async def get_longevity_protocols(patient_id: str, date: str = None):
    """
    Returns the Longevity Protocols checklist for a specific date (defaults to today).
    """
    if not date:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        
    try:
        # Check completions for today
        completions_res = supabase.table("longevity_protocol_completions") \
            .select("protocol_id") \
            .eq("patient_id", patient_id) \
            .eq("completed_on", date) \
            .execute()
        completed_ids = {row["protocol_id"] for row in (completions_res.data or [])}

        res = supabase.table("patient_longevity_protocols") \
            .select("*") \
            .eq("patient_id", patient_id) \
            .eq("effective_date", date) \
            .execute()
            
        if not res.data:
            # If nothing for today, default to the latest baseline plan
            baseline_res = supabase.table("patient_longevity_baselines") \
                .select("*") \
                .eq("patient_id", patient_id) \
                .eq("is_active", True) \
                .execute()
            
            if not baseline_res.data:
                # Cold start: create onboarding baseline
                await generate_weekly_strategy(patient_id)
                baseline_res = supabase.table("patient_longevity_baselines") \
                    .select("*") \
                    .eq("patient_id", patient_id) \
                    .eq("is_active", True) \
                    .execute()
            
            if baseline_res.data:
                baseline = baseline_res.data[0]
                protocols = baseline.get("protocols", [])
                for idx, p in enumerate(protocols):
                    normalize_protocol(p, idx)
                    p["isCompleted"] = p.get("id") in completed_ids
                
                return {
                    "patient_id": patient_id,
                    "effective_date": date,
                    "date": date,
                    "protocols": protocols
                }
            
            return {"patient_id": patient_id, "effective_date": date, "date": date, "protocols": []}
            
        data = res.data[0]
        protocols = data.get("protocols", [])
        for idx, p in enumerate(protocols):
            normalize_protocol(p, idx)
            p["isCompleted"] = p.get("id") in completed_ids

        data["protocols"] = protocols
        data["date"] = date
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/protocols/{patient_id}/complete/{protocol_id}")
async def complete_longevity_protocol(
    patient_id: str, 
    protocol_id: str, 
    payload: Optional[Dict[str, Any]] = Body(default=None)
):
    """
    Marks a specific protocol as completed/uncompleted for today (or specified date).
    Payload optional: {"date": "2026-08-28", "completed": true}
    If payload is empty, toggles current status.
    """
    date = (payload or {}).get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    
    try:
        existing = supabase.table("longevity_protocol_completions") \
            .select("id") \
            .eq("patient_id", patient_id) \
            .eq("protocol_id", protocol_id) \
            .eq("completed_on", date) \
            .execute()
            
        if payload and "completed" in payload:
            completed_status = bool(payload["completed"])
        else:
            completed_status = not bool(existing.data)

        if completed_status:
            # Insert into longevity_protocol_completions
            supabase.table("longevity_protocol_completions").upsert({
                "patient_id": patient_id,
                "protocol_id": protocol_id,
                "completed_on": date
            }, on_conflict="patient_id, protocol_id, completed_on").execute()
        else:
            # Delete from longevity_protocol_completions
            supabase.table("longevity_protocol_completions") \
                .delete() \
                .eq("patient_id", patient_id) \
                .eq("protocol_id", protocol_id) \
                .eq("completed_on", date) \
                .execute()
                
        return {"success": True, "completed": completed_status, "message": f"Protocol completion status set to {completed_status}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/protocols/{patient_id}/trigger")
async def trigger_longevity_engine(patient_id: str, background_tasks: BackgroundTasks):
    """
    Manually triggers the Weekly Strategist (for testing or onboarding).
    """
    background_tasks.add_task(generate_weekly_strategy, patient_id)
    return {"status": "Weekly Strategist triggered in background"}
