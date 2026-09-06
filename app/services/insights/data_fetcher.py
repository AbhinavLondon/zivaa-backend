import os
from datetime import datetime, timedelta, timezone
from supabase import create_client, Client

from app.config import settings
from app.utils.crypto import decrypt_text
from app.services.insights.context import (
    EvalContext, VitalsContext, LabContext, MedContext, MetricValue
)
from app.services.insights.baseline import get_or_refresh_baselines

# Initialize Supabase client with service role for backend processing
supabase: Client = create_client(
    settings.SUPABASE_URL,
    settings.SUPABASE_SERVICE_ROLE_KEY
)

_VALIDITY_WINDOWS_CACHE = None

def get_validity_windows():
    global _VALIDITY_WINDOWS_CACHE
    if _VALIDITY_WINDOWS_CACHE is None:
        try:
            resp = supabase.table("lab_validity_windows").select("loinc_code, validity_days").execute()
            _VALIDITY_WINDOWS_CACHE = {r["loinc_code"]: r["validity_days"] for r in resp.data}
        except Exception as e:
            print(f"Failed to load validity windows: {e}")
            _VALIDITY_WINDOWS_CACHE = {}
    return _VALIDITY_WINDOWS_CACHE

def fetch_patient_context(patient_id: str) -> EvalContext:
    """
    Fetches raw data from Supabase and transforms it into the structured 
    EvalContext required by the Insight Rules Engine.
    """
    
    # 1. Fetch Vitals (last 60 days)
    sixty_days_ago = (datetime.now() - timedelta(days=60)).date().isoformat()
    vitals_resp = supabase.table("vitals_daily") \
        .select("*") \
        .eq("patient_id", patient_id) \
        .gte("date", sixty_days_ago) \
        .order("date") \
        .execute()
        
    vitals_dict = {}
    for row in vitals_resp.data:
        date_obj = datetime.strptime(row["date"][:10], "%Y-%m-%d").date()
        
        hrr_raw = row.get("heart_rate_recovery_calculated")
        hrr_max = None
        if hrr_raw and isinstance(hrr_raw, list) and len(hrr_raw) > 0:
            try:
                bpm_values = [int(item.get("bpm", 0)) for item in hrr_raw if isinstance(item, dict) and "bpm" in item]
                if bpm_values:
                    hrr_max = max(bpm_values)
            except (ValueError, TypeError):
                pass

        # Map Supabase columns to internal metrics
        metrics_mapping = {
            "bp_systolic": row.get("bp_systolic"),
            "bp_diastolic": row.get("bp_diastolic"),
            "avg_heart_rate": row.get("avg_heart_rate"),
            "hr_avg_morning": row.get("hr_avg_morning"),
            "hr_avg_afternoon": row.get("hr_avg_afternoon"),
            "hr_avg_evening": row.get("hr_avg_evening"),
            "hr_avg_night": row.get("hr_avg_night"),
            "steps": row.get("total_steps"),
            "sleep_hours": row.get("sleep_hours"),
            #"sleep_quality": row.get("sleep_quality_score"),
            #"sleep_efficiency": row.get("sleep_efficiency"),  # Wearable-derived (%)
            "blood_glucose": row.get("blood_glucose_avg"),
            "oxygen_sat": row.get("oxygen_sat_avg"),
            "body_temp": row.get("body_temp_avg"),
            "skin_temp_delta": row.get("skin_temperature_delta"),
            "weight": row.get("weight_kg"),
            "mood_score": row.get("mood_score"),
            "phq2_score": row.get("phq2_score"),       # PHQ-2 (0-6, biweekly)
            "psqi_item6": row.get("psqi_item6"),        # PSQI Item 6 (0-3, weekly)
            # New metrics from Health Connect (Build Now — Jun 2026)
            "respiratory_rate": row.get("respiratory_rate_avg"),   # breaths/min (wearable-derived, sleep)
            "resting_heart_rate": row.get("resting_heart_rate_calculated"),  # bpm (min sustained HR)
            #"sleep_max_heart_rate": row.get("sleep_max_heart_rate"), # bpm (max HR during sleep session)
            "exercise_minutes": row.get("exercise_minutes"),  # total exercise duration
            "avg_speed": row.get("avg_speed"), # m/s walking speed
            "heart_rate_recovery": hrr_max, # max HRR bpm from json array
            "sleep_stage_1_hours": row.get("sleep_stage_1_hours"),
            "sleep_stage_2_hours": row.get("sleep_stage_2_hours"),
            "sleep_stage_3_hours": row.get("sleep_stage_3_hours"),
            "sleep_stage_4_hours": row.get("sleep_stage_4_hours"),
            "sleep_stage_5_hours": row.get("sleep_stage_5_hours"),
            "sleep_stage_6_hours": row.get("sleep_stage_6_hours"),
            "sleep_stage_1_pct": row.get("sleep_stage_1_pct"),
            "sleep_stage_2_pct": row.get("sleep_stage_2_pct"),
            "sleep_stage_3_pct": row.get("sleep_stage_3_pct"),
            "sleep_stage_4_pct": row.get("sleep_stage_4_pct"),
            "sleep_stage_5_pct": row.get("sleep_stage_5_pct"),
            "sleep_stage_6_pct": row.get("sleep_stage_6_pct"),
            # Phone Sensor Metrics
            "cough_count_night": row.get("cough_count_night"),
            "snoring_events_count": row.get("snoring_events_count"),
            "sit_to_stand_seconds": row.get("sit_to_stand_seconds"),
            # Advanced Sleep Metrics
            "sleep_efficiency_pct": row.get("sleep_efficiency_pct"),
            "awakenings_count_greater_than_5mins": row.get("awakenings_count_greater_than_5mins"),
            "sleep_latency_mins": row.get("sleep_latency_mins"),
            "waso_mins": row.get("waso_mins"),
            #"awakenings_count": row.get("awakenings_count"),
        }
        
        for metric_name, value in metrics_mapping.items():
            if value is not None:
                if metric_name not in vitals_dict:
                    vitals_dict[metric_name] = []
                vitals_dict[metric_name].append(MetricValue(float(value), date_obj))
                
    # 1b. Compute / refresh baselines for this patient
    try:
        baseline_status = get_or_refresh_baselines(patient_id, vitals_dict)
        baselines_dict = baseline_status.baselines
    except Exception as e:
        print(f"Warning: Baseline computation failed for {patient_id}: {e}")
        baseline_status = None
        baselines_dict = {}
    
    vitals_ctx = VitalsContext(vitals_dict, baselines=baselines_dict)
    
    # 2. Fetch Labs from FHIR tables
    labs_resp = supabase.table("fhir_observations") \
        .select("loinc_code, value_numeric, reference_low, reference_high, fhir_diagnostic_reports(effective_datetime)") \
        .eq("patient_id", patient_id) \
        .execute()
        
    labs_dict = {}
    for row in labs_resp.data:
        code = row.get("loinc_code")
        
        # Extract effective_datetime from the joined fhir_diagnostic_reports
        diag_reports = row.get("fhir_diagnostic_reports")
        effective_dt = None
        if isinstance(diag_reports, dict):
            effective_dt = diag_reports.get("effective_datetime")
            
        if code and effective_dt:
            if code not in labs_dict:
                labs_dict[code] = []
            labs_dict[code].append({
                "value": row.get("value_numeric"),
                "measured_at": effective_dt,
                "reference_low": row.get("reference_low"),
                "reference_high": row.get("reference_high"),
                "flag": "normal"
            })
            
    # Sort each lab's array by measured_at (since we removed order("created_at") from the joined query)
    for code in labs_dict:
        labs_dict[code].sort(key=lambda x: x["measured_at"])

    # 2b. Compute RCV-based lab trends (EFLM Biological Variation Database)
    #     This provides per-biomarker trend_direction, clinical_flag, and
    #     rate_alert data that Tier 3 rules use for evidence-based reasoning.
    #     Falls back gracefully to empty trends on failure.
    lab_trends = {}
    try:
        from app.services.lab_history import get_patient_lab_trends
        trends_result = get_patient_lab_trends(patient_id)
        lab_trends = trends_result.get("trend_summary", {})
    except Exception as e:
        print(f"Warning: Lab trend computation failed for {patient_id}: {e}")
        lab_trends = {}

    validity_windows = get_validity_windows()
    labs_ctx = LabContext(labs_dict, trend_data=lab_trends, validity_windows=validity_windows)
    
    # 3. Fetch Medication Adherence (last 7 days)
    seven_days_ago = (datetime.now() - timedelta(days=7)).isoformat()
    meds_resp = supabase.table("medication_logs") \
        .select("*") \
        .eq("patient_id", patient_id) \
        .gte("scheduled_at", seven_days_ago) \
        .execute()
        
    total_logs = len(meds_resp.data)
    if total_logs > 0:
        taken = sum(1 for m in meds_resp.data if m.get("status") == "taken")
        missed = sum(1 for m in meds_resp.data if m.get("status") in ("missed", "skipped"))
        adherence = taken / total_logs
    else:
        adherence = None
        missed = 0
        
    meds_ctx = MedContext(adherence_rate=adherence, recent_misses=missed)
    
    # 4. Fetch patient demographics (gender, age)
    #    Actual patients table columns: id, full_name, date_of_birth, gender,
    #    blood_group, emergency_contact, location_city, timezone
    patient_sex = None
    patient_age = None
    patient_location = None
    patient_blood_group = None
    patient_timezone = None
    patient_conditions = []
    try:
        patient_resp = supabase.table("patients") \
            .select("gender, date_of_birth, location_city, blood_group, timezone") \
            .eq("id", patient_id) \
            .single() \
            .execute()
        
        if patient_resp.data:
            # Map "gender" column to our internal "sex" field
            gender = patient_resp.data.get("gender")
            if gender:
                patient_sex = gender.lower()  # normalize to "male" | "female"
            dob = patient_resp.data.get("date_of_birth")
            if dob:
                from datetime import date as date_type
                try:
                    birth = datetime.strptime(dob, "%Y-%m-%d").date() if isinstance(dob, str) else dob
                except ValueError:
                    try:
                        birth = datetime.strptime(dob, "%d-%m-%Y").date() if isinstance(dob, str) else dob
                    except ValueError:
                        birth = None
                if birth:
                    patient_age = (datetime.now().date() - birth).days // 365
            patient_location = patient_resp.data.get("location_city")
            patient_blood_group = patient_resp.data.get("blood_group")
            patient_timezone = patient_resp.data.get("timezone")
            # Note: no "conditions" column exists yet in the patients table.
            # When added, uncomment and adapt:
            # conditions_raw = patient_resp.data.get("conditions")
    except Exception as e:
        print(f"Warning: Could not fetch patient demographics for {patient_id}: {e}")
    
    # 5. Fetch existing active insights for stateful resolution/deduplication
    active_insights = []
    try:
        insights_resp = supabase.table("active_clinical_insights") \
            .select("*") \
            .eq("patient_id", patient_id) \
            .eq("status", "active") \
            .execute()
        if insights_resp.data:
            active_insights = insights_resp.data
    except Exception as e:
        print(f"Warning: Could not fetch active insights for {patient_id}: {e}")
    
    # 5b. Fetch explicit device status (if provided by client)
    device_battery_level = None
    device_is_charging = None
    try:
        dev_resp = supabase.table("vitals_raw") \
            .select("values") \
            .eq("patient_id", patient_id) \
            .eq("metric_type", "device_status") \
            .order("recorded_at", desc=True) \
            .limit(1) \
            .execute()
        
        if dev_resp.data and "values" in dev_resp.data[0]:
            vals = dev_resp.data[0]["values"]
            device_battery_level = vals.get("battery_level")
            device_is_charging = vals.get("is_charging")
    except Exception as e:
        print(f"Warning: Could not fetch device status for {patient_id}: {e}")
    
    # 6. Fetch patient plan setup preferences
    setup_prefs = {}
    try:
        setup_resp = supabase.table("patient_plan_setup") \
            .select("*") \
            .eq("patient_id", patient_id) \
            .order("created_at", desc=True) \
            .limit(1) \
            .execute()
        if setup_resp.data:
            fields = [
                "primary_focus", "wake_time", "movement_level", "steps_goal", 
                "diet_type", "height_inches", "weight_kg", "goal_weight_kg", 
                "health_conditions", "evening_activities", "reminders",
                "target_calories_user_generated", "protein_g_user_generated", 
                "carbs_g_user_generated", "fat_g_user_generated", "diet_preference"
            ]
            row = setup_resp.data[0]
            for field in fields:
                val = row.get(field)
                if val is not None:
                    if isinstance(val, list) and not val:
                        continue
                    if isinstance(val, str) and not val.strip():
                        continue
                    setup_prefs[field] = val
    except Exception as e:
        print(f"Warning: Could not fetch patient plan setup for {patient_id}: {e}")
        
    # 7. Fetch Domain-Driven Care Model tables
    preferences = []
    symptoms = []
    agreed_actions = []
    suggested_actions = []
    active_medications = []
    try:
        pref_resp = supabase.table("patient_preferences").select("*").eq("patient_id", patient_id).execute()
        if pref_resp.data: preferences = pref_resp.data

        sym_resp = supabase.table("patient_symptoms").select("*").eq("patient_id", patient_id).in_("status", ["Active", "Resolving"]).execute()
        if sym_resp.data:
            symptoms = sym_resp.data
            for s in symptoms:
                if s.get("name"):
                    try:
                        s["name"] = decrypt_text(s["name"])
                    except Exception:
                        pass

        act_resp = supabase.table("care_plan_actions").select("*").eq("patient_id", patient_id).execute()
        if act_resp.data:
            agreed_actions = [a for a in act_resp.data if a.get("status") == "Agreed"]
            suggested_actions = [a for a in act_resp.data if a.get("status") == "Suggested"]

        med_resp = supabase.table("patient_medications").select("*").eq("patient_id", patient_id).eq("status", "Active").execute()
        if med_resp.data:
            active_medications = med_resp.data
            for m in active_medications:
                if m.get("name"):
                    try:
                        m["name"] = decrypt_text(m["name"])
                    except Exception:
                        pass
                if m.get("dose"):
                    try:
                        m["dose"] = decrypt_text(m["dose"])
                    except Exception:
                        pass
    except Exception as e:
        print(f"Warning: Could not fetch care models for {patient_id}: {e}")
        
    # 8. Return combined Context (with baseline status + demographics + insights + device state + setup_prefs)
    return EvalContext(
        patient_id=patient_id,
        vitals=vitals_ctx,
        labs=labs_ctx,
        meds=meds_ctx,
        baseline_status=baseline_status,
        patient_sex=patient_sex,
        patient_age=patient_age,
        location_city=patient_location,
        blood_group=patient_blood_group,
        patient_timezone=patient_timezone,
        patient_conditions=patient_conditions,
        active_insights=active_insights,
        device_battery_level=device_battery_level,
        device_is_charging=device_is_charging,
        setup_prefs=setup_prefs,
        preferences=preferences,
        symptoms=symptoms,
        agreed_actions=agreed_actions,
        suggested_actions=suggested_actions,
        active_medications=active_medications,
    )
