"""
Yesterday's Metrics Service

Retrieves steps, sleep hours, and mood score for the latest logged day.
"""

from typing import Dict, Any

async def get_yesterday_metrics(patient_id: str) -> Dict[str, Any]:
    """
    Retrieves steps, sleep hours, and mood score for the latest logged day (yesterday).
    """
    from app.services.insights.data_fetcher import fetch_patient_context
    ctx = fetch_patient_context(patient_id)
    
    vitals_dict = ctx.vitals._vitals
    
    # Find the latest date with any vital readings in history
    all_dates = []
    for metric_name, values in vitals_dict.items():
        for val in values:
            all_dates.append(val.date)
            
    if not all_dates:
        return {
            "date": None,
            "steps": None,
            "sleep_hours": None,
            "mood_score": None
        }
        
    target_date = max(all_dates)
    
    # Extract steps, sleep, mood
    steps_vals = [val.value for val in vitals_dict.get("steps", []) if val.date == target_date]
    sleep_vals = [val.value for val in vitals_dict.get("sleep_hours", []) if val.date == target_date]
    mood_vals = [val.value for val in vitals_dict.get("mood_score", []) if val.date == target_date]
    
    return {
        "date": target_date.isoformat(),
        "steps": int(steps_vals[0]) if steps_vals else None,
        "sleep_hours": round(sleep_vals[0], 1) if sleep_vals else None,
        "mood_score": int(mood_vals[0]) if mood_vals else None
    }
