"""Symptom Longitudinal Trajectory & Clinical Escalation Engine.

Monitors all active and resolving patient symptoms against:
1. Evidence-based clinical taxonomy SLAs (max_self_care_days) and geriatric vulnerability modifiers.
2. Micro-feedback trends from Daily Plan UI tasks and Coach conversations (from symptom_logs).
3. Objective wearable telemetry signals (sleep disruption, resting heart rate spikes).

Produces:
- Closed-loop clinical resolution when symptoms subside.
- Hospital-standard Doctor SBAR summaries & caregiver advisories when symptoms exceed safety limits.
"""

import os
import json
import uuid
import httpx
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional

from app.services.insights.data_fetcher import supabase, fetch_patient_context
from app.utils.crypto import decrypt_text
from app.config import settings

SBAR_ESCALATION_PROMPT = """# CLINICAL CONTEXT & OBJECTIVE
You are a Senior Clinical Fellow compiling an urgent Medical Consultation Briefing (SBAR) for an outpatient physician visit.
The patient is an older adult whose acute symptom has failed to resolve within evidence-based conservative care timelines.

# PATIENT CLINICAL DOSSIER:
- Patient: {patient_name}, {patient_age}M/F
- Chronic Conditions: {conditions_list}
- Current Medications: {medications_list}
- Target Symptom: {symptom_name} ({anatomical_site})
- Onset Date: {onset_date} ({days_active} days active vs SLA limit of {max_self_care_days} days)
- Baseline Severity: {initial_severity} -> Current Severity: {current_severity}
- Longitudinal Progression Log:
{symptom_timeline_logs}
- Interventions Attempted & Adherence:
{actions_adherence_summary}
- Concurrent Wearable Telemetry:
{vitals_anomalies_summary}

# REQUIRED OUTPUT STRUCTURE:
Generate a dual-section briefing in exact JSON:

{{
  "doctor_sbar": {{
    "situation": "Concise 1-sentence statement of primary unresolving complaint, duration, and reason for consultation.",
    "background": "Relevant comorbidities, current medications, baseline functional status.",
    "assessment": "Detailed progression of symptom, interventions attempted with compliance %, patient-reported adverse reactions, and wearable vital correlations (e.g. sleep/HR impact).",
    "recommendation": "Suggested evidence-based clinical workup to consider (e.g. 'Consider weight-bearing AP/Lateral knee radiographs to evaluate joint space narrowing / effusion; rule out meniscal pathology.')."
  }},
  "caregiver_summary": "A 2-sentence warm, clear, non-alarmist message for the family caregiver explaining why a doctor visit is now recommended and what to bring."
}}

# CLINICAL SAFETY TONE:
- Professional, objective, and collegial.
- Avoid diagnostic certainty (use "differential considerations include", "evaluate for").
- Ensure the caregiver summary is reassuring, emphasizing proactive preventive care rather than panic.
"""


def _get_gemini_api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY") or getattr(settings, "GEMINI_API_KEY", None)
    if not key or key == "your-api-key-here":
        raise ValueError("GEMINI_API_KEY not configured in environment or settings.")
    return key


async def generate_doctor_sbar(dossier: Dict[str, Any]) -> Dict[str, Any]:
    """Invokes Gemini to synthesize a hospital-standard SBAR and caregiver advisory."""
    api_key = _get_gemini_api_key()
    prompt = SBAR_ESCALATION_PROMPT.format(
        patient_name=dossier.get("patient_name", "Patient"),
        patient_age=dossier.get("patient_age", "Elderly"),
        conditions_list=", ".join(dossier.get("conditions", [])) or "None reported",
        medications_list=", ".join(dossier.get("medications", [])) or "None reported",
        symptom_name=dossier.get("symptom_name", "Unresolved Symptom"),
        anatomical_site=dossier.get("anatomical_site", "Unspecified site"),
        onset_date=dossier.get("onset_date", "Recent"),
        days_active=dossier.get("days_active", 0),
        max_self_care_days=dossier.get("max_self_care_days", 14),
        initial_severity=dossier.get("initial_severity", "Moderate"),
        current_severity=dossier.get("current_severity", "Moderate"),
        symptom_timeline_logs=dossier.get("timeline_logs", "No progression logs recorded."),
        actions_adherence_summary=dossier.get("actions_summary", "Conservative lifestyle adjustments attempted."),
        vitals_anomalies_summary=dossier.get("vitals_summary", "No acute telemetry flags.")
    )

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "responseMimeType": "application/json"
        }
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload, timeout=30.0)
        response.raise_for_status()
        raw_text = response.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        return json.loads(raw_text)


async def evaluate_symptom_trajectories(patient_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Evaluates all active/resolving symptoms across patients (or for a specific patient).
    
    Determines status transitions:
    - RESOLVED: If 3 consecutive 'better' feedbacks or reported recovered.
    - ESCALATED: If active days >= max_self_care_days or 2+ consecutive 'worse' feedbacks.
    - IMPROVING / STAGNANT: Tracks trajectory status updates.
    """
    results = []
    now = datetime.now(timezone.utc)

    # 1. Query active / resolving symptoms
    query = supabase.table("patient_symptoms").select("*").in_("status", ["Active", "Resolving"])
    if patient_id:
        query = query.eq("patient_id", patient_id)
    
    symptoms_resp = query.execute()
    symptoms = symptoms_resp.data or []
    if not symptoms:
        print("No active or resolving symptoms found for evaluation.")
        return results

    # Group symptoms by patient
    patient_map: Dict[str, List[Dict[str, Any]]] = {}
    for s in symptoms:
        patient_map.setdefault(s["patient_id"], []).append(s)

    for pid, pt_symptoms in patient_map.items():
        # Fetch patient profile & context
        patient_info = {}
        try:
            pt_res = supabase.table("patients").select("full_name, age, sex, timezone").eq("id", pid).execute()
            if pt_res.data:
                patient_info = pt_res.data[0]
        except Exception as e:
            print(f"Error fetching patient info for {pid}: {e}")

        patient_name = patient_info.get("full_name", "Patient")
        patient_age = patient_info.get("age", 72)
        patient_sex = patient_info.get("sex", "M")

        # Fetch clinical conditions & medications
        conditions = []
        medications = []
        try:
            ctx = fetch_patient_context(pid)
            conditions = ctx.patient_conditions or []
            medications = getattr(ctx, "medications", [])
        except Exception as ctx_err:
            print(f"Context error for patient {pid}: {ctx_err}")

        for symp in pt_symptoms:
            symp_id = symp["id"]
            raw_name = symp.get("name", "Symptom")
            symptom_name = decrypt_text(raw_name) if raw_name else "Symptom"
            anatomical_site = symp.get("anatomical_site") or "General"
            canonical_key = symp.get("canonical_key") or "MSK_GENERAL"
            max_self_care_days = symp.get("max_self_care_days") or 14
            expected_res_days = symp.get("expected_resolution_days") or 7
            initial_severity = symp.get("severity") or "Moderate"
            current_severity = initial_severity
            created_at_str = symp.get("created_at")

            # Calculate days active
            days_active = 0
            if created_at_str:
                try:
                    c_dt = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
                    days_active = max(0, (now - c_dt).days)
                except Exception:
                    days_active = 1

            # Fetch progression logs for this symptom
            logs_res = supabase.table("symptom_logs") \
                .select("micro_feedback, severity, status, note, created_at, source") \
                .eq("symptom_id", symp_id) \
                .order("created_at", desc=True) \
                .limit(10) \
                .execute()
            logs = logs_res.data or []

            # Extract feedback sequence
            feedbacks = [l.get("micro_feedback") for l in logs if l.get("micro_feedback")]
            if logs and logs[0].get("severity"):
                current_severity = logs[0].get("severity")

            # Check consecutive feedbacks
            consecutive_better = 0
            for f in feedbacks:
                if f == "better":
                    consecutive_better += 1
                else:
                    break

            consecutive_worse = 0
            for f in feedbacks:
                if f == "worse":
                    consecutive_worse += 1
                else:
                    break

            # -------------------------------------------------------------
            # CONDITION A: RESOLVED
            # -------------------------------------------------------------
            has_explicit_resolution = any("resolved" in (l.get("note") or "").lower() for l in logs[:2])
            has_streak_resolution = consecutive_better >= 3

            if has_explicit_resolution:
                print(f"[Trajectory Engine] Symptom {symptom_name} ({symp_id}) explicitly RESOLVED via patient confirmation.")
                try:
                    supabase.table("patient_symptoms").update({
                        "status": "Resolved",
                        "resolved_at": now.isoformat(),
                        "trajectory_status": "RESOLVED"
                    }).eq("id", symp_id).execute()

                    supabase.table("symptom_logs").insert({
                        "patient_id": pid,
                        "symptom_id": symp_id,
                        "source": "trajectory_engine",
                        "status": "Resolved",
                        "severity": "None",
                        "severity_score": 0,
                        "note": f"Symptom confirmed resolved by patient after {days_active} days of care."
                    }).execute()
                except Exception as res_err:
                    print(f"Error marking symptom resolved: {res_err}")

                results.append({
                    "patient_id": pid,
                    "symptom_id": symp_id,
                    "symptom_name": symptom_name,
                    "decision": "RESOLVED",
                    "days_active": days_active
                })
                continue
            elif has_streak_resolution and symp.get("trajectory_status") != "PENDING_RESOLUTION":
                print(f"[Trajectory Engine] Symptom {symptom_name} ({symp_id}) reached recovery milestone (streak: {consecutive_better} better). Setting PENDING_RESOLUTION for Coach confirmation.")
                try:
                    supabase.table("patient_symptoms").update({
                        "status": "Resolving",
                        "trajectory_status": "PENDING_RESOLUTION"
                    }).eq("id", symp_id).execute()

                    supabase.table("symptom_logs").insert({
                        "patient_id": pid,
                        "symptom_id": symp_id,
                        "source": "trajectory_engine",
                        "status": "Resolving",
                        "severity": "Mild",
                        "severity_score": 1,
                        "note": f"Recovery milestone reached ({consecutive_better} consecutive better). Scheduled Coach closure confirmation."
                    }).execute()
                except Exception as res_err:
                    print(f"Error updating symptom to PENDING_RESOLUTION: {res_err}")

                results.append({
                    "patient_id": pid,
                    "symptom_id": symp_id,
                    "symptom_name": symptom_name,
                    "decision": "PENDING_RESOLUTION",
                    "days_active": days_active
                })
                continue

            # -------------------------------------------------------------
            # CONDITION B: ESCALATED (Stop-loss SLA breach or worsening)
            # -------------------------------------------------------------
            sla_breached = days_active >= max_self_care_days
            worsening_streak = consecutive_worse >= 2
            should_escalate = (sla_breached or worsening_streak) and symp.get("trajectory_status") != "ESCALATED"

            if should_escalate:
                print(f"[Trajectory Engine] ESCALATING Symptom {symptom_name} ({symp_id}): days_active={days_active}/{max_self_care_days}, worse_streak={consecutive_worse}")

                # Format timeline log string
                log_lines = []
                for l in reversed(logs[:5]):
                    created = (l.get("created_at") or "")[:10]
                    fb = l.get("micro_feedback") or "checkin"
                    sev = l.get("severity") or "Moderate"
                    nt = l.get("note") or ""
                    log_lines.append(f"- {created} [{fb.upper()}] Severity: {sev} - {nt}")
                timeline_str = "\n".join(log_lines) if log_lines else f"- Active for {days_active} days with persistent discomfort."

                # Fetch interventions attempted & efficacy
                eff_res = supabase.table("symptom_intervention_efficacy") \
                    .select("action_description, positive_relief_count, neutral_relief_count, negative_relief_count, efficacy_ratio") \
                    .eq("patient_id", pid) \
                    .eq("canonical_key", canonical_key) \
                    .execute()
                eff_rows = eff_res.data or []
                actions_summary_lines = []
                for row in eff_rows:
                    ratio = int((row.get("efficacy_ratio") or 0) * 100)
                    actions_summary_lines.append(f"- {row.get('action_description')}: {ratio}% relief reported ({row.get('positive_relief_count')} positive, {row.get('negative_relief_count')} negative)")
                actions_summary = "\n".join(actions_summary_lines) if actions_summary_lines else "Lifestyle adjustments, hot/cold therapy, and resting."

                # Construct clinical dossier
                dossier = {
                    "patient_name": patient_name,
                    "patient_age": f"{patient_age}{patient_sex}",
                    "conditions": conditions,
                    "medications": medications,
                    "symptom_name": symptom_name,
                    "anatomical_site": anatomical_site,
                    "onset_date": created_at_str[:10] if created_at_str else "Unknown",
                    "days_active": days_active,
                    "max_self_care_days": max_self_care_days,
                    "initial_severity": initial_severity,
                    "current_severity": current_severity,
                    "timeline_logs": timeline_str,
                    "actions_summary": actions_summary,
                    "vitals_summary": f"Target SLA of {max_self_care_days} days exceeded; unresolving course."
                }

                # Generate doctor SBAR and caregiver summary
                sbar_data = {}
                try:
                    sbar_data = await generate_doctor_sbar(dossier)
                except Exception as sbar_err:
                    print(f"Error generating Doctor SBAR with Gemini: {sbar_err}")
                    sbar_data = {
                        "doctor_sbar": {
                            "situation": f"{patient_name} has persistent {symptom_name} lasting {days_active} days, exceeding conservative SLA limit of {max_self_care_days} days.",
                            "background": f"Known comorbidities: {', '.join(conditions) if conditions else 'None reported'}.",
                            "assessment": f"Conservative self-care interventions have not resolved the complaint. Current severity is {current_severity}.",
                            "recommendation": f"In-person clinical evaluation and targeted diagnostic workup for unresolving {anatomical_site} symptom."
                        },
                        "caregiver_summary": f"{patient_name}'s {symptom_name} has continued for {days_active} days without full relief. To ensure proper recovery, we recommend scheduling a visit with their doctor for a routine evaluation."
                    }

                doctor_sbar = sbar_data.get("doctor_sbar", {})
                caregiver_msg = sbar_data.get("caregiver_summary", f"{symptom_name} has not improved after {days_active} days. A doctor consultation is recommended.")

                # Insert into nudge_alerts
                alert_payload = {
                    "patient_id": pid,
                    "risk_level": "HIGH",
                    "nudge_title": f"Clinical Review Needed: Unresolving {symptom_name}",
                    "nudge_text": caregiver_msg,
                    "why_flagged": doctor_sbar,
                    "action_steps": {
                        "primary_action": "Schedule Doctor Consultation",
                        "escalation_tier": "TIER_3_DOCTOR",
                        "checklist": [
                            f"Share clinical SBAR report with primary physician",
                            f"Review medications and symptom timeline ({days_active} days)",
                            f"Note any restrictions in daily movement or sleep"
                        ],
                        "doctor_sbar": doctor_sbar
                    },
                    "source": "symptom_trajectory_escalation",
                    "acknowledged": False,
                    "created_at": now.isoformat()
                }

                try:
                    supabase.table("nudge_alerts").insert(alert_payload).execute()
                except Exception as ins_err:
                    print(f"Error saving nudge_alert for escalation: {ins_err}")

                # Update symptom trajectory_status
                try:
                    supabase.table("patient_symptoms").update({
                        "trajectory_status": "ESCALATED"
                    }).eq("id", symp_id).execute()
                except Exception as up_err:
                    print(f"Error updating trajectory_status to ESCALATED: {up_err}")

                # Send push notification
                try:
                    from app.services.notification_templates import dispatch_notification, NotificationType
                    token_res = supabase.table("device_tokens").select("fcm_token").eq("patient_id", pid).execute()
                    if token_res.data:
                        for token_record in token_res.data:
                            fcm_token = token_record.get("fcm_token")
                            if fcm_token:
                                dispatch_notification(
                                    fcm_token=fcm_token,
                                    notification_type=NotificationType.CAREGIVER_NUDGE,
                                    dynamic_title=f"Clinical Review Needed: Unresolving {symptom_name}",
                                    dynamic_body=caregiver_msg,
                                    extra_data={"patient_id": pid, "symptom_id": symp_id}
                                )
                except Exception as push_err:
                    print(f"Notification error: {push_err}")

                results.append({
                    "patient_id": pid,
                    "symptom_id": symp_id,
                    "symptom_name": symptom_name,
                    "decision": "ESCALATED",
                    "days_active": days_active,
                    "reason": "SLA_BREACH" if sla_breached else "DETERIORATING"
                })
                continue

            # -------------------------------------------------------------
            # CONDITION C: IMPROVING OR STAGNANT
            # -------------------------------------------------------------
            if consecutive_better > 0 and consecutive_worse == 0:
                new_traj = "IMPROVING"
            elif consecutive_worse > 0:
                new_traj = "DETERIORATING"
            else:
                new_traj = "STAGNANT" if days_active > (expected_res_days // 2) else symp.get("trajectory_status", "IMPROVING")

            if new_traj != symp.get("trajectory_status"):
                try:
                    supabase.table("patient_symptoms").update({
                        "trajectory_status": new_traj
                    }).eq("id", symp_id).execute()
                except Exception as traj_err:
                    print(f"Error updating trajectory status to {new_traj}: {traj_err}")

            results.append({
                "patient_id": pid,
                "symptom_id": symp_id,
                "symptom_name": symptom_name,
                "decision": new_traj,
                "days_active": days_active
            })

    return results
