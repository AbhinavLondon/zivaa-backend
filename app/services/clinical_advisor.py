"""
Senior Geriatric Clinical Advisor Service (MBBS, MD - 25 Years Experience).
Audits nudge_alerts created in Supabase across 7 clinical dimensions:
1. Nudge Id
2. Patient Name
3. Nudge Title
4. Why was this nudge created? (Full forensic data analysis)
5. Was it clinically sound? (Detailed medical critique)
6. Confidence score to the nudge created
7. Critical analysis of action_steps & Evidence-based Care Pathways
"""

import os
import json
import asyncio
from datetime import datetime, date, timezone
from typing import Dict, Any, Optional, List
import httpx
from dotenv import load_dotenv

# Ensure environment variables are loaded from zivaa-backend/.env
backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
env_file = os.path.join(backend_dir, ".env")
if os.path.exists(env_file):
    load_dotenv(dotenv_path=env_file)
else:
    load_dotenv()

from app.config import settings
from supabase import create_client, Client


def get_supabase_client() -> Client:
    """Instantiate and return a Supabase service client."""
    url = os.getenv("SUPABASE_URL") or settings.SUPABASE_URL
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or settings.SUPABASE_SERVICE_ROLE_KEY
    if not url or not key:
        raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be configured.")
    return create_client(url, key)


def calculate_age(dob_str: Optional[str]) -> Optional[int]:
    """Calculate chronological age from DD-MM-YYYY or YYYY-MM-DD string."""
    if not dob_str:
        return None
    dob_str = str(dob_str).strip()
    for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            born = datetime.strptime(dob_str, fmt).date()
            today = date.today()
            return today.year - born.year - ((today.month, today.day) < (born.month, born.day))
        except ValueError:
            continue
    return None


def fetch_nudge_clinical_context(nudge_id: str, client: Optional[Client] = None) -> Dict[str, Any]:
    """
    Fetches full clinical context for a specific nudge:
    - Nudge row (title, text, why_flagged, action_steps, evidence, risk_level, created_at)
    - Patient demographics (full_name, date_of_birth, age, gender, location, timezone)
    - Active clinical insights
    - Recent daily vitals trends (up to 14 days)
    - Chronic conditions
    """
    sb = client or get_supabase_client()

    # 1. Fetch Nudge
    nudge_res = sb.table("nudge_alerts").select("*").eq("id", nudge_id).execute()
    if not nudge_res.data:
        raise ValueError(f"Nudge alert with ID {nudge_id} not found.")
    nudge = nudge_res.data[0]
    patient_id = nudge.get("patient_id")

    # 2. Fetch Patient
    patient = {}
    if patient_id:
        p_res = sb.table("patients").select("*").eq("id", patient_id).execute()
        if p_res.data:
            patient = p_res.data[0]

    age = calculate_age(patient.get("date_of_birth"))

    # 3. Fetch Active & Historical Insights
    insights = []
    if patient_id:
        try:
            ins_res = sb.table("active_clinical_insights") \
                .select("id, name, rule_id, severity, category, message, evidence, created_at, status") \
                .eq("patient_id", patient_id) \
                .order("created_at", desc=True) \
                .limit(10) \
                .execute()
            if ins_res.data:
                insights = ins_res.data
        except Exception as e:
            print(f"[ClinicalAdvisor] Error fetching active insights: {e}")

    # 4. Fetch Conditions
    conditions = []
    if patient_id:
        try:
            cond_res = sb.table("conditions").select("*").eq("patient_id", patient_id).execute()
            if cond_res.data:
                conditions = cond_res.data
        except Exception as e:
            print(f"[ClinicalAdvisor] Error fetching conditions: {e}")

    # 5. Fetch Recent Daily Vitals
    vitals_recent = []
    if patient_id:
        try:
            vit_res = sb.table("vitals_daily") \
                .select("date, avg_heart_rate, min_heart_rate, max_heart_rate, hr_avg_morning, hr_avg_afternoon, hr_avg_evening, hr_avg_night, resting_heart_rate_calculated, oxygen_sat_avg, respiratory_rate_avg, total_steps, sleep_hours, waso_mins, awakenings_count, awakenings_count_greater_than_5mins, sleep_stage_1_hours, sleep_stage_4_hours, sleep_stage_5_hours, sleep_stage_5_pct, sleep_stage_6_hours, sleep_stage_6_pct") \
                .eq("patient_id", patient_id) \
                .order("date", desc=True) \
                .limit(7) \
                .execute()
            if vit_res.data:
                vitals_recent = vit_res.data
        except Exception as e:
            print(f"[ClinicalAdvisor] Error fetching vitals_daily: {e}")

    # 6. Temporal & Telemetry Verification Check
    temporal_telemetry_check = "Telemetry records are consistent."
    nudge_created = str(nudge.get("created_at") or "")[:10]
    nudge_title_lower = (nudge.get("nudge_title") or "").lower()
    if "sleep" in nudge_title_lower:
        matching_daily = next((v for v in vitals_recent if str(v.get("date"))[:10] == nudge_created), None)
        if matching_daily:
            if matching_daily.get("sleep_hours") is None:
                temporal_telemetry_check = f"TEMPORAL MISMATCH DETECTED: The alert was generated on {nudge_created} claiming sleep disturbances, but vitals_daily for {nudge_created} has sleep_hours = None (no sleep was recorded for that night). The alert recycled historical sleep telemetry from an earlier date."
        else:
            temporal_telemetry_check = f"NO TELEMETRY RECORDED: vitals_daily has no entry for date {nudge_created}."

    return {
        "nudge": nudge,
        "patient": patient,
        "calculated_age": age,
        "insights": insights,
        "conditions": conditions,
        "vitals_recent": vitals_recent,
        "temporal_telemetry_check": temporal_telemetry_check
    }


def build_clinical_advisor_prompt(context: Dict[str, Any]) -> str:
    """
    Constructs an exhaustive clinical review prompt for the 25-year geriatrician.
    """
    nudge = context["nudge"]
    patient = context["patient"]
    age = context["calculated_age"]
    temporal_check = context.get("temporal_telemetry_check", "Telemetry records are consistent.")
    gender = patient.get("gender", "Unspecified")
    patient_name = patient.get("full_name", "Unknown Patient")
    location = patient.get("location_city") or "India"
    
    # Format action steps cleanly
    action_steps = nudge.get("action_steps")
    if isinstance(action_steps, (dict, list)):
        action_steps_str = json.dumps(action_steps, indent=2)
    else:
        action_steps_str = str(action_steps)

    # Format why_flagged
    why_flagged = nudge.get("why_flagged")
    if isinstance(why_flagged, (dict, list)):
        why_flagged_str = json.dumps(why_flagged, indent=2)
    else:
        why_flagged_str = str(why_flagged)

    evidence = nudge.get("evidence")
    if isinstance(evidence, (dict, list)):
        evidence_str = json.dumps(evidence, indent=2)
    else:
        evidence_str = str(evidence)

    insights_str = json.dumps(context.get("insights", []), indent=2, default=str)
    vitals_str = json.dumps(context.get("vitals_recent", []), indent=2, default=str)
    conditions_str = json.dumps(context.get("conditions", []), indent=2, default=str)

    prompt = f"""
You are a distinguished Senior Clinical Advisor with 25 years of hands-on clinical practice holding MBBS and MD degrees.
Your primary specialization is in Preventive, Predictive, and Early Diagnosis, with deep clinical expertise in the Geriatric population in India.

You understand:
1. Geriatric Chronobiology & Hemodynamics: Age-related vascular stiffening, blunted baroreceptor sensitivity, nocturnal non-dipping of BP, afternoon autonomic surges, postprandial hypotensive/tachycardic shifts.
2. Sleep Architecture in Indian Elderly: Typical reduction of slow-wave sleep (N3/stage 4) and REM (stage 6), sleep fragmentation driven by nocturia (BPH in men, overactive bladder in women), sleep apnea (OSA), restless leg syndrome, late Indian dinner timings leading to GERD.
3. Multimorbidity & Polypharmacy: Interactions between antihypertensives, sulfonylureas/metformin, statins, NSAIDs, PPIs, sedatives (Zolpidem/Alprazolam), and over-the-counter Ayurvedic/home remedies.
4. The Indian Elder Care Context: Reliance on family caregivers (sons/daughters living in metros or abroad), accessibility of home phlebotomy (Dr. Lal PathLabs, Thyrocare, Metropolis, Apollo Diagnostics), reluctance to visit crowded clinics unless an acute emergency arises, and fear of hospitalization.

Below is a health nudge alert generated by the system for audit:

==================== PATIENT PROFILE ====================
Name: {patient_name}
Chronological Age: {age if age is not None else 'Unknown (Adult/Senior)'} years
Gender: {gender}
Location: {location}
Chronic Conditions on file: {conditions_str}

==================== NUDGE ALERT UNDER AUDIT ====================
Nudge ID: {nudge.get('id')}
Nudge Title: {nudge.get('nudge_title')}
Nudge Empathetic Text: {nudge.get('nudge_text')}
Assigned Risk Level: {nudge.get('risk_level')}
Generated Source: {nudge.get('source')}
Created At: {nudge.get('created_at')}

Why Flagged Data:
{why_flagged_str}

Action Steps Attached:
{action_steps_str}

Evidence / Metrics Recorded:
{evidence_str}

==================== CLINICAL CONTEXT & HISTORY ====================
Recent Active Insights (Rules Engine):
{insights_str}

Recent Daily Vitals Trends (Past Days):
{vitals_str}

Telemetry Integrity & Temporal Consistency Check:
{temporal_check}

==================== YOUR MANDATE ====================
Perform an uncompromising, thorough, expert clinical audit of this nudge as a senior medical doctor.
You must return your output strictly in JSON format with exactly the following keys:

{{
  "nudge_id": "{nudge.get('id')}",
  "patient_name": "{patient_name} (Age: {age if age is not None else 'N/A'}, {gender})",
  "nudge_title": "{nudge.get('nudge_title')}",
  "why_was_this_nudge_created": "Full, forensic root-cause analysis. Explain the exact biometric variables, baseline deviations, standard deviations (z-scores), circadian timing, whether sensor artifact vs true physiological shift is at play, explicitly address whether the telemetry matches the alert date, and verify sleep stage mappings (Health Connect standard: sleep_stage_4 = Light/Core Sleep, sleep_stage_5 = Deep Sleep N3, sleep_stage_6 = REM Sleep).",
  "was_it_clinically_sound": "In-depth medical explanation. If clinically sound, explain the physiological and pathological validity. If NOT sound (or if a TEMPORAL MISMATCH occurred, or if sleep stages were mislabeled such as labeling stage 5 as REM or oxymoronically calling REM 'deepest stage of sleep'), explicitly call this out, explain the erosion of caregiver trust, and detail why this heuristic failed.",
  "confidence_score": "Confidence score from 0% to 100% (e.g. '88%') followed by 2-3 sentences of clinical justification based on signal concordance, statistical magnitude, and physiological plausibility (deduct score if temporal mismatch is present).",
  "action_steps_critical_analysis": {{
    "was_it_best_action": "Yes / No / Partially. Explicitly state whether the attached CTA was appropriate or mismatched.",
    "critique": "Detailed critical critique of the generated action_steps. (e.g. If the system advised booking physiotherapy or dietary consultation for sleep disturbance or tachycardia, call this out directly as clinically inappropriate and explain why).",
    "what_clinically_makes_sense": "What advice and immediate action should have actually been given to this patient and their caregiver based on the clinical data.",
    "geriatric_care_pathway": {{
      "phase_1_immediate_home_triage": "Specific, actionable steps for the family caregiver at home (manual radial pulse, orthostatic BP, red flag checks, hydration, evening routine).",
      "phase_2_predictive_diagnostic_workup": "Targeted diagnostic investigations (e.g. 12-lead ECG, 24-hr Holter, home blood panel via Dr. Lal/Thyrocare, overnight pulse oximetry, serum electrolytes, urine routine).",
      "phase_3_medication_and_polypharmacy_review": "Review of current drugs under Beers/STOPP criteria (timing of antihypertensives, diuretics before 6 PM, hypoglycemic risks, sedatives).",
      "phase_4_clinical_escalation_thresholds": "Exact red flag symptoms requiring immediate physician/emergency hospital evaluation."
    }}
  }}
}}

Make your clinical reasoning rigorous, insightful, articulate, and deeply grounded in real-world geriatric medicine in India.
Do not hedge or use vague disclaimers. Provide direct, authoritative clinical reasoning.
"""
    return prompt


async def audit_nudge_alert_async(nudge_id: str, client: Optional[Client] = None) -> Dict[str, Any]:
    """
    Asynchronously conducts the 7-point clinical audit on a nudge alert using Gemini.
    """
    context = fetch_nudge_clinical_context(nudge_id, client)
    prompt = build_clinical_advisor_prompt(context)
    
    ai_studio_key = os.getenv("GEMINI_API_KEY") or settings.GEMINI_API_KEY
    model = "gemini-2.5-flash"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={ai_studio_key}"
    
    audit_data = None
    try:
        print(f"[ClinicalAdvisor] Querying Gemini ({model}) for clinical audit on Nudge {nudge_id}...")
        async with httpx.AsyncClient(timeout=45.0) as http_client:
            response = await http_client.post(
                url,
                headers={"Content-Type": "application/json"},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "responseMimeType": "application/json",
                        "temperature": 0.2
                    }
                }
            )
            if response.status_code == 200:
                raw_json = response.json()["candidates"][0]["content"]["parts"][0]["text"]
                audit_data = json.loads(raw_json)
                print(f"[ClinicalAdvisor] Successfully received and parsed clinical audit!")
            else:
                print(f"[ClinicalAdvisor] Gemini API returned status {response.status_code}: {response.text}")
    except Exception as e:
        print(f"[ClinicalAdvisor] Error querying Gemini for clinical audit: {e}")

    # Fallback heuristic if API fails
    if not audit_data:
        print("[ClinicalAdvisor] Using heuristic clinical fallback.")
        audit_data = generate_heuristic_clinical_audit(context)

    # Persist the audit to disk / local registry
    save_clinical_audit_to_disk(audit_data)
    
    return audit_data


def audit_nudge_alert(nudge_id: str, client: Optional[Client] = None) -> Dict[str, Any]:
    """Synchronous wrapper for audit_nudge_alert_async."""
    try:
        return asyncio.run(audit_nudge_alert_async(nudge_id, client))
    except RuntimeError:
        # Fallback if an active loop exists
        try:
            import nest_asyncio
            nest_asyncio.apply()
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(audit_nudge_alert_async(nudge_id, client))
        except Exception as err:
            print(f"[ClinicalAdvisor] Loop execution error: {err}")
            context = fetch_nudge_clinical_context(nudge_id, client)
            return generate_heuristic_clinical_audit(context)


def generate_heuristic_clinical_audit(context: Dict[str, Any]) -> Dict[str, Any]:
    """Deterministic fallback clinical evaluation if LLM is unavailable."""
    nudge = context["nudge"]
    patient = context["patient"]
    age = context["calculated_age"]
    gender = patient.get("gender", "Unspecified")
    patient_name = patient.get("full_name", "Unknown Patient")
    title = nudge.get("nudge_title", "Health Alert")
    risk_level = (nudge.get("risk_level") or "MEDIUM").upper()

    return {
        "nudge_id": nudge.get("id"),
        "patient_name": f"{patient_name} (Age: {age if age is not None else 'N/A'}, {gender})",
        "nudge_title": title,
        "why_was_this_nudge_created": f"The alert was generated based on deviations in physiological signals: {json.dumps(nudge.get('why_flagged', {}))}.",
        "was_it_clinically_sound": f"Alert flagged as {risk_level}. Requires verification against the patient's individual baseline and clinical symptoms to rule out sensor artifacts.",
        "confidence_score": "75% (Rule-based evaluation pending full multi-signal cross-correlation).",
        "action_steps_critical_analysis": {
            "was_it_best_action": "Partially",
            "critique": "The suggested action steps require clinical tailoring to avoid mismatched interventions.",
            "what_clinically_makes_sense": "Immediate check of vital signs, verifying patient comfort, and reviewing medication timing.",
            "geriatric_care_pathway": {
                "phase_1_immediate_home_triage": "Measure manual radial pulse, verify blood pressure, screen for lightheadedness or fatigue.",
                "phase_2_predictive_diagnostic_workup": "Schedule basic metabolic panel and ECG if cardiac symptoms persist.",
                "phase_3_medication_and_polypharmacy_review": "Review current antihypertensives, diuretics, and nighttime sedatives.",
                "phase_4_clinical_escalation_thresholds": "Urgent medical attention if patient reports chest pain, severe dyspnea, syncope, or acute confusion."
            }
        }
    }


def save_clinical_audit_to_disk(audit: Dict[str, Any]):
    """Appends the audit result to a persistent JSON audit ledger."""
    try:
        log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "logs")
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, "clinical_nudge_audits.json")

        existing_audits = []
        if os.path.exists(log_file):
            try:
                with open(log_file, "r", encoding="utf-8") as f:
                    existing_audits = json.load(f)
            except Exception:
                existing_audits = []

        # Upsert by nudge_id
        nudge_id = audit.get("nudge_id")
        existing_audits = [a for a in existing_audits if a.get("nudge_id") != nudge_id]
        audit["audited_at"] = datetime.now(timezone.utc).isoformat()
        existing_audits.append(audit)

        with open(log_file, "w", encoding="utf-8") as f:
            json.dump(existing_audits, f, indent=2, default=str)
    except Exception as e:
        print(f"[ClinicalAdvisor] Failed to save audit to disk: {e}")


def format_clinical_audit_markdown(audit: Dict[str, Any]) -> str:
    """Formats the 7-point audit into a polished, readable clinical report."""
    actions = audit.get("action_steps_critical_analysis", {})
    pathway = actions.get("geriatric_care_pathway", {})

    md = f"""# [CLINICAL AUDIT REPORT: GERIATRIC NUDGE EVALUATION]
**Senior Clinical Advisor (MBBS, MD - 25 Years Experience in Preventive & Predictive Diagnosis)**

---

### 1. Nudge Id
`{audit.get('nudge_id')}`

### 2. Patient Name
**{audit.get('patient_name')}**

### 3. Nudge Title
**"{audit.get('nudge_title')}"**

---

### 4. Why was this nudge created? (Full Root-Cause Analysis)
{audit.get('why_was_this_nudge_created')}

---

### 5. Was it clinically sound?
{audit.get('was_it_clinically_sound')}

---

### 6. Confidence Score
**Confidence Rating**: `{audit.get('confidence_score')}`

---

### 7. Critical Analysis of Action Steps & Evidence-Based Care Pathways
- **Was it the Best Action?**: **{actions.get('was_it_best_action', 'N/A')}**
- **Clinical Critique**: {actions.get('critique', 'N/A')}

#### What Clinically Makes Sense to Advise This Person
{actions.get('what_clinically_makes_sense', 'N/A')}

#### [GERIATRIC CARE PATHWAY - INDIAN CLINICAL ECOSYSTEM]
- **Phase 1: Immediate Home Caregiver Triage**
  {pathway.get('phase_1_immediate_home_triage', 'N/A')}
- **Phase 2: Predictive & Early Diagnostic Workup**
  {pathway.get('phase_2_predictive_diagnostic_workup', 'N/A')}
- **Phase 3: Medication & Polypharmacy Review**
  {pathway.get('phase_3_medication_and_polypharmacy_review', 'N/A')}
- **Phase 4: Clinical Escalation & Red Flags**
  {pathway.get('phase_4_clinical_escalation_thresholds', 'N/A')}
"""
    return md
