from typing import List, Dict, Any, Optional
from datetime import datetime
from app.services.insights.engine import engine
from app.services.medgemma_services import generate_medgemma_alerts, generate_medgemma_nudge
from app.services.insights.data_fetcher import fetch_patient_context, supabase
from app.services.notification_templates import dispatch_notification, NotificationType
from pydantic import BaseModel

async def run_tripwire_evaluation(patient_id: str, trigger_type: str = "vitals", evaluation_mode: str = "realtime", send_nudge: bool = True):
    """
    Evaluates the patient using the fast deterministic rules engine.
    If a HIGH or MEDIUM anomaly is detected, dispatches to LLM for alert reasoning
    and subsequently notifies the caregiver.
    """
    if not patient_id:
        return
        
    print(f"Running deterministic tripwire for patient {patient_id} in mode {evaluation_mode}...")
    ctx = fetch_patient_context(patient_id)
    rules_output = engine.evaluate_patient(patient_id, ctx, evaluation_mode=evaluation_mode)
    
    # Filter for active insights (mostly used for Labs / Cold Start)
    flagged_insights = [
        insight for insight in rules_output.active_insights 
        if insight.severity.value in ("HIGH", "MEDIUM", "CRITICAL", "LOW")
    ]
    print(f"Flagged deterministic insights: {[i.rule_id for i in flagged_insights]}")
    
    should_wake_medgemma = False
    
    # Calculate the absolute most recent date that any vital was recorded
    latest_global_date = None
    vitals_metrics = list(ctx.vitals._vitals.keys())
    all_dates = []
    for metric_name in vitals_metrics:
        try:
            m = ctx.vitals.metric(metric_name)
            if m.has_data:
                all_dates.append(m.data[-1].date)
        except Exception:
            pass
    if all_dates:
        latest_global_date = max(all_dates)
    
    if trigger_type == "vitals":
        has_any_established_baseline = False
        for metric_name in vitals_metrics:
            # Skip overall avg_heart_rate anomaly checks to rely strictly on the 
            # more accurate time-segmented HR averages (morning, afternoon, etc.)
            if metric_name == "avg_heart_rate":
                continue
                
            try:
                m = ctx.vitals.metric(metric_name)
                b = m.established_baseline
                if b and b.std > 0 and m.has_data:
                    has_any_established_baseline = True
                    # Only calculate Z-Score if this specific vital was updated on the fresh date
                    if latest_global_date and m.data[-1].date == latest_global_date:
                        z_score = abs((m.latest - b.mean) / b.std)
                        if z_score >= 1.5:
                            should_wake_medgemma = True
                            print(f"Tripwire Gatekeeper: {metric_name} deviated by {z_score:.2f} std devs on {latest_global_date}!")
                            break # Found one anomaly, wake MedGemma
            except Exception:
                pass
                
        if not has_any_established_baseline:
            # Cold start: Fallback to deterministic rules engine output for vitals
            if flagged_insights:
                should_wake_medgemma = True
                print("Tripwire Gatekeeper: No established baselines. Falling back to deterministic rules.")
                
        if not should_wake_medgemma:
            if flagged_insights:
                should_wake_medgemma = True
                print("Tripwire Gatekeeper: Deterministic engine caught an insight. Bypassing Z-score check.")
    else:
        # If trigger is "labs", always use the deterministic engine rules to gate MedGemma
        if flagged_insights:
            should_wake_medgemma = True
            
    if not should_wake_medgemma:
        print("Tripwire: Patient stable (Z-Score/Rules normal). MedGemma not woken up.")
        return
        
    print("Tripwire Gatekeeper opened! Waking up MedGemma independent pattern-finder...")
    
    try:
        # Fetch existing active and historical insights to prevent duplication
        active_res = supabase.table("active_clinical_insights").select("*").eq("patient_id", patient_id).neq("status", "resolved").neq("status", "resolved_stale").execute()
        existing_insights = active_res.data if active_res.data else []

        # --- AUTO-RESOLUTION FOR STALE DATA ---
        stale_insights = [fi for fi in flagged_insights if getattr(fi, 'is_stale', False)]
        if stale_insights:
            for stale in stale_insights:
                matching_old = next((o for o in existing_insights if o.get("rule_id") == stale.rule_id), None)
                if matching_old:
                    print(f"Auto-resolving {stale.rule_id} due to stale data.")
                    supabase.table("active_clinical_insights").update({"status": "resolved_stale"}).eq("id", matching_old["id"]).execute()
                    # Remove from existing_insights so MedGemma ignores it
                    existing_insights = [o for o in existing_insights if o.get("rule_id") != stale.rule_id]
            # Remove stale from flagged_insights so MedGemma doesn't re-trigger it
            flagged_insights = [fi for fi in flagged_insights if not getattr(fi, 'is_stale', False)]

        # LLM Cooldown Check
        if existing_insights and not flagged_insights:
            latest_update = None
            for i in existing_insights:
                if i.get("updated_at"):
                    try:
                        dt = datetime.fromisoformat(i["updated_at"].replace("Z", "+00:00"))
                        if not latest_update or dt > latest_update:
                            latest_update = dt
                    except ValueError:
                        pass
            
            if latest_update:
                hours_since_update = (datetime.utcnow().replace(tzinfo=latest_update.tzinfo) - latest_update).total_seconds() / 3600
                if hours_since_update < 4:
                    print("LLM Cooldown active (last evaluation < 4h ago and no new deterministic rules). MedGemma not woken up.")
                    return

        trigger_date_str = latest_global_date.isoformat() if (latest_global_date and trigger_type == "vitals") else None
        medgemma_response = await generate_medgemma_alerts(
            ctx, 
            tripped_insights=flagged_insights,
            trigger_type=trigger_type, 
            existing_insights=existing_insights,
            trigger_date=trigger_date_str
        )
        
        medgemma_alerts = medgemma_response.get("active_insights", [])
        resolved_ids = medgemma_response.get("resolved_insights", [])
        
        # Save active insights to database with Stateful Reconciliation
        new_rule_ids = [a.get("rule_id") for a in medgemma_alerts if "rule_id" in a]
        
        # Map back historical flag from deterministic engine
        for alert in medgemma_alerts:
            r_id = alert.get("rule_id")
            matching = next((t for t in flagged_insights if t.rule_id == r_id), None)
            if matching:
                if getattr(matching, 'is_historical', False):
                    alert["is_historical"] = True
                alert["effective_datetime"] = getattr(matching, 'effective_datetime', None)
        
        # 1. Explicitly mark resolved insights
        for r_id in resolved_ids:
            matching_old = next((o for o in existing_insights if o.get("rule_id") == r_id), None)
            if matching_old:
                supabase.table("active_clinical_insights").update({"status": "resolved"}).eq("id", matching_old["id"]).execute()
        
        # 2. Insert new or update existing
        state_change_occurred = False
        
        for alert in medgemma_alerts:
            rule_id = alert.get("rule_id", "unknown")
            is_historical = alert.get("is_historical", False)
            status = "historical" if is_historical else "active"
            
            matching_old = next((o for o in existing_insights if o.get("rule_id") == rule_id), None)
            
            if not matching_old:
                state_change_occurred = True
                payload = {
                    "patient_id": patient_id,
                    "rule_id": rule_id,
                    "name": alert.get("name", "Alert"),
                    "severity": alert.get("severity", "MEDIUM"),
                    "category": alert.get("category", "CLINICAL"),
                    "message": alert.get("message", ""),
                    "evidence": alert.get("evidence", {}),
                    "status": status
                }
                if alert.get("effective_datetime"):
                    payload["effective_datetime"] = alert.get("effective_datetime")
                    
                supabase.table("active_clinical_insights").insert(payload).execute()
                
                # Proactively reach out to the patient (if it's not purely historical)
                if status == "active" and alert.get("severity") in ("MEDIUM", "HIGH", "CRITICAL"):
                    from app.services.proactive_coach import generate_proactive_message
                    context_str = f"Alert: {alert.get('name')}. Message: {alert.get('message')}"
                    await generate_proactive_message(patient_id, "CLINICAL_ALERT", context_str)
            else:
                # Update message if changed
                if matching_old.get("message") != alert.get("message") or matching_old.get("severity") != alert.get("severity"):
                    # Check for escalation
                    old_sev = matching_old.get("severity", "LOW").upper()
                    new_sev = alert.get("severity", "MEDIUM").upper()
                    severity_rank = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
                    if severity_rank.get(new_sev, 1) > severity_rank.get(old_sev, 1):
                        state_change_occurred = True
                        
                    old_evidence = matching_old.get("evidence") or {}
                    history = old_evidence.get("history", [])
                    history.append({
                        "timestamp": matching_old.get("updated_at", datetime.utcnow().isoformat()),
                        "severity": matching_old.get("severity"),
                        "message": matching_old.get("message")
                    })
                    
                    new_evidence = alert.get("evidence", {})
                    new_evidence["history"] = history

                    supabase.table("active_clinical_insights").update({
                        "message": alert.get("message", ""),
                        "severity": alert.get("severity", "MEDIUM"),
                        "evidence": new_evidence,
                        "status": status,
                        "updated_at": datetime.utcnow().isoformat()
                    }).eq("id", matching_old["id"]).execute()
        
        # Check caregiver preference
        # We need to fetch the caregiver_nudge_preference from the patients table
        patient_res = supabase.table("patients").select("caregiver_nudge_preference, full_name").eq("id", patient_id).execute()
        nudge_pref = "HIGH"
        patient_name = "Patient"
        if patient_res.data:
            nudge_pref = patient_res.data[0].get("caregiver_nudge_preference", "HIGH")
            patient_name = patient_res.data[0].get("full_name", "Patient")
            
        # Determine if we should send a nudge based on preference
        highest_severity = "LOW"
        for alert in medgemma_alerts:
            sev = alert.get("severity", "LOW").upper()
            if sev == "HIGH": highest_severity = "HIGH"
            elif sev == "MEDIUM" and highest_severity != "HIGH": highest_severity = "MEDIUM"
            
        should_nudge = False
        has_historical = any(alert.get("is_historical", False) for alert in medgemma_alerts)
        
        if nudge_pref == "ALL": should_nudge = True
        elif state_change_occurred:
            if nudge_pref == "HIGH" and highest_severity == "HIGH": should_nudge = True
            elif nudge_pref == "MEDIUM" and highest_severity in ("HIGH", "MEDIUM"): should_nudge = True
            elif nudge_pref == "LOW": should_nudge = True
        elif has_historical: should_nudge = True # Always send re-test nudge for historical findings
        else:
            print("Nudge suppressed: No state change or escalation occurred.")
        
        if should_nudge and send_nudge:
            print("Dispatching Caregiver Nudge...")
            nudge = await generate_medgemma_nudge(medgemma_alerts, patient_name=patient_name, patient_id=patient_id)
            print("Caregiver Nudge generated:", nudge.get("nudge_title"))
            
            # Fetch device tokens for the patient and send push notification
            token_res = supabase.table("device_tokens").select("fcm_token").eq("patient_id", patient_id).execute()
            if token_res.data:
                for token_record in token_res.data:
                    fcm_token = token_record.get("fcm_token")
                    if fcm_token:
                        dispatch_notification(
                            fcm_token=fcm_token,
                            notification_type=NotificationType.CAREGIVER_NUDGE,
                            dynamic_title=nudge.get("nudge_title", "New Health Insight"),
                            dynamic_body=nudge.get("nudge_message", "Tap to view details."),
                            extra_data={"patient_id": patient_id}
                        )
            else:
                print(f"No device tokens found for patient {patient_id}. Push notification skipped.")
            
    except Exception as e:
        print(f"Error during Tripwire LLM evaluation: {e}")
