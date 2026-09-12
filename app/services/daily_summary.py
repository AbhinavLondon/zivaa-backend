"""
Daily Summary Service

Generates a 2-sentence morning briefing for the senior user themselves.
Unlike the nudge (which fires on alerts for the caregiver), this runs once daily
and covers the FULL picture of how their yesterday went.

The summary is anchored by raw metrics and baseline deviations but expressed
in plain, warm English that a senior user can easily understand.
"""

import httpx
import json
from typing import Dict, Any, Optional
from app.config import settings
from app.services.insights.engine import InsightEngine, EngineOutput
from app.services.insights.core import RiskLevel
from app.services.multilingual import (
    get_patient_language,
    get_proactive_language_directive,
    get_fallback_text,
)


async def generate_daily_summary(
    patient_id: str,
    patient_name: str = "your loved one",
) -> Dict[str, Any]:
    """
    Produces a holistic 2-sentence morning summary for the senior user themselves,
    summarizing how their day went yesterday and what they should focus on today.

    Returns:
        {
            "summary": "Plain English 2-sentence summary",
            "overall_status": "good" | "needs_attention" | "concerning" | "calibrating",
            "insights_count": {"high": 0, "medium": 0, "low": 0},
            "top_concern": "rule name" or null
        }
    """
    # 1. Fetch patient context and language preference
    from app.services.insights.data_fetcher import fetch_patient_context
    ctx = fetch_patient_context(patient_id)
    pref_lang = get_patient_language(patient_id)

    # 2. Run the engine with pre-fetched context
    engine = InsightEngine()
    output = engine.evaluate_patient(patient_id, ctx)

    # 3. If calibrating, return onboarding summary
    if output.calibration_message and not output.active_insights:
        calib_msg = get_fallback_text("calibration_message", pref_lang)
        return {
            "summary": calib_msg,
            "overall_status": "calibrating",
            "insights_count": {"high": 0, "medium": 0, "low": 0},
            "top_concern": None,
        }

    # 4. Categorize insights
    high = [i for i in output.active_insights if i.severity == RiskLevel.HIGH]
    medium = [i for i in output.active_insights if i.severity == RiskLevel.MEDIUM]
    low = [i for i in output.active_insights if i.severity == RiskLevel.LOW]

    counts = {"high": len(high), "medium": len(medium), "low": len(low)}
    top_concern = high[0].name if high else (medium[0].name if medium else None)

    # 5. Determine overall status
    if len(high) >= 1:
        overall = "concerning"
    elif len(medium) >= 1:
        overall = "needs_attention"
    else:
        overall = "good"

    # 6. Extract raw vitals from yesterday (or latest recorded date)
    vitals_dict = ctx.vitals._vitals
    baselines_dict = ctx.baseline_status.baselines if ctx.baseline_status else {}

    # Find the latest date with any vital readings in history
    all_dates = []
    for metric_name, values in vitals_dict.items():
        for val in values:
            all_dates.append(val.date)

    from datetime import datetime, timedelta
    target_date = max(all_dates) if all_dates else (datetime.now() - timedelta(days=1)).date()

    # Extract metrics for that target date
    yesterday_vitals = {}
    for metric_name, values in vitals_dict.items():
        day_vals = [val.value for val in values if val.date == target_date]
        if day_vals:
            yesterday_vitals[metric_name] = day_vals[0]

    # Format vitals into bullet points with baseline comparisons
    from app.services.insights.baseline import METRIC_THRESHOLDS
    vitals_summary = []
    for metric_name, val in yesterday_vitals.items():
        label = METRIC_THRESHOLDS.get(metric_name, {}).get("label", metric_name)
        unit = ""
        if "steps" in metric_name:
            unit = " steps"
        elif "sleep_hours" in metric_name:
            unit = " hours"
        elif "efficiency" in metric_name:
            unit = "%"
        elif "heart_rate" in metric_name:
            unit = " bpm"
        elif "glucose" in metric_name:
            unit = " mg/dL"
        elif "temp" in metric_name:
            unit = "°C"

        baseline_info = baselines_dict.get(metric_name)
        if baseline_info and baseline_info.is_established:
            vitals_summary.append(
                f"- {label}: {val}{unit} (Your typical baseline: {round(baseline_info.mean, 1)}{unit})"
            )
        else:
            vitals_summary.append(f"- {label}: {val}{unit}")

    # Combine blood pressure systolic/diastolic for a cleaner display
    if "bp_systolic" in yesterday_vitals and "bp_diastolic" in yesterday_vitals:
        sys_val = yesterday_vitals["bp_systolic"]
        dia_val = yesterday_vitals["bp_diastolic"]
        vitals_summary = [s for s in vitals_summary if "Systolic" not in s and "Diastolic" not in s]
        
        sys_base = baselines_dict.get("bp_systolic")
        dia_base = baselines_dict.get("bp_diastolic")
        if sys_base and sys_base.is_established and dia_base and dia_base.is_established:
            vitals_summary.append(
                f"- Blood Pressure: {int(sys_val)}/{int(dia_val)} mmHg (Your typical baseline: {int(sys_base.mean)}/{int(dia_base.mean)} mmHg)"
            )
        else:
            vitals_summary.append(f"- Blood Pressure: {int(sys_val)}/{int(dia_val)} mmHg")

    vitals_bullet = "\n".join(vitals_summary) if vitals_summary else "No vital logs recorded."

    # Build active clinical alerts bullet points
    if output.active_insights:
        insights_bullet = "\n".join([
            f"- Clinical Concern: [{i.severity.value}] {i.name}: {i.message[:120]}"
            for i in output.active_insights
        ])
    else:
        insights_bullet = "No clinical alerts or concerns."

    # 7. Construct LLM prompt
    prompt = f"""You are writing a brief, encouraging morning health summary addressed directly to an elderly senior user about how their day went yesterday and how they are doing today.

Here are their logged health metrics for yesterday ({target_date.strftime('%B %d, %Y')}):
{vitals_bullet}

Clinical system findings / concerns:
{insights_bullet}

RULES:
1. Write EXACTLY 2 sentences. No more.
2. First sentence: A warm, positive, and encouraging recap of how their day went yesterday based on their logged vitals (e.g. steps, sleep, mood, blood pressure), comparing it gently to their usual baseline if available (e.g., "You did a wonderful job staying active yesterday, walking over five thousand steps and getting a restful night of sleep.").
3. Second sentence: A supportive, actionable tip or gentle focus area for them today (e.g., "For today, remember to take nice, easy walks and drink plenty of water to keep your energy up.").
4. If there are active clinical concerns (such as blood pressure spikes or heart rate changes), weave them in extremely gently and constructively (e.g. "Your heart rate was a little higher than usual, so today is a perfect day to rest and take things slowly.") rather than sounding clinical or alarmist.
5. Speak directly to the user in the second person ("you", "your"). Do NOT refer to them in the third person (do not use their name or "he/she").
6. Do NOT use medical jargon, numbers, percentages, or symbols in the final summary. Translate numbers into words (e.g. use "eight hours" instead of "8 hours" or "8 hrs", and "six thousand steps" instead of "6,000 steps").
7. Do NOT use lists, bullet points, or headers. Just 2 flowing, natural sentences.
8. {get_proactive_language_directive(pref_lang, content_type="briefing")}

Return ONLY the 2 sentences as plain text. No JSON, no formatting."""

    # 8. Call Gemini
    summary_text = None

    if settings.GEMINI_API_KEY and settings.GEMINI_API_KEY != "your-api-key-here":
        try:
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"gemini-3.5-flash:generateContent?key={settings.GEMINI_API_KEY}"
            )
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    headers={"Content-Type": "application/json"},
                    json={
                        "contents": [{"parts": [{"text": prompt}]}],
                    },
                    timeout=30.0,
                )
                if response.status_code == 200:
                    summary_text = (
                        response.json()["candidates"][0]["content"]["parts"][0]["text"]
                    ).strip()
                else:
                    print(f"Daily summary LLM error status: {response.status_code}, response: {response.text}")
        except Exception as e:
            print(f"Daily summary LLM exception: {repr(e)}")

    # 9. Fallback if LLM unavailable
    if not summary_text:
        summary_text = _build_fallback_summary(yesterday_vitals, overall, top_concern, language=pref_lang)

    return {
        "summary": summary_text,
        "overall_status": overall,
        "insights_count": counts,
        "top_concern": top_concern,
    }


def _build_fallback_summary(
    yesterday_vitals: Dict[str, float],
    overall: str,
    top_concern: Optional[str] = None,
    language: str = "English"
) -> str:
    """Deterministic fallback when the LLM is unavailable."""
    steps = yesterday_vitals.get("steps")
    sleep = yesterday_vitals.get("sleep_hours")
    
    if language.lower() == "hindi":
        if steps is not None and sleep is not None:
            first_sent = f"कल आप {int(steps)} कदमों के साथ सक्रिय रहे और आपको {round(sleep, 1)} घंटे की अच्छी नींद मिली।"
        elif steps is not None:
            first_sent = f"कल आपने {int(steps)} कदम चलकर खुद को सक्रिय रखा, बहुत बढ़िया।"
        elif sleep is not None:
            first_sent = f"कल रात आपको लगभग {round(sleep, 1)} घंटे की आरामदायक नींद मिली।"
        else:
            first_sent = "कल आपके स्वास्थ्य के सभी आंकड़े स्थिर और सामान्य रहे।"

        if overall == "concerning" and top_concern:
            second_sent = f"हमने आपके {top_concern.lower()} में कुछ बदलाव देखे हैं, इसलिए आज आराम करें और डॉक्टर से परामर्श लें।"
        elif overall == "needs_attention" and top_concern:
            second_sent = f"आज अपनी दिनचर्या आराम से रखें और अपने {top_concern.lower()} का ध्यान रखें।"
        else:
            second_sent = "आज भी अपनी अच्छी दिनचर्या बनाए रखें और पर्याप्त पानी पीते रहें।"
            
        return f"{first_sent} {second_sent}"

    # 1. First sentence: recap of yesterday
    if steps is not None and sleep is not None:
        first_sent = f"Yesterday, you stayed active with {int(steps)} steps and got {round(sleep, 1)} hours of sleep."
    elif steps is not None:
        first_sent = f"Yesterday, you did great keeping active with {int(steps)} steps."
    elif sleep is not None:
        first_sent = f"Yesterday, you got a restful {round(sleep, 1)} hours of sleep."
    else:
        first_sent = "Your health metrics and vitals looked stable and steady yesterday."
        
    # 2. Second sentence: tip for today
    if overall == "concerning" and top_concern:
        second_sent = f"We noticed some changes regarding your {top_concern.lower()}, so it is a good day to rest and check in with your doctor."
    elif overall == "needs_attention" and top_concern:
        second_sent = f"Remember to take things at a comfortable pace today and keep an eye on your {top_concern.lower()}."
    else:
        second_sent = "Keep up the excellent routine today and make sure to stay well hydrated."
        
    return f"{first_sent} {second_sent}"

