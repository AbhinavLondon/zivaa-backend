import sys
import os
import httpx
import json
from typing import Dict, Any, List
from app.config import settings
from app.services.insights.core import InsightResult
from app.services.multilingual import (
    get_patient_language,
    get_proactive_language_directive,
    get_fallback_text,
)

async def generate_clinical_nudge(insights: Any, patient_name: str = "Ranjit", patient_id: str = None) -> Dict[str, Any]:
    """
    Constructs an optimized clinical prompt and queries the Gemini API.
    Supports:
      1. A list of InsightResult objects from the Rules Engine.
      2. A dictionary of features (vitals) from the Ingest flow.
    """
    pref_lang = get_patient_language(patient_id)

    # 1. Handle empty inputs
    if not insights:
        if pref_lang.lower() == "hindi":
            return {
                "risk_level": "LOW",
                "nudge_title": "सब कुछ स्थिर है",
                "nudge_text": f"आज {patient_name} के लिए कोई गंभीर स्वास्थ्य अलर्ट नहीं मिला। वाइटल्स स्थिर दिख रहे हैं।",
                "why_flagged": "कोई सक्रिय अलर्ट नहीं।",
                "action_steps": "किसी विशेष कार्रवाई की आवश्यकता नहीं है। अपनी दिनचर्या जारी रखें!"
            }
        return {
            "risk_level": "LOW",
            "nudge_title": "All is stable",
            "nudge_text": f"No critical health insights triggered for {patient_name} today. Vitals appear stable.",
            "why_flagged": "No active alerts.",
            "action_steps": "No action needed. Keep up the good work!"
        }

    # 2. Check if input is a dictionary of features (vitals)
    if isinstance(insights, dict):
        anomaly_detected = insights.get("ml_anomaly_detected", False)
        systolic = insights.get("bp_systolic", 120.0)
        diastolic = insights.get("bp_diastolic", 80.0)
        heart_rate = insights.get("avg_heart_rate", 72.0)
        
        is_high_risk = anomaly_detected or (systolic is not None and systolic >= 140.0) or (diastolic is not None and diastolic >= 90.0) or (heart_rate is not None and (heart_rate >= 100.0 or heart_rate <= 50.0))
        highest_severity_str = "HIGH" if is_high_risk else "LOW"
        
        # Build prompt using the features dict
        insights_text = f"""
        Current Vitals:
        - Heart Rate: {heart_rate if heart_rate is not None else 72.0:.1f} bpm
        - Blood Pressure: {systolic if systolic is not None else 120.0:.1f}/{diastolic if diastolic is not None else 80.0:.1f} mmHg
        - Sleep: {insights.get("sleep_hours", 7.0) if insights.get("sleep_hours") is not None else 7.0:.1f} hrs
        - Total Steps: {insights.get("total_steps", 0.0) if insights.get("total_steps") is not None else 0.0:.1f}
        - Anomaly Detected by ML: {anomaly_detected}
        """
        
        prompt = f"""
        You are an expert conversational clinical guide for Zivaa Eldercare.
        Review the following health metrics for the patient, {patient_name}:
        
        {insights_text}
    
        Instructions:
        1. Determine the appropriate overall Risk Level (LOW, MEDIUM, HIGH) based on the metrics. (Recommended: {highest_severity_str}).
        2. Write in a warm, comforting, less-clinical tone. Speak like a reassuring friend or family nurse to the caregiver, not a cold algorithm.
        3. Exclude dense medical terminology (no jargon).
        4. UNDER THE "why_flagged" SECTION, YOU MUST PROVIDE a simple, non-clinical explanation of why we are flagging this, summarizing any deviations. DO NOT include any visual graphs.
        5. {get_proactive_language_directive(pref_lang, content_type="nudge")}
        
        Format the response as exact JSON:
        {{
          "risk_level": "LOW | MEDIUM | HIGH",
          "nudge_title": "Warm, human-friendly title in {pref_lang}",
          "nudge_text": "Empathetic, comforting description in {pref_lang}.",
          "why_flagged": "Why we are flagging this in {pref_lang}",
          "action_steps": "What you can do about it in {pref_lang}"
        }}
        """
        
        if pref_lang.lower() == "hindi":
            fallback_nudge = {
                "risk_level": highest_severity_str,
                "nudge_title": "वाइटल्स सिंक पूर्ण" if highest_severity_str == "LOW" else "स्वास्थ्य अलर्ट",
                "nudge_text": f"{patient_name} के वाइटल्स सफलतापूर्वक अपडेट हो गए हैं और स्थिर दिख रहे हैं।" if highest_severity_str == "LOW" else f"हमने आज {patient_name} के स्वास्थ्य आंकड़ों में कुछ बदलाव देखे हैं।",
                "why_flagged": "वाइटल्स सामान्य ऐतिहासिक सीमा के भीतर हैं।" if highest_severity_str == "LOW" else "एक या अधिक वाइटल्स (हार्ट रेट, ब्लड प्रेशर) सामान्य से भिन्न हैं।",
                "action_steps": "वर्तमान दैनिक देखभाल योजना जारी रखें।" if highest_severity_str == "LOW" else "कृपया उनकी स्थिति जांचें और वाइटल्स पर नज़र रखें।"
            }
        else:
            fallback_nudge = {
                "risk_level": highest_severity_str,
                "nudge_title": "Vitals Sync Completed" if highest_severity_str == "LOW" else "Health Alert Detected",
                "nudge_text": f"Vitals for {patient_name} have been updated successfully and appear stable." if highest_severity_str == "LOW" else f"We noticed some deviations in {patient_name}'s vitals today.",
                "why_flagged": "Vitals are within normal historical baseline ranges." if highest_severity_str == "LOW" else "One or more vitals (heart rate, blood pressure) deviated from baseline.",
                "action_steps": "Maintain the current daily care plan." if highest_severity_str == "LOW" else "Please check in on them and monitor vitals closely."
            }
        
    else:
        # Standard List[InsightResult] logic
        try:
            first_insight = insights[0]
            if hasattr(first_insight, 'severity'):
                highest_severity = first_insight.severity
                highest_severity_val = highest_severity.value if hasattr(highest_severity, 'value') else str(highest_severity)
            else:
                highest_severity_val = first_insight.get('severity', 'LOW')
            
            insights_list = []
            for i in insights:
                if hasattr(i, 'name'):
                    insights_list.append(f"- {i.name} (Risk: {i.severity}): {i.message} [Evidence: {i.evidence}]")
                else:
                    insights_list.append(f"- {i.get('name', '')} (Risk: {i.get('severity', '')}): {i.get('message', '')} [Evidence: {i.get('evidence', '')}]")
            insights_text = "\n".join(insights_list)
        except Exception:
            highest_severity_val = "LOW"
            insights_text = str(insights)
            
        prompt = f"""
        You are an expert conversational clinical guide for Zivaa Eldercare.
        Review the following triggered health insights for the patient, {patient_name}:
        
        {insights_text}
    
        Instructions:
        1. Determine the appropriate overall Risk Level (LOW, MEDIUM, HIGH) based on the insights provided. The highest triggered risk is {highest_severity_val}.
        2. Write in a warm, comforting, less-clinical tone. Speak like a reassuring friend or family nurse to the caregiver, not a cold algorithm.
        3. Exclude dense medical terminology (no jargon).
        4. UNDER THE "why_flagged" SECTION, YOU MUST PROVIDE a simple, non-clinical explanation of why we are flagging this, summarizing the clinical rules that fired. DO NOT include any visual graphs.
        5. {get_proactive_language_directive(pref_lang, content_type="nudge")}
        
        Format the response as exact JSON:
        {{
          "risk_level": "LOW | MEDIUM | HIGH",
          "nudge_title": "Warm, human-friendly title in {pref_lang}",
          "nudge_text": "Empathetic, comforting description in {pref_lang}.",
          "why_flagged": "Why we are flagging this in {pref_lang}",
          "action_steps": "What you can do about it in {pref_lang}"
        }}
        """
        
        try:
            first_name = insights[0].name if hasattr(insights[0], 'name') else insights[0].get('name', 'Alert')
        except Exception:
            first_name = "Alert"
            
        if pref_lang.lower() == "hindi":
            fallback_nudge = {
                "risk_level": highest_severity_val,
                "nudge_title": "स्वास्थ्य अलर्ट",
                "nudge_text": f"हमने आज {patient_name} के स्वास्थ्य में कुछ बदलाव देखे हैं।",
                "why_flagged": f"निम्नलिखित अलर्ट दर्ज किया गया: {first_name}",
                "action_steps": "कृपया विस्तृत जानकारी की समीक्षा करें और आवश्यकता होने पर डॉक्टर से परामर्श लें।"
            }
        else:
            fallback_nudge = {
                "risk_level": highest_severity_val,
                "nudge_title": "Health Alert Detected",
                "nudge_text": f"We noticed some changes in {patient_name}'s health metrics that triggered an alert.",
                "why_flagged": f"The following insights were flagged: {first_name}",
                "action_steps": "Please review the detailed metrics and consult a doctor if necessary."
            }

    # Use the active Gemini API key from environment if available and not placeholder
    ai_studio_key = settings.GEMINI_API_KEY if settings.GEMINI_API_KEY != "your-api-key-here" else ""
    if ai_studio_key:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key={ai_studio_key}"
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    headers={"Content-Type": "application/json"},
                    json={
                        "contents": [{"parts": [{"text": prompt}]}],
                        "generationConfig": {"responseMimeType": "application/json"}
                    },
                    timeout=20.0
                )
                if response.status_code == 200:
                    text_content = response.json()["candidates"][0]["content"]["parts"][0]["text"]
                    parsed = json.loads(text_content)
                    
                    if patient_id:
                        try:
                            from supabase import create_client
                            supabase = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
                            nudge_record = {
                                "patient_id": patient_id,
                                "risk_level": parsed.get("risk_level", "LOW"),
                                "nudge_title": parsed.get("nudge_title", ""),
                                "nudge_text": parsed.get("nudge_text", ""),
                                "why_flagged": parsed.get("why_flagged", ""),
                                "action_steps": parsed.get("action_steps", ""),
                                "source": "gemini-3.5-flash"
                            }
                            res_db = supabase.table("nudge_alerts").insert(nudge_record).execute()
                            if res_db.data and len(res_db.data) > 0:
                                parsed["created_at"] = res_db.data[0].get("created_at")
                        except Exception as db_err:
                            print(f"Failed to save nudge_alert to DB: {db_err}")
                            
                    if "created_at" not in parsed:
                        from datetime import datetime, timezone
                        parsed["created_at"] = datetime.now(timezone.utc).isoformat()
                            
                    return parsed
        except Exception as e:
            print(f"LLM Error: {e}")

    # Fallback if no LLM or call failed
    if patient_id:
        try:
            from supabase import create_client
            supabase = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
            nudge_record = {
                "patient_id": patient_id,
                "risk_level": fallback_nudge.get("risk_level", "LOW"),
                "nudge_title": fallback_nudge.get("nudge_title", ""),
                "nudge_text": fallback_nudge.get("nudge_text", ""),
                "why_flagged": fallback_nudge.get("why_flagged", ""),
                "action_steps": fallback_nudge.get("action_steps", ""),
                "source": "heuristic_fallback"
            }
            res_db = supabase.table("nudge_alerts").insert(nudge_record).execute()
            if res_db.data and len(res_db.data) > 0:
                fallback_nudge["created_at"] = res_db.data[0].get("created_at")
        except Exception as db_err:
            print(f"Failed to save nudge_alert to DB: {db_err}")
            
    if "created_at" not in fallback_nudge:
        from datetime import datetime, timezone
        fallback_nudge["created_at"] = datetime.now(timezone.utc).isoformat()
            
    return fallback_nudge
