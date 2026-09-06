from fastapi import APIRouter, HTTPException, BackgroundTasks
from app.utils.crypto import encrypt_text, decrypt_text
from typing import Dict, Any, List
from datetime import datetime, timezone
from app.services.insights.data_fetcher import supabase
from app.services.longevity_engine import generate_weekly_strategy

router = APIRouter()

@router.get("/protocols/{patient_id}")
async def get_longevity_protocols(patient_id: str, date: str = None):
    """
    Returns the Longevity Protocols checklist for a specific date (defaults to today).
    """
    if not date:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        
    try:
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
            
            if baseline_res.data:
                baseline = baseline_res.data[0]
                protocols = baseline.get("protocols", [])
                for p in protocols:
                    for k in ["title", "description", "reasoning", "modification_note"]:
                        if k in p and p[k]:
                            p[k] = decrypt_text(p[k])
                
                # Format to match the expected protocol structure
                return {
                    "patient_id": patient_id,
                    "effective_date": date,
                    "protocols": protocols
                }
            
            return {"date": date, "protocols": []}
            
        data = res.data[0]
        protocols = data.get("protocols", [])
        for p in protocols:
            for k in ["title", "description", "reasoning", "modification_note"]:
                if k in p and p[k]:
                    p[k] = decrypt_text(p[k])
        data["protocols"] = protocols
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/protocols/{patient_id}/complete/{protocol_id}")
async def complete_longevity_protocol(patient_id: str, protocol_id: str, payload: Dict[str, Any]):
    """
    Marks a specific protocol as completed for today (or specified date).
    Payload: {"date": "2026-08-28", "completed": true}
    """
    date = payload.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    completed_status = payload.get("completed", True)
    
    try:
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
                
        return {"success": True, "message": f"Protocol completion status set to {completed_status}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/protocols/{patient_id}/trigger")
async def trigger_longevity_engine(patient_id: str, background_tasks: BackgroundTasks):
    """
    Manually triggers the Weekly Strategist (for testing or onboarding).
    """
    background_tasks.add_task(generate_weekly_strategy, patient_id)
    return {"status": "Weekly Strategist triggered in background"}
