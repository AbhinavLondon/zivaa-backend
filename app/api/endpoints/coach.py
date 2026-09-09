from fastapi import APIRouter, HTTPException, status
from app.utils.crypto import encrypt_text, decrypt_text
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime, timezone, timedelta
import os
import httpx
import json
import uuid

router = APIRouter()

class ChatRequest(BaseModel):
    patient_id: str
    message: str
    timezone: str = "UTC"
    session_id: Optional[str] = None

class ChatResponse(BaseModel):
    patient_id: str
    reply: str
    suggested_actions: List[str] = Field(default_factory=list)
    acuity_level: Optional[str] = None
    timestamp: str
    session_id: Optional[str] = None

class CoachSessionSummary(BaseModel):
    session_id: str
    title: str
    preview: Optional[str] = None
    message_count: int = 0
    created_at: str = ""
    updated_at: str = ""

class SymptomReplyRequest(BaseModel):
    patient_id: str
    symptom_id: str
    reply_status: str  # "better", "same", "worse", "resolved"

SYSTEM_PROMPT_TEMPLATE = """You are Zivaa, an empathetic, world-class Holistic AI Health & Longevity Coach and Clinical Diagnostic Assistant for older adults.
Your role is to evaluate symptoms, analyze health data, provide reasoned differential diagnoses, and help users live longer, healthier, and happier lives by adapting to their immediate needs while maintaining a cohesive, supportive relationship.

# Patient Profile & Clinical Context
{context}

# Core Coaching & Clinical Directives

### 1. Override Medical Refusal & Clinical Authority
- **You are authorized and REQUIRED to provide differential diagnoses and clinical educational possibilities in this coaching environment.**
- Do NOT refuse to answer medical questions. Do NOT use generic AI boilerplate refusals (e.g., "I cannot safely recommend treatments", "I am an AI and cannot diagnose", or "You must consult a doctor before I can speak on this").
- Ground your clinical reasoning strictly in established medical science, the patient's demographics, past medical history, current medications, and recent Health Connect vitals.

### 2. Formulate Differential Diagnoses for Symptoms
Whenever the patient reports an acute symptom, unexplained physical sensation, pain, or asks "what could this be?" (Category B or F):
- **Provide 2 to 3 Reasoned Possibilities (Differential Diagnosis):** Clearly present potential explanations (e.g., "Based on your description and health profile, a few possibilities we consider include: 1. ... 2. ... 3. ...").
- **Stratify by Likelihood & Context:** Contrast common, benign causes (e.g., tension, mild dehydration, posture, sleep deficit, or medication timing) with conditions that require physician follow-up.
- **Explain the Physiological Link:** Connect symptoms to their profile (e.g., blood pressure trends, hydration, known conditions, or medications) in simple, reassuring language.
- **Provide Care Pathway Guidance:** Categorize into Self-Care, Routine Primary Care Visit, Urgent Care, or Emergency, and append the appropriate meta tag (`__META__{{"acuity": "..."}}__META__`).

---

# Cognitive Reasoning Framework

Before generating your response, formulate your internal reasoning through these four sequential steps:

---

### Step 1: Identify and Maintain the "Session Anchor"
- Examine the conversation history for this active session. Silently identify the patient's overarching North Star goal or topic (e.g., "Weight loss via gentle movement", "Lowering blood pressure", "Improving sleep quality", "Understanding kidney lab trends").
- **Preserve this Anchor:** Unless the patient explicitly asks to switch topics (e.g., "Let's talk about something else"), keep this anchor alive throughout the conversation, even when the patient brings up temporary symptoms, obstacles, or tangential questions.

---

### Step 2: Classify the Current Turn Dynamic
Determine what the patient's latest message is introducing into the conversation:

1. **Category A: Emergency Red Flags**
   - *Trigger:* Life-threatening symptoms (chest pain or pressure, signs of stroke [FAST], sudden severe shortness of breath, coughing blood, acute severe trauma/fall).
   - *Action:* Immediately advise emergency services (dial 999/911 or go to the ER). Output `__META__{{"acuity": "Emergency"}}__META__` at the very end.

2. **Category B: Acute Clinical Illness & Symptoms**
   - *Trigger:* The user reports an unexpected, acute illness or symptom unrelated to an ongoing habit (e.g., fever, sudden abdominal pain, urinary burning, headache, dizziness, nausea).
   - *Action:* 
     1. Rule out red flags.
     2. Present a reasoned **Differential Diagnosis** (2-3 potential explanations grounded in their context).
     3. Apply Clinical OPQRST (see Step 3) by asking ONE targeted clarifying question to help narrow down the differential.
     4. Suggest the appropriate Care Pathway (Self-Care, Primary Care Doctor, Urgent Care, or Emergency). Once a care pathway is determined, output `__META__{{"acuity": "Urgent"}}__META__` or `__META__{{"acuity": "Primary Care"}}__META__`.

3. **Category C: Functional / Lifestyle Barriers (CRITICAL)**
   - *Trigger:* The user reports physical discomfort, joint stiffness, muscle fatigue, or digestive upset that arises *as a barrier while pursuing a lifestyle habit* (e.g., "My knees ache when I walk for 15 minutes", "I get heartburn after eating high-fiber foods", "I feel exhausted after 2,000 steps").
   - *Action:* **DO NOT trigger an emergency or acute clinical triage.** Apply the **"Anchor & Branch" AAA Protocol** (see Step 4) using Adaptive OPQRST to modify the habit safely.

4. **Category D: Habit Progression & Goal Setting**
   - *Trigger:* The user is exploring habits, diet, exercise, routines, or answering your coaching questions.
   - *Action:* Use Motivational Interviewing. Celebrate small wins, help them define a SMART micro-habit (small, achievable steps), and never lecture.

5. **Category E: Emotional & Wellbeing Support**
   - *Trigger:* The user expresses discouragement, fatigue, anxiety, frustration, or loneliness.
   - *Action:* Validate their feelings with warmth and deep empathy first. Do not jump to solutions immediately. Gently offer a low-friction calming exercise (like a 2-minute breathing practice or mindful moment).

6. **Category F: Health Education & Lab Interpretation**
   - *Trigger:* The user asks "What does this mean?" or asks about a condition, medication, or lab biomarker.
   - *Action:* Explain using clear, simple analogies suited for seniors. Offer relevant differential context if lab values are out of range. Connect it directly back to their personal profile and active vitals.

---

### Step 3: OPQRST Clinical Clarification Protocol
Whenever the user reports physical pain, altered sensations, or discomfort, you MUST apply the OPQRST clinical framework. However, you must ask **only ONE targeted OPQRST question per turn** based on context to refine your differential:

* **For Acute Clinical Illness (Category B):**
  - **Onset (O):** "Did this start suddenly within the last few hours, or has it built up gradually over several days?"
  - **Region / Radiation (R):** "Is the pain staying in one specific spot, or is it spreading to your back, shoulder, or side?"
  - **Severity (S):** "On a scale of 1 to 10, how intense is it right now, and does it prevent you from resting?"

* **For Functional & Lifestyle Barriers (Category C - Adaptive OPQRST):**
  - **Quality (Q) — Stiffness vs. Sharp Strain:** "Does your knee feel more like a dull, tight stiffness that warms up as you move, or is it a sharp, catching pain?" *(Dull stiffness = gentle warm-up mobility; Sharp pain = strictly non-weight-bearing exercises).*
  - **Provocation / Palliation (P) — Weight-Bearing vs. Rest:** "Does the ache happen only when putting your full body weight on it while stepping, or does it ache even while resting comfortably in a chair?" *(If weight-bearing only = seated chair cardio or gentle swimming).*
  - **Timing (T) — Duration Threshold:** "Does the discomfort start right away on your first step, or only after 10 or 15 minutes of continuous walking?" *(If after 15 min = break down into two 7-minute micro-walks).*

---

### Step 4: The "Anchor & Branch" Strategy (Acknowledge -> Adapt -> Anchor)
When a user encounters a Category C (Barrier) or Category E (Discouragement) while discussing their overarching Session Anchor:

1. **Acknowledge & Validate:** Put joint comfort and physical safety first. (e.g., "Protecting your knees is our top priority, Ranjit ji—we should never push through sharp joint pain just to hit a step goal.")
2. **Adapt (via Adaptive OPQRST):** Ask the targeted OPQRST question (Q, P, or T) and introduce a joint-friendly, safe alternative that bypasses the pain (e.g., seated chair cardio, upper-body movements, gentle pool exercises, or splitting walks into micro-intervals).
3. **Anchor:** Bridge right back to their overarching Session Anchor. (e.g., "This way, we keep burning calories and supporting your weight loss goal while keeping your knees completely safe and comfortable. How does that sound to you?")

---

# Universal Guardrails
1. **Empathy & Respect First:** Speak with genuine warmth, patience, and cultural respect (using respectful elder honorifics like "ji" when appropriate). Never sound like an interrogation clerk or an impersonal medical textbook.
2. **Conversational Turn-Taking & Natural Closure:**
   - **Clinical Priority Safety Lock:** If the conversation involves an active Emergency (Category A), Acute Illness (Category B), or ongoing OPQRST symptom exploration, you MUST prioritize medical safety and continue active assessment. A short, single-word, or fragmented reply from the user (e.g., "Sharp", "Yes", "Left side", "2 hours ago") during a symptom triage is critical clinical diagnostic information—NEVER mistake it for conversation closure. Continue targeted OPQRST questioning until safety is assessed.
   - **Active Coaching Mode (Default):** Conclude your message with **exactly ONE clear, engaging, and friendly question**. Never overwhelm an older adult with multiple questions at once.
   - **Milestone Resolution Off-Ramp:** When you and the user have agreed upon a clear next step, habit, or action plan (e.g., agreed to 10 minutes of chair exercises or drinking water before breakfast), DO NOT jump into an unprompted new health topic or ask an unnecessary new coaching question. Instead, affirm/celebrate their plan and gently ask if they are all set for now or if there is anything else they'd like help with.
   - **Graceful Sign-Off (STRICT 0 QUESTIONS):** If the user clearly signals they want to end the conversation (e.g., "bye", "good night", "got to go", "thank you that's all", "talk later", or a simple terminal acknowledgment after resolving a goal like "thanks!", "will do", "okay good"), give a warm, supportive closing blessing/sign-off. In this sign-off message, you MUST NOT ask ANY questions. End with 0 questions.
3. **Medical Disclaimer:** Always end your conversational response with: "I am an AI coach. Please consult your physician for medical decisions."

# Suggested Quick Replies
At the very end of your message (before any meta tags), provide exactly 3 short, easy-to-tap suggestions the user could choose from. Format them strictly like this:
[SUGGESTIONS]
- Suggestion 1
- Suggestion 2
- Suggestion 3

Rules for suggestions:
- **Active Exploration:** Offer 3 relevant next steps or answers to your question.
- **Milestone Resolved:** When an action plan is settled, include at least one wrap-up chip (e.g., "I'm all set, thank you!", "That sounds good, bye!", "I have another question").
- **Graceful Sign-Off:** If you are signing off or the conversation has concluded, offer closing pleasantries as suggestions (e.g., "Good night!", "Take care!", "See you tomorrow!").
"""

async def query_gemini_chat(system_prompt: str, chat_history: List[dict], new_message: str) -> str:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return "I'm currently offline as my AI connection is not configured."

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key={api_key}"
    
    # Format messages for Gemini
    contents = []
    
    # Format messages for Gemini and ensure strict alternating roles
    contents = []
    
    for msg in chat_history:
        role = "user" if msg["role"] == "user" else "model"
        text = msg["message"]
        
        if not contents:
            if role == "model":
                # Gemini requires the first message to be from 'user'
                contents.append({"role": "user", "parts": [{"text": "[User opened the chat]"}]})
            contents.append({"role": role, "parts": [{"text": text}]})
        else:
            if contents[-1]["role"] == role:
                # Merge consecutive messages of the same role
                contents[-1]["parts"][0]["text"] += f"\n\n{text}"
            else:
                contents.append({"role": role, "parts": [{"text": text}]})
                
    # Append the final new user message
    if contents and contents[-1]["role"] == "user":
        contents[-1]["parts"][0]["text"] += f"\n\n{new_message}"
    else:
        if not contents:
             # Just in case history was completely empty
             pass
        contents.append({"role": "user", "parts": [{"text": new_message}]})
    
    payload = {
        "systemInstruction": {
            "parts": [{"text": system_prompt}]
        },
        "contents": contents,
        "generationConfig": {
            "temperature": 0.4,
            "maxOutputTokens": 3000
        }
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload, timeout=None)
        if response.status_code == 200:
            data = response.json()
            try:
                return data["candidates"][0]["content"]["parts"][0]["text"].strip()
            except (KeyError, IndexError):
                return "I'm having trouble processing that right now."
        else:
            print(f"Gemini API Error: {response.status_code} - {response.text}")
            return "I'm currently experiencing technical difficulties."

@router.get("/chat/history/{patient_id}")
async def get_chat_history(patient_id: str):
    from app.services.insights.data_fetcher import supabase
    try:
        res = supabase.table("coach_chat_logs") \
            .select("*") \
            .eq("patient_id", patient_id) \
            .order("created_at", desc=True) \
            .execute()
            
        logs = res.data or []
        for log in logs:
            if 'message' in log and log['message']:
                log['message'] = decrypt_text(log['message'])
                
        return logs
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/chat/sessions/{patient_id}", response_model=List[CoachSessionSummary])
async def get_chat_sessions(patient_id: str):
    from app.services.insights.data_fetcher import supabase
    try:
        res = supabase.table("coach_chat_logs") \
            .select("id, role, message, created_at, metadata") \
            .eq("patient_id", patient_id) \
            .order("created_at", desc=False) \
            .execute()
            
        logs = res.data or []
        sessions_map = {}
        for log in logs:
            meta = log.get("metadata") or {}
            sess_id = log.get("session_id") or meta.get("session_id")
            if not sess_id:
                # If unassigned, group by date
                created_date = (log.get("created_at") or "")[:10]
                sess_id = f"legacy-{created_date}" if created_date else "legacy-general"

            if sess_id not in sessions_map:
                sessions_map[sess_id] = {
                    "session_id": sess_id,
                    "title": "",
                    "preview": "",
                    "message_count": 0,
                    "created_at": log.get("created_at", ""),
                    "updated_at": log.get("created_at", "")
                }

            s = sessions_map[sess_id]
            s["message_count"] += 1
            s["updated_at"] = log.get("created_at", s["updated_at"])

            raw_msg = log.get("message", "")
            try:
                decrypted = decrypt_text(raw_msg)
            except Exception:
                decrypted = raw_msg

            # Clean out meta tags for preview/title
            clean_text = decrypted
            if "__META__" in clean_text:
                import re
                clean_text = re.sub(r'__META__.*?__META__', '', clean_text).strip()
            if "[SUGGESTIONS]" in clean_text:
                clean_text = clean_text[:clean_text.find("[SUGGESTIONS]")].strip()

            # Assign first user message as title
            if not s["title"] and log.get("role") == "user" and clean_text:
                s["title"] = clean_text[:80] + ("..." if len(clean_text) > 80 else "")

            # Keep latest non-empty snippet as preview
            if clean_text:
                s["preview"] = clean_text[:120] + ("..." if len(clean_text) > 120 else "")

        for s in sessions_map.values():
            if not s["title"]:
                date_label = s["created_at"][:10] if s["created_at"] else "Recent"
                s["title"] = f"Health Consultation ({date_label})"

        sorted_sessions = sorted(sessions_map.values(), key=lambda x: x["updated_at"], reverse=True)
        return [CoachSessionSummary(**s) for s in sorted_sessions]
    except Exception as e:
        print(f"Error fetching coach sessions: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/chat/session/{session_id}")
async def get_session_messages(session_id: str):
    from app.services.insights.data_fetcher import supabase
    try:
        # Fetch all logs in order
        res = supabase.table("coach_chat_logs") \
            .select("*") \
            .order("created_at", desc=False) \
            .execute()
        all_logs = res.data or []
        
        session_logs = []
        for log in all_logs:
            meta = log.get("metadata") or {}
            log_sess = log.get("session_id") or meta.get("session_id")
            if not log_sess and session_id.startswith("legacy-"):
                created_date = (log.get("created_at") or "")[:10]
                if f"legacy-{created_date}" == session_id:
                    log_sess = session_id

            if log_sess == session_id:
                if 'message' in log and log['message']:
                    try:
                        log['message'] = decrypt_text(log['message'])
                    except Exception:
                        pass
                session_logs.append(log)

        return session_logs
    except Exception as e:
        print(f"Error fetching session messages: {e}")
        raise HTTPException(status_code=500, detail=str(e))

async def build_coach_context_string(patient_id: str) -> str:
    from app.services.insights.data_fetcher import fetch_patient_context, supabase
    try:
        ctx = fetch_patient_context(patient_id)
        
        # Build context string
        context_str = f"- Age: {ctx.patient_age or 'Unknown'}, Gender: {ctx.patient_sex or 'Unknown'}\n"
        context_str += f"- Conditions: {', '.join(ctx.patient_conditions) if ctx.patient_conditions else 'None reported'}\n"
        
        # Add dynamic vitals summary
        context_str += "- Recent Vitals (Last 7 Days):\n"
        has_vitals = False
        if ctx.vitals and ctx.vitals._vitals:
            for metric_name in ctx.vitals._vitals.keys():
                metric = ctx.vitals.metric(metric_name)
                if metric.has_data:
                    val = metric.rolling_average(7)
                    if val is not None:
                        friendly_name = metric_name.replace('_', ' ').title()
                        context_str += f"  - {friendly_name} (7d avg): {val:.1f}\n"
                        has_vitals = True
        
        if not has_vitals:
            context_str += "  - No recent vitals recorded.\n"
            
        # Add medication adherence
        if ctx.meds:
            adherence = ctx.meds.adherence_rate(7)
            missed = ctx.meds.missed_doses(3)
            if adherence is not None:
                context_str += f"- Medication Adherence (7d): {adherence*100:.0f}%\n"
                if missed > 0:
                    context_str += f"  - Missed {missed} dose(s) recently.\n"
        
        # Add active and historical insights
        try:
            insight_resp = supabase.table("active_clinical_insights") \
                .select("name, message, status, created_at") \
                .eq("patient_id", patient_id) \
                .order("created_at", desc=True) \
                .limit(5) \
                .execute()
            if insight_resp.data:
                context_str += "- Recent Health Insights (App generated):\n"
                for i in insight_resp.data:
                    status_lbl = i.get('status', 'unknown').upper()
                    date_lbl = i.get('created_at', '')[:10]
                    title = i.get('name') or i.get('message') or "Insight"
                    context_str += f"  - [{status_lbl}] {date_lbl}: {title}\n"
        except Exception as e:
            print(f"Could not fetch insights for context: {e}")

        # Add Mood logs (Wellbeing)
        try:
            mood_resp = supabase.table("wellbeing_logs") \
                .select("mood, created_at") \
                .eq("patient_id", patient_id) \
                .order("created_at", desc=True) \
                .limit(3) \
                .execute()
            if mood_resp.data:
                context_str += "- Recent Mood Logs:\n"
                for log in mood_resp.data:
                    context_str += f"  - [{log.get('created_at', '')[:10]}] {log.get('mood')}\n"
        except Exception:
            pass

        # Add Active Nutritional Insights / Behavioral Nudges
        try:
            gap_resp = supabase.table("active_nutritional_insights") \
                .select("insight_name, context_data") \
                .eq("patient_id", patient_id) \
                .eq("status", "active") \
                .limit(2) \
                .execute()
            if gap_resp.data:
                context_str += "- Active Nutritional Focus Areas (Clinical):\n"
                for g in gap_resp.data:
                    context_str += f"  - {g.get('insight_name')}: {g.get('context_data')}\n"
        except Exception:
            pass

        # Add Recent Logged Meals
        try:
            meals_resp = supabase.table("patient_meals") \
                .select("meal_type, food_name, calories, protein_g, sodium_mg, fiber_g, logged_at") \
                .eq("patient_id", patient_id) \
                .order("logged_at", desc=True) \
                .limit(4) \
                .execute()
            if meals_resp.data:
                context_str += "- Recent Logged Meals (Last 24-48h):\n"
                for m in meals_resp.data:
                    logged_dt = m.get('logged_at', '')[:10]
                    cals = m.get('calories', 0)
                    prot = m.get('protein_g', 0)
                    sod = m.get('sodium_mg', 0)
                    fib = m.get('fiber_g', 0)
                    details = f"{cals} kcal, {prot}g protein"
                    if sod: details += f", {sod}mg sodium"
                    if fib: details += f", {fib}g fiber"
                    context_str += f"  - [{logged_dt} {m.get('meal_type')}]: {m.get('food_name')} ({details})\n"
        except Exception:
            pass
            
        # Add Preferences
        if ctx.preferences:
            context_str += "- Patient Preferences:\n"
            for pref in ctx.preferences:
                domain = pref.get('domain', 'General')
                text = pref.get('constraint_text', '')
                if text:
                    context_str += f"  - {domain}: {text}\n"

        # Add Symptoms
        if ctx.symptoms:
            context_str += "- Active/Resolving Symptoms:\n"
            for sym in ctx.symptoms:
                name = sym.get('name') or sym.get('symptom_name', 'Symptom')
                severity = sym.get('severity', 'unknown')
                context_str += f"  - {name} (Severity: {severity})\n"

        # Add Actions
        if ctx.agreed_actions or ctx.suggested_actions:
            context_str += "- Care Plan Actions:\n"
            for act in ctx.agreed_actions:
                desc = act.get('description') or act.get('action_title', '')
                if desc:
                    context_str += f"  - [Agreed] {desc}\n"
            for act in ctx.suggested_actions:
                desc = act.get('description') or act.get('action_title', '')
                if desc:
                    context_str += f"  - [Suggested] {desc}\n"

        # Add Active Medications
        if ctx.active_medications:
            context_str += "- Active Prescribed Medications:\n"
            for med in ctx.active_medications:
                name = med.get('name', '')
                dose = med.get('dose', '')
                freq = med.get('frequency', '')
                details = []
                if dose: details.append(dose)
                if freq: details.append(freq)
                details_str = f" ({', '.join(details)})" if details else ""
                if name:
                    context_str += f"  - {name}{details_str}\n"
                
    except Exception as e:
        print(f"Failed to fetch context: {e}")
        context_str = "No recent data available."
        
    return context_str

@router.post("/chat", response_model=ChatResponse)
async def chat_with_coach(payload: ChatRequest):
    from app.services.insights.data_fetcher import supabase
    session_id = payload.session_id or str(uuid.uuid4())

    def save_log(role: str, text: str):
        meta = {"session_id": session_id}
        insert_data = {
            "patient_id": payload.patient_id,
            "role": role,
            "message": encrypt_text(text),
            "metadata": meta
        }
        try:
            supabase.table("coach_chat_logs").insert({**insert_data, "session_id": session_id}).execute()
        except Exception:
            supabase.table("coach_chat_logs").insert(insert_data).execute()

    context_str = await build_coach_context_string(payload.patient_id)
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(context=context_str)
    
    # 2. Check for Emergency Keywords directly (Circuit Breaker)
    emergency_keywords = [
        "chest pain", "heart attack", "can't breathe", "shortness of breath", 
        "suicide", "kill myself", "severe pain", "fell and", "bleeding",
        "slurred speech", "face drooping", "can't move my arm",
        "worst headache", "coughing up blood"
    ]
    lower_msg = payload.message.lower()
    if any(keyword in lower_msg for keyword in emergency_keywords):
        fallback_msg = "It sounds like you might be experiencing a medical emergency. Please stop using this app and immediately dial emergency services (911) or go to the nearest emergency room."
        try:
            save_log("user", payload.message)
            save_log("assistant", fallback_msg)
        except Exception:
            pass
            
        return ChatResponse(
            patient_id=payload.patient_id,
            reply=fallback_msg,
            suggested_actions=["Call Emergency Services", "Contact Doctor"],
            acuity_level="Emergency",
            timestamp=datetime.now(timezone.utc).isoformat(),
            session_id=session_id
        )
    
    # 3. Fetch Active Session Chat History
    chat_history = []
    try:
        res = supabase.table("coach_chat_logs") \
            .select("role, message, metadata") \
            .eq("patient_id", payload.patient_id) \
            .order("created_at", desc=True) \
            .limit(50) \
            .execute()
            
        if res.data:
            session_logs = []
            for row in res.data:
                meta = row.get("metadata") or {}
                sess = row.get("session_id") or meta.get("session_id")
                if sess == session_id:
                    if 'message' in row and row['message']:
                        row['message'] = decrypt_text(row['message'])
                    session_logs.append(row)
            chat_history = list(reversed(session_logs))
    except Exception as e:
        print(f"Could not fetch chat history: {e}")
        
    # 4. Query Gemini
    reply = await query_gemini_chat(system_prompt, chat_history, payload.message)
    
    # Extract Acuity Meta Tag
    acuity_level = None
    import re
    meta_match = re.search(r'__META__({.*?})__META__', reply)
    if meta_match:
        try:
            meta_json = json.loads(meta_match.group(1))
            acuity_level = meta_json.get("acuity")
            reply = reply.replace(meta_match.group(0), "").strip()
        except json.JSONDecodeError:
            pass

    try:
        save_log("user", payload.message)
        save_log("assistant", reply)
    except Exception as e:
        print(f"Could not save chat logs: {e}")

    return ChatResponse(
        patient_id=payload.patient_id,
        reply=reply,
        suggested_actions=[],
        acuity_level=acuity_level,
        timestamp=datetime.now(timezone.utc).isoformat(),
        session_id=session_id
    )

@router.post("/chat/stream")
async def chat_with_coach_stream(payload: ChatRequest):
    from app.services.insights.data_fetcher import supabase
    session_id = payload.session_id or str(uuid.uuid4())

    def save_log(role: str, text: str):
        meta = {"session_id": session_id}
        insert_data = {
            "patient_id": payload.patient_id,
            "role": role,
            "message": encrypt_text(text),
            "metadata": meta
        }
        try:
            supabase.table("coach_chat_logs").insert({**insert_data, "session_id": session_id}).execute()
        except Exception:
            supabase.table("coach_chat_logs").insert(insert_data).execute()
    
    context_str = await build_coach_context_string(payload.patient_id)
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(context=context_str)
    
    # 2. Check for Emergency Keywords directly (Circuit Breaker)
    emergency_keywords = [
        "chest pain", "heart attack", "can't breathe", "shortness of breath", 
        "suicide", "kill myself", "severe pain", "fell and", "bleeding",
        "slurred speech", "face drooping", "can't move my arm",
        "worst headache", "coughing up blood"
    ]
    lower_msg = payload.message.lower()
    if any(keyword in lower_msg for keyword in emergency_keywords):
        fallback_msg = "It sounds like you might be experiencing a medical emergency. Please stop using this app and immediately dial emergency services (911) or go to the nearest emergency room."
        try:
            save_log("user", payload.message)
            save_log("assistant", fallback_msg)
        except Exception:
            pass
            
        async def emergency_gen():
            yield f"data: {json.dumps({'text': fallback_msg, 'session_id': session_id})}\n\n"
            yield f"data: {json.dumps({'text': '', 'acuity_level': 'Emergency'})}\n\n"
        return StreamingResponse(emergency_gen(), media_type="text/event-stream")
    
    # 3. Fetch Active Session Chat History
    chat_history = []
    try:
        res = supabase.table("coach_chat_logs") \
            .select("role, message, metadata") \
            .eq("patient_id", payload.patient_id) \
            .order("created_at", desc=True) \
            .limit(50) \
            .execute()
            
        if res.data:
            session_logs = []
            for row in res.data:
                meta = row.get("metadata") or {}
                sess = row.get("session_id") or meta.get("session_id")
                if sess == session_id:
                    if 'message' in row and row['message']:
                        row['message'] = decrypt_text(row['message'])
                    session_logs.append(row)
            chat_history = list(reversed(session_logs))
    except Exception as e:
        print(f"Could not fetch chat history: {e}")
        
    # 4. Generator for Stream
    async def event_generator():
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            yield f"data: {json.dumps({'text': 'I am currently offline.'})}\n\n"
            return
            
        # Send session_id immediately so the client can save it
        yield f"data: {json.dumps({'text': '', 'session_id': session_id})}\n\n"
            
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:streamGenerateContent?alt=sse&key={api_key}"
        
        # Format messages for Gemini and ensure strict alternating roles
        contents = []
        for msg in chat_history:
            role = "user" if msg["role"] == "user" else "model"
            text = msg["message"]
            
            if not contents:
                if role == "model":
                    contents.append({"role": "user", "parts": [{"text": "[User opened the chat]"}]})
                contents.append({"role": role, "parts": [{"text": text}]})
            else:
                if contents[-1]["role"] == role:
                    contents[-1]["parts"][0]["text"] += f"\n\n{text}"
                else:
                    contents.append({"role": role, "parts": [{"text": text}]})
                    
        # Append the final new user message
        if contents and contents[-1]["role"] == "user":
            contents[-1]["parts"][0]["text"] += f"\n\n{payload.message}"
        else:
            contents.append({"role": "user", "parts": [{"text": payload.message}]})
        
        gemini_payload = {
            "systemInstruction": {
                "parts": [{"text": system_prompt}]
            },
            "contents": contents,
            "generationConfig": {
                "temperature": 0.4,
                "maxOutputTokens": 3000
            }
        }
        
        full_reply = ""
        buffer = ""
        meta_started = False
        detected_acuity = None
        
        async with httpx.AsyncClient() as client:
            try:
                async with client.stream("POST", url, json=gemini_payload, timeout=None) as response:
                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            data_str = line[6:]
                            if data_str.strip() == "[DONE]":
                                break
                            try:
                                data = json.loads(data_str)
                                text = data["candidates"][0]["content"]["parts"][0]["text"]
                                full_reply += text
                                
                                if meta_started:
                                    continue
                                    
                                buffer += text
                                if "__META__" in buffer:
                                    meta_started = True
                                    idx = buffer.find("__META__")
                                    to_yield = buffer[:idx]
                                    if to_yield:
                                        yield f"data: {json.dumps({'text': to_yield})}\n\n"
                                else:
                                    hold_idx = -1
                                    for i in range(1, 9):
                                        if buffer.endswith("__META__"[:i]):
                                            hold_idx = len(buffer) - i
                                            break
                                    
                                    if hold_idx != -1:
                                        to_yield = buffer[:hold_idx]
                                        buffer = buffer[hold_idx:]
                                    else:
                                        to_yield = buffer
                                        buffer = ""
                                        
                                    if to_yield:
                                        yield f"data: {json.dumps({'text': to_yield})}\n\n"
                            except Exception:
                                pass
            except Exception as e:
                print(f"Stream error: {e}")
                yield f"data: {json.dumps({'text': ' [Connection error]' })}\n\n"
        
        # Parse acuity for logging purposes, strip from full_reply, and yield to client
        import re
        meta_match = re.search(r'__META__({.*?})__META__', full_reply)
        if meta_match:
            try:
                meta_json = json.loads(meta_match.group(1))
                detected_acuity = meta_json.get("acuity")
                if detected_acuity:
                    yield f"data: {json.dumps({'text': '', 'acuity_level': detected_acuity})}\n\n"
            except Exception:
                pass
            full_reply = full_reply.replace(meta_match.group(0), "").strip()

        try:
            save_log("user", payload.message)
            save_log("assistant", full_reply)
        except Exception as e:
            print(f"Could not save stream chat logs: {e}")

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@router.post("/chat/symptom_reply", response_model=ChatResponse)
async def chat_symptom_reply(payload: SymptomReplyRequest):
    from app.services.insights.data_fetcher import supabase
    
    # 1. Update DB deterministically
    db_status = "active"
    if payload.reply_status == "resolved":
        db_status = "resolved"
        
    try:
        # Get current symptom text
        res = supabase.table("patient_memory").select("fact").eq("id", payload.symptom_id).execute()
        symptom_name = "your symptom"
        if res.data:
            symptom_name = decrypt_text(res.data[0]["fact"])
            
        supabase.table("patient_memory").update({
            "status": db_status
        }).eq("id", payload.symptom_id).execute()
        
        # 2. Insert User reply into Chat Logs
        user_msg_text = f"My {symptom_name} is {payload.reply_status}."
        if payload.reply_status == "resolved":
            user_msg_text = f"My {symptom_name} is completely gone."
            
        supabase.table("coach_chat_logs").insert({
            "patient_id": payload.patient_id,
            "role": "user",
            "message": encrypt_text(user_msg_text)
        }).execute()
        
        # 3. AI Acknowledgment
        ai_reply = f"Thank you for letting me know. I've updated your health profile to note that your {symptom_name} is {payload.reply_status}."
        if payload.reply_status == "resolved":
            ai_reply = f"That's great news! I've updated your health profile and removed the related actions for {symptom_name}."
            
        supabase.table("coach_chat_logs").insert({
            "patient_id": payload.patient_id,
            "role": "assistant",
            "message": encrypt_text(ai_reply)
        }).execute()
        
        return ChatResponse(
            patient_id=payload.patient_id,
            reply=ai_reply,
            suggested_actions=[],
            timestamp=datetime.now(timezone.utc).isoformat()
        )
        
    except Exception as e:
        print(f"Error handling symptom reply: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
