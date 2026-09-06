from fastapi import FastAPI
from contextlib import asynccontextmanager
from app.api.endpoints import health, fhir
from app.services.scheduler import start_scheduler, stop_scheduler, setup_cron_jobs

@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_cron_jobs()
    await start_scheduler()
    yield
    await stop_scheduler()

app = FastAPI(
    title="Zivaa Eldercare Backend Engine",
    description="Time-series ingestion and AI clinical alert classifier.",
    version="1.0.0",
    lifespan=lifespan
)

# Register health analytics router
app.include_router(health.router, prefix="/api/v1/health", tags=["Health Telemetry"])
from app.api.endpoints import fhir, coach, nutrition, longevity
# Register FHIR integrations router
app.include_router(fhir.router, prefix="/api/v1/fhir", tags=["FHIR Integrations"])
app.include_router(coach.router, prefix="/api/v1/coach", tags=["AI Health Coach"])
app.include_router(nutrition.router, prefix="/api/v1/nutrition", tags=["Nutrition Processing"])
app.include_router(longevity.router, prefix="/api/v1/longevity", tags=["Longevity Protocols"])

@app.get("/")
def read_root():
    return {"message": "Welcome to Zivaa Health Analytics AI Platform"}

from pydantic import BaseModel
from app.services.insights.data_fetcher import supabase

class DeviceRegistration(BaseModel):
    patient_id: str
    fcm_token: str
    timezone: str

@app.post("/api/register-device")
async def register_device(registration: DeviceRegistration):
    try:
        # 1. Ensure patient exists in `patients` table
        p_res = supabase.table("patients").select("id").eq("id", registration.patient_id).execute()
        if not p_res.data:
            full_name = "Beta User"
            try:
                user_resp = supabase.auth.admin.get_user_by_id(registration.patient_id)
                if user_resp and user_resp.user:
                    meta = user_resp.user.user_metadata or {}
                    full_name = meta.get("full_name") or meta.get("name") or user_resp.user.email or "Beta User"
            except Exception as auth_err:
                print(f"Could not fetch auth user details: {auth_err}")

            supabase.table("patients").insert({
                "id": registration.patient_id,
                "full_name": full_name,
                "timezone": registration.timezone or "UTC",
                "caregiver_nudge_preference": "HIGH"
            }).execute()
            print(f"Auto-created patient profile for {registration.patient_id} ({full_name})")
        else:
            # Sync the timezone for existing patient
            supabase.table("patients").update({"timezone": registration.timezone}).eq("id", registration.patient_id).execute()
        
        # 2. Use upsert to handle both insert and update based on unique constraint (fcm_token)
        res = supabase.table("device_tokens").select("id").eq("fcm_token", registration.fcm_token).execute()
        if res.data:
            supabase.table("device_tokens").update({
                "patient_id": registration.patient_id
            }).eq("id", res.data[0]["id"]).execute()
        else:
            supabase.table("device_tokens").insert({
                "patient_id": registration.patient_id,
                "fcm_token": registration.fcm_token
            }).execute()
        return {"status": "success"}
    except Exception as e:
        print(f"Error registering device: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/api/ensure-patient/{patient_id}")
async def ensure_patient(patient_id: str):
    try:
        p_res = supabase.table("patients").select("id").eq("id", patient_id).execute()
        if not p_res.data:
            full_name = "Beta User"
            try:
                user_resp = supabase.auth.admin.get_user_by_id(patient_id)
                if user_resp and user_resp.user:
                    meta = user_resp.user.user_metadata or {}
                    full_name = meta.get("full_name") or meta.get("name") or user_resp.user.email or "Beta User"
            except Exception as auth_err:
                print(f"Could not fetch auth user details: {auth_err}")

            supabase.table("patients").insert({
                "id": patient_id,
                "full_name": full_name,
                "timezone": "UTC",
                "caregiver_nudge_preference": "HIGH"
            }).execute()
            print(f"Auto-created patient profile for {patient_id} ({full_name})")
            return {"status": "created", "patient_id": patient_id, "full_name": full_name}
        return {"status": "exists", "patient_id": patient_id}
    except Exception as e:
        print(f"Error ensuring patient: {e}")
        return {"status": "error", "message": str(e)}

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    errors = exc.errors()
    safe_errors = []
    for error in errors:
        error_dict = dict(error)
        if "input" in error_dict:
            # Drop input to prevent bytes serialization error
            del error_dict["input"]
        safe_errors.append(error_dict)
    return JSONResponse(
        status_code=422,
        content={"detail": safe_errors},
    )
