from fastapi import APIRouter, HTTPException, status, UploadFile, File, Form, Body, Request, BackgroundTasks
from typing import Dict, Any, Optional
from datetime import datetime
from app.services.medgemma_services import parse_lab_report_to_fhir
from app.services.tripwire import run_tripwire_evaluation
from app.services.notification_templates import dispatch_notification, NotificationType
from supabase import create_client
from app.config import settings
import json

router = APIRouter()
supabase = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)

@router.post("/Bundle/upload", status_code=status.HTTP_202_ACCEPTED)
async def upload_fhir_bundle_file(
    request: Request,
    background_tasks: BackgroundTasks
):
    patient_id = request.query_params.get("patient_id")
    effective_date_override = request.query_params.get("effective_date")
    form = await request.form()
    if not patient_id:
        patient_id = form.get("patient_id")
    if not effective_date_override:
        effective_date_override = form.get("effective_date")
        
    if not patient_id:
        raise HTTPException(status_code=400, detail="patient_id is required either as a query parameter or form field.")
        
    file = None
    for key, value in form.multi_items():
        if hasattr(value, "filename") and getattr(value, "filename"):
            file = value
            break
            
    if not file:
        raise HTTPException(status_code=400, detail="No file uploaded. Please provide a file.")

    """
    Ingestion endpoint for PDF/Image lab reports.
    Uses MedGemma to extract it into a FHIR Bundle, then ingests.
    """
    try:
        file_bytes = await file.read()
        mime_type = file.content_type
        
        background_tasks.add_task(
            _process_and_ingest_bundle,
            patient_id=patient_id,
            file_bytes=file_bytes,
            mime_type=mime_type,
            effective_date_override=effective_date_override
        )
        
        return {
            "status": "processing",
            "message": "FHIR Bundle processing started.",
            "report_id": None
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to read uploaded file.")

@router.post("/Bundle", status_code=status.HTTP_202_ACCEPTED)
async def ingest_fhir_bundle_json(
    request: Request,
    background_tasks: BackgroundTasks
):
    """
    Ingestion endpoint for FHIR JSON Bundles or PDF/Image lab reports.
    """
    content_type = request.headers.get("content-type", "")
    
    patient_id = request.query_params.get("patient_id")
    effective_date_override = request.query_params.get("effective_date")
    
    if "multipart/form-data" in content_type:
        form = await request.form()
        if not patient_id:
            patient_id = form.get("patient_id")
        if not effective_date_override:
            effective_date_override = form.get("effective_date")
            
        if not patient_id:
            raise HTTPException(status_code=400, detail="patient_id is required either as a query parameter or form field.")
            
        file = None
        for key, value in form.multi_items():
            if hasattr(value, "filename") and getattr(value, "filename"):
                file = value
                break
                
        if not file:
            raise HTTPException(status_code=400, detail="No file uploaded. Please provide a file.")
            
        try:
            file_bytes = await file.read()
            mime_type = file.content_type
            
            background_tasks.add_task(
                _process_and_ingest_bundle,
                patient_id=patient_id,
                file_bytes=file_bytes,
                mime_type=mime_type,
                effective_date_override=effective_date_override
            )
            
            return {
                "status": "processing",
                "message": "FHIR Bundle processing started.",
                "report_id": None
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail="Failed to read uploaded file.")
    else:
        # Assume JSON
        try:
            bundle = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON provided.")
            
        if not patient_id:
            raise HTTPException(status_code=400, detail="patient_id query parameter is required.")

    if not bundle or bundle.get("resourceType") != "Bundle":
        raise HTTPException(status_code=400, detail="Invalid FHIR Bundle provided.")
        
    res = process_fhir_bundle_internal(patient_id, bundle, effective_date_override)
    if res.get("status") == "success" and not res.get("is_draft"):
        background_tasks.add_task(run_tripwire_evaluation, patient_id, trigger_type="labs")
    return res

async def _process_and_ingest_bundle(patient_id: str, file_bytes: bytes, mime_type: str, effective_date_override: str = None):
    try:
        bundle = await parse_lab_report_to_fhir(file_bytes, mime_type)
        if not bundle or bundle.get("resourceType") != "Bundle":
            print("Invalid FHIR Bundle generated in background.")
            return
            
        res = process_fhir_bundle_internal(patient_id, bundle, effective_date_override)
        if res.get("status") == "success" and not res.get("is_draft"):
            await run_tripwire_evaluation(patient_id, trigger_type="labs")
            
            # Dispatch push notification to the client
            token_res = supabase.table("device_tokens").select("fcm_token").eq("patient_id", patient_id).execute()
            if token_res.data and token_res.data[0].get("fcm_token"):
                fcm_token = token_res.data[0]["fcm_token"]
                dispatch_notification(fcm_token, NotificationType.LAB_REPORT_READY)
    except Exception as e:
        print(f"Background extraction failed: {e}")

def process_fhir_bundle_internal(patient_id: str, bundle: dict, effective_date_override: str = None):
        
    # Process the Bundle and insert into Supabase
    diagnostic_report = None
    observations = []
    
    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})
        resource_type = resource.get("resourceType")
        
        # If it has a valueQuantity, it's a biomarker (Observation), even if MedGemma mislabeled it
        if resource_type == "Observation" or "valueQuantity" in resource:
            # Force the correct type
            resource["resourceType"] = "Observation"
            observations.append(resource)
        elif resource_type == "DiagnosticReport":
            # Only keep the first one as the true report header to prevent overwrites
            if not diagnostic_report:
                diagnostic_report = resource
            
    if not diagnostic_report:
        # If MedGemma forgot to make a header, create a dummy one
        diagnostic_report = {
            "resourceType": "DiagnosticReport",
            "status": "final",
            "presentedForm": [{"title": "Lab Report"}]
        }
        
    effective_date = effective_date_override or diagnostic_report.get("effectiveDateTime")
    is_draft = False
    if not effective_date:
        is_draft = True
        
    # Inject the date into the resource so frontend can read it!
    if effective_date:
        diagnostic_report["effectiveDateTime"] = effective_date
        
    # Insert DiagnosticReport
    try:
        report_status = "draft" if is_draft else diagnostic_report.get("status", "final")
        report_data = {
            "patient_id": patient_id,
            "status": report_status,
            "effective_datetime": effective_date if not is_draft else None,
            "performer": diagnostic_report.get("performer", [{"display": "Unknown"}])[0].get("display"),
            "resource": diagnostic_report,
            "summary_explanation": diagnostic_report.get("presentedForm", [{"title": ""}])[0].get("title", "")
        }
        
        report_res = supabase.table("fhir_diagnostic_reports").insert(report_data).execute()
        if not report_res.data:
            raise Exception("Failed to insert DiagnosticReport")
            
        report_id = report_res.data[0]["id"]
        
        # Insert Observations
        obs_inserts = []
        for obs in observations:
            # SKIP INVALID OBSERVATIONS (e.g. Gemini hallucinated an empty object)
            if not obs.get("code", {}).get("text"):
                continue
                
            val_quantity = obs.get("valueQuantity", {})
            value_numeric = val_quantity.get("value")
            if value_numeric is not None and value_numeric <= -99990:
                value_numeric = None
                
            value_string = obs.get("valueString")
            
            if value_numeric is None and not value_string:
                continue

            # Extract LOINC Code
            loinc = None
            for coding in obs.get("code", {}).get("coding", []):
                if coding.get("system") == "http://loinc.org":
                    loinc = coding.get("code")
                    break
                    
            if not loinc:
                # Fallback if AI missed it
                raw_text = obs.get("code", {}).get("text")
                if raw_text:
                    loinc = f"UNKNOWN_{raw_text.upper().replace(' ', '_')}"
                else:
                    loinc = obs.get("code", {}).get("coding", [{}])[0].get("code", "UNKNOWN")
                
            ref_range = obs.get("referenceRange", [{}])[0] if obs.get("referenceRange") else {}
            
            ref_low = ref_range.get("low", {}).get("value")
            if ref_low is not None and ref_low <= -99990:
                ref_low = None
                
            ref_high = ref_range.get("high", {}).get("value")
            if ref_high is not None and ref_high <= -99990:
                ref_high = None
                
            obs_inserts.append({
                "patient_id": patient_id,
                "report_id": report_id,
                "loinc_code": loinc,
                "value_numeric": value_numeric,
                "value_string": value_string,
                "unit": val_quantity.get("unit"),
                "reference_low": ref_low,
                "reference_high": ref_high,
                "resource": obs,
                "patient_explanation": obs.get("presentedForm", [{"title": ""}])[0].get("title", "")
            })
            
        if obs_inserts:
            supabase.table("fhir_observations").insert(obs_inserts).execute()
            
        if is_draft:
            try:
                nudge_record = {
                    "patient_id": patient_id,
                    "risk_level": "HIGH",
                    "nudge_title": "Lab Report Needs Date",
                    "nudge_text": "We analyzed your lab report, but the date was smudged or missing.",
                    "why_flagged": {
                        "summary": "Date required to analyze trends accurately.",
                        "conclusion": "We need the date to place this report in your timeline.",
                        "vitals": []
                    },
                    "action_steps": {
                        "title": "Set Sample Date",
                        "title_emphasis": "Action Required",
                        "description": "Please tap here to set the sample collection date.",
                        "intent_key": "ADD_DATE_TO_LAB"
                    },
                    "source": "system_upload"
                }
                supabase.table("nudge_alerts").insert(nudge_record).execute()
            except Exception as e:
                print(f"Failed to insert nudge: {e}")
            
        return {
            "status": "success",
            "message": "FHIR Bundle successfully ingested.",
            "report_id": report_id,
            "observations_count": len(obs_inserts),
            "is_draft": is_draft
        }
        
    except Exception as e:
        print(f"DB Insertion failed: {e}")
        raise HTTPException(status_code=500, detail=f"Database insertion failed: {e}")

@router.patch("/Bundle/{report_id}/date", status_code=status.HTTP_200_OK)
async def update_report_date(report_id: str, request: Request, background_tasks: BackgroundTasks):
    body = await request.json()
    effective_date = body.get("effective_date")
    if not effective_date:
        raise HTTPException(status_code=400, detail="effective_date is required")
        
    try:
        res = supabase.table("fhir_diagnostic_reports").update({
            "effective_datetime": effective_date,
            "status": "final"
        }).eq("id", report_id).execute()
        
        if not res.data:
            raise HTTPException(status_code=404, detail="Report not found")
            
        patient_id = res.data[0].get("patient_id")
        if patient_id:
            background_tasks.add_task(run_tripwire_evaluation, patient_id, trigger_type="labs")
            
        return {"status": "success", "message": "Date updated successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
