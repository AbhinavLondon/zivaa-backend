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
