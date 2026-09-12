"""
Centralized Multilingual Architecture Engine for Zivaa Backend.

Provides a single source of truth for:
1. Patient language lookup from the database (`get_patient_language`).
2. Standardized prompt directives for:
   - Proactive / Ambient senior surfaces (Morning Briefings, Mid-day & Evening Check-ins, Nudges, Daily Care Plans).
   - Interactive Conversational Health Coach (Dynamic mirroring, turn-by-turn code-switching, anchor fallback).
   - Clinical Memory Extraction & Normalization (Extracting native-script chats into standardized English clinical facts).
3. Standardized fallback copy across supported languages.
"""

from typing import Optional, Dict, Any

def get_patient_language(patient_id: Optional[str], default: str = "English") -> str:
    """
    Queries the patient's configured preferred language from the Supabase patients table.
    Falls back gracefully to the default if patient_id is missing, column is empty, or on query failure.
    """
    if not patient_id:
        return default
    try:
        from app.services.insights.data_fetcher import supabase
        res = supabase.table("patients").select("preferred_language").eq("id", patient_id).single().execute()
        if res.data and res.data.get("preferred_language"):
            lang = res.data["preferred_language"].strip()
            if lang:
                return lang
    except Exception:
        # Avoid crashing pipelines if table or network is temporarily unavailable
        pass
    return default


def get_proactive_language_directive(language: str = "English", content_type: str = "general") -> str:
    """
    Generates the standardized language directive for unprompted senior-facing surfaces:
    - Morning Briefings
    - Mid-day Check-ins
    - Evening Wind-downs
    - Proactive Nudge Alerts
    - Daily Care Plan Schedules

    Args:
        language: The target language (e.g. "English", "Hindi", "Bengali", "Tamil", etc.)
        content_type: Specific surface nuance ("briefing", "checkin", "nudge", "plan", or "general")
    """
    lang_clean = language.strip() if language else "English"
    is_english = lang_clean.lower() in ("english", "en")

    if is_english:
        return (
            "LANGUAGE & CULTURAL TONE DIRECTIVE:\n"
            "- Write the response in clear, warm, empathetic English.\n"
            "- Maintain an encouraging, respectful tone suitable for older adults."
        )

    # For Indian languages & other non-English languages:
    type_specific_rules = ""
    if content_type in ("briefing", "checkin"):
        type_specific_rules = (
            "- Numeral Formulation: Express numbers in natural written words where appropriate "
            "(e.g., in Hindi write 'पाँच हजार कदम' or 'सात घंटे') rather than raw machine figures in conversational prose.\n"
        )
    elif content_type == "plan":
        type_specific_rules = (
            "- Schedule Times & Measurement Formats: Keep clock times in familiar readable format (e.g. 08:00 AM, 01:30 PM). "
            "Translate task descriptions and reminders into the target language, but keep medical dosages and units clear.\n"
        )
    elif content_type == "nudge":
        type_specific_rules = (
            "- All JSON fields ('nudge_title', 'nudge_text', 'why_flagged', 'action_steps') MUST be written in the target language.\n"
        )

    return f"""LANGUAGE & CULTURAL TONE DIRECTIVE:
1. TARGET LANGUAGE: Write the entire generated content in **{lang_clean}**.
2. CULTURALLY RESONANT ELDER RESPECT:
   - Use the highest tier of polite address and respectful honorifics suited for elders (e.g., in Hindi always use 'आप', 'आपने', and attach 'जी' to names; in Bengali use 'আপনি', etc.).
   - Never sound cold, clinical, dismissive, or authoritarian. Maintain a deeply reassuring, warm, family-like tone.
3. MEDICAL TERMINOLOGY & MEASUREMENT PRESERVATION:
   - Even when writing in native scripts (e.g. Devanagari, Bengali script), ALWAYS keep vital test names, medical brands, pharmaceutical names, and numerical readings in familiar English/Latin script alongside or within the sentence (e.g., write "Blood Pressure 120/80 mmHg", "Metformin 500mg", "Blood Sugar / HbA1c", "Pulse 72 bpm") so elderly users and their caregivers can instantly recognize their familiar clinical terms without confusion.
{type_specific_rules}4. CLARITY: Use everyday, familiar words. Avoid obscure, overly formal, or archaic vocabulary that older adults may struggle to understand."""


def get_coach_language_directive(default_language: str = "English") -> str:
    """
    Generates the dynamic turn-by-turn language directive for the interactive AI Health Coach.
    Equips the coach to mirror whatever language the user speaks, code-switch mid-chat,
    and fall back to default_language when turns are ambiguous or language-neutral.
    """
    default_clean = default_language.strip() if default_language else "English"

    return f"""### Multilingual Adaptability & Dynamic Code-Switching Directive
The patient's configured default language preference is: **{default_clean}**.
You must adhere strictly to these linguistic principles:
- **Dynamic Language Mirroring:** Always detect and respond in the language or dialect used by the patient in their most recent message (e.g., Hindi, Bengali, Tamil, Telugu, Marathi, Gujarati, English, Hinglish, etc.).
- **Fluid Turn-by-Turn Code-Switching:** If the patient switches language mid-conversation (e.g., starts in English, then switches to Hindi, or starts in Hindi and switches to English), you MUST immediately switch your response language to match their latest turn without friction, commentary, or delay.
- **Language-Neutral Turn Fallback:** If the patient's turn is ambiguous or language-neutral (e.g., single numbers like "130/85", short confirmations like "OK", "done", "yes", or tapping a quick reply suggestion chip), maintain the active conversation's language, or fall back to their configured default language: **{default_clean}**.
- **Culturally Resonant Elder Respect:** When conversing in Indian languages, always use the highest tier of polite address and honorifics suited for elders (e.g., in Hindi use 'आप' and respectful verb conjugations, attaching 'जी' to their name like 'रणजीत जी'; in Bengali use 'আপনি', etc.). Maintain a deeply warm, reassuring, and dignified tone.
- **Medical Terminology & Measurement Preservation:** Even when communicating in Indian languages and native scripts (Devanagari, Bengali, etc.), ALWAYS preserve vital clinical terms, medication brand/chemical names, lab tests, and numerical readings in familiar English/Latin script alongside or within the sentence (e.g., write "Blood Pressure 120/80 mmHg", "Metformin 500mg", "Blood Sugar / HbA1c", "Walking Steps") rather than obscure or unfamiliar vernacular translations that elderly patients cannot easily recognize.
- **Suggested Quick Replies Language:** The 3 suggested quick replies at the end of your message `[SUGGESTIONS]` MUST also be in the same language as your response so the user can easily tap them.
- **Adaptive Medical Disclaimer:** End your conversational response with the standard medical disclaimer in the active conversation language (e.g., in English: "I am an AI coach. Please consult your physician for medical decisions." or in Hindi: "मैं एक AI कोच हूँ। कृपया चिकित्सीय निर्णयों के लिए अपने डॉक्टर से परामर्श लें।" or appropriate translation in the active language)."""


def get_clinical_normalization_directive() -> str:
    """
    Generates the clinical memory extraction rule.
    Ensures background clinical facts (symptoms, preferences, medications, actions)
    are always normalized into clinical English, while raw transcripts remain verbatim.
    """
    return (
        "Clinical English Normalization: Regardless of what language, script, or dialect the patient "
        "or coach used in the conversation (such as Hindi, Bengali, Tamil, Hinglish, Spanish, etc.), "
        "you MUST ALWAYS translate and normalize all extracted symptom names, progression notes, "
        "medication names, dosages, frequencies, care plan action descriptions, and preference constraint "
        "texts into standardized, professional clinical English. NEVER output non-English scripts "
        "(like Devanagari, Bengali, etc.) in the extracted JSON keys or values."
    )


FALLBACK_MESSAGES: Dict[str, Dict[str, str]] = {
    "morning_briefing": {
        "English": "Hope you have a wonderful and restful day ahead! Remember to stay active and hydrated.",
        "Hindi": "आशा है कि आपका आज का दिन बहुत अच्छा और सुखद रहेगा! सक्रिय और हाइड्रेटेड रहना याद रखें।",
        "Bengali": "আশা করি আপনার আজকের দিনটি সুন্দর ও শান্তিময় কাটবে! সক্রিয় থাকুন এবং পর্যাপ্ত জল পান করুন।"
    },
    "morning_headline": {
        "English": "A bright, active day",
        "Hindi": "एक उज्ज्वल और सक्रिय दिन",
        "Bengali": "একটি সুন্দর ও সক্রিয় দিন"
    },
    "midday_checkin": {
        "English": "You're doing great today! Keep up the good momentum this afternoon.",
        "Hindi": "आप आज बहुत अच्छा कर रहे हैं! दोपहर में भी अपनी यह अच्छी गति बनाए रखें।",
        "Bengali": "আপনি আজ খুব ভালো করছেন! বিকেলেও এই ধারাবাহিকতা বজায় রাখুন।"
    },
    "evening_wind_down": {
        "English": "You've had a productive day. Now is a wonderful time to relax and rest.",
        "Hindi": "आज आपका दिन बहुत अच्छा रहा। अब आराम करने और सुकून पाने का सबसे अच्छा समय है।",
        "Bengali": "আজ আপনার দিনটি খুব ভালো কেটেছে। এখন বিশ্রাম নেওয়ার উপযুক্ত সময়।"
    },
    "emergency_fallback": {
        "English": "It sounds like you might be experiencing a medical emergency. Please stop using this app and immediately dial emergency services (911/999) or go to the nearest emergency room.",
        "Hindi": "ऐसा लगता है कि आपको चिकित्सीय आपात स्थिति (Medical Emergency) हो सकती है। कृपया तुरंत इस ऐप का उपयोग बंद करें और आपातकालीन सेवाओं (108/112) से संपर्क करें या निकटतम अस्पताल जाएं।"
    },
    "calibration_message": {
        "English": "We're still learning your daily patterns. Keep logging your vitals daily — your personalized health summaries will be ready soon.",
        "Hindi": "हम अभी भी आपके दैनिक स्वास्थ्य पैटर्न को समझ रहे हैं। कृपया हर दिन अपने वाइटल्स लॉग करते रहें — आपका व्यक्तिगत स्वास्थ्य सारांश जल्द ही तैयार हो जाएगा।",
        "Bengali": "আমরা এখনও আপনার প্রতিদিনের স্বাস্থ্য প্যাটার্ন বুঝতে চেষ্টা করছি। প্রতিদিন আপনার পরিমাপ রেকর্ড করতে থাকুন — আপনার ব্যক্তিগত স্বাস্থ্য বিবরণী শীঘ্রই প্রস্তুত হবে।"
    }
}

def get_fallback_text(key: str, language: str = "English") -> str:
    """
    Returns localized fallback text for offline or service failure scenarios.
    """
    lang_clean = language.capitalize() if language else "English"
    cat = FALLBACK_MESSAGES.get(key, {})
    return cat.get(lang_clean) or cat.get("English", "")
