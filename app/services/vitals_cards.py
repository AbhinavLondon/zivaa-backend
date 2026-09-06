"""
Vitals Cards Service

Extracts data for the vitals cards dynamically filtered by timeframe:
- "Today" (1 day)
- "7 days" (7 days)
- "30 Days" (30 days)
- "3 Months" (90 days)

Each card contains the latest reading or aggregated average/total, the unit,
the chart data points with clinical status flags, and a timeframe-specific one-sentence insight.
"""

import os
import httpx
import json
from typing import List, Dict, Any, Optional
from datetime import datetime, date
from app.config import settings
from app.services.insights.data_fetcher import fetch_patient_context


SUPPORTED_METRICS = {
    "blood_pressure": {
        "title": "Blood Pressure",
        "unit": "mmHg",
        "label": "AVG"
    },
    "steps": {
        "title": "Steps",
        "unit": "steps",
        "label": "AVG"
    },
    "sleep_hours": {
        "title": "Sleep",
        "unit": "hrs",
        "label": "AVG"
    },
    "heart_rate": {
        "title": "Heart Rate",
        "unit": "bpm",
        "label": "AVG"
    },
    "oxygen_sat": {
        "title": "Oxygen Saturation",
        "unit": "%",
        "label": "AVG"
    },
    "blood_glucose": {
        "title": "Blood Glucose",
        "unit": "mg/dL",
        "label": "LATEST"
    },
    "body_temp": {
        "title": "Body Temperature",
        "unit": "°C",
        "label": "AVG"
    },
    "skin_temp_delta": {
        "title": "Skin Temp Delta",
        "unit": "°C",
        "label": "AVG"
    },
    "mood_score": {
        "title": "Mood",
        "unit": "score",
        "label": "AVG"
    },
    "sleep_quality": {
        "title": "Sleep Quality",
        "unit": "score",
        "label": "AVG"
    }
}


def determine_day_status(metric_name: str, val: float, baseline: Optional[Any] = None) -> str:
    """Clinically informed status checks based on baselines or static thresholds."""
    if metric_name == "heart_rate":
        mean = baseline.mean if (baseline and baseline.is_established) else 70.0
        std = baseline.std if (baseline and baseline.is_established) else 5.0
        if val > mean + 2 * std or val > 100 or val < 50:
            return "abnormal"
        if val > mean + 1 * std or val > 90 or val < 55:
            return "elevated"
        return "normal"

    elif metric_name == "bp_systolic":
        if val >= 140:
            return "abnormal"
        if val >= 120:
            return "elevated"
        return "normal"

    elif metric_name == "bp_diastolic":
        if val >= 90:
            return "abnormal"
        if val >= 80:
            return "elevated"
        return "normal"

    elif metric_name == "steps":
        mean = baseline.mean if (baseline and baseline.is_established) else 6000.0
        std = baseline.std if (baseline and baseline.is_established) else 1000.0
        if val < 1000 or val < mean - 2 * std:
            return "abnormal"
        if val < 3000 or val < mean - 1 * std:
            return "elevated"
        return "normal"

    elif metric_name == "sleep_hours":
        mean = baseline.mean if (baseline and baseline.is_established) else 7.5
        std = baseline.std if (baseline and baseline.is_established) else 1.0
        if val < 5.0 or val > 10.0 or abs(val - mean) > 2 * std:
            return "abnormal"
        if val < 6.0 or val > 9.0 or abs(val - mean) > 1 * std:
            return "elevated"
        return "normal"

    elif metric_name == "oxygen_sat":
        if val < 93.0:
            return "abnormal"
        if val < 95.0:
            return "elevated"
        return "normal"

    elif metric_name == "blood_glucose":
        if val > 140.0 or val < 70.0:
            return "abnormal"
        if val > 100.0 or val < 80.0:
            return "elevated"
        return "normal"

    elif metric_name == "body_temp":
        if val > 37.8 or val < 35.5:
            return "abnormal"
        if val > 37.3 or val < 36.0:
            return "elevated"
        return "normal"

    elif metric_name == "skin_temp_delta":
        if val > 2.0 or val < -2.0:
            return "abnormal"
        if val > 1.0 or val < -1.0:
            return "elevated"
        return "normal"

    elif metric_name == "mood_score":
        if val <= 2:
            return "abnormal"
        if val == 3:
            return "elevated"
        return "normal"

    elif metric_name == "sleep_quality":
        if val < 60:
            return "abnormal"
        if val < 75:
            return "elevated"
        return "normal"

    return "normal"


def get_fallback_insight(metric_id: str, card_data: Dict[str, Any], timeframe_str: str) -> str:
    """Generates a warm, direct deterministic fallback insight based on the trend and timeframe."""
    trend_bars = card_data["trend_bars"]
    if not trend_bars:
        return f"Your metrics were stable and steady {timeframe_str}."

    statuses = [bar["status"] for bar in trend_bars]
    values = [bar["value"] for bar in trend_bars]
    avg_val = sum(values) / len(values) if values else 0.0

    is_today = timeframe_str == "today"

    if metric_id == "blood_pressure":
        if is_today:
            latest_bar = trend_bars[-1]
            if latest_bar["status"] == "abnormal":
                return "Your blood pressure is higher than usual today – worth a quick review."
            if latest_bar["status"] == "elevated":
                return "Your blood pressure is slightly elevated today; try to keep things relaxed."
            return "Your blood pressure is stable and within your typical range today."
        
        if "abnormal" in statuses:
            return f"Your blood pressure showed a couple of higher readings {timeframe_str} – worth a quick review."
        if "elevated" in statuses:
            return f"Your blood pressure has been slightly elevated {timeframe_str}; try to keep things relaxed."
        return f"Your blood pressure has been stable and within your typical range {timeframe_str}."

    elif metric_id == "steps":
        if is_today:
            val = int(values[-1])
            if val >= 10000:
                return f"You reached a wonderful total of {val:,} steps today, keeping your activity strong!"
            if val < 3000:
                return f"You walked {val:,} steps today; a gentle walk later could help boost your energy."
            return f"You completed a steady {val:,} steps today. Keep up the good movement!"
            
        if avg_val >= 9000:
            return f"You stayed highly active {timeframe_str}, keeping your daily movement strong and steady!"
        if values[-1] < 3000:
            return f"Your activity levels dropped slightly recently; a gentle walk today could help boost your energy."
        return f"You maintained a steady and consistent walking routine {timeframe_str}."

    elif metric_id == "sleep_hours":
        if is_today:
            val = round(values[-1], 1)
            if val < 6.0:
                return f"You got {val} hours of sleep last night; try to rest and catch up today."
            return f"You got a restful {val} hours of sleep last night, a great start to your day."

        if avg_val < 6.0:
            return f"You got less sleep than usual {timeframe_str}; try to rest and catch up on sleep today."
        if avg_val < 7.0:
            return f"Your sleep has been slightly shorter recently, but overall consistent."
        return f"You enjoyed a wonderful, restful sleep pattern {timeframe_str}."

    elif metric_id == "heart_rate":
        if is_today:
            val = int(values[-1])
            if val > 90:
                return f"Your heart rate is resting slightly higher today ({val} bpm); take things slowly."
            return f"Your resting heart rate is stable today at {val} bpm."

        if avg_val > 80:
            return f"Your resting heart rate was slightly elevated {timeframe_str}; a perfect day to rest and take things slow."
        if avg_val < 52:
            return f"Your resting heart rate is a bit low; let us know if you feel any dizziness."
        return f"Your heart rate remained stable and within your normal range {timeframe_str}."

    elif metric_id == "oxygen_sat":
        if is_today:
            val = int(values[-1])
            if val < 94:
                return f"Your oxygen level is slightly low today at {val}%; take some deep breaths."
            return f"Your oxygen level is excellent today, resting at {val}%."

        if any(v < 94 for v in values):
            return f"Your oxygen level dipped slightly {timeframe_str}; take some deep breaths and monitor it."
        return f"Your oxygen levels remained excellent and stable {timeframe_str}, staying above 95%."

    elif metric_id == "blood_glucose":
        if is_today:
            val = int(values[-1])
            if val > 140:
                return f"Your blood glucose was high today at {val} mg/dL; keep an eye on your meals."
            return f"Your blood glucose is steady and well-managed today at {val} mg/dL."

        if any(v > 140 for v in values):
            return f"Fasting blood sugar showed some fluctuations {timeframe_str}; it is a good time to monitor your meals."
        return f"Your blood glucose readings remained steady and well-managed {timeframe_str}."

    elif metric_id == "body_temp":
        if is_today:
            val = round(values[-1], 1)
            if val > 37.5:
                return f"Your body temperature is slightly elevated today at {val}°C; monitor for any fever."
            return f"Your body temperature is normal at {val}°C."

        if any(v > 37.5 for v in values):
            return f"Your body temperature rose slightly {timeframe_str}; monitor closely for any signs of fever."
        return f"Your body temperature remained stable and perfectly normal {timeframe_str}."

    elif metric_id == "mood_score":
        if is_today:
            val = int(values[-1])
            if val <= 2:
                return "You logged a lower mood today; remember that we are here to support you."
            return "You logged a positive and cheerful mood rating today!"

        if avg_val <= 2.5:
            return f"You have been feeling a bit low {timeframe_str}; remember that we are here to support you."
        if avg_val <= 3.5:
            return f"Your mood was steady {timeframe_str}, with some quiet moments. Hope you have a bright day today!"
        return f"You have been in high spirits, logging positive and cheerful mood ratings {timeframe_str}!"

    elif metric_id == "sleep_quality":
        if is_today:
            val = int(values[-1])
            if val < 70:
                return f"Your sleep quality was slightly lower last night ({val}/100); try a relaxing routine tonight."
            return f"You enjoyed excellent sleep quality last night ({val}/100)."

        if avg_val < 70:
            return f"Your sleep quality dipped slightly {timeframe_str}; try a relaxing bedtime routine tonight."
        return f"You reported excellent sleep quality {timeframe_str}."

    return f"Your vitals remained stable and steady {timeframe_str}."


async def generate_vitals_cards(patient_id: str, timeframe: str = "7 days") -> List[Dict[str, Any]]:
    """
    Fetches raw patient context and generates structured vital card data.
    Dynamically filters and aggregates metrics based on the specified timeframe.
    Queries Gemini for conversational insights or falls back to rules.
    """
    today_date = datetime.now().date()
    
    # 1. Normalize timeframe parameter
    tf = timeframe.lower().strip()
    if tf in ("today", "1 day", "1day"):
        limit = 1
        timeframe_str = "today"
    elif tf in ("7 days", "7day", "7days", "1 week", "7 Days"):
        limit = 7
        timeframe_str = "over the past 7 days"
    elif tf in ("30 days", "30day", "30days", "1 month", "30 Days"):
        limit = 30
        timeframe_str = "over the past 30 days"
    elif tf in ("3 months", "3month", "3months", "90 days", "90day", "90days", "3 Months"):
        limit = 90
        timeframe_str = "over the past 3 months"
    else:
        limit = 7
        timeframe_str = "over the past 7 days"

    ctx = fetch_patient_context(patient_id)
    vitals_dict = ctx.vitals._vitals
    baselines_dict = ctx.baseline_status.baselines if ctx.baseline_status else {}

    cards = []

    # 2. Process Blood Pressure (combined bp_systolic and bp_diastolic)
    has_sys = "bp_systolic" in vitals_dict and len(vitals_dict["bp_systolic"]) > 0
    has_dia = "bp_diastolic" in vitals_dict and len(vitals_dict["bp_diastolic"]) > 0
    if has_sys or has_dia:
        sys_vals = sorted(vitals_dict.get("bp_systolic", []), key=lambda x: x.date)
        dia_vals = sorted(vitals_dict.get("bp_diastolic", []), key=lambda x: x.date)

        # Map by date to combine
        bp_by_date = {}
        for sv in sys_vals:
            bp_by_date[sv.date] = {"sys": sv.value, "dia": None}
        for dv in dia_vals:
            if dv.date not in bp_by_date:
                bp_by_date[dv.date] = {"sys": None, "dia": dv.value}
            else:
                bp_by_date[dv.date]["dia"] = dv.value

        sorted_dates = sorted(bp_by_date.keys())
        if limit > 1:
            sorted_dates = [d for d in sorted_dates if d != today_date]
        recent_dates = sorted_dates[-limit:]

        trend_bars = []
        bp_sys_baseline = baselines_dict.get("bp_systolic")
        bp_dia_baseline = baselines_dict.get("bp_diastolic")

        for d in recent_dates:
            sys_val = bp_by_date[d]["sys"]
            dia_val = bp_by_date[d]["dia"]
            
            # Use fallback default if one is missing
            s_val = sys_val if sys_val is not None else 120.0
            d_val = dia_val if dia_val is not None else 80.0

            sys_status = determine_day_status("bp_systolic", s_val, bp_sys_baseline)
            dia_status = determine_day_status("bp_diastolic", d_val, bp_dia_baseline)
            
            if sys_status == "abnormal" or dia_status == "abnormal":
                merged_status = "abnormal"
            elif sys_status == "elevated" or dia_status == "elevated":
                merged_status = "elevated"
            else:
                merged_status = "normal"

            trend_bars.append({
                "date": d.isoformat(),
                "value": s_val,
                "diastolic": d_val,
                "status": merged_status
            })

        if trend_bars:
            if limit == 1:
                latest_bar = trend_bars[-1]
                display_val = f"{int(latest_bar['value'])}/{int(latest_bar['diastolic'])}"
            else:
                sys_values = [bar["value"] for bar in trend_bars]
                dia_values = [bar["diastolic"] for bar in trend_bars]
                avg_sys = sum(sys_values) / len(sys_values) if sys_values else 120.0
                avg_dia = sum(dia_values) / len(dia_values) if dia_values else 80.0
                display_val = f"{int(avg_sys)}/{int(avg_dia)}"

            cards.append({
                "metric_id": "blood_pressure",
                "title": SUPPORTED_METRICS["blood_pressure"]["title"],
                "display_value": display_val,
                "unit": SUPPORTED_METRICS["blood_pressure"]["unit"],
                "label": "LATEST" if limit == 1 else SUPPORTED_METRICS["blood_pressure"]["label"],
                "trend_bars": trend_bars,
                "insight": ""
            })

    # 3. Process other individual metrics
    for metric_name, details in SUPPORTED_METRICS.items():
        if metric_name == "blood_pressure":
            continue

        internal_name = metric_name
        if metric_name == "oxygen_sat":
            internal_name = "oxygen_sat"
        elif metric_name == "body_temp":
            internal_name = "body_temp"
        elif metric_name == "skin_temp_delta":
            internal_name = "skin_temp_delta"
        elif metric_name == "blood_glucose":
            internal_name = "blood_glucose"

        if internal_name in vitals_dict and len(vitals_dict[internal_name]) > 0:
            raw_vals = sorted(vitals_dict[internal_name], key=lambda x: x.date)
            if limit > 1:
                raw_vals = [v for v in raw_vals if v.date != today_date]
            recent_vals = raw_vals[-limit:]
            baseline = baselines_dict.get(internal_name)

            trend_bars = []
            for d in recent_vals:
                status = determine_day_status(internal_name, d.value, baseline)
                trend_bars.append({
                    "date": d.date.isoformat(),
                    "value": d.value,
                    "status": status
                })

            if not trend_bars:
                continue

            latest_val = trend_bars[-1]["value"]
            
            # Format display value and override label based on timeframe limit
            label_val = details["label"]
            if limit == 1:
                label_val = "LATEST"
                # For single-day steps, show it raw (it is total for that day)
                if metric_name == "steps":
                    display_val = f"{int(latest_val):,}"
                elif metric_name == "sleep_hours":
                    display_val = f"{round(latest_val, 1)}"
                elif metric_name == "heart_rate":
                    display_val = f"{int(latest_val)}"
                elif metric_name == "oxygen_sat":
                    display_val = f"{int(latest_val)}%"
                elif metric_name == "blood_glucose":
                    display_val = f"{int(latest_val)}"
                elif metric_name == "body_temp":
                    display_val = f"{round(latest_val, 1)}°C"
                elif metric_name == "skin_temp_delta":
                    sign = "+" if latest_val > 0 else ""
                    display_val = f"{sign}{round(latest_val, 1)}°C"
                elif metric_name == "mood_score":
                    display_val = f"{int(latest_val)}/5"
                elif metric_name == "sleep_quality":
                    display_val = f"{int(latest_val)}/100"
                else:
                    display_val = str(latest_val)
            else:
                # Timeframe > 1 day: aggregate appropriately
                if metric_name == "steps":
                    avg_steps = sum(bar["value"] for bar in trend_bars) / len(trend_bars)
                    display_val = f"{int(avg_steps):,}"
                    label_val = "AVG"
                elif metric_name == "sleep_hours":
                    avg_sleep = sum(bar["value"] for bar in trend_bars) / len(trend_bars)
                    display_val = f"{round(avg_sleep, 1)}"
                    label_val = "AVG"
                elif metric_name == "heart_rate":
                    avg_hr = sum(bar["value"] for bar in trend_bars) / len(trend_bars)
                    display_val = f"{int(avg_hr)}"
                    label_val = "AVG"
                elif metric_name == "oxygen_sat":
                    avg_spo2 = sum(bar["value"] for bar in trend_bars) / len(trend_bars)
                    display_val = f"{int(avg_spo2)}%"
                    label_val = "AVG"
                elif metric_name == "blood_glucose":
                    # glucose remains "LATEST"
                    display_val = f"{int(latest_val)}"
                    label_val = "LATEST"
                elif metric_name == "body_temp":
                    avg_temp = sum(bar["value"] for bar in trend_bars) / len(trend_bars)
                    display_val = f"{round(avg_temp, 1)}°C"
                    label_val = "AVG"
                elif metric_name == "skin_temp_delta":
                    avg_skin_temp = sum(bar["value"] for bar in trend_bars) / len(trend_bars)
                    sign = "+" if avg_skin_temp > 0 else ""
                    display_val = f"{sign}{round(avg_skin_temp, 1)}°C"
                    label_val = "AVG"
                elif metric_name == "mood_score":
                    avg_mood = sum(bar["value"] for bar in trend_bars) / len(trend_bars)
                    display_val = f"{round(avg_mood, 1)}/5"
                    label_val = "AVG"
                elif metric_name == "sleep_quality":
                    avg_qual = sum(bar["value"] for bar in trend_bars) / len(trend_bars)
                    display_val = f"{int(avg_qual)}/100"
                    label_val = "AVG"
                else:
                    display_val = str(latest_val)

            cards.append({
                "metric_id": metric_name,
                "title": details["title"],
                "display_value": display_val,
                "unit": details["unit"],
                "label": label_val,
                "trend_bars": trend_bars,
                "insight": ""
            })

    if not cards:
        return []

    # 4. Call Gemini in a single call to generate conversational insights for all cards
    vitals_data_summary = []
    for card in cards:
        m_id = card["metric_id"]
        title = card["title"]
        d_val = card["display_value"]
        unit = card["unit"]
        
        if m_id == "blood_pressure":
            history = [f"{bar['value']}/{bar['diastolic']}" for bar in card["trend_bars"]]
        else:
            history = [str(bar["value"]) for bar in card["trend_bars"]]

        vitals_data_summary.append(
            f"- {title} (ID: {m_id}): Current value/aggregation is {d_val} {unit} ({card['label']}). "
            f"Readings in this window: {', '.join(history)}."
        )

    vitals_summary_str = "\n".join(vitals_data_summary)

    prompt = f"""You are a compassionate clinical assistant at Zivaa Eldercare.
For each active vital metric listed below, write a warm, encouraging, one-sentence insight (10 to 15 words maximum) summarizing the senior patient's trend {timeframe_str}.

Guidelines:
1. Address the senior user directly in the second person ("you", "your").
2. Keep the tone warm, friendly, reassuring, and non-clinical.
3. Do NOT use medical jargon or reference technical guidelines.
4. Highlight positive behaviors (e.g., meeting step targets or getting enough rest) or gently mention mild deviations from normal or baseline (e.g., sleep being slightly shorter than usual).
5. Output your response as a JSON object where the keys are the exact metric IDs and the values are the 1-sentence insight strings. Do not add any markdown formatting outside of the JSON block.

Patient Vital Trends {timeframe_str}:
{vitals_summary_str}

Format the response as exact JSON:
{{
  "steps": "Warm, one-sentence steps insight...",
  "sleep_hours": "Warm, one-sentence sleep insight...",
  ...
}}"""

    llm_insights = {}
    if settings.GEMINI_API_KEY and settings.GEMINI_API_KEY != "your-api-key-here":
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key={settings.GEMINI_API_KEY}"
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
                    llm_insights = json.loads(text_content.strip())
                else:
                    print(f"Vitals cards LLM error status: {response.status_code}, response: {response.text}")
        except Exception as e:
            print(f"Vitals cards LLM exception: {repr(e)}")

    # 5. Fill insights (use fallback if LLM failed or key is missing)
    for card in cards:
        m_id = card["metric_id"]
        insight_text = llm_insights.get(m_id)
        if not insight_text:
            insight_text = get_fallback_insight(m_id, card, timeframe_str)
        card["insight"] = insight_text

    return cards
