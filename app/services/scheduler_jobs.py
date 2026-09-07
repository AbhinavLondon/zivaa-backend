import asyncio
from typing import List, Dict, Any
from app.services.insights.data_fetcher import supabase, fetch_patient_context
from app.services.medgemma_services import generate_medgemma_summary, generate_medgemma_plan
from app.services.llm_plan import build_plan_context


def is_target_local_hour(patient_tz: str, target_hour: int, target_day_of_week: int = None) -> bool:
    import zoneinfo
    from datetime import datetime, timezone
    try:
        tz = zoneinfo.ZoneInfo(patient_tz or "UTC")
    except Exception:
        tz = zoneinfo.ZoneInfo("UTC")
    local_now = datetime.now(timezone.utc).astimezone(tz)
    
    if target_day_of_week is not None and local_now.weekday() != target_day_of_week:
        return False
        
    return local_now.hour == target_hour and local_now.minute < 15


async def run_morning_generation_pipeline(patient_id: str):
    print(f"Running morning generation pipeline for {patient_id}...")
    from app.services.medgemma_services import generate_medgemma_summary, generate_medgemma_plan
    from app.services.llm_plan import build_plan_context
    from app.services.reinforcement import fetch_history_data, calculate_task_correlations, generate_reinforcement_message
    from app.services.firebase_service import send_push_notification
    from datetime import datetime, timezone
    
    try:
        # Get patient name
        res_patient = supabase.table("patients").select("full_name").eq("id", patient_id).execute()
        patient_name = "your loved one"
        if res_patient.data and "full_name" in res_patient.data[0]:
            patient_name = res_patient.data[0]["full_name"]

        # 1. Generate Morning Summary
        print("Calling generate_medgemma_summary...")
        summary_res = await generate_medgemma_summary(patient_id, patient_name)
        print("generate_medgemma_summary returned.")
        history_data = fetch_history_data(patient_id)
        correlations = calculate_task_correlations(history_data)
        print("Calling generate_reinforcement_message...")
        reinforcement = await generate_reinforcement_message(patient_id, history_data, correlations)
        print("generate_reinforcement_message returned.")
        
        summary_text = summary_res.get("summary", "")
        if reinforcement and reinforcement.get("message"):
            summary_text += f"\n\nPositive Insight: {reinforcement['message']}"
            
        payload_briefing = {
            "patient_id": patient_id,
            "summary": summary_text,
            "headline": summary_res.get("headline", "A bright, active day"),
        }
        supabase.table("daily_morning_briefings").insert(payload_briefing).execute()

        # 2. Generate Daily Plan
        plan_context = build_plan_context(patient_id)
        plan = await generate_medgemma_plan(plan_context)
        
        payload_plan = {
            "patient_id": patient_id,
            "summary": plan.get("summary", "Your plan for today"),
            "schedule": plan.get("schedule", {}),
            "health_context": plan.get("health_context", {}),
            "source": "gemini_llm",
            "date": datetime.now(timezone.utc).date().isoformat(),
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        
        # Upsert logic to avoid duplicates
        today_date_str = payload_plan["date"]
        existing_res = supabase.table("daily_plans").select("id").eq("patient_id", patient_id).eq("date", today_date_str).execute()
        if existing_res.data:
            plan_id = existing_res.data[0]["id"]
            supabase.table("daily_plans").update(payload_plan).eq("id", plan_id).execute()
        else:
            supabase.table("daily_plans").insert(payload_plan).execute()

        # 3. Send Push Notifications
        from app.services.notification_templates import dispatch_notification, NotificationType
        
        # Fetch FCM token for patient
        token_res = supabase.table("device_tokens").select("fcm_token").eq("patient_id", patient_id).execute()
        
        if token_res.data and token_res.data[0].get("fcm_token"):
            fcm_token = token_res.data[0]["fcm_token"]
            
            dispatch_notification(
                fcm_token=fcm_token,
                notification_type=NotificationType.MORNING_BRIEFING,
                patient_name=patient_name,
                dynamic_body=summary_text
            )
            
            dispatch_notification(
                fcm_token=fcm_token,
                notification_type=NotificationType.DAILY_PLAN,
                patient_name=patient_name
            )
        else:
            print(f"No FCM token found for {patient_id}. Skipping push notifications.")
            
        print(f"Morning generation pipeline for {patient_id} completed successfully.")

    except Exception as e:
        print(f"Failed morning generation pipeline for {patient_id}: {e}")

async def run_morning_fallback():
    print("Running morning fallback cron job...")
    from datetime import datetime, timezone
    import zoneinfo
    
    res = supabase.table("patients").select("id, timezone").execute()
    if not res.data:
        return
        
    for p in res.data:
        if not is_target_local_hour(p.get("timezone"), 9):
            continue
            
        patient_id = p["id"]
        
        # Calculate local today_start
        now = datetime.now(timezone.utc)
        try:
            tz = zoneinfo.ZoneInfo(p.get("timezone") or "UTC")
        except Exception:
            tz = zoneinfo.ZoneInfo("UTC")
            
        local_now = now.astimezone(tz)
        local_today_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_start_utc = local_today_start.astimezone(timezone.utc).isoformat()
        
        # Check if morning briefing exists for today
        res_briefing = supabase.table("daily_morning_briefings").select("id").eq("patient_id", patient_id).gte("created_at", today_start_utc).limit(1).execute()
        
        # Check if MedGemma daily plan exists for today
        res_plan = supabase.table("daily_plans").select("id").eq("patient_id", patient_id).gte("created_at", today_start_utc).limit(1).execute()
        
        if not res_briefing.data or not res_plan.data:
            print(f"Fallback triggered for {patient_id}. Missing morning briefing or daily plan.")
            await run_morning_generation_pipeline(patient_id)

async def _build_checkin_context(patient_id: str):
    from datetime import datetime, timezone
    import zoneinfo
    
    ctx = fetch_patient_context(patient_id)
    
    # Calculate patient local date and today_start_utc
    now = datetime.now(timezone.utc)
    patient_tz_str = ctx.patient_timezone or "UTC"
    try:
        tz = zoneinfo.ZoneInfo(patient_tz_str)
    except Exception:
        tz = zoneinfo.ZoneInfo("UTC")
        
    local_now = now.astimezone(tz)
    local_today = local_now.date()
    local_today_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_start_utc = local_today_start.astimezone(timezone.utc).isoformat()
    today_date = local_today
    
    # 1. Vitals
    today_vitals = []
    vitals_dict = ctx.vitals._vitals
    for name, vals in vitals_dict.items():
        if vals:
            y_vals = [v for v in vals if (str(v.date).startswith(str(today_date)) if isinstance(v.date, str) else v.date == today_date)]
            if y_vals:
                today_vitals.append(f"- {name}: {y_vals[-1].value}")
    vitals_bullet = "\n".join(today_vitals) if today_vitals else "No vitals logged today yet."
    
    # 2. Mood
    mood_text = "No mood logged."
    try:
        mood_res = supabase.table("patient_checkins").select("mood_label, emotions, causes, user_comments").eq("patient_id", patient_id).gte("created_at", today_start_utc).order("created_at", desc=True).limit(1).execute()
        if mood_res.data:
            latest_mood = mood_res.data[0]
            m_label = latest_mood.get("mood_label")
            m_emotions = latest_mood.get("emotions")
            m_causes = latest_mood.get("causes")
            m_comments = latest_mood.get("user_comments")
            
            parts = []
            if m_label: parts.append(f"Mood: {m_label}")
            if m_emotions:
                emotions_str = ", ".join(m_emotions) if isinstance(m_emotions, list) else m_emotions
                parts.append(f"Emotions: {emotions_str}")
            if m_causes:
                causes_str = ", ".join(m_causes) if isinstance(m_causes, list) else m_causes
                parts.append(f"Causes: {causes_str}")
            if m_comments: parts.append(f"Comments: {m_comments}")
            
            if parts:
                mood_text = " | ".join(parts)
    except Exception as e:
        print(f"Failed to fetch mood for {patient_id}: {e}")
    
    # 3. Adherence
    adherence_text = "No tasks planned."
    try:
        plan_res = supabase.table("daily_plans").select("schedule").eq("patient_id", patient_id).eq("date", today_date.isoformat()).order("created_at", desc=True).limit(1).execute()
        if plan_res.data and plan_res.data[0].get("schedule"):
            sched = plan_res.data[0]["schedule"]
            completed = []
            pending = []
            for period, tasks in sched.items():
                if isinstance(tasks, list):
                    for t in tasks:
                        if t.get("completed"):
                            completed.append(t.get("task"))
                        else:
                            pending.append(t.get("task"))
            adherence_text = f"Completed tasks: {', '.join(completed) if completed else 'None'}. Pending tasks: {', '.join(pending) if pending else 'None'}."
    except Exception as e:
        print(f"Failed to fetch plan for {patient_id}: {e}")
        
    # 4. Nutrition (Logged meals today vs Plan targets)
    nutrition_text = "No meals logged yet today."
    try:
        from app.services.insights.nutrition_analyzer import get_patient_macro_targets
        targets = get_patient_macro_targets(patient_id)
        
        meals_res = supabase.table("patient_meals") \
            .select("food_name, meal_type, calories, protein_g, carbs_g, fat_g, fiber_g, sodium_mg") \
            .eq("patient_id", patient_id) \
            .gte("logged_at", today_start_utc) \
            .order("logged_at") \
            .execute()
            
        meals = meals_res.data or []
        if meals:
            tot_cal = sum(m.get("calories") or 0 for m in meals)
            tot_prot = sum(m.get("protein_g") or 0 for m in meals)
            tot_carbs = sum(m.get("carbs_g") or 0 for m in meals)
            tot_fat = sum(m.get("fat_g") or 0 for m in meals)
            tot_fiber = sum(m.get("fiber_g") or 0 for m in meals)
            tot_sodium = sum(m.get("sodium_mg") or 0 for m in meals)
            
            meal_items = [f"{m.get('food_name', 'Meal')} ({m.get('meal_type', 'Meal').capitalize()})" for m in meals]
            
            cal_pct = int(round((tot_cal / targets['calories_max']) * 100)) if targets.get('calories_max') else 0
            prot_pct = int(round((tot_prot / targets['protein_min']) * 100)) if targets.get('protein_min') else 0
            carbs_pct = int(round((tot_carbs / targets['carbs_max']) * 100)) if targets.get('carbs_max') else 0
            fat_pct = int(round((tot_fat / targets['fat_max']) * 100)) if targets.get('fat_max') else 0
            fiber_pct = int(round((tot_fiber / targets['fiber_min']) * 100)) if targets.get('fiber_min') else 0
            sodium_pct = int(round((tot_sodium / targets['sodium_max']) * 100)) if targets.get('sodium_max') else 0
            
            nutrition_lines = [
                f"- Meals Logged Today: {', '.join(meal_items)}",
                f"- Nutrition Consumed vs Daily Plan Targets:",
                f"  • Calories: {tot_cal} / {targets['calories_max']} kcal ({cal_pct}% of daily target)",
                f"  • Protein: {tot_prot} / {targets['protein_min']}g ({prot_pct}% of daily target)",
                f"  • Carbs: {tot_carbs} / {targets['carbs_max']}g ({carbs_pct}% of daily target)",
                f"  • Fat: {tot_fat} / {targets['fat_max']}g ({fat_pct}% of daily target)",
                f"  • Fiber: {tot_fiber} / {targets['fiber_min']}g ({fiber_pct}% of daily target)",
                f"  • Sodium: {tot_sodium} / {targets['sodium_max']}mg ({sodium_pct}% of daily limit)"
            ]
            
            # Check for active clinical nutritional insights
            gap_res = supabase.table("active_nutritional_insights") \
                .select("insight_name, context_data") \
                .eq("patient_id", patient_id) \
                .eq("status", "active") \
                .limit(1) \
                .execute()
            if gap_res.data:
                g = gap_res.data[0]
                nutrition_lines.append(f"- Active Clinical Focus: {g.get('insight_name')} ({g.get('context_data')})")
                
            nutrition_text = "\n".join(nutrition_lines)
        else:
            nutrition_text = f"No meals logged yet today. (Daily Plan Targets: {targets['calories_max']} kcal, {targets['protein_min']}g protein, {targets['fiber_min']}g fiber, {targets['sodium_max']}mg sodium limit)."
    except Exception as e:
        print(f"Failed to compile nutrition context for {patient_id}: {e}")
        
    return vitals_bullet, mood_text, adherence_text, nutrition_text, ctx.patient_conditions, ctx.patient_age, ctx.patient_sex, ctx.setup_prefs, ctx.preferences, ctx.symptoms

async def run_midday_checkins():
    print("Running mid-day checkins...")
    from app.services.medgemma_services import generate_midday_checkin
    from datetime import datetime, timezone
    
    res = supabase.table("patients").select("id, full_name, timezone").execute()
    if not res.data:
        return
        
    for p in res.data:
        if not is_target_local_hour(p.get("timezone"), 12):
            continue
        patient_id = p["id"]
        patient_name = p.get("full_name", "Patient")
        
        try:
            vitals_bullet, mood_text, adherence_text, nutrition_text, patient_conditions, patient_age, patient_sex, setup_prefs, preferences, symptoms = await _build_checkin_context(patient_id)
            message = await generate_midday_checkin(
                patient_id, 
                patient_name, 
                adherence_text, 
                vitals_bullet, 
                mood_text, 
                patient_conditions, 
                patient_age, 
                patient_sex, 
                setup_prefs, 
                preferences, 
                symptoms,
                nutrition_text=nutrition_text
            )
            
            payload = {
                "patient_id": patient_id,
                "insight_date": datetime.now(timezone.utc).date().isoformat(),
                "insight_type": "MIDDAY_CHECKIN",
                "insight_text": message
            }
            existing_res = supabase.table("user_insights").select("id").eq("patient_id", patient_id).eq("insight_date", payload["insight_date"]).eq("insight_type", "MIDDAY_CHECKIN").execute()
            if existing_res.data:
                supabase.table("user_insights").update({"insight_text": message}).eq("id", existing_res.data[0]["id"]).execute()
            else:
                supabase.table("user_insights").insert(payload).execute()
            
            from app.services.notification_templates import dispatch_notification, NotificationType
            token_res = supabase.table("device_tokens").select("fcm_token").eq("patient_id", patient_id).execute()
            if token_res.data and token_res.data[0].get("fcm_token"):
                fcm_token = token_res.data[0]["fcm_token"]
                dispatch_notification(
                    fcm_token=fcm_token,
                    notification_type=NotificationType.MIDDAY_CHECKIN,
                    dynamic_body=message
                )
        except Exception as e:
            print(f"Failed to generate mid-day checkin for {patient_id}: {e}")

async def run_evening_checkins():
    print("Running evening checkins...")
    from app.services.medgemma_services import generate_evening_wind_down
    from datetime import datetime, timezone
    
    res = supabase.table("patients").select("id, full_name, timezone").execute()
    if not res.data:
        return
        
    for p in res.data:
        if not is_target_local_hour(p.get("timezone"), 20):
            continue
        patient_id = p["id"]
        patient_name = p.get("full_name", "Patient")
        
        try:
            vitals_bullet, mood_text, adherence_text, nutrition_text, patient_conditions, patient_age, patient_sex, setup_prefs, preferences, symptoms = await _build_checkin_context(patient_id)
            message = await generate_evening_wind_down(
                patient_id, 
                patient_name, 
                adherence_text, 
                vitals_bullet, 
                mood_text, 
                patient_conditions, 
                patient_age, 
                patient_sex, 
                setup_prefs, 
                preferences, 
                symptoms,
                nutrition_text=nutrition_text
            )
            
            payload = {
                "patient_id": patient_id,
                "insight_date": datetime.now(timezone.utc).date().isoformat(),
                "insight_type": "EVENING_CHECKIN",
                "insight_text": message
            }
            existing_res = supabase.table("user_insights").select("id").eq("patient_id", patient_id).eq("insight_date", payload["insight_date"]).eq("insight_type", "EVENING_CHECKIN").execute()
            if existing_res.data:
                supabase.table("user_insights").update({"insight_text": message}).eq("id", existing_res.data[0]["id"]).execute()
            else:
                supabase.table("user_insights").insert(payload).execute()
            
            from app.services.notification_templates import dispatch_notification, NotificationType
            token_res = supabase.table("device_tokens").select("fcm_token").eq("patient_id", patient_id).execute()
            if token_res.data and token_res.data[0].get("fcm_token"):
                fcm_token = token_res.data[0]["fcm_token"]
                dispatch_notification(
                    fcm_token=fcm_token,
                    notification_type=NotificationType.EVENING_CHECKIN,
                    dynamic_body=message
                )
        except Exception as e:
            print(f"Failed to generate evening checkin for {patient_id}: {e}")

from app.services.medgemma_services import generate_medgemma_nudge
from datetime import datetime, timedelta

async def run_weekly_retest_digest():
    print("Running weekly re-test digest...")
    from app.services.medgemma_services import generate_retest_nudge
    res = supabase.table("patients").select("id, full_name, timezone").execute()
    if not res.data:
        return
        
    for p in res.data:
        # Target: Saturday (5), 10 AM
        if not is_target_local_hour(p.get("timezone"), 10, target_day_of_week=5):
            continue
        patient_id = p["id"]
        patient_name = p.get("full_name", "Patient")
        
        try:
            # Fetch historical insights (overdue labs)
            alert_res = supabase.table("active_clinical_insights").select("*").eq("patient_id", patient_id).eq("status", "historical").execute()
            alerts = alert_res.data if alert_res.data else []
            
            if alerts:
                nudge_data = await generate_retest_nudge(patient_id, patient_name, alerts)
                if nudge_data:
                    supabase.table("nudge_alerts").insert({
                        "patient_id": patient_id,
                        "nudge_type": "CLINICAL",
                        "title": nudge_data.get("nudge_title", "Lab Re-test"),
                        "message": nudge_data.get("nudge_text", "Time to schedule a lab test."),
                        "is_read": False,
                        "created_at": datetime.utcnow().isoformat()
                    }).execute()
                    
                    from app.services.firebase_service import send_push_notification
                    await send_push_notification(patient_id, nudge_data.get("nudge_title", "Lab Re-test"), nudge_data.get("nudge_text", "Time to schedule a lab test."))
        except Exception as e:
            print(f"Failed to generate retest digest for {patient_id}: {e}")

async def run_weekly_caregiver_digest():
    print("Running weekly caregiver digest...")
    res = supabase.table("patients").select("id, full_name, timezone").execute()
    if not res.data:
        return
        
    last_week = (datetime.utcnow() - timedelta(days=7)).isoformat()
    
    for p in res.data:
        # Target: Sunday (6), 10 AM
        if not is_target_local_hour(p.get("timezone"), 10, target_day_of_week=6):
            continue
        patient_id = p["id"]
        patient_name = p.get("full_name", "Patient")
        
        try:
            # Fetch insights from the past week
            alert_res = supabase.table("active_clinical_insights").select("*").eq("patient_id", patient_id).eq("status", "active").gte("created_at", last_week).execute()
            alerts = alert_res.data if alert_res.data else []
            
            if alerts:
                nudge_res = await generate_medgemma_nudge(alerts, patient_name, is_weekly_digest=True, patient_id=patient_id)
                print(f"Weekly digest for {patient_id}: {nudge_res}")
                # In a real app, this would be pushed via FCM or email to the caregiver
            else:
                print(f"No insights for {patient_name} this week. Skipping digest.")
        except Exception as e:
            print(f"Failed to generate weekly digest for {patient_id}: {e}")

async def run_weekly_patient_reinforcement():
    print("Running weekly patient positive reinforcement digest...")
    from app.services.reinforcement import fetch_history_data, calculate_task_correlations, generate_reinforcement_message
    res = supabase.table("patients").select("id, full_name, timezone").execute()
    if not res.data:
        return
        
    for p in res.data:
        # Target: Sunday (6), 10 AM
        if not is_target_local_hour(p.get("timezone"), 10, target_day_of_week=6):
            continue
        patient_id = p["id"]
        patient_name = p.get("full_name", "Patient")
        
        try:
            history_data = fetch_history_data(patient_id, days=14)
            correlations = calculate_task_correlations(history_data)
            reinforcement = await generate_reinforcement_message(patient_id, history_data, correlations)
            if reinforcement:
                print(f"Weekly Win for {patient_name}: {reinforcement.get('message')}")
        except Exception as e:
            print(f"Failed to generate weekly reinforcement for {patient_id}: {e}")

async def run_batch_pattern_detection():
    print("Running batch pattern detection (nightly)...")
    res = supabase.table("patients").select("id, timezone").execute()
    if not res.data:
        return
        
    from app.services.tripwire import run_tripwire_evaluation
    for p in res.data:
        if not is_target_local_hour(p.get("timezone"), 23):
            continue
        patient_id = p["id"]
        try:
            # Run tripwire in batch mode, but DO NOT send the nudge yet.
            await run_tripwire_evaluation(patient_id, trigger_type="vitals", evaluation_mode="batch", send_nudge=False)
        except Exception as e:
            print(f"Failed to run batch pattern detection for {patient_id}: {e}")

async def run_morning_nudge_dispatch():
    print("Running morning nudge dispatch for newly detected patterns...")
    from app.services.medgemma_services import generate_medgemma_nudge
    from datetime import datetime, timezone, timedelta
    
    # We look for active insights created or updated in the last 12 hours
    twelve_hours_ago = (datetime.now(timezone.utc) - timedelta(hours=12)).isoformat()
    
    res = supabase.table("patients").select("id, full_name, caregiver_nudge_preference, timezone").execute()
    if not res.data:
        return
        
    for p in res.data:
        if not is_target_local_hour(p.get("timezone"), 8):
            continue
        patient_id = p["id"]
        patient_name = p.get("full_name", "Patient")
        nudge_pref = p.get("caregiver_nudge_preference", "HIGH")
        
        try:
            # Fetch all active insights for this patient
            alert_res = supabase.table("active_clinical_insights") \
                .select("*") \
                .eq("patient_id", patient_id) \
                .eq("status", "active") \
                .execute()
                
            all_alerts = alert_res.data if alert_res.data else []
            if not all_alerts:
                continue
                
            # Filter in Python for ones created or updated recently
            alerts = []
            for a in all_alerts:
                c_at = a.get("created_at")
                u_at = a.get("updated_at")
                # If either created_at or updated_at is within the last 12 hours, include it
                if c_at and c_at >= twelve_hours_ago:
                    alerts.append(a)
                elif u_at and u_at >= twelve_hours_ago:
                    alerts.append(a)
                    
            if not alerts:
                continue
                
            # Filter by severity and preference
            highest_severity = "LOW"
            for alert in alerts:
                sev = alert.get("severity", "LOW").upper()
                if sev == "HIGH": highest_severity = "HIGH"
                elif sev == "MEDIUM" and highest_severity != "HIGH": highest_severity = "MEDIUM"
                
            should_nudge = False
            if nudge_pref == "ALL": should_nudge = True
            elif nudge_pref == "HIGH" and highest_severity == "HIGH": should_nudge = True
            elif nudge_pref == "MEDIUM" and highest_severity in ("HIGH", "MEDIUM"): should_nudge = True
            elif nudge_pref == "LOW": should_nudge = True
            
            if should_nudge:
                # Layer 4: Check if patient already received a nudge in the last 4 hours (e.g. from an early morning tripwire sync)
                four_hours_ago = (datetime.now(timezone.utc) - timedelta(hours=4)).isoformat()
                recent_check = supabase.table("nudge_alerts") \
                    .select("id, created_at, nudge_title") \
                    .eq("patient_id", patient_id) \
                    .gte("created_at", four_hours_ago) \
                    .limit(1) \
                    .execute()
                if recent_check.data:
                    print(f"Morning Nudge Dispatch: Patient {patient_name} already received a nudge within the last 4 hours ({recent_check.data[0].get('created_at')}). Skipping scheduled 8 AM nudge.")
                    continue

                print(f"Dispatching Morning Caregiver Nudge for {patient_name}...")
                nudge = await generate_medgemma_nudge(alerts, patient_name=patient_name, patient_id=patient_id)
                print("Morning Caregiver Nudge dispatched:", nudge.get("nudge_title"))
                
        except Exception as e:
            print(f"Failed to dispatch morning nudge for {patient_id}: {e}")

async def run_memory_extraction():
    print("Running memory extraction for inactive chat sessions...")
    from app.services.memory_summarizer import process_inactive_chat_sessions
    await process_inactive_chat_sessions()

async def run_proactive_followups():
    # Deprecated. Merged into run_symptom_checkins.
    pass

async def run_symptom_checkins():
    print("Running intelligent symptom checkins...")
    from app.services.notification_templates import dispatch_notification, NotificationType
    from app.utils.crypto import decrypt_text
    from datetime import datetime, timezone, timedelta
    
    res = supabase.table("patients").select("id").execute()
    if not res.data:
        return
        
    for p in res.data:
        patient_id = p["id"]
        
        try:
            # Query Logic: Active symptoms ordered by severity (Severe first)
            mem_res = supabase.table("patient_symptoms") \
                .select("*") \
                .eq("patient_id", patient_id) \
                .eq("status", "Active") \
                .order("severity", desc=True) \
                .execute()
                
            if not mem_res.data:
                continue
                
            for memory in mem_res.data:
                raw_name = memory.get('name')
                symptom_name = decrypt_text(raw_name) if raw_name else "a symptom"
                symptom_id = memory.get('id')
                cadence = memory.get('follow_up_cadence_days', 3)
                last_follow = memory.get('last_followed_up_at')
                created = memory.get('created_at')
                
                # Cadence logic
                base_time = datetime.fromisoformat(last_follow.replace('Z', '+00:00')) if last_follow else datetime.fromisoformat(created.replace('Z', '+00:00'))
                if (datetime.now(timezone.utc) - base_time).days < cadence:
                    continue # Not time yet
                    
                # Use LLM-driven proactive coach
                print(f"Triggering LLM check-in for symptom: {symptom_name} (Severity: {memory.get('severity')})")
                checkin_metadata = {
                    "type": "symptom_checkin",
                    "symptom_id": symptom_id,
                    "symptom_name": symptom_name,
                    "options": ["Better", "Same", "Worse", "Completely Gone"]
                }
                
                from app.services.proactive_coach import generate_proactive_message
                await generate_proactive_message(
                    patient_id=patient_id,
                    trigger_type="SYMPTOM_FOLLOWUP",
                    trigger_context=f"The patient previously reported experiencing {symptom_name} (Severity: {memory.get('severity')}). Ask them how their {symptom_name} is feeling today. Keep it short and natural, ending with a question.",
                    metadata=checkin_metadata
                )
                
                # Mark as followed up
                supabase.table("patient_symptoms").update({
                    "last_followed_up_at": datetime.now(timezone.utc).isoformat()
                }).eq("id", symptom_id).execute()
                
                break # Only dispatch one check-in per patient per run
                
        except Exception as e:
            print(f"Failed to run symptom checkins for {patient_id}: {e}")

async def run_weekly_planning():
    print("Running weekly planning...")
    from app.services.notification_templates import dispatch_notification, NotificationType
    
    # 1. Fetch all patients
    res = supabase.table("patients").select("id, full_name").execute()
    if not res.data:
        print("No patients found for weekly planning.")
        return
        
    for p in res.data:
        patient_id = p["id"]
        try:
            # Generate the weekly plan
            from app.services.weekly_planner import generate_weekly_plan
            success = await generate_weekly_plan(patient_id)
            
            if success:
                # Dispatch notification
                token_res = supabase.table("device_tokens").select("fcm_token").eq("patient_id", patient_id).execute()
                if token_res.data and token_res.data[0].get("fcm_token"):
                    dispatch_notification(
                        fcm_token=token_res.data[0]["fcm_token"],
                        notification_type=NotificationType.WEEKLY_PLAN_READY,
                        patient_name=p.get("full_name", "Patient")
                    )
        except Exception as e:
            print(f"Failed to generate weekly plan for {patient_id}: {e}")

async def run_weekly_longevity_strategy():
    print("Running weekly longevity strategy...")
    
    # 1. Fetch all patients
    res = supabase.table("patients").select("id, full_name").execute()
    if not res.data:
        print("No patients found for weekly longevity strategy.")
        return
        
    for p in res.data:
        patient_id = p["id"]
        try:
            # Generate the weekly longevity strategy
            from app.services.longevity_engine import generate_weekly_strategy
            await generate_weekly_strategy(patient_id)
            
            # (Optional) We can add a notification here later if desired:
            # NotificationType.LONGEVITY_STRATEGY_READY
            
        except Exception as e:
            print(f"Failed to generate weekly longevity strategy for {patient_id}: {e}")

async def run_nightly_nutritional_analysis():
    print("Running nightly nutritional analysis...")
    from app.services.insights.nutrition_analyzer import evaluate_and_save_nutritional_insights
    
    # 1. Fetch all patients
    res = supabase.table("patients").select("id").execute()
    if not res.data:
        print("No patients found for nutritional analysis.")
        return
        
    for p in res.data:
        patient_id = p["id"]
        try:
            await evaluate_and_save_nutritional_insights(patient_id)
        except Exception as e:
            print(f"Failed to run nutritional analysis for {patient_id}: {e}")

async def run_memory_consolidation():
    print("Running memory consolidation (nightly)...")
    from datetime import datetime, timezone
    import json
    import os
    import httpx
    
    # 1. Fetch all patients
    res = supabase.table("patients").select("id").execute()
    if not res.data:
        return
        
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    if not GEMINI_API_KEY:
        print("GEMINI_API_KEY missing, skipping memory consolidation")
        return
        
    for p in res.data:
        patient_id = p["id"]
        try:
            # Fetch all symptoms (Active, Resolved, Resolving, Chronic) for deduplication
            mem_res = supabase.table("patient_symptoms").select("id, name, status, severity").eq("patient_id", patient_id).eq("status", "Active").execute()
            facts = mem_res.data if mem_res.data else []
            
            if len(facts) < 2:
                continue
                
            print(f"Checking {len(facts)} active symptoms for duplicates for patient {patient_id}")
            
            prompt = """
You are a medical data consolidation assistant. 
Below is a list of active symptoms for a patient.
Your task is to identify any duplicate or highly similar concepts (e.g. "dry skin" and "flaky skin", or "shoulder hurts" and "shoulder pain").
If you find duplicates, group them together and provide a single consolidated description for them.
Do NOT group facts that are distinctly different (e.g. "shoulder pain" and "knee pain" are different).

Return a JSON object in exactly this format, and nothing else (no markdown blocks):
{
  "consolidations": [
    {
      "duplicate_ids": ["uuid1", "uuid2", "uuid3"],
      "consolidated_name": "The combined best description of the symptom"
    }
  ]
}
If there are no duplicates, return {"consolidations": []}
"""
            facts_cleaned = [{"id": f["id"], "name": f["name"]} for f in facts]
            
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key={GEMINI_API_KEY}"
            payload = {
                "contents": [{"role": "user", "parts": [{"text": prompt + "\n\nSymptoms:\n" + json.dumps(facts_cleaned, indent=2)}]}],
                "generationConfig": {
                    "temperature": 0.1,
                    "responseMimeType": "application/json"
                }
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, timeout=60.0)
                response.raise_for_status()
                data = response.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                
                try:
                    result = json.loads(text.strip())
                except Exception:
                    # Clean markdown if present
                    t = text.strip()
                    if t.startswith("```json"): t = t[7:]
                    elif t.startswith("```"): t = t[3:]
                    if t.endswith("```"): t = t[:-3]
                    result = json.loads(t.strip())
                    
                consolidations = result.get("consolidations", [])
                
                for cons in consolidations:
                    dup_ids = cons.get("duplicate_ids", [])
                    consolidated_text = cons.get("consolidated_name", "")
                    
                    if len(dup_ids) > 1 and consolidated_text:
                        primary_id = dup_ids[0]
                        other_ids = dup_ids[1:]
                        
                        print(f"Merging {len(other_ids)} duplicates into primary {primary_id} as '{consolidated_text}'")
                        
                        # 1. Update primary fact text
                        supabase.table("patient_symptoms").update({"name": consolidated_text}).eq("id", primary_id).execute()
                        
                        # 2. Re-link actions to primary
                        for oid in other_ids:
                            supabase.table("care_plan_actions").update({"symptom_id": primary_id}).eq("symptom_id", oid).execute()
                            
                        # 3. Re-link symptom logs to primary
                        for oid in other_ids:
                            supabase.table("symptom_logs").update({"symptom_id": primary_id}).eq("symptom_id", oid).execute()
                            
                        # 4. Delete duplicates
                        for oid in other_ids:
                            supabase.table("patient_symptoms").delete().eq("id", oid).execute()
                            
        except Exception as e:
            print(f"Failed memory consolidation for {patient_id}: {e}")


async def run_daily_longevity_fallback():
    print("Running daily longevity fallback check...")
    from datetime import datetime, timezone
    from app.services.insights.data_fetcher import supabase
    from app.services.longevity_engine import generate_daily_protocols
    
    # Run roughly every 15 minutes checking for users who passed 9 AM local time
    # For simplicity, we just sweep anyone missing today's plan
    
    res = supabase.table("patients").select("id").execute()
    if not res.data:
        return
        
    today_utc_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    for p in res.data:
        patient_id = p["id"]
        try:
            # Check if plan already generated today
            plan_res = supabase.table("patient_longevity_protocols").select("id").eq("patient_id", patient_id).eq("date", today_utc_str).execute()
            if not plan_res.data:
                # No plan yet. Generate it.
                print(f"Fallback triggered: Generating missing daily protocol for {patient_id}")
                await generate_daily_protocols(patient_id)
        except Exception as e:
            print(f"Failed to run daily longevity fallback for {patient_id}: {e}")

