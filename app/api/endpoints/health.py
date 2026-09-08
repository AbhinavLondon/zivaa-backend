import asyncio
from fastapi import APIRouter, HTTPException, status, Query
from app.utils.crypto import encrypt_text, decrypt_text
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from app.services.ml_pipeline import extract_features
from app.services.llm_nudge import generate_clinical_nudge
from app.services.llm_plan import generate_daily_plan, build_plan_context, generate_daily_plan_legacy
from app.services.daily_summary import generate_daily_summary
from app.services.yesterday_metrics import get_yesterday_metrics
from app.services.vitals_cards import generate_vitals_cards
from app.services.lab_history import get_patient_lab_history, get_patient_lab_trends
from app.services.medgemma_services import (
    generate_medgemma_alerts,
    generate_medgemma_nudge,
    generate_medgemma_plan,
    generate_medgemma_summary,
    generate_category_summary
)

router = APIRouter()

# Timer dictionary to coalesce rapid burst sync chunks from mobile clients
_debounce_timers: Dict[str, asyncio.Task] = {}

def schedule_debounced_tripwire(patient_id: str, delay_seconds: int = 25):
    """
    Schedules a tripwire evaluation after a quiet period of `delay_seconds`.
    If another sync chunk arrives before the timer expires, the existing timer is cancelled
    and reset, coalescing all burst sync chunks into a single unified evaluation.
    """
    async def _debounced_worker():
        try:
            await asyncio.sleep(delay_seconds)
            print(f"[DEBOUNCE] {delay_seconds}s quiet period elapsed for patient {patient_id}. Dispatching unified Tripwire evaluation.")
            await run_tripwire_evaluation(patient_id, "vitals")
        except asyncio.CancelledError:
            # Expected when a newer sync chunk resets the debounce timer
            pass
        except Exception as e:
            print(f"[DEBOUNCE] Error in debounced tripwire worker for patient {patient_id}: {e}")
        finally:
            if _debounce_timers.get(patient_id) is task:
                _debounce_timers.pop(patient_id, None)

    existing_timer = _debounce_timers.get(patient_id)
    if existing_timer and not existing_timer.done():
        existing_timer.cancel()
        print(f"[DEBOUNCE] Resetting debounce timer for patient {patient_id} (new sync chunk arrived).")

    task = asyncio.create_task(_debounced_worker())
    _debounce_timers[patient_id] = task


class MetricRecord(BaseModel):
    type: str = Field(..., description="Metric type (steps, heart_rate, sleep, blood_pressure, etc.)")
    timestamp: datetime
    values: Dict[str, float] = Field(..., description="Raw properties of the metric")

class DeviceStatus(BaseModel):
    battery_level: int = Field(..., description="Battery percentage 0-100")
    is_charging: bool = Field(False)
    is_connected: bool = Field(True)

class IngestionPayload(BaseModel):
    patient_id: Optional[str] = Field(None, description="Patient ID for tripwire evaluation")
    client_time: datetime
    timezone: str
    records: List[MetricRecord]
    device_status: Optional[DeviceStatus] = None

class IngestionResponse(BaseModel):
    status: str
    processed_count: int
    nudge_alert: Dict[str, Any]

class DailyPlanRequest(BaseModel):
    vitals: Optional[Dict[str, float]] = Field(None, description="Dictionary of vital readings (optional if patient_id is provided)")
    conditions: List[str] = Field(default_factory=list, description="Active chronic medical conditions")
    patient_id: Optional[str] = Field(None, description="Patient ID for insights-driven plan generation")
    location: Optional[str] = Field(None, description="Location to customize food recommendations")

class UpdateTaskRequest(BaseModel):
    patient_id: str
    period: str
    task_index: int
    completed: bool

class TaskItem(BaseModel):
    task: str
    completed: bool = False

class DailyPlanSchedule(BaseModel):
    morning: List[TaskItem]
    afternoon: List[TaskItem]
    evening: List[TaskItem]
    night: List[TaskItem]

class DailyPlanResponse(BaseModel):
    summary: str
    schedule: DailyPlanSchedule
    # Optional: which health conditions influenced the plan (Tier 4 derived data)
    health_context: Optional[Dict[str, Any]] = None
    # Optional: names of active health alerts addressed by the plan
    active_alerts: Optional[List[str]] = None

class TrendBarItem(BaseModel):
    date: str
    value: float
    diastolic: Optional[float] = None
    status: str

class VitalCardItem(BaseModel):
    metric_id: str
    title: str
    display_value: str
    unit: str
    label: str
    trend_bars: List[TrendBarItem]
    insight: str

class VitalsCardsResponse(BaseModel):
    cards: List[VitalCardItem]

class AvailableBiomarker(BaseModel):
    code: str
    name: str
    category: str
    unit: str

class LabHistoryEntry(BaseModel):
    value: float
    flag: str
    measured_at: datetime
    report_name: Optional[str] = None
    lab_name: Optional[str] = None

class LabBiomarkerHistory(BaseModel):
    code: str
    name: str
    unit: str
    reference_low: Optional[float] = None
    reference_high: Optional[float] = None
    category: str
    history: List[LabHistoryEntry]

class LabHistoryResponse(BaseModel):
    patient_id: str
    available_biomarkers: List[AvailableBiomarker]
    comparison_data: Dict[str, LabBiomarkerHistory]

class TrendReadingItem(BaseModel):
    value: float
    date: Optional[str] = None
    flag: str = "normal"

class RateAlertItem(BaseModel):
    label: str
    citation: str

class BiomarkerTrend(BaseModel):
    code: str
    name: str
    unit: str
    category: str
    data_points: int
    first_reading: TrendReadingItem
    latest_reading: TrendReadingItem
    reference_low: Optional[float] = None
    reference_high: Optional[float] = None
    trend_direction: str
    change_absolute: float
    change_percent: float
    rate_per_month: float
    zone: str
    clinical_flag: str
    rcv_threshold_pct: float
    rate_alert: Optional[RateAlertItem] = None
    history: List[TrendReadingItem]

class LabTrendsResponse(BaseModel):
    patient_id: str
    trend_summary: Dict[str, BiomarkerTrend]

from fastapi import BackgroundTasks
from app.services.tripwire import run_tripwire_evaluation

@router.post("/ingest", response_model=IngestionResponse, status_code=status.HTTP_201_CREATED)
async def ingest_health_data(payload: IngestionPayload, background_tasks: BackgroundTasks):
    if not payload.records:
        return IngestionResponse(
            status="success",
            processed_count=0,
            message="No records to process."
        )
    
    outlier_count = 0
    if payload.patient_id:
        from app.services.insights.data_fetcher import supabase
        
        if payload.timezone:
            try:
                supabase.table("patients").update({"timezone": payload.timezone}).eq("id", payload.patient_id).execute()
            except Exception as e:
                print(f"Failed to update patient timezone: {e}")
                
        # Inject device_status as a metric record if present
        if payload.device_status:
            payload.records.append(MetricRecord(
                type="device_status",
                timestamp=payload.client_time,
                values={
                    "battery_level": payload.device_status.battery_level,
                    "is_charging": payload.device_status.is_charging,
                    "is_connected": payload.device_status.is_connected
                }
            ))

        metric_type_map = {
            "steps": "StepsRecord",
            "heart_rate": "HeartRateRecord",
            "sleep": "SleepSessionRecord",
            "blood_pressure": "BloodPressureRecord",
            "blood_glucose": "BloodGlucoseRecord",
            "body_temperature": "BodyTemperatureRecord",
            "oxygen_saturation": "OxygenSaturationRecord",
            "respiratory_rate": "RespiratoryRateRecord",
            "distance": "DistanceRecord",
            "active_calories": "ActiveCaloriesBurnedRecord",
            "speed": "SpeedRecord",
            "hrv": "HeartRateVariabilityRmssdRecord",
            "resting_heart_rate": "RestingHeartRateRecord",
            "skin_temperature": "SkinTemperatureRecord"
        }

        insert_payload = []
        for r in payload.records:
            is_outlier = False
            r_type = r.type.lower()
            
            # Map Android aliases to explicit SQL metric_type
            db_metric_type = metric_type_map.get(r_type, r.type)
            
            # Static Hardware Bounds (Noise Filtering)
            if r_type == "heart_rate" and "bpm" in r.values:
                bpm = r.values["bpm"]
                if bpm < 30 or bpm > 220:
                    is_outlier = True
            elif r_type == "blood_pressure":
                sys = r.values.get("systolic")
                dia = r.values.get("diastolic")
                if (sys is not None and (sys < 70 or sys > 250)) or \
                   (dia is not None and (dia < 30 or dia > 180)):
                    is_outlier = True
            elif r_type == "steps" and "count" in r.values:
                if r.values["count"] < 0:
                    is_outlier = True
            elif r_type == "sleep" and "duration_minutes" in r.values:
                if r.values["duration_minutes"] < 0 or r.values["duration_minutes"] > (24 * 60):
                    is_outlier = True
            elif r_type == "blood_glucose" and "mg_dl" in r.values:
                if r.values["mg_dl"] < 20 or r.values["mg_dl"] > 1000:
                    is_outlier = True
            elif r_type == "body_temperature" and "fahrenheit" in r.values:
                if r.values["fahrenheit"] < 85.0 or r.values["fahrenheit"] > 110.0:
                    is_outlier = True
            
            if is_outlier:
                outlier_count += 1
                
            insert_payload.append({
                "patient_id": payload.patient_id,
                "metric_type": db_metric_type,
                "recorded_at": r.timestamp.isoformat(),
                "timezone": payload.timezone,
                "values": r.values,
                "source": "api_ingest",
                "is_outlier": is_outlier,
                "cleaned_values": None if is_outlier else r.values
            })
            
        try:
            if insert_payload:
                response = supabase.table("vitals_raw").upsert(insert_payload, ignore_duplicates=True).execute()
        except Exception as e:
            print(f"Failed to insert into vitals_raw: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to insert health data: {str(e)}")

        # Dispatch Tripwire Evaluation (MedGemma will evaluate clinical anomalies based on the clean aggregates)
        background_tasks.add_task(run_tripwire_evaluation, payload.patient_id)
        
    
    return IngestionResponse(
        status="success",
        processed_count=len(payload.records),
        nudge_alert={
            "risk_level": "LOW",
            "nudge_title": "Processing Vitals",
            "nudge_text": f"Vitals ingested successfully. Evaluated {len(payload.records)} readings, filtered {outlier_count} noise artifacts.",
            "why_flagged": "",
            "action_steps": "",
            "timestamp": datetime.utcnow().isoformat()
        }
    )

class LabIngestionPayload(BaseModel):
    patient_id: str
    reports: List[Dict[str, Any]]

@router.post("/ingest-lab", status_code=status.HTTP_201_CREATED)
async def ingest_lab_data(payload: LabIngestionPayload, background_tasks: BackgroundTasks):
    if not payload.reports:
        raise HTTPException(status_code=400, detail="No lab reports provided.")
    
    # Save lab reports to DB here...
    
    # Dispatch Tripwire Evaluation (Heavy Mode for Labs)
    background_tasks.add_task(run_tripwire_evaluation, payload.patient_id, trigger_type="labs")
    
    return {"status": "success", "message": "Lab reports ingested. Evaluation triggered."}

class TriggerTripwirePayload(BaseModel):
    patient_id: str

@router.post("/trigger-tripwire", status_code=status.HTTP_200_OK)
async def trigger_tripwire(payload: TriggerTripwirePayload, background_tasks: BackgroundTasks):
    if not payload.patient_id:
        raise HTTPException(status_code=400, detail="patient_id is required")
        
    # Dispatch Tripwire Evaluation
    background_tasks.add_task(run_tripwire_evaluation, payload.patient_id, "vitals")
    return {"status": "success", "message": "Tripwire evaluation triggered."}

class SyncCompletePayload(BaseModel):
    patient_id: str
    timezone: Optional[str] = "UTC"
    sync_type: Optional[str] = None
    records_synced: Optional[int] = 0
    metric_types: Optional[list[str]] = []

@router.post("/sync-complete", status_code=status.HTTP_200_OK)
async def sync_complete(payload: SyncCompletePayload, background_tasks: BackgroundTasks):
    print(f"RAW PAYLOAD RECEIVED: {payload.model_dump()}")
    if not payload.patient_id:
        raise HTTPException(status_code=400, detail="patient_id is required")
        
    from app.services.insights.data_fetcher import supabase
    if payload.sync_type:
        print(f"[SYNC] {payload.patient_id} completed {payload.sync_type} sync. Records: {payload.records_synced}, Types: {payload.metric_types}")
        try:
            supabase.table("sync_logs").insert({
                "patient_id": payload.patient_id,
                "sync_type": payload.sync_type,
                "status": "Success",
                "records_synced": payload.records_synced,
                "metric_types": payload.metric_types
            }).execute()
        except Exception as e:
            print(f"Failed to insert into sync_logs: {e}")

    # 1. Dispatch Tripwire Evaluation (Debounced 25s to coalesce burst sync chunks)
    schedule_debounced_tripwire(payload.patient_id, delay_seconds=25)
    
    # 2. Event-Driven Morning Generation Pipeline
    try:
        import zoneinfo
        from datetime import datetime, timezone
        from app.services.insights.data_fetcher import supabase
        
        now = datetime.now(timezone.utc)
        try:
            tz = zoneinfo.ZoneInfo(payload.timezone or "UTC")
        except Exception:
            tz = zoneinfo.ZoneInfo("UTC")
            
        local_now = now.astimezone(tz)
        
        # Check if it's morning (e.g. 4 AM to 11 AM local time)
        if 4 <= local_now.hour <= 11:
            # Correct today_start math: calculate midnight in local time, then convert back to UTC
            local_today_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
            today_start_utc = local_today_start.astimezone(timezone.utc).isoformat()
            
            # Check if we already generated the morning briefing today
            res_briefing = supabase.table("daily_morning_briefings").select("id").eq("patient_id", payload.patient_id).gte("created_at", today_start_utc).limit(1).execute()
            
            if not res_briefing.data:
                # Briefing hasn't been generated yet today.
                # Check if sleep data was ingested today in the database.
                res_sleep = supabase.table("vitals_raw").select("id").eq("patient_id", payload.patient_id).eq("metric_type", "SleepSessionRecord").gte("ingested_at", today_start_utc).limit(1).execute()
                
                if res_sleep.data:
                    from app.services.scheduler_jobs import run_morning_generation_pipeline
                    from app.services.longevity_engine import generate_daily_protocols
                    print(f"Sync-complete triggered morning generation pipeline for {payload.patient_id} (Sleep data ingested today)")
                    background_tasks.add_task(run_morning_generation_pipeline, payload.patient_id)
                    background_tasks.add_task(generate_daily_protocols, payload.patient_id)
    except Exception as e:
        print(f"Failed to check/trigger morning generation pipeline: {e}")
        
    return {"status": "success", "message": "Post-sync orchestration queued."}

@router.post("/daily-plan/update-task")
async def update_task_status(payload: UpdateTaskRequest):
    """Updates the completed status of a specific task in the current daily plan."""
    from app.services.insights.data_fetcher import supabase
    
    # Get the most recent plan for this patient
    res = supabase.table("daily_plans").select("id, schedule").eq("patient_id", payload.patient_id).order("created_at", desc=True).limit(1).execute()
    
    if not res.data:
        raise HTTPException(status_code=404, detail="No daily plan found for this patient.")
        
    plan = res.data[0]
    schedule = plan.get("schedule", {})
    
    period = payload.period.lower()
    if period not in schedule or not isinstance(schedule[period], list):
        raise HTTPException(status_code=400, detail=f"Invalid period: {period}")
        
    if payload.task_index < 0 or payload.task_index >= len(schedule[period]):
        raise HTTPException(status_code=400, detail="Invalid task index.")
        
    # Update the completed status
    schedule[period][payload.task_index]["completed"] = payload.completed
    
    # Save back to database
    update_res = supabase.table("daily_plans").update({"schedule": schedule}).eq("id", plan["id"]).execute()
    
    return {"status": "success", "message": "Task status updated."}

@router.post("/daily-plan")
async def get_daily_plan(payload: DailyPlanRequest):
    """
    Generate a personalised daily care plan.

    If patient_id is provided, uses the full insights-driven flow:
      1. Runs the Insights Engine (18 clinical rules)
      2. Fetches RCV-based lab trends
      3. Checks medication adherence
      4. Builds a plan grounded in the patient's actual health context

    If only vitals + conditions are provided (legacy), falls back to
    the original plan generation without insights context.
    """
    try:
        if payload.patient_id:
            import asyncio
            from app.services.insights.data_fetcher import fetch_patient_context
            from app.config import settings
            
            from app.services.insights.data_fetcher import supabase
            
            from datetime import datetime, time, timezone
            
            # Check DB for pre-computed plan for today
            today_start = datetime.combine(datetime.now(timezone.utc).date(), time.min).isoformat()
            res = supabase.table("daily_plans").select("summary, schedule, health_context").eq("patient_id", payload.patient_id).gte("created_at", today_start).order("created_at", desc=True).limit(1).execute()
            
            pure_medgemma_plan = {}
            if res.data and "schedule" in res.data[0] and res.data[0]["schedule"]:
                pure_medgemma_plan = {
                    "summary": res.data[0].get("summary", ""),
                    "schedule": res.data[0]["schedule"],
                    "health_context": res.data[0].get("health_context", {})
                }
            else:
                # Fallback to generate
                if settings.ENABLE_MEDGEMMA_PIPELINE:
                    try:
                        plan_context = build_plan_context(payload.patient_id, phone_location=payload.location)
                        # Fetch active alerts from db
                        alert_res = supabase.table("active_clinical_insights").select("*").eq("patient_id", payload.patient_id).eq("status", "active").execute()
                        plan_context["active_insights"] = alert_res.data if alert_res.data else []
                        pure_medgemma_plan = await generate_medgemma_plan(plan_context)
                        
                        # Save the generated plan to the database
                        if "error" not in pure_medgemma_plan and pure_medgemma_plan.get("schedule"):
                            try:
                                supabase.table("daily_plans").insert({
                                    "patient_id": payload.patient_id,
                                    "date": datetime.now(timezone.utc).date().isoformat(),
                                    "schedule": pure_medgemma_plan.get("schedule", {}),
                                    "summary": pure_medgemma_plan.get("summary", ""),
                                    "health_context": pure_medgemma_plan.get("health_context", {}),
                                    "source": "gemini_llm"
                                }).execute()
                            except Exception as db_e:
                                print(f"Failed to save plan to DB: {db_e}")
                    except Exception as e:
                        pure_medgemma_plan = {"error": str(e)}
            
            return {
                "rules_engine_plan": {}, # Deprecated
                "pure_medgemma_plan": pure_medgemma_plan
            }
        elif payload.vitals:
            # â”€â”€ Legacy fallback: raw vitals + conditions â”€â”€
            from app.services.llm_plan import get_region_from_location
            region = get_region_from_location(payload.location)
            plan_context = {
                "patient": {
                    "name": "Patient",
                    "age": None,
                    "sex": None,
                    "location": payload.location,
                    "region": region,
                    "conditions": payload.conditions,
                },
                "vitals_today": {
                    "avg_heart_rate": payload.vitals.get("avg_heart_rate") or payload.vitals.get("heart_rate"),
                    "bp_systolic": payload.vitals.get("bp_systolic"),
                    "bp_diastolic": payload.vitals.get("bp_diastolic"),
                    "steps": payload.vitals.get("total_steps", payload.vitals.get("steps", 0)),
                    "sleep_hours": payload.vitals.get("sleep_hours"),
                    "blood_glucose": (
                        payload.vitals.get("glucose_mg_dl")
                        or payload.vitals.get("blood_glucose")
                        or payload.vitals.get("avg_blood_glucose")
                    ),
                },
                "active_insights": [],
                "lab_alerts": [],
                "med_adherence": {"rate": 100.0, "missed_count": 0},
            }
            plan = await generate_medgemma_plan(plan_context)
            return {
                "rules_engine_plan": plan,
                "pure_medgemma_plan": plan
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Either patient_id or vitals must be provided."
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate daily plan: {str(e)}"
        )

@router.get("/insights/{patient_id}")
async def get_patient_insights(patient_id: str):
    from app.services.insights.engine import engine
    
    try:
        # Run rules engine (includes baseline gate)
        output = engine.evaluate_patient(patient_id)
        
        # If still calibrating, return early with calibration status
        active_only = [i for i in output.active_insights if not i.is_historical]
        if output.calibration_message and not active_only:
            return {
                "status": "calibrating",
                "patient_id": patient_id,
                "calibration_message": output.calibration_message,
                "baseline_status": output.baseline_status,
                "active_insights": [],
                "skipped_rules": [],
                "nudge_alert": {
                    "risk_level": "LOW",
                    "nudge_title": "Getting to know you",
                    "nudge_text": output.calibration_message,
                    "why_flagged": "We need a few more days of data to understand normal patterns.",
                    "action_steps": "Keep wearing the device and logging vitals daily. Insights will activate automatically."
                },
                "timestamp": datetime.utcnow().isoformat()
            }
        
        # Format human-readable nudge via LLM
        nudge = await generate_medgemma_nudge(active_only, patient_name="Patient", patient_id=patient_id)
        
        status_value = "calibrating_vitals" if output.calibration_message else "success"
        
        return {
            "status": status_value,
            "patient_id": patient_id,
            "calibration_message": output.calibration_message,
            "active_insights": [i.model_dump() for i in active_only],
            "skipped_rules": [
                {"rule": s.rule_id, "name": s.name, "reason": s.skip_reason}
                for s in output.skipped_rules
            ],
            "nudge_alert": nudge,
            "baseline_status": output.baseline_status,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate insights: {str(e)}"
        )

@router.get("/baseline/{patient_id}")
async def get_baseline_status(patient_id: str):
    """
    Returns the calibration status for a patient's baselines.
    The caregiver app uses this to show onboarding progress:
    'We're learning Ranjit's patterns â€” 3 more days until full insights.'
    """
    from app.services.insights.data_fetcher import fetch_patient_context
    
    try:
        # Fetch context triggers baseline computation/refresh
        ctx = fetch_patient_context(patient_id)
        
        if ctx.baseline_status:
            return {
                "status": "success",
                **ctx.baseline_status.to_dict(),
                "calibration_message": ctx.calibration_message,
                "timestamp": datetime.utcnow().isoformat()
            }
        else:
            return {
                "status": "success",
                "patient_id": patient_id,
                "overall_status": "no_data",
                "calibration_message": "No health data recorded yet. Start logging vitals to begin baseline calibration.",
                "metrics": {},
                "timestamp": datetime.utcnow().isoformat()
            }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch baseline status: {str(e)}"
        )

@router.get("/daily-summary/{patient_id}")
async def get_daily_summary(patient_id: str, patient_name: str = "your loved one"):
    """
    Morning briefing for the caregiver â€” a 2-sentence holistic summary
    of how the patient is doing. Designed to be shown as the first thing
    the caregiver sees when they open the app each morning.

    Query params:
        patient_name: The name to use in the summary (e.g. "Papa", "Nana")
    """
    import asyncio
    try:
        from app.config import settings
        
        from app.services.insights.data_fetcher import supabase
        
        from datetime import datetime, timezone, timedelta
        
        # Determine start of today
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        
        # Check DB for pre-computed summary generated TODAY
        res = supabase.table("daily_morning_briefings").select("summary, headline").eq("patient_id", patient_id).gte("created_at", today_start).order("created_at", desc=True).limit(1).execute()
        
        medgemma_summary = {}
        if res.data and "summary" in res.data[0] and res.data[0]["summary"]:
            medgemma_summary = {
                "summary": res.data[0]["summary"], 
                "headline": res.data[0].get("headline", ""),
                "model_used": "Database Cache"
            }
        else:
            medgemma_summary = {
                "summary": "We are still analyzing your latest vitals and preparing your personalized briefing. Please check back shortly.",
                "headline": "Analyzing Vitals...",
                "model_used": "Pending Pipeline"
            }
        
        return {
            "patient_id": patient_id,
            "timestamp": datetime.utcnow().isoformat(),
            "rules_engine_summary": {}, # Deprecated
            "pure_medgemma_summary": medgemma_summary
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate daily summaries: {str(e)}"
        )


@router.get("/yesterday-metrics/{patient_id}")
async def get_yesterday_metrics_endpoint(patient_id: str):
    """
    Exposes a GET endpoint to retrieve yesterday's (latest logged day) steps,
    sleep hours, and mood score for a patient.
    """
    try:
        metrics = await get_yesterday_metrics(patient_id)
        return metrics
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch yesterday's metrics: {str(e)}"
        )


@router.get("/vitals-cards/{patient_id}", response_model=VitalsCardsResponse)
async def get_vitals_cards_endpoint(patient_id: str, timeframe: str = "7 days"):
    """
    Exposes a GET endpoint to retrieve structured vitals cards for the patient,
    supporting Today, 7 days, 30 Days, or 3 Months filters.
    """
    try:
        cards = await generate_vitals_cards(patient_id, timeframe)
        return VitalsCardsResponse(cards=cards)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch vitals cards: {str(e)}"
        )


@router.get("/lab-history/{patient_id}", response_model=LabHistoryResponse)
async def get_lab_history_endpoint(
    patient_id: str,
    biomarker: Optional[List[str]] = Query(None, description="Biomarker codes to filter comparison data")
):
    """
    Exposes a GET endpoint to compare patient lab metrics over time.
    Supports filtering to specific biomarkers via '?biomarker=HBA1C&biomarker=FBS'.
    """
    try:
        history = get_patient_lab_history(patient_id, biomarker)
        return LabHistoryResponse(**history)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch lab history: {str(e)}"
        )


@router.get("/lab-trends/{patient_id}", response_model=LabTrendsResponse)
async def get_lab_trends_endpoint(
    patient_id: str,
    biomarker: Optional[List[str]] = Query(None, description="Biomarker codes to filter trends")
):
    """
    Returns computed biomarker trend analysis across all historical lab reports.
    Each biomarker gets: trend_direction, rate_per_month, zone, clinical_flag.
    Supports filtering via '?biomarker=HBA1C&biomarker=EGFR'.
    """
    try:
        trends = get_patient_lab_trends(patient_id, biomarker)
        return LabTrendsResponse(**trends)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to compute lab trends: {str(e)}"
        )


@router.get("/health-profile/{patient_id}")
async def get_health_profile(patient_id: str):
    """
    Generates a qualitative, human-like holistic health persona for a patient
    using MedGemma. Bypasses the deterministic rules engine entirely.
    """
    from app.services.health_profile import generate_health_profile

    try:
        profile = await generate_health_profile(patient_id)
        return profile.to_dict()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate health profile: {str(e)}"
        )


@router.get("/compare/{patient_id}")
async def compare_gemini_vs_medgemma(patient_id: str):
    """
    Runs both standard Gemini and parallel MedGemma pipelines side-by-side
    on the patient's data, comparing active alerts (deterministic rules vs MedGemma diagnostics),
    nudges, daily care plans, and summaries.
    """
    import asyncio
    from app.services.insights.data_fetcher import fetch_patient_context
    from app.services.insights.engine import engine
    from app.services.llm_plan import build_plan_context, generate_daily_plan
    from app.services.daily_summary import generate_daily_summary

    try:
        # 1. Fetch Shared Patient Context
        ctx = fetch_patient_context(patient_id)
        
        # 2. Run Deterministic Rules Engine (Gemini Alerts source of truth)
        rules_output = engine.evaluate_patient(patient_id, ctx)
        
        # Convert Rules Active Insights to comparable dict format
        rules_alerts = []
        for insight in rules_output.active_insights:
            rules_alerts.append({
                "rule_id": insight.rule_id,
                "name": insight.name,
                "severity": insight.severity.value,
                "category": insight.category.value,
                "message": insight.message,
                "evidence": insight.evidence
            })

        # 3. Build Plan Context (for Plans and summaries)
        plan_ctx = build_plan_context(patient_id)

        # 4. Trigger Gemini Pipeline and MedGemma Pipeline in Parallel
        # Run MedGemma raw diagnostics alerts
        medgemma_alerts = await generate_medgemma_alerts(ctx)
        
        medgemma_plan_ctx = {**plan_ctx, "active_insights": medgemma_alerts}

        # Run generation tasks concurrently
        results = await asyncio.gather(
            generate_clinical_nudge(rules_output.active_insights, patient_name="Patient", patient_id=patient_id),
            generate_daily_plan(plan_ctx),
            generate_daily_summary(patient_id, patient_name="your loved one"),
            generate_medgemma_nudge(medgemma_alerts, patient_name="Patient", patient_id=patient_id),
            generate_medgemma_plan(medgemma_plan_ctx),
            generate_medgemma_summary(patient_id, patient_name="your loved one"),
            return_exceptions=True
        )
        
        # Unpack results with fallback in case of exceptions
        def get_val(idx):
            val = results[idx]
            if isinstance(val, Exception):
                print(f"Comparison task {idx} failed: {val}")
                return {"error": str(val)}
            return val

        gemini_nudge = get_val(0)
        gemini_plan = get_val(1)
        gemini_summary = get_val(2)
        medgemma_nudge = get_val(3)
        medgemma_plan = get_val(4)
        medgemma_summary = get_val(5)

        return {
            "patient_id": patient_id,
            "timestamp": datetime.utcnow().isoformat(),
            "alerts": {
                "rules_engine": rules_alerts,
                "med_gemma_diagnostics": medgemma_alerts
            },
            "nudge": {
                "gemini_flash": gemini_nudge,
                "med_gemma": medgemma_nudge
            },
            "daily_plan": {
                "gemini_flash": gemini_plan,
                "med_gemma": medgemma_plan
            },
            "daily_summary": {
                "gemini_flash": gemini_summary,
                "med_gemma": medgemma_summary
            }
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate comparisons: {str(e)}"
        )

@router.get("/patient/{patient_id}/checkins/today")
async def get_todays_checkins(patient_id: str):
    """
    Retrieves the mid-day and evening check-in messages generated for the patient today.
    """
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).date().isoformat()
    
    try:
        from app.services.insights.data_fetcher import supabase
        res = supabase.table("patient_checkins").select("*").eq("patient_id", patient_id).eq("date", today).order("created_at", desc=False).execute()
        
        checkins = {"MIDDAY": None, "EVENING": None}
        if res.data:
            for row in res.data:
                checkins[row["checkin_type"]] = row["message"]
                
        return {
            "status": "success",
            "date": today,
            "patient_id": patient_id,
            "checkins": checkins
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/lab-category-summary/{report_id}/{category}")
async def get_lab_category_summary(report_id: str, category: str, patient_name: str = "your loved one"):
    """
    Fetches or generates an LLM summary for a specific lab report category (e.g. Kidney, Liver).
    Checks the JSONB column on fhir_diagnostic_reports first.
    """
    try:
        from app.services.insights.data_fetcher import supabase
        # 1. Fetch the report to see if we already have a summary cached
        report_res = supabase.table("fhir_diagnostic_reports").select("patient_id, category_level_explanation").eq("id", report_id).execute()
        if not report_res.data:
            raise HTTPException(status_code=404, detail="Diagnostic report not found")
            
        report_data = report_res.data[0]
        explanations = report_data.get("category_level_explanation") or {}
        
        # Check if valid non-fallback cached summary exists
        cached = explanations.get(category)
        if cached and not cached.startswith("No recent data") and not cached.startswith("We're still analyzing"):
            return {"summary": cached}
            
        # Resolve real patient first name if default is used
        if patient_name == "your loved one" and report_data.get("patient_id"):
            try:
                pat_res = supabase.table("patients").select("full_name").eq("id", report_data["patient_id"]).execute()
                if pat_res.data and pat_res.data[0].get("full_name"):
                    patient_name = pat_res.data[0]["full_name"].strip().split()[0]
            except Exception:
                pass
            
        # 2. No cached summary found, fetch observations
        obs_res = supabase.table("fhir_observations").select("*").eq("report_id", report_id).execute()
        observations = obs_res.data
        
        # Filter observations by category
        # Supports both legacy text format and FHIR coding format (consumer-category / clinical-category)
        category_obs = []
        cat_lower = category.strip().lower()
        for row in observations:
            obs = row.get("resource", {})
            obs_categories = obs.get("category", [])
            matched = False
            for c in obs_categories:
                if c.get("text", "").strip().lower() == cat_lower:
                    matched = True
                    break
                for coding in c.get("coding", []):
                    if (coding.get("display", "").strip().lower() == cat_lower or 
                        coding.get("code", "").strip().lower() == cat_lower):
                        matched = True
                        break
                if matched:
                    break
            if matched:
                category_obs.append(obs)
                
        # 3. Generate summary
        summary_text = await generate_category_summary(category_obs, category, patient_name)
        
        # 4. Save back to DB only if a valid summary was generated
        if not summary_text.startswith("No recent data") and not summary_text.startswith("We're still analyzing"):
            explanations[category] = summary_text
            supabase.table("fhir_diagnostic_reports").update({"category_level_explanation": explanations}).eq("id", report_id).execute()
        
        return {"summary": summary_text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class UpdateSymptomPayload(BaseModel):
    status: str
    progression_note: Optional[str] = None

@router.put('/memory/symptoms/{symptom_id}')
async def update_symptom(symptom_id: str, payload: UpdateSymptomPayload):
    try:
        from app.services.insights.data_fetcher import supabase
        from datetime import datetime, timezone
        
        # Verify symptom exists
        res = supabase.table('patient_symptoms').select('patient_id, severity').eq('id', symptom_id).execute()
        if not res.data:
            raise HTTPException(status_code=404, detail='Symptom not found')
            
        patient_id = res.data[0]['patient_id']
        severity = res.data[0]['severity']
        
        # 1. Update patient_symptoms
        update_data = {'status': payload.status}
        if payload.status == 'Resolved':
            update_data['resolved_at'] = datetime.now(timezone.utc).isoformat()
            
            # Cascade: Archive any linked care plan actions since the symptom is now resolved
            supabase.table('care_plan_actions').update({'status': 'Archived'}).eq('symptom_id', symptom_id).execute()
            
        supabase.table('patient_symptoms').update(update_data).eq('id', symptom_id).execute()
        
        # 2. Add entry to symptom_logs
        log_data = {
            'symptom_id': symptom_id,
            'patient_id': patient_id,
            'severity': severity,
            'status': payload.status,
            'note': payload.progression_note or 'Status updated manually via UI'
        }
        supabase.table('symptom_logs').insert(log_data).execute()
        
        return {'status': 'success'}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class UpdateActionPayload(BaseModel):
    status: str

@router.put('/memory/actions/{action_id}')
async def update_action(action_id: str, payload: UpdateActionPayload):
    try:
        from app.services.insights.data_fetcher import supabase
        
        # 1. Update care_plan_actions
        supabase.table('care_plan_actions').update({'status': payload.status}).eq('id', action_id).execute()
        
        return {'status': 'success'}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get('/memory/longevity-plan/{patient_id}')
async def get_longevity_plan(patient_id: str):
    from app.services.insights.data_fetcher import supabase
    try:
        prefs_res = supabase.table('patient_preferences').select('*').eq('patient_id', patient_id).execute()
        symp_res = supabase.table('patient_symptoms').select('*').eq('patient_id', patient_id).execute()
        logs_res = supabase.table('symptom_logs').select('id, symptom_id, severity, status, note, created_at').eq('patient_id', patient_id).order('created_at', desc=True).execute()
        act_res = supabase.table('care_plan_actions').select('*').eq('patient_id', patient_id).execute()
        meds_res = supabase.table('patient_medications').select('*').eq('patient_id', patient_id).execute()
        
        symptoms = symp_res.data or []
        for s in symptoms:
            if 'name' in s:
                s['name'] = decrypt_text(s['name'])
                
        logs = logs_res.data or []
        for s in symptoms:
            s['logs'] = [l for l in logs if l['symptom_id'] == s['id']]
            
        medications = meds_res.data or []
        for m in medications:
            if 'name' in m:
                m['name'] = decrypt_text(m['name'])
            if 'dose' in m:
                m['dose'] = decrypt_text(m['dose'])
        
        return {
            'preferences': prefs_res.data or [],
            'symptoms': symptoms,
            'actions': act_res.data or [],
            'medications': medications
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

