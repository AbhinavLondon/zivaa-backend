import os
import json
import uuid
import re
import httpx
from datetime import datetime, timezone, timedelta
from app.config import settings
from app.services.insights.data_fetcher import supabase
from app.utils.crypto import encrypt_text, decrypt_text
from app.services.multilingual import get_clinical_normalization_directive

SYSTEM_PROMPT = """You are an AI Memory Extraction engine for a senior care application.
Your job is to read a recent conversation between a patient and their AI Health Coach and extract structured clinical memory facts.

CRITICAL CLINICAL RULES:
1. Trait vs. State: If it is a permanent constraint (e.g., "Prefers morning walks", "Vegan"), it is a preference. If it is a temporary health state, it is a symptom.
2. Diagnoses are NOT Symptoms: Do not extract known medical conditions (e.g., Diabetes, Hypertension) as temporary symptoms.
3. Medications are NOT Actions: Do not extract medication routines as generic actions; place them ONLY in the medications list.
4. Entity Resolution: You must check the existing active symptoms, actions, and medications before extracting a new one. If the user mentions an issue conceptually identical to an existing one, output an 'update' rather than creating a new one.
5. User Medications ONLY: Only extract medications that the PATIENT explicitly states they are currently taking or have been prescribed. Do NOT extract medications that the AI Coach is merely suggesting, explaining, or educating the patient about.
6. Preferences: ONLY extract preferences if the patient explicitly stated, updated, or removed a dietary or lifestyle preference in this conversation. If no preferences were discussed or changed, return an empty list: "preferences": [].
7. """ + get_clinical_normalization_directive() + """

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
    {"name": "Lower back pain", "status": "Active", "severity": "Mild", "progression_note": "Triggered after gardening"}
  ],
  "updated_symptoms": [
    {"id": "uuid", "status": "Resolved", "severity": "Mild", "progression_note": "Pain is completely gone now"}
  ],
  "new_actions": [
    {"symptom_id": "uuid (optional, if linked to a symptom)", "description": "Ice the lower back", "status": "Suggested"}
  ],
  "updated_actions": [
    {"id": "uuid", "status": "Abandoned"}
  ]
}

- For updated items, you MUST include the existing 'id'.
- Action statuses can be: Suggested, Agreed, Completed, Abandoned.
- Symptom statuses can be: Active, Resolving, Resolved, Chronic.
- Symptom severities can be: Mild, Moderate, Severe.
- Medication statuses can be: Active, Discontinued.

DO NOT output markdown formatting like ```json.
"""

async def extract_memory_from_chats(patient_id: str):
    """
    Reads recent unprocessed chat logs for the patient, extracts facts using Gemini, 
    and updates the domain-driven care model tables with ePHI encryption.
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

    # 2. Fetch recent unprocessed chat logs
    try:
        chat_res = supabase.table("coach_chat_logs") \
            .select("id, role, message") \
            .eq("patient_id", patient_id) \
            .eq("processed_by_memory", False) \
            .order("created_at", desc=True) \
            .limit(20) \
            .execute()
        
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
        
        # Symptoms (Encrypted name)
        for ns in parsed.get("new_symptoms", []):
            name_raw = ns.get("name")
            if not name_raw:
                continue
            symp_id = str(uuid.uuid4())
            supabase.table("patient_symptoms").insert({
                "id": symp_id,
                "patient_id": patient_id,
                "name": encrypt_text(name_raw),
                "status": ns.get("status", "Active"),
                "severity": ns.get("severity", "Mild")
            }).execute()
            if ns.get("progression_note"):
                supabase.table("symptom_logs").insert({
                    "symptom_id": symp_id,
                    "patient_id": patient_id, 
                    "severity": ns.get("severity", "Mild"),
                    "status": ns.get("status", "Active"),
                    "note": ns.get("progression_note")
                }).execute()
                
        for us in parsed.get("updated_symptoms", []):
            if not us.get("id"):
                continue
            payload = {}
            if us.get("status"):
                payload["status"] = us.get("status")
            if us.get("severity"):
                payload["severity"] = us.get("severity")
            if us.get("name"):
                payload["name"] = encrypt_text(us.get("name"))
            if us.get("status") == "Resolved":
                payload["resolved_at"] = datetime.now(timezone.utc).isoformat()
            if payload:
                supabase.table("patient_symptoms").update(payload).eq("id", us.get("id")).execute()
            
            if us.get("progression_note"):
                supabase.table("symptom_logs").insert({
                    "symptom_id": us.get("id"),
                    "patient_id": patient_id, 
                    "severity": us.get("severity", "Mild"),
                    "status": us.get("status", "Active"),
                    "note": us.get("progression_note")
                }).execute()
                
        # Actions
        for na in parsed.get("new_actions", []):
            action_desc = na.get("description")
            if not action_desc:
                continue
            payload = {
                "patient_id": patient_id,
                "description": action_desc,
                "status": na.get("status", "Suggested")
            }
            if na.get("symptom_id"):
                payload["symptom_id"] = na.get("symptom_id")
            supabase.table("care_plan_actions").insert(payload).execute()
            
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
            
        # Flag chats as processed
        chat_ids = [c['id'] for c in chats]
        if chat_ids:
            supabase.table("coach_chat_logs").update({"processed_by_memory": True}).in_("id", chat_ids).execute()
            print(f"Successfully flagged {len(chat_ids)} chats as processed for {patient_id}")

    except Exception as e:
        print(f"Failed to update patient memory in DB: {e}")

async def process_inactive_chat_sessions():
    """
    Finds patients who have unprocessed chat logs (processed_by_memory == False)
    where the latest message was created > 5 minutes ago (patient is no longer typing).
    Extracts clinical memory facts and flags the logs as processed.
    """
    try:
        now = datetime.now(timezone.utc)
        
        # 1. Fetch unprocessed chat messages
        res = supabase.table("coach_chat_logs") \
            .select("patient_id, created_at") \
            .eq("processed_by_memory", False) \
            .order("created_at", desc=False) \
            .execute()
            
        if not res.data:
            return
            
        # 2. Group by patient_id and find the newest message timestamp
        patient_latest_msg = {}
        for row in res.data:
            pid = row["patient_id"]
            dt = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
            if pid not in patient_latest_msg or dt > patient_latest_msg[pid]:
                patient_latest_msg[pid] = dt
                
        # 3. Only process patients whose latest message is older than 5 minutes
        five_mins_ago = now - timedelta(minutes=5)
        ready_patients = [pid for pid, dt in patient_latest_msg.items() if dt <= five_mins_ago]
        
        for pid in ready_patients:
            print(f"Triggering memory extraction for {pid} (inactive for >5 mins)")
            await extract_memory_from_chats(pid)
            
    except Exception as e:
        print(f"Error in process_inactive_chat_sessions: {e}")
