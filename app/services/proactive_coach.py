import httpx
import os
import uuid
from datetime import datetime, timezone
from app.services.insights.data_fetcher import fetch_patient_context, supabase
from app.services.notification_templates import dispatch_notification, NotificationType

PROACTIVE_PROMPT_TEMPLATE = """You are Zivaa, an empathetic AI Health Coach for older adults.
Your role right now is to initiate a proactive conversation with your patient.

# Patient Profile
{context}

# Trigger Details
{trigger_instructions}

# Guidelines
1. Write a short, warm, and natural opening message (1 to 3 sentences maximum).
2. Do NOT act like a robot. Speak like a caring human coach checking in.
3. If this is a clinical alert, be supportive and ask if they are okay or experiencing symptoms.
4. If this is a memory follow-up, ask how they are feeling regarding their previous symptom.
5. End with an open-ended question to encourage them to reply.
6. Do NOT include any JSON, markdown, or placeholder text. Just the exact message you want to send.
"""

async def generate_proactive_message(patient_id: str, trigger_type: str, trigger_context: str, metadata: dict = None):
    """
    Generates and sends a proactive chat message to the patient.
    """
    print(f"Triggering proactive outreach for {patient_id}. Reason: {trigger_type}")
    
    # 1. Fetch Patient Context
    try:
        ctx = fetch_patient_context(patient_id)
        
        context_str = f"- Age: {ctx.patient_age or 'Unknown'}, Gender: {ctx.patient_sex or 'Unknown'}\n"
        context_str += f"- Conditions: {', '.join(ctx.patient_conditions) if ctx.patient_conditions else 'None reported'}\n"
        
        preferences = getattr(ctx, 'preferences', [])
        symptoms = getattr(ctx, 'symptoms', [])
        mem_lines = []
        if preferences:
            mem_lines.extend([f"  - (Preference: {p.get('domain', 'General')}) {p.get('constraint_text', '')}" for p in preferences[:3]])
        if symptoms:
            mem_lines.extend([f"  - (Symptom) {s.get('name', '')} (Severity: {s.get('severity', '')}, Status: {s.get('status', '')})" for s in symptoms[:3]])
        
        if mem_lines:
            context_str += "- Recent Context (from past chats):\n" + "\n".join(mem_lines) + "\n"
            
    except Exception as e:
        print(f"Failed to fetch context for proactive message: {e}")
        context_str = "No recent data available."
        
    # 2. Build Prompt
    trigger_instructions = f"Trigger Type: {trigger_type}\nContext: {trigger_context}\n\nPlease generate the opening message."
    prompt = PROACTIVE_PROMPT_TEMPLATE.format(context=context_str, trigger_instructions=trigger_instructions)
    
    # 3. Query Gemini directly
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        from app.config import settings
        api_key = settings.GEMINI_API_KEY
        if not api_key or api_key == "your-api-key-here":
            print("Skipping proactive message: GEMINI_API_KEY not set.")
            return
        
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.5,
            "maxOutputTokens": 1500
        }
    }
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, timeout=20.0)
            if response.status_code == 200:
                data = response.json()
                reply = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                
                # 4. Save to Database
                insert_meta = dict(metadata or {})
                if "session_id" not in insert_meta:
                    insert_meta["session_id"] = str(uuid.uuid4())

                insert_payload = {
                    "patient_id": patient_id,
                    "role": "assistant",
                    "message": reply,
                    "metadata": insert_meta
                }
                try:
                    supabase.table("coach_chat_logs").insert([{**insert_payload, "session_id": insert_meta["session_id"]}]).execute()
                except Exception:
                    supabase.table("coach_chat_logs").insert([insert_payload]).execute()
                
                # 5. Dispatch Notification
                token_res = supabase.table("device_tokens").select("fcm_token").eq("patient_id", patient_id).execute()
                if token_res.data and token_res.data[0].get("fcm_token"):
                    fcm_token = token_res.data[0]["fcm_token"]
                    n_type = NotificationType.SYMPTOM_CHECKIN if trigger_type == "SYMPTOM_FOLLOWUP" else NotificationType.COACH_MESSAGE
                    dispatch_notification(
                        fcm_token=fcm_token,
                        notification_type=n_type,
                        dynamic_body=reply,
                        extra_data=metadata if trigger_type == "SYMPTOM_FOLLOWUP" else None
                    )
                    print(f"Proactive message sent to {patient_id}")
                else:
                    print(f"Message generated but no FCM token found for {patient_id}")
            else:
                print(f"Failed to generate proactive message: {response.text}")
    except Exception as e:
        print(f"Proactive outreach failed: {e}")


SYMPTOM_FOLLOWUP_PROMPT_TEMPLATE = """# CLINICAL PERSONA & OBJECTIVE
You are Coach Zivaa. You are reaching out to check on {patient_name} regarding a symptom they previously reported.
Your goal is to conduct a brief, caring clinical follow-up to evaluate their SYMPTOM TRAJECTORY.

# SYMPTOM CONTEXT:
- Symptom: {symptom_name}
- Anatomical Site: {anatomical_site}
- Initial Severity: {baseline_severity}
- Days Active: {days_active} of max {max_self_care_days} days
- Recent Interventions Prescribed: {recent_actions_list}
- Last Recorded Feedback: {last_feedback}

# CLINICAL COMMUNICATION RULES:
1. FUNCTIONAL OUTCOME FOCUS:
   - In older adults, pain numbers (1-10) are less informative than functional abilities.
   - Frame your inquiry around functional milestones:
     * For Joints/Back: "Are you able to take your steps more comfortably today?" or "Did morning stiffness ease up faster?"
     * For Sleep/Headache: "Did you manage to sleep through the night without discomfort waking you?"
     * For Digestion/GERD: "Did you feel comfortable after your lunch today?"

2. WARM, RESPECTFUL TONE:
   - Address the patient with respect (use 'ji' suffix, e.g. '{patient_name} ji').
   - Never sound like an automated survey (DO NOT SAY: "Please rate your pain on a scale of 1 to 10 for our records").
   - Speak like an attentive family doctor calling in.

3. CONVERSATIONAL TAPPABLE CHIPS:
   - At the end of the message, output exactly 3 first-person quick replies written in the patient's voice preceded by [SUGGESTIONS]:
     [SUGGESTIONS]
     - It's feeling much better today
     - About the same, still a bit stiff
     - It felt more uncomfortable today
"""


async def generate_symptom_followup(patient_id: str, symptom: dict):
    """
    Generates a clinically-grounded proactive symptom check-in focusing on functional milestones.
    Saves to coach_chat_logs and dispatches push notification.
    """
    from app.utils.crypto import decrypt_text
    
    raw_name = symptom.get("name") or "symptom"
    symptom_name = decrypt_text(raw_name) if raw_name else "symptom"
    anatomical_site = symptom.get("anatomical_site") or "affected area"
    baseline_sev = symptom.get("severity") or "Moderate"
    max_days = symptom.get("max_self_care_days") or 14
    symptom_id = symptom.get("id")

    # Calculate days active
    days_active = 1
    c_str = symptom.get("created_at")
    if c_str:
        try:
            c_dt = datetime.fromisoformat(c_str.replace("Z", "+00:00"))
            days_active = max(1, (datetime.now(timezone.utc) - c_dt).days)
        except Exception:
            days_active = 1

    # Fetch patient name
    p_name = "ji"
    try:
        p_res = supabase.table("patients").select("full_name").eq("id", patient_id).execute()
        if p_res.data and p_res.data[0].get("full_name"):
            full = p_res.data[0]["full_name"].strip()
            p_name = full.split()[0]
    except Exception:
        pass

    # Fetch recent actions and feedback
    actions_list = []
    last_fb = "No feedback logged yet"
    try:
        act_res = supabase.table("care_plan_actions").select("description").eq("patient_id", patient_id).limit(3).execute()
        if act_res.data:
            actions_list = [a.get("description") for a in act_res.data if a.get("description")]
        
        fb_res = supabase.table("symptom_logs").select("micro_feedback, note").eq("symptom_id", symptom_id).order("created_at", desc=True).limit(1).execute()
        if fb_res.data:
            last_fb = fb_res.data[0].get("micro_feedback") or fb_res.data[0].get("note") or last_fb
    except Exception as e:
        print(f"Error fetching recent symptom history for check-in: {e}")

    actions_str = ", ".join(actions_list) if actions_list else "gentle rest and heat/cold pack"

    prompt = SYMPTOM_FOLLOWUP_PROMPT_TEMPLATE.format(
        patient_name=p_name,
        symptom_name=symptom_name,
        anatomical_site=anatomical_site,
        baseline_severity=baseline_sev,
        days_active=days_active,
        max_self_care_days=max_days,
        recent_actions_list=actions_str,
        last_feedback=last_fb
    )

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        from app.config import settings
        api_key = settings.GEMINI_API_KEY
    if not api_key or api_key == "your-api-key-here":
        print("Skipping symptom followup: GEMINI_API_KEY not configured.")
        return

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.4,
            "maxOutputTokens": 600
        }
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, timeout=25.0)
            if resp.status_code == 200:
                raw_reply = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                
                # Parse suggestions
                suggestions = ["It's feeling much better today", "About the same, still a bit stiff", "It felt more uncomfortable today"]
                clean_message = raw_reply
                if "[SUGGESTIONS]" in raw_reply:
                    parts = raw_reply.split("[SUGGESTIONS]")
                    clean_message = parts[0].strip()
                    parsed_suggs = [s.strip().lstrip("-").strip() for s in parts[1].strip().split("\n") if s.strip()]
                    if parsed_suggs:
                        suggestions = parsed_suggs[:3]

                session_id = str(uuid.uuid4())
                meta = {
                    "type": "symptom_checkin",
                    "symptom_id": symptom_id,
                    "symptom_name": symptom_name,
                    "anatomical_site": anatomical_site,
                    "options": suggestions,
                    "session_id": session_id
                }

                insert_payload = {
                    "patient_id": patient_id,
                    "role": "assistant",
                    "message": clean_message,
                    "metadata": meta,
                    "session_id": session_id
                }
                supabase.table("coach_chat_logs").insert([insert_payload]).execute()

                # Dispatch FCM notification
                token_res = supabase.table("device_tokens").select("fcm_token").eq("patient_id", patient_id).execute()
                if token_res.data and token_res.data[0].get("fcm_token"):
                    dispatch_notification(
                        fcm_token=token_res.data[0]["fcm_token"],
                        notification_type=NotificationType.SYMPTOM_CHECKIN,
                        dynamic_body=clean_message,
                        extra_data=meta
                    )
                print(f"[Proactive Coach] Successfully dispatched symptom check-in for {symptom_name} to patient {patient_id}")
            else:
                print(f"Error calling Gemini for symptom followup: {resp.text}")
    except Exception as err:
        print(f"Failed to generate and send symptom followup: {err}")
