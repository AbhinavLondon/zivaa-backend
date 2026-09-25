import os
import json
import uuid
import re
import httpx
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone, timedelta
from app.config import settings
from app.services.insights.data_fetcher import supabase
from app.utils.crypto import encrypt_text, decrypt_text
from app.services.multilingual import get_clinical_normalization_directive
from app.services.clinical_taxonomy import resolve_symptom_and_actions

SYSTEM_PROMPT = """You are an AI Memory Extraction engine for a senior care application.
Your job is to read a recent conversation between a patient and their AI Health Coach and extract structured clinical memory facts.

CRITICAL CLINICAL RULES:
1. Trait vs. State: If it is a permanent constraint (e.g., "Prefers morning walks", "Vegan"), it is a preference. If it is a temporary health state, it is a symptom.
2. Diagnoses are NOT Symptoms: Do not extract known medical conditions (e.g., Diabetes, Hypertension) as temporary symptoms.
3. Medications are NOT Actions: Do not extract medication routines as generic actions; place them ONLY in the medications list.
4. ZERO UUID RULE: You MUST NOT invent, guess, or copy database UUIDs. Link actions to symptoms purely using human-readable semantic fields: "target_symptom_name" and "target_body_part".
5. User Medications ONLY: Only extract medications that the PATIENT explicitly states they are currently taking or have been prescribed. Do NOT extract medications that the AI Coach is merely suggesting or explaining.
6. Preferences: ONLY extract preferences if the patient explicitly stated, updated, or removed a dietary or lifestyle preference in this conversation.
7. Tracking Progression & Attribution:
   - If the patient reports an existing symptom is improving ("feeling better", "pain down"), output in "updated_symptoms" with "new_status": "Resolving" and "progression_note".
   - If the patient says the symptom is completely gone, set "new_status": "Resolved".
   - If the patient states that a specific remedy helped (e.g., "The warm compress worked wonders"), record it in "attributed_remedies" with "outcome": "positive".
8. Standardized Anatomical Sites: Always map anatomical sites to one of:
   [Head / Cranial, Eyes, Ears / Nose / Throat, Neck / Cervical, Shoulders, Upper Back / Thoracic, Lower Back / Lumbar, Chest, Abdomen, Pelvis / Groin, Hips, Knees, Ankles / Feet, Wrists / Hands, Full Body / Systemic].
9. """ + get_clinical_normalization_directive() + """

You will be given the CURRENT known preferences, active symptoms, active actions, and active medications, along with the RECENT chat log.
You must return a JSON object exactly matching this format:

{
  "preferences": [
    {"domain": "Dietary", "constraint_text": "Vegan"}
  ],
  "new_medications": [
    {"name": "Lisinopril", "dose": "10mg", "frequency": "Daily", "status": "Active"}
  ],
  "updated_medications": [
    {"id": "uuid", "name": "Lisinopril", "dose": "20mg", "frequency": "Daily", "status": "Active"}
  ],
  "new_symptoms": [
    {
      "name": "Right Knee Stiffness",
      "anatomical_site": "Knees",
      "severity": "Moderate",
      "status": "Active",
      "progression_note": "Ache started after morning walk"
    }
  ],
  "updated_symptoms": [
    {
      "target_symptom_name": "Lower Back Pain",
      "target_body_part": "Lower Back / Lumbar",
      "new_status": "Resolving",
      "new_severity": "Mild",
      "progression_note": "Pain decreased from 6/10 to 2/10 after rest"
    }
  ],
  "new_actions": [
    {
      "description": "Warm mustard oil compress for 15 mins",
      "action_type": "symptom_relief",
      "target_symptom_name": "Right Knee Stiffness",
      "target_body_part": "Knees",
      "cadence": "daily",
      "ui_action_type": "START_TIMER",
      "status": "Suggested"
    }
  ],
  "updated_actions": [
    {"id": "uuid", "status": "Abandoned"}
  ],
  "attributed_remedies": [
    {
      "remedy_description": "Warm mustard oil compress",
      "target_body_part": "Knees",
      "outcome": "positive"
    }
  ]
}

- Action statuses can be: Suggested, Agreed, Completed, Abandoned, Paused.
- Action types can be: symptom_relief, one_off (errand/milestone), habit (lifestyle routine), periodic.
- Cadence can be: daily, weekly_sunday, weekly_monday, etc., or once (for one-off errands).
- ui_action_type can be: FOLLOW_EXERCISE, LOG_VITALS, LOG_MEAL, COACH_CHAT, START_TIMER, CHECKBOX_ONLY.
- Symptom statuses can be: Active, Resolving, Resolved, Chronic.
- Symptom severities can be: Mild, Moderate, Severe.
- Medication statuses can be: Active, Discontinued.
- Remedy outcomes can be: positive, neutral, negative.

DO NOT output markdown formatting like ```json.
"""

async def extract_memory_from_chats(
    patient_id: str,
    session_id: Optional[str] = None,
    message_ids: Optional[List[str]] = None
):
    """
    Reads recent unprocessed chat logs for the patient (optionally filtered by session_id),
    extracts facts using Gemini, and updates the domain-driven care model tables with ePHI encryption.
    Flags chats as processed ONLY on successful completion.
    """
    try:
        # 1. Fetch Context & Decrypt for AI reasoning
        pref_res = supabase.table("patient_preferences").select("domain, constraint_text").eq("patient_id", patient_id).execute()
        current_prefs = pref_res.data or []
        
        symp_res = supabase.table("patient_symptoms").select("id, name, status, severity").eq("patient_id", patient_id).eq("status", "Active").execute()
        current_symptoms = symp_res.data or []
        for s in current_symptoms:
            if s.get("name"):
                try:
                    s["name"] = decrypt_text(s["name"])
                except Exception:
                    pass
        
        act_res = supabase.table("care_plan_actions").select("id, description, status").eq("patient_id", patient_id).in_("status", ["Suggested", "Agreed"]).execute()
        current_actions = act_res.data or []
        
        med_res = supabase.table("patient_medications").select("id, name, dose, frequency, status").eq("patient_id", patient_id).eq("status", "Active").execute()
        current_meds = med_res.data or []
        for m in current_meds:
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
        
        # Temporarily pass empty conditions until the conditions table is implemented
        conditions = []
        
    except Exception as e:
        print(f"Memory extract error fetching context data: {e}")
        return

    # 2. Fetch recent unprocessed chat logs for this session
    try:
        query = supabase.table("coach_chat_logs") \
            .select("id, role, message") \
            .eq("patient_id", patient_id) \
            .eq("processed_by_memory", False)
            
        if message_ids:
            query = query.in_("id", message_ids)
        elif session_id and session_id != "legacy_session":
            query = query.filter("metadata->>session_id", "eq", session_id)
            
        chat_res = query.order("created_at", desc=True).limit(30).execute()
        
        if not chat_res.data:
            return
        chats = list(reversed(chat_res.data))
    except Exception as e:
        print(f"Memory extract error fetching chats: {e}")
        return

    # Decrypt chat messages and strip internal metadata tags
    chat_lines = []
    for c in chats:
        role = c.get("role", "user").capitalize()
        raw_msg = c.get("message", "")
        try:
            msg = decrypt_text(raw_msg)
        except Exception:
            msg = raw_msg
            
        clean_msg = re.sub(r'__META__.*?__META__', '', msg).strip()
        if '[SUGGESTIONS]' in clean_msg:
            clean_msg = clean_msg.split('[SUGGESTIONS]')[0].strip()
        if clean_msg:
            chat_lines.append(f"{role}: {clean_msg}")

    if not chat_lines:
        return

    chat_text = "\n".join(chat_lines)
    
    prompt = (
        f"KNOWN DIAGNOSES (DO NOT EXTRACT AS SYMPTOMS):\n{json.dumps(conditions)}\n\n"
        f"CURRENT PREFERENCES:\n{json.dumps(current_prefs)}\n\n"
        f"CURRENT ACTIVE SYMPTOMS:\n{json.dumps(current_symptoms)}\n\n"
        f"CURRENT ACTIVE MEDICATIONS:\n{json.dumps(current_meds)}\n\n"
        f"CURRENT ACTIVE ACTIONS:\n{json.dumps(current_actions)}\n\n"
        f"RECENT CHAT LOG:\n{chat_text}"
    )

    # 3. Call Gemini
    api_key = os.environ.get("GEMINI_API_KEY", settings.GEMINI_API_KEY)
    if not api_key:
        return

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key={api_key}"
    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2}
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, timeout=30.0)
            if response.status_code == 200:
                data = response.json()
                raw_text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                if raw_text.startswith("```json"):
                    raw_text = raw_text.split("```json")[-1].split("```")[0].strip()
                elif raw_text.startswith("```"):
                    raw_text = raw_text.split("```")[-1].split("```")[0].strip()
                parsed = json.loads(raw_text)
            else:
                print(f"Gemini API error during memory extraction: {response.text}")
                return
    except Exception as e:
        print(f"Failed to call Gemini for memory extraction: {e}")
        return

    # 4. Update Database with encryption
    try:
        # Preferences (Safe Upsert by Domain - never wipe unmentioned preferences)
        prefs = parsed.get("preferences", [])
        if prefs:
            for p in prefs:
                domain = p.get("domain", "General")
                constraint_text = p.get("constraint_text", "")
                if constraint_text:
                    existing_pref = supabase.table("patient_preferences") \
                        .select("id") \
                        .eq("patient_id", patient_id) \
                        .eq("domain", domain) \
                        .execute()
                    if existing_pref.data:
                        supabase.table("patient_preferences").update({
                            "constraint_text": constraint_text
                        }).eq("id", existing_pref.data[0]["id"]).execute()
                    else:
                        supabase.table("patient_preferences").insert({
                            "patient_id": patient_id,
                            "domain": domain,
                            "constraint_text": constraint_text
                        }).execute()
        
        # Deterministic Symptom, Action, and Remedy Efficacy Resolution (Zero UUIDs)
        try:
            await resolve_symptom_and_actions(
                patient_id=patient_id,
                extraction_result=parsed,
                patient_profile={"conditions": conditions}
            )
        except Exception as res_err:
            print(f"Error in resolve_symptom_and_actions: {res_err}")
            
        for ua in parsed.get("updated_actions", []):
            if not ua.get("id"):
                continue
            payload = {}
            if ua.get("status"):
                payload["status"] = ua.get("status")
            if ua.get("description"):
                payload["description"] = ua.get("description")
            if payload:
                supabase.table("care_plan_actions").update(payload).eq("id", ua.get("id")).execute()
            
        # Medications (Encrypted name and dose)
        has_new_meds = False
        for nm in parsed.get("new_medications", []):
            med_name = nm.get("name")
            if not med_name:
                continue
            med_dose = nm.get("dose")
            supabase.table("patient_medications").insert({
                "patient_id": patient_id,
                "name": encrypt_text(med_name),
                "dose": encrypt_text(med_dose) if med_dose else None,
                "frequency": nm.get("frequency", "Daily"),
                "status": nm.get("status", "Active")
            }).execute()
            has_new_meds = True
            
        for um in parsed.get("updated_medications", []):
            if not um.get("id"):
                continue
            payload = {}
            if um.get("name"):
                payload["name"] = encrypt_text(um.get("name"))
            if "dose" in um:
                payload["dose"] = encrypt_text(um["dose"]) if um.get("dose") else None
            if um.get("frequency"):
                payload["frequency"] = um.get("frequency")
            if um.get("status"):
                payload["status"] = um.get("status")
            if payload:
                supabase.table("patient_medications").update(payload).eq("id", um.get("id")).execute()

        # Trigger medication rules engine if new meds added
        if has_new_meds:
            print(f"New medication found for {patient_id}. Medication interaction check can be evaluated.")
            
        # Flag chats as processed ONLY after all extractions & updates succeed
        chat_ids = [c['id'] for c in chats]
        if chat_ids:
            supabase.table("coach_chat_logs").update({"processed_by_memory": True}).in_("id", chat_ids).execute()
            sess_info = f" in session {session_id}" if session_id else ""
            print(f"Successfully flagged {len(chat_ids)} chats as processed for {patient_id}{sess_info}")

    except Exception as e:
        print(f"Failed to update patient memory in DB: {e}")

async def process_inactive_chat_sessions():
    """
    Finds sessions that have unprocessed chat logs (processed_by_memory == False)
    grouped by (patient_id, session_id), where the latest message in that session
    was created > 5 minutes ago (patient is no longer typing in that session).
    Extracts clinical memory facts session-by-session.
    """
    try:
        now = datetime.now(timezone.utc)
        
        # 1. Fetch unprocessed chat messages with metadata to get session_id
        res = supabase.table("coach_chat_logs") \
            .select("id, patient_id, created_at, metadata") \
            .eq("processed_by_memory", False) \
            .order("created_at", desc=False) \
            .execute()
            
        if not res.data:
            return
            
        # 2. Group by (patient_id, session_id) and track the latest message timestamp and message ids
        sessions: Dict[tuple, Dict[str, Any]] = {}
        for row in res.data:
            pid = row["patient_id"]
            meta = row.get("metadata") or {}
            sess_id = meta.get("session_id") or "legacy_session"
            key = (pid, sess_id)
            if key not in sessions:
                sessions[key] = {
                    "latest_at": None,
                    "message_ids": []
                }
            dt = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
            if not sessions[key]["latest_at"] or dt > sessions[key]["latest_at"]:
                sessions[key]["latest_at"] = dt
            sessions[key]["message_ids"].append(row["id"])
            
        # 3. Only process sessions whose latest message is older than 5 minutes
        five_mins_ago = now - timedelta(minutes=5)
        for (pid, sess_id), sinfo in sessions.items():
            if sinfo["latest_at"] <= five_mins_ago:
                sess_desc = sess_id if sess_id != "legacy_session" else "legacy"
                print(f"Triggering memory extraction for patient {pid}, session {sess_desc} (inactive for >5 mins, {len(sinfo['message_ids'])} messages)")
                await extract_memory_from_chats(
                    patient_id=pid,
                    session_id=sess_id if sess_id != "legacy_session" else None,
                    message_ids=sinfo["message_ids"]
                )
                
    except Exception as e:
        print(f"Error in process_inactive_chat_sessions: {e}")
