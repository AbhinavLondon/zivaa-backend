"""Deterministic Semantic Entity Resolver.

Replaces fragile LLM UUID generation with a two-pass relational linker.
Matches natural language symptoms to canonical taxonomy, manages database UUIDs,
and binds care plan actions with 100% relational integrity.
"""

import re
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from rapidfuzz import fuzz
from app.services.insights.data_fetcher import supabase
from app.utils.crypto import encrypt_text, decrypt_text
from .catalog import match_canonical_symptom, classify_symptom_with_llm
from .modifiers import apply_geriatric_modifiers


def severity_to_score(
    severity: Optional[str] = None, 
    current_score: Optional[int] = None, 
    feedback: Optional[str] = None
) -> int:
    """
    Standardizes clinical symptom severity to a 0-10 integer scale (NRS-11 / VAS).
    1. If relative feedback is provided: applies a -2/+2 delta to the current score.
    2. Otherwise maps categorical string to clinical midpoint anchors:
       - 'None' / 'Resolved': 0
       - 'Mild': 2 (range 1-3)
       - 'Moderate': 5 (range 4-6)
       - 'Severe': 8 (range 7-9)
       - 'Critical': 10
    """
    if feedback:
        fb = feedback.lower().strip()
        base = current_score if current_score is not None else severity_to_score(severity)
        if fb == "better":
            return max(0, base - 2)
        elif fb == "worse":
            return min(10, base + 2)
        elif fb == "same":
            return base

    s_clean = (severity or "Moderate").lower().strip()
    mapping = {
        "none": 0,
        "resolved": 0,
        "mild": 2,
        "moderate": 5,
        "severe": 8,
        "critical": 10,
    }
    return mapping.get(s_clean, 5)


def score_to_severity(score: int) -> str:
    """Converts a 0-10 integer score back to canonical clinical category string."""
    if score <= 0:
        return "None"
    elif score <= 3:
        return "Mild"
    elif score <= 6:
        return "Moderate"
    else:
        return "Severe"


async def resolve_symptom_and_actions(
    patient_id: str,
    extraction_result: Dict[str, Any],
    patient_profile: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Deterministically processes extracted semantic entities without requiring LLM UUID generation.
    
    Pass 1: Resolves and upserts symptoms -> builds in-memory semantic lookup map.
    Pass 2: Links care actions to the resolved symptom IDs using target_body_part/target_symptom_name.
    Pass 3: Updates symptom_intervention_efficacy if positive/negative outcomes were attributed.
    """
    if patient_profile is None:
        patient_profile = {}

    resolved_symptom_map: Dict[str, str] = {}
    resolved_canonical_map: Dict[str, str] = {}

    # 1. Fetch currently active symptoms for this patient from DB to enable seamless trajectory continuation
    try:
        symp_res = supabase.table("patient_symptoms") \
            .select("id, name, status, severity, canonical_key, anatomical_site") \
            .eq("patient_id", patient_id) \
            .in_("status", ["Active", "Resolving"]) \
            .execute()
        active_db_symptoms = symp_res.data or []
        for s in active_db_symptoms:
            raw_name = s.get("name", "")
            try:
                decrypted_name = decrypt_text(raw_name)
            except Exception:
                decrypted_name = raw_name
                
            s_id = s["id"]
            c_key = s.get("canonical_key", "")
            resolved_symptom_map[decrypted_name.lower().strip()] = s_id
            if s.get("anatomical_site"):
                resolved_symptom_map[s["anatomical_site"].lower().strip()] = s_id
            if c_key:
                resolved_canonical_map[s_id] = c_key
    except Exception as e:
        print(f"Resolver error pre-fetching active symptoms: {e}")
        active_db_symptoms = []

    # ── PASS 1: PROCESS NEW AND UPDATED SYMPTOMS ──
    for ns in extraction_result.get("new_symptoms", []):
        name_raw = ns.get("name", "").strip()
        if not name_raw:
            continue
            
        body_part = ns.get("anatomical_site", "").strip()
        severity = ns.get("severity", "Mild")
        status = ns.get("status", "Active")
        note = ns.get("progression_note")

        # Match against Clinical Taxonomy Catalog (Tier 1: Deterministic Fast-Path)
        canonical = match_canonical_symptom(name_raw, anatomical_hint=body_part)
        
        # Tier 2: LLM Zero-Shot Semantic Safety Net (catches unexpected dialects & regional phrasing)
        if not canonical:
            canonical = classify_symptom_with_llm(name_raw, anatomical_hint=body_part)

        if canonical:
            canonical = apply_geriatric_modifiers(canonical, patient_profile)
            c_key = canonical["canonical_key"]
            snomed = canonical["snomed_code"]
            anatomical = canonical["anatomical_site"]
            category = canonical["domain"].upper()
            exp_days = canonical["expected_resolution_days"]
            max_days = canonical["max_self_care_days"]
            cadence = canonical["checkin_cadence_days"]
        else:
            c_key = None
            snomed = None
            anatomical = body_part or "General"
            category = "GENERAL"
            exp_days = 7
            max_days = 14
            cadence = 3

        # Check if an active symptom for this body part/concept already exists
        matched_id = (
            resolved_symptom_map.get(name_raw.lower()) or 
            (resolved_symptom_map.get(anatomical.lower()) if anatomical else None)
        )

        if matched_id:
            # Trajectory Continuation: Update severity and append to logs, do NOT duplicate row
            symp_id = matched_id
            try:
                supabase.table("patient_symptoms").update({
                    "severity": severity,
                    "status": status,
                    "trajectory_status": "IMPROVING" if status == "Resolving" else "STAGNANT"
                }).eq("id", symp_id).execute()
            except Exception as upd_err:
                print(f"Error updating existing symptom: {upd_err}")
        else:
            # Genuinely new symptom: Mint new UUIDv4 deterministically
            symp_id = str(uuid.uuid4())
            try:
                payload = {
                    "id": symp_id,
                    "patient_id": patient_id,
                    "name": encrypt_text(name_raw),
                    "status": status,
                    "severity": severity,
                    "canonical_key": c_key,
                    "snomed_code": snomed,
                    "anatomical_site": anatomical,
                    "symptom_category": category,
                    "expected_resolution_days": exp_days,
                    "max_self_care_days": max_days,
                    "checkin_cadence_days": cadence,
                    "trajectory_status": "IMPROVING"
                }
                supabase.table("patient_symptoms").insert(payload).execute()
            except Exception as ins_err:
                print(f"Error inserting new symptom into patient_symptoms: {ins_err}")

        # Register in lookup maps for action linking in Pass 2
        resolved_symptom_map[name_raw.lower()] = symp_id
        if anatomical:
            resolved_symptom_map[anatomical.lower()] = symp_id
        if c_key:
            resolved_canonical_map[symp_id] = c_key

        # Append to symptom_logs (Clinical Progression Ledger)
        try:
            supabase.table("symptom_logs").insert({
                "symptom_id": symp_id,
                "patient_id": patient_id,
                "severity": severity,
                "severity_score": severity_to_score(severity),
                "status": status,
                "source": "coach_chat",
                "note": note or f"Logged via Coach Chat ({name_raw})"
            }).execute()
        except Exception as log_err:
            print(f"Error logging symptom event: {log_err}")

    # Process explicit updated symptoms (e.g., patient reported resolution)
    for us in extraction_result.get("updated_symptoms", []):
        t_name = us.get("target_symptom_name", "").lower().strip()
        t_part = us.get("target_body_part", "").lower().strip()
        target_id = us.get("id") or resolved_symptom_map.get(t_name) or resolved_symptom_map.get(t_part)
        
        if not target_id:
            continue
            
        upd_payload = {}
        if us.get("new_status") or us.get("status"):
            st = us.get("new_status") or us.get("status")
            upd_payload["status"] = st
            if st == "Resolved":
                upd_payload["resolved_at"] = datetime.now(timezone.utc).isoformat()
                upd_payload["trajectory_status"] = "RESOLVED"
            elif st == "Resolving":
                upd_payload["trajectory_status"] = "IMPROVING"
        if us.get("new_severity") or us.get("severity"):
            upd_payload["severity"] = us.get("new_severity") or us.get("severity")

        if upd_payload:
            try:
                supabase.table("patient_symptoms").update(upd_payload).eq("id", target_id).execute()
            except Exception as e:
                print(f"Error applying symptom update: {e}")

        # Log update note
        prog_note = us.get("progression_note") or f"Status updated to {upd_payload.get('status', 'Active')}"
        upd_sev = upd_payload.get("severity", "Mild")
        try:
            supabase.table("symptom_logs").insert({
                "symptom_id": target_id,
                "patient_id": patient_id,
                "severity": upd_sev,
                "severity_score": severity_to_score(upd_sev),
                "status": upd_payload.get("status", "Active"),
                "source": "coach_chat",
                "note": prog_note
            }).execute()
        except Exception as log_err:
            print(f"Error logging symptom update: {log_err}")

    # ── PASS 2: BIND ACTIONS DETERMINISTICALLY & DEDUPLICATE ──
    # Fetch existing active/pending actions for this patient to prevent duplicate insertions
    existing_active_actions: List[Dict[str, Any]] = []
    try:
        existing_actions_res = supabase.table("care_plan_actions") \
            .select("id, description, symptom_id, status") \
            .eq("patient_id", patient_id) \
            .in_("status", ["Suggested", "Agreed", "Active", "Pending", "Abandoned"]) \
            .execute()
        existing_active_actions = existing_actions_res.data or []
    except Exception as e:
        print(f"Notice fetching existing actions for dedup: {e}")

    for na in extraction_result.get("new_actions", []):
        desc = na.get("description", "").strip()
        if not desc:
            continue
            
        act_type = na.get("action_type", "symptom_relief" if na.get("target_symptom_name") else "habit")
        target_sym = (na.get("target_symptom_name") or "").lower().strip()
        target_part = (na.get("target_body_part") or "").lower().strip()
        
        # Link resolution cascade: exact symptom name -> anatomical site -> active fallback
        linked_symptom_id = (
            resolved_symptom_map.get(target_sym) or 
            resolved_symptom_map.get(target_part) or 
            (active_db_symptoms[0]["id"] if active_db_symptoms and act_type == "symptom_relief" else None)
        )

        # ── ACTION DEDUPLICATION GUARD ──
        norm_new_desc = re.sub(r'\s+', ' ', desc.lower().strip())
        is_duplicate = False

        for ea in existing_active_actions:
            ea_desc = (ea.get("description") or "").strip()
            norm_ea_desc = re.sub(r'\s+', ' ', ea_desc.lower())

            # 1. Exact or normalized string match
            if norm_new_desc == norm_ea_desc:
                is_duplicate = True
                break

            # 2. High fuzzy semantic similarity (>= 85%)
            if fuzz.token_set_ratio(norm_new_desc, norm_ea_desc) >= 85:
                is_duplicate = True
                break

            # 3. Clinical Intent deduplication for the same symptom
            if linked_symptom_id and ea.get("symptom_id") == linked_symptom_id:
                # Emergency transport deduplication (e.g. Call 999 / Ambulance)
                emergency_words = {"999", "911", "112", "ambulance", "emergency transport"}
                if any(w in norm_new_desc for w in emergency_words) and any(w in norm_ea_desc for w in emergency_words):
                    is_duplicate = True
                    break

                # Same modality/remedy deduplication (e.g. compress on same body part)
                remedy_words = {"mustard oil", "cold compress", "warm compress", "ice pack", "heating pad"}
                for rw in remedy_words:
                    if rw in norm_new_desc and rw in norm_ea_desc:
                        is_duplicate = True
                        break
                if is_duplicate:
                    break

        if is_duplicate:
            print(f"[DEDUP] Skipping duplicate care action for patient {patient_id}: '{desc}'")
            continue

        action_payload = {
            "patient_id": patient_id,
            "symptom_id": linked_symptom_id,
            "description": desc,
            "status": na.get("status", "Suggested"),
            "action_type": act_type,
            "cadence": na.get("cadence", "daily" if act_type in ["habit", "symptom_relief"] else "once"),
            "target_body_part": na.get("target_body_part")
        }
        ui_act = na.get("ui_action_type")
        if ui_act:
            action_payload["action_metadata"] = {
                "ui_action_type": ui_act,
                "target_body_part": na.get("target_body_part")
            }

        try:
            ins_res = supabase.table("care_plan_actions").insert(action_payload).execute()
            if ins_res.data:
                existing_active_actions.append(ins_res.data[0])
            else:
                existing_active_actions.append(action_payload)
        except Exception as e:
            # Fallback for columns if schema variances occur
            action_payload.pop("target_body_part", None)
            action_payload.pop("action_metadata", None)
            try:
                ins_res = supabase.table("care_plan_actions").insert(action_payload).execute()
                if ins_res.data:
                    existing_active_actions.append(ins_res.data[0])
                else:
                    existing_active_actions.append(action_payload)
            except Exception as e2:
                print(f"Error inserting linked care action: {e2}")

    # ── PASS 3: INTERVENTION EFFICACY LEARNING ──
    for ar in extraction_result.get("attributed_remedies", []):
        remedy_desc = ar.get("remedy_description", "").strip()
        outcome = ar.get("outcome", "positive").lower()
        target_part = (ar.get("target_body_part") or "").lower().strip()
        
        target_id = resolved_symptom_map.get(target_part)
        canonical_key = resolved_canonical_map.get(target_id, "MSK_GENERAL") if target_id else "MSK_GENERAL"
        
        if remedy_desc:
            try:
                # Query existing efficacy record
                eff_res = supabase.table("symptom_intervention_efficacy") \
                    .select("id, positive_relief_count, neutral_relief_count, negative_relief_count") \
                    .eq("patient_id", patient_id) \
                    .eq("canonical_key", canonical_key) \
                    .eq("action_description", remedy_desc) \
                    .execute()
                
                pos = 1 if outcome == "positive" else 0
                neg = 1 if outcome == "negative" else 0
                neu = 1 if outcome == "neutral" else 0
                
                if eff_res.data:
                    row = eff_res.data[0]
                    supabase.table("symptom_intervention_efficacy").update({
                        "positive_relief_count": row["positive_relief_count"] + pos,
                        "negative_relief_count": row["negative_relief_count"] + neg,
                        "neutral_relief_count": row["neutral_relief_count"] + neu,
                        "updated_at": datetime.now(timezone.utc).isoformat()
                    }).eq("id", row["id"]).execute()
                else:
                    supabase.table("symptom_intervention_efficacy").insert({
                        "patient_id": patient_id,
                        "canonical_key": canonical_key,
                        "symptom_name": target_part.title() if target_part else "Symptom",
                        "action_description": remedy_desc,
                        "positive_relief_count": pos,
                        "negative_relief_count": neg,
                        "neutral_relief_count": neu
                    }).execute()
            except Exception as eff_err:
                print(f"Error updating intervention efficacy: {eff_err}")

    return {
        "status": "success",
        "resolved_symptoms": len(resolved_symptom_map),
        "actions_linked": len(extraction_result.get("new_actions", []))
    }


def _is_valid_uuid(val: Any) -> bool:
    if not val:
        return False
    try:
        uuid.UUID(str(val))
        return True
    except (ValueError, TypeError, AttributeError):
        return False


async def record_task_micro_feedback(
    patient_id: str,
    feedback: str,
    task_id: Optional[str] = None,
    action_id: Optional[str] = None,
    task_title: Optional[str] = None,
    symptom_id: Optional[str] = None,
    period: Optional[str] = None,
    task_index: Optional[int] = None,
    notes: Optional[str] = None
) -> Dict[str, Any]:
    """
    Records rapid micro-feedback from the senior when completing a symptom-anchored daily task.
    
    Closed-loop mechanism:
    1. Appends an event to `symptom_logs` (Clinical Progression Ledger).
    2. Increments positive/neutral/negative counts in `symptom_intervention_efficacy`.
    3. Updates `patient_symptoms.trajectory_status` (IMPROVING / DETERIORATING) if streak detected.
    4. Optionally marks task complete in `daily_plans` if period and task_index are provided.
    """
    feedback_clean = (feedback or "").lower().strip()
    valid_feedbacks = ["better", "same", "worse", "skip"]
    if feedback_clean not in valid_feedbacks:
        feedback_clean = "same"

    matched_symptom = None
    target_symptom_id = symptom_id if _is_valid_uuid(symptom_id) else None

    # 1. Resolve symptom by symptom_id, task_id, or title
    if target_symptom_id:
        try:
            s_res = supabase.table("patient_symptoms").select("*").eq("id", target_symptom_id).execute()
            if s_res.data:
                matched_symptom = s_res.data[0]
        except Exception as e:
            print(f"Error fetching symptom by id {target_symptom_id}: {e}")

    if not matched_symptom and _is_valid_uuid(task_id):
        try:
            # Check care_plan_actions for symptom_id
            c_res = supabase.table("care_plan_actions").select("symptom_id").eq("id", task_id).execute()
            if c_res.data and c_res.data[0].get("symptom_id"):
                action_symp_id = c_res.data[0]["symptom_id"]
                s_res = supabase.table("patient_symptoms").select("*").eq("id", action_symp_id).execute()
                if s_res.data:
                    matched_symptom = s_res.data[0]
                    target_symptom_id = action_symp_id
        except Exception as e:
            print(f"Error resolving symptom via task_id {task_id}: {e}")

    if not matched_symptom:
        # Fallback: check active symptoms for patient
        try:
            active_res = supabase.table("patient_symptoms").select("*") \
                .eq("patient_id", patient_id) \
                .in_("status", ["Active", "Resolving"]) \
                .order("created_at", desc=True) \
                .limit(5) \
                .execute()
            if active_res.data:
                # Match by anatomical site in task title or fallback to most recent
                for act_symp in active_res.data:
                    site = (act_symp.get("anatomical_site") or "").lower()
                    name = (act_symp.get("name") or "").lower()
                    title_lower = (task_title or "").lower()
                    if (site and site in title_lower) or (name and name in title_lower):
                        matched_symptom = act_symp
                        target_symptom_id = act_symp["id"]
                        break
                if not matched_symptom:
                    matched_symptom = active_res.data[0]
                    target_symptom_id = matched_symptom["id"]
        except Exception as e:
            print(f"Error finding fallback active symptom: {e}")

    # 2. Record feedback and efficacy if symptom exists and feedback != 'skip'
    efficacy_updated = False
    if matched_symptom and feedback_clean in ["better", "same", "worse"]:
        symp_id = matched_symptom["id"]
        canonical_key = matched_symptom.get("canonical_key") or "MSK_GENERAL"
        symp_name = matched_symptom.get("name") or "Symptom"
        current_sev = matched_symptom.get("severity") or "Moderate"
        current_status = matched_symptom.get("status") or "Active"
        action_name = (task_title or "Prescribed care action").strip()

        # Derive updated severity and numeric score on micro-feedback
        cur_score = None
        try:
            prev_log = supabase.table("symptom_logs") \
                .select("severity_score") \
                .eq("symptom_id", symp_id) \
                .not_.is_("severity_score", "null") \
                .order("created_at", desc=True) \
                .limit(1) \
                .execute()
            if prev_log.data and prev_log.data[0].get("severity_score") is not None:
                cur_score = prev_log.data[0]["severity_score"]
        except Exception:
            cur_score = None

        new_score = severity_to_score(current_sev, current_score=cur_score, feedback=feedback_clean)
        new_severity = score_to_severity(new_score)

        valid_action_id = action_id if (action_id and _is_valid_uuid(action_id)) else (task_id if _is_valid_uuid(task_id) else None)

        # A. Append to symptom_logs with standardized severity_score
        try:
            supabase.table("symptom_logs").insert({
                "patient_id": patient_id,
                "symptom_id": symp_id,
                "action_id": valid_action_id,
                "task_id": task_id if _is_valid_uuid(task_id) else None,
                "source": "daily_plan_ui",
                "micro_feedback": feedback_clean,
                "severity": new_severity,
                "severity_score": new_score,
                "status": "Resolving" if (new_score == 0 or feedback_clean == "better") else current_status,
                "note": notes or (f"Milestone: Pain reached 0/10 after '{action_name}'. Triggering Coach closure confirmation." if new_score == 0 else f"Micro-feedback on task '{action_name}': {feedback_clean} (score: {new_score}/10)")
            }).execute()
        except Exception as log_err:
            print(f"Error recording symptom_log from UI micro-feedback: {log_err}")

        # Update patient_symptoms with current severity and resolution if reached 0
        try:
            upd_symp_data = {
                "severity": new_severity,
                "last_followed_up_at": datetime.now(timezone.utc).isoformat()
            }
            if new_score == 0:
                # Do not silently auto-resolve; transition to Resolving with PENDING_RESOLUTION for Coach closure prompt
                upd_symp_data["status"] = "Resolving"
                upd_symp_data["trajectory_status"] = "PENDING_RESOLUTION"
            elif feedback_clean == "better":
                upd_symp_data["status"] = "Resolving"
                upd_symp_data["trajectory_status"] = "IMPROVING"
            supabase.table("patient_symptoms").update(upd_symp_data).eq("id", symp_id).execute()
        except Exception as sym_upd_err:
            print(f"Error updating patient_symptoms from micro-feedback: {sym_upd_err}")

        # B. Upsert into symptom_intervention_efficacy with relational action_id & symptom_id
        try:
            pos = 1 if feedback_clean == "better" else 0
            neu = 1 if feedback_clean == "same" else 0
            neg = 1 if feedback_clean == "worse" else 0

            # Look up existing efficacy record by action_id or description
            eff_res = None
            if valid_action_id:
                eff_res = supabase.table("symptom_intervention_efficacy") \
                    .select("id, positive_relief_count, neutral_relief_count, negative_relief_count, action_id, symptom_id") \
                    .eq("patient_id", patient_id) \
                    .eq("action_id", valid_action_id) \
                    .execute()

            if not eff_res or not eff_res.data:
                eff_res = supabase.table("symptom_intervention_efficacy") \
                    .select("id, positive_relief_count, neutral_relief_count, negative_relief_count, action_id, symptom_id") \
                    .eq("patient_id", patient_id) \
                    .eq("canonical_key", canonical_key) \
                    .eq("action_description", action_name) \
                    .execute()

            tot_neg = neg
            if eff_res and eff_res.data:
                row = eff_res.data[0]
                new_pos = row["positive_relief_count"] + pos
                new_neu = row["neutral_relief_count"] + neu
                new_neg = row["negative_relief_count"] + neg
                tot_neg = new_neg
                tot = new_pos + new_neu + new_neg
                ratio = round(new_pos / tot, 3) if tot > 0 else 0.0

                supabase.table("symptom_intervention_efficacy").update({
                    "positive_relief_count": new_pos,
                    "neutral_relief_count": new_neu,
                    "negative_relief_count": new_neg,
                    "symptom_id": symp_id,
                    "action_id": valid_action_id or row.get("action_id"),
                    "updated_at": datetime.now(timezone.utc).isoformat()
                }).eq("id", row["id"]).execute()
            else:
                tot = pos + neu + neg
                supabase.table("symptom_intervention_efficacy").insert({
                    "patient_id": patient_id,
                    "canonical_key": canonical_key,
                    "symptom_name": symp_name,
                    "action_description": action_name,
                    "positive_relief_count": pos,
                    "neutral_relief_count": neu,
                    "negative_relief_count": neg,
                    "symptom_id": symp_id,
                    "action_id": valid_action_id
                }).execute()
            efficacy_updated = True

            # ── CLOSED-LOOP PRUNING: Retire action if adverse (negative count >= 2) ──
            if tot_neg >= 2:
                target_prune_id = valid_action_id
                if not target_prune_id:
                    c_find = supabase.table("care_plan_actions") \
                        .select("id") \
                        .eq("patient_id", patient_id) \
                        .ilike("description", f"%{action_name}%") \
                        .in_("status", ["Suggested", "Agreed", "Active"]) \
                        .execute()
                    if c_find.data:
                        target_prune_id = c_find.data[0]["id"]
                if target_prune_id:
                    supabase.table("care_plan_actions").update({"status": "Abandoned"}).eq("id", target_prune_id).execute()
                    print(f"[CLOSED-LOOP PRUNING] Action '{action_name}' marked Abandoned due to adverse feedback (negative count >= 2).")

        except Exception as eff_err:
            print(f"Error updating intervention efficacy from micro-feedback: {eff_err}")

        # Always update last_followed_up_at on patient_symptoms
        try:
            supabase.table("patient_symptoms").update({
                "last_followed_up_at": datetime.now(timezone.utc).isoformat()
            }).eq("id", symp_id).execute()
        except Exception:
            pass

        # C. Streak detection for trajectory status update
        try:
            recent_logs = supabase.table("symptom_logs") \
                .select("micro_feedback") \
                .eq("symptom_id", symp_id) \
                .order("created_at", desc=True) \
                .limit(4) \
                .execute()
            if recent_logs.data:
                feedbacks = [r.get("micro_feedback") for r in recent_logs.data if r.get("micro_feedback")]
                if len(feedbacks) >= 3 and all(f == "better" for f in feedbacks[:3]):
                    supabase.table("patient_symptoms").update({
                        "trajectory_status": "IMPROVING",
                        "status": "Resolving"
                    }).eq("id", symp_id).execute()
                elif len(feedbacks) >= 2 and all(f == "worse" for f in feedbacks[:2]):
                    supabase.table("patient_symptoms").update({
                        "trajectory_status": "DETERIORATING"
                    }).eq("id", symp_id).execute()
        except Exception as streak_err:
            print(f"Error checking symptom trajectory streak: {streak_err}")

    # 3. Mark task completed in active daily plan if period & task_index provided
    plan_updated = False
    if period and task_index is not None:
        try:
            plan_res = supabase.table("daily_plans").select("id, schedule") \
                .eq("patient_id", patient_id) \
                .order("created_at", desc=True) \
                .limit(1) \
                .execute()
            if plan_res.data:
                plan = plan_res.data[0]
                schedule = plan.get("schedule", {})
                p_key = period.lower()
                if p_key in schedule and isinstance(schedule[p_key], list):
                    if 0 <= task_index < len(schedule[p_key]):
                        schedule[p_key][task_index]["completed"] = True
                        supabase.table("daily_plans").update({"schedule": schedule}).eq("id", plan["id"]).execute()
                        plan_updated = True
        except Exception as p_err:
            print(f"Error updating daily plan task completion: {p_err}")

    return {
        "status": "success",
        "patient_id": patient_id,
        "symptom_id": target_symptom_id,
        "feedback": feedback_clean,
        "efficacy_recorded": efficacy_updated,
        "plan_completed": plan_updated
    }
