import json
import httpx
from typing import Dict, Any, List, Optional
from datetime import datetime, date, timedelta
from app.config import settings
from app.services.insights.context import EvalContext, MetricValue
from app.services.insights.core import OVERNIGHT_METRICS, CUMULATIVE_METRICS
from app.services.macro_calculator import calculate_daily_macros
from app.services.loinc_dictionary import get_loinc_mapping, LOINC_DICTIONARY, get_consumer_category

async def _call_medgemma(prompt: str, json_mode: bool = False, prefill: bool = True, response_schema: Optional[Dict] = None, file_part: Optional[Dict] = None) -> str:
    """
    Asynchronously calls the MedGemma (or Gemini 2.5 Pro medical proxy) endpoint.
    Supports standard Vertex AI endpoints, overridden URLs, and fallbacks to Google AI Studio.
    Includes rate limit retry logic (429 handling) with backoff.
    """
    import asyncio
    
    if getattr(settings, "FORCE_GEMINI", False):
        model = "gemini-2.5-flash"
        ai_studio_key = settings.GEMINI_API_KEY if settings.GEMINI_API_KEY != "your-api-key-here" else settings.VERTEX_API_KEY
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={ai_studio_key}"
        headers = {"Content-Type": "application/json"}
        
        parts = []
        if file_part:
            parts.append(file_part)
        parts.append({"text": prompt})
        
        payload = {"contents": [{"parts": parts}]}
        if json_mode:
            gen_config = {"responseMimeType": "application/json"}
            if response_schema:
                gen_config["responseSchema"] = response_schema
            payload["generationConfig"] = gen_config
            
        # Bypass Vertex checks by returning immediately with the Gemini payload logic below
        # Wait, the rest of the function executes the HTTP request. We just need to make sure
        # url, headers, and payload are set and bypass the Vertex payload setup.
    else:
        url = settings.MEDGEMMA_API_URL
        headers = {
            "Content-Type": "application/json",
        }
    
        if url:
            if ("googleapis.com" in url or "vertexai.goog" in url) and settings.VERTEX_API_KEY:
                is_gcp_token = settings.VERTEX_API_KEY.startswith("ya29.") or len(settings.VERTEX_API_KEY) > 80
                if is_gcp_token:
                    headers["Authorization"] = f"Bearer {settings.VERTEX_API_KEY}"
        else:
            # Check if the key looks like a GCP OAuth2 token (usually starts with ya29. or is extremely long)
            is_gcp_token = settings.VERTEX_API_KEY.startswith("ya29.") or len(settings.VERTEX_API_KEY) > 80
            
            if is_gcp_token:
                # Vertex AI REST URL
                url = (
                    f"https://{settings.VERTEX_REGION}-aiplatform.googleapis.com/v1/"
                    f"projects/{settings.VERTEX_PROJECT_ID}/locations/{settings.VERTEX_REGION}/"
                    f"publishers/google/models/{settings.MEDGEMMA_MODEL_NAME}:generateContent"
                )
                headers["Authorization"] = f"Bearer {settings.VERTEX_API_KEY}"
            else:
                # If the user has supplied a standard developer API key, fallback to Google AI Studio endpoint structure
                model = settings.MEDGEMMA_MODEL_NAME if settings.MEDGEMMA_MODEL_NAME != "medlm-large" else "gemini-2.5-flash"
                ai_studio_key = settings.GEMINI_API_KEY if settings.GEMINI_API_KEY != "your-api-key-here" else settings.VERTEX_API_KEY
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={ai_studio_key}"

    if settings.MEDGEMMA_API_URL and not getattr(settings, "FORCE_GEMINI", False):
        # Wrap prompt in the official Gemma Instruct chat template
        # If in json_mode and prefill is True, pre-fill the output prefix to suppress the verbose 'thought' block.
        if json_mode and prefill:
            formatted_prompt = f"<start_of_turn>user\n{prompt}<end_of_turn>\n<start_of_turn>model\nOutput:\n{{"
        else:
            formatted_prompt = f"<start_of_turn>user\n{prompt}<end_of_turn>\n<start_of_turn>model\nOutput:\n"
        payload = {
            "instances": [
                {
                    "prompt": formatted_prompt,
                    "max_tokens": 2048,
                    "temperature": 0.2
                }
            ],
            "parameters": {
                "max_tokens": 2048,
                "temperature": 0.2
            }
        }
    else:
        parts = []
        if file_part:
            parts.append(file_part)
        parts.append({"text": prompt})
        
        payload = {
            "contents": [{"parts": parts}],
        }
        if json_mode:
            gen_config = {"responseMimeType": "application/json"}
            if response_schema:
                gen_config["responseSchema"] = response_schema
            payload["generationConfig"] = gen_config

    max_attempts = 4
    backoff_factor = 5.0

    for attempt in range(max_attempts):
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, headers=headers, json=payload, timeout=120.0)
                
                if response.status_code == 200:
                    try:
                        data = response.json()
                    except Exception as json_err:
                        print(f"Failed to parse model response as JSON. Status 200. Raw text: {response.text[:1000]}")
                        raise json_err
                    print(f"DEBUG: Vertex AI Endpoint response JSON: {data}")
                    if "predictions" in data:
                        pred = data["predictions"][0]
                        if isinstance(pred, dict):
                            text = pred.get("generated_text") or pred.get("text") or str(pred)
                        else:
                            text = str(pred)
                        
                        # Extract everything after the model turn marker
                        model_marker = "<start_of_turn>model\n"
                        if model_marker in text:
                            text = text.split(model_marker)[-1]
                        
                        # If "Output:" is present anywhere in the text, split by the last occurrence
                        # to bypass the thinking phase and get the actual JSON/response.
                        if "Output:" in text:
                            text = text.split("Output:")[-1]
                        elif "output:" in text:
                            text = text.split("output:")[-1]
                        
                        # Strip standard Output: headers from the start of the text
                        if text.startswith("Output:\n"):
                            text = text[len("Output:\n"):]
                        elif text.startswith("Output:"):
                            text = text[len("Output:"):]
                        
                        # If in json_mode and it doesn't start with '{' or codeblock, we prepend it
                        if json_mode and not text.strip().startswith("{") and not text.strip().startswith("`"):
                            text = "{" + text.strip()
                            
                        return text.strip()
                    
                    text_res = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                    return text_res
                
                elif response.status_code == 429:
                    retry_delay = 10.0
                    try:
                        resp_json = response.json()
                        error_details = resp_json.get("error", {}).get("details", [])
                        for detail in error_details:
                            if "retryDelay" in str(detail):
                                delay_str = detail.get("retryDelay", "10s")
                                if delay_str.endswith("s"):
                                    retry_delay = float(delay_str[:-1])
                                else:
                                    retry_delay = float(delay_str)
                    except Exception:
                        pass
                    
                    sleep_time = max(retry_delay, backoff_factor * (attempt + 1))
                    print(f"  [Rate Limit 429] Exceeded quota. Retrying in {sleep_time:.1f}s (attempt {attempt+1}/{max_attempts})...")
                    await asyncio.sleep(sleep_time)
                    continue
                
                else:
                    # If Vertex failed and we haven't tried AI Studio, try it as a robust fallback
                    if "generativelanguage" not in url:
                        fallback_model = "gemini-2.5-flash"
                        ai_studio_key = settings.GEMINI_API_KEY if settings.GEMINI_API_KEY != "your-api-key-here" else settings.VERTEX_API_KEY
                        fallback_url = f"https://generativelanguage.googleapis.com/v1beta/models/{fallback_model}:generateContent?key={ai_studio_key}"
                        fallback_resp = await client.post(fallback_url, headers={"Content-Type": "application/json"}, json=payload, timeout=30.0)
                        
                        if fallback_resp.status_code == 200:
                            data = fallback_resp.json()
                            return data["candidates"][0]["content"]["parts"][0]["text"].strip()
                        elif fallback_resp.status_code == 429:
                            # Propagate 429 to trigger loop retry
                            print(f"  [Rate Limit 429] Fallback failed with 429. Retrying loop...")
                            await asyncio.sleep(backoff_factor * (attempt + 1))
                            continue
                    
                    raise Exception(f"API Call failed (Status {response.status_code}): {response.text}")
        except Exception as e:
            if attempt == max_attempts - 1:
                # Final fallback to standard Google AI Studio endpoint if everything fails and we have a key
                ai_studio_key = settings.GEMINI_API_KEY if settings.GEMINI_API_KEY != "your-api-key-here" else settings.VERTEX_API_KEY
                if ai_studio_key and "generativelanguage" not in url:
                    try:
                        fallback_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={ai_studio_key}"
                        async with httpx.AsyncClient() as fallback_client:
                            fallback_resp = await fallback_client.post(fallback_url, headers={"Content-Type": "application/json"}, json=payload, timeout=30.0)
                            if fallback_resp.status_code == 200:
                                return fallback_resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                    except Exception as inner_e:
                        print(f"MedGemma fallback failed: {inner_e}")
                raise e
            
            # Simple wait before next retry
            await asyncio.sleep(backoff_factor * (attempt + 1))

    raise Exception("API call failed after max retries due to rate limits or connection errors.")

async def _call_gemini_with_grounding(prompt: str) -> Optional[str]:
    import asyncio
    import re
    
    ai_studio_key = settings.GEMINI_API_KEY if settings.GEMINI_API_KEY != "your-api-key-here" else settings.VERTEX_API_KEY
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={ai_studio_key}"
    headers = {"Content-Type": "application/json"}
    
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"googleSearch": {}}]
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=payload, timeout=60.0)
            if response.status_code == 200:
                data = response.json()
                if "candidates" in data and data["candidates"]:
                    text = data["candidates"][0]["content"]["parts"][0].get("text", "")
                    return text
    except Exception as e:
        print(f"Error calling Gemini with Grounding: {e}")
        
    return None

async def fallback_grounded_loinc_search(search_term: str) -> Optional[Dict]:
    import re
    
    if not search_term:
        return None
        
    prompt = (
        f"You are a clinical pathologist mapping lab test names to LOINC codes. "
        f"Find the definitive, official LOINC code for the following test: '{search_term}'. "
        f"Reply ONLY with the LOINC code itself (e.g., 1234-5) and absolutely no other text, punctuation, or explanations."
    )
    
    response_text = await _call_gemini_with_grounding(prompt)
    if not response_text:
        return None
        
    # Extract LOINC code using regex (format: digits-digit, e.g. 26464-8 or 804-5)
    match = re.search(r"\b\d{2,7}-\d{1}\b", response_text)
    if not match:
        print(f"DEBUG: Grounded search failed to return a valid LOINC format for '{search_term}'. Raw LLM text: {response_text}")
        return None
        
    loinc_code = match.group(0)
    
    # Check if the code exists in our local dictionary to get name and category
    if loinc_code in LOINC_DICTIONARY:
        name = LOINC_DICTIONARY[loinc_code].get("name", "Unknown Name")
        category = LOINC_DICTIONARY[loinc_code].get("category", "Unmapped")
    else:
        # Code not in our 20k subset, but LLM retrieved it via Grounding!
        name = "Web Resolved Biomarker"
        category = "Unmapped"
        
    print(f"DEBUG: Grounding resolved '{search_term}' to '{loinc_code}'")
    return {
        "loinc_code": loinc_code,
        "name": name,
        "category": category,
        "similarity": 0.99
    }

def _clean_json(text: str) -> Dict[str, Any]:
    """Helper to strip markdown JSON block wrappers and parse the string."""
    print(f"DEBUG: _clean_json input: {text[:200]}... [total len: {len(text)}]")
    text = text.strip()
    text = text.replace("{\nOutput:", "{")
    
    # 1. Try to locate standard ```json wrappers from the end of the text
    if "```json" in text:
        try:
            parts = text.split("```json")
            candidate = parts[-1]
            if "```" in candidate:
                candidate = candidate.split("```")[0]
            text = candidate.strip()
        except Exception:
            pass
    elif "```" in text:
        try:
            parts = text.split("```")
            candidate = parts[-2] if len(parts) >= 3 else parts[-1]
            text = candidate.strip()
        except Exception:
            pass
            
    # 2. Extract bounding braces { } by walking backwards from the last closing brace.
    text = text.strip()
    if not (text.startswith("{") and text.endswith("}")):
        end_brace_idx = text.rfind("}")
        if end_brace_idx != -1:
            brace_count = 0
            start_brace_idx = -1
            for i in range(end_brace_idx, -1, -1):
                if text[i] == "}":
                    brace_count += 1
                elif text[i] == "{":
                    brace_count -= 1
                    if brace_count == 0:
                        start_brace_idx = i
                        break
            if start_brace_idx != -1:
                text = text[start_brace_idx:end_brace_idx+1]
            
    print(f"DEBUG: _clean_json final output passed to json.loads: {text}")
    return json.loads(text.strip())


# ═══════════════════════════════════════════════════════════════════
# 1. MEDGEMMA DIAGNOSTICS ENGINE
# ═══════════════════════════════════════════════════════════════════

def format_patient_chart_prompt(ctx: EvalContext, include_labs: bool = True, active_insights: list = None) -> str:
    """
    Formats the patient's full raw telemetry and history into a structured text prompt for MedGemma.
    
    This function supports a dual-mode "Stateful Context Pruning" strategy to save tokens:
    - HEAVY MODE (include_labs=True): Appends the full historical lab data and RCV trends. 
      Used when a new lab report is ingested and we need a deep evaluation.
    - LIGHT MODE (include_labs=False): Omits the expensive lab data block. Instead, it injects 
      a summary of the 'active_insights' fetched from the database, acting as MedGemma's memory.
      Used for daily vital spikes where lab data hasn't changed.
    """
    lines = []
    lines.append(f"PATIENT DEMOGRAPHICS & BACKGROUND:")
    lines.append(f"  - Age: {ctx.patient_age or 'Unknown'}")
    lines.append(f"  - Sex: {ctx.patient_sex or 'Unknown'}")
    lines.append(f"  - Known Chronic Conditions: {', '.join(ctx.patient_conditions) if ctx.patient_conditions else 'None recorded'}")
    lines.append("")

    # 1. Vitals History
    lines.append("DAILY VITALS HISTORY (Last 7 days):")
    vitals_data = ctx.vitals._vitals
    baselines = ctx.vitals._baselines or {}
    
    if not vitals_data:
        lines.append("  - No vitals recorded.")
    else:
        from datetime import datetime, timedelta
        seven_days_ago = (datetime.now() - timedelta(days=7)).date()
        
        for name, vals in vitals_data.items():
            # Show baseline if established
            baseline_str = "None established"
            b = None
            if name in baselines and baselines[name].is_established:
                b = baselines[name]
                baseline_str = f"Mean: {round(b.mean, 2)}, Std: {round(b.std, 2)}"
            
            # Show last 7 days values with Math Injection for anomalies.
            # MATH INJECTION: We pre-calculate Z-Scores in Python and inject them as text strings.
            # This prevents MedGemma from having to do complex floating-point math itself, which LLMs struggle with.
            recent_vals = [v for v in vals if v.date >= seven_days_ago]
            sorted_vals = sorted(recent_vals, key=lambda x: x.date, reverse=True)
            formatted_vals = []
            for v in sorted_vals:
                val_str = f"{v.value} ({v.date})"
                # Math Injection: Calculate Z-Score if baseline exists
                if b and b.std > 0:
                    z_score = (v.value - b.mean) / b.std
                    if abs(z_score) >= 2.0:
                        direction = "SPIKE" if z_score > 0 else "DROP"
                        val_str += f" [CRITICAL {direction}: {z_score:+.1f} standard deviations from normal!]"
                    elif abs(z_score) >= 1.5:
                        direction = "Elevated" if z_score > 0 else "Decreased"
                        val_str += f" [Warning {direction}: {z_score:+.1f} std devs]"
                        
                formatted_vals.append(val_str)
                
            vals_str = ", ".join(formatted_vals)
            lines.append(f"  - {name}:")
            lines.append(f"    - Baseline: {baseline_str}")
            lines.append(f"    - Recent Readings (latest first): {vals_str}")
    lines.append("")

    # 2. Lab History or Active Insights (Stateful Context Pruning)
    # -----------------------------------------------------------
    # If include_labs is True (Heavy Mode), we dump all the raw lab data.
    # If False (Light Mode), we skip it to save tokens and use the active_insights memory instead.
    if include_labs:
        lines.append("LAB RESULTS & HISTORICAL TRENDS:")
        labs_data = ctx.labs._labs
        trend_data = ctx.labs._trends or {}
        
        if not labs_data:
            lines.append("  - No lab results recorded.")
        else:
            for code, reports in labs_data.items():
                lines.append(f"  - Biomarker Code: {code}")
                
                # Math Injection for Labs: Show pre-computed Reference Change Value (RCV) trends.
                if code in trend_data:
                    tr = trend_data[code]
                    lines.append(f"    - Computed RCV Trend: {tr.get('trend_direction', 'stable')} (Change: {tr.get('change_percent', 0.0):+.1f}%, Rate/Month: {tr.get('rate_per_month', 0.0):+.2f}, Zone: {tr.get('zone', 'normal')}, Flag: {tr.get('clinical_flag', 'normal')})")
                
                # List historical readings
                readings = []
                for r in sorted(reports, key=lambda x: x.get("measured_at", ""), reverse=True):
                    val = r.get("value")
                    unit = r.get("unit", "")
                    low = r.get("reference_low")
                    high = r.get("reference_high")
                    flag = r.get("flag", "normal")
                    date_str = r.get("measured_at", "")[:10]
                    readings.append(f"{val} {unit} [Ref: {low}-{high}] ({flag}) on {date_str}")
        lines.append("")
    else:
        lines.append("ACTIVE CLINICAL ISSUES (from recent lab analysis):")
        if not active_insights:
            lines.append("  - No active clinical issues recorded.")
        else:
            for insight in active_insights:
                lines.append(f"  - {insight.get('name', 'Issue')}: {insight.get('message', '')}")
        lines.append("")

    # 3. Medication Adherence
    lines.append("MEDICATION ADHERENCE (Past 7 days):")
    rate = ctx.meds.adherence_rate()
    if rate is not None:
        lines.append(f"  - Adherence Rate: {rate * 100:.1f}%")
        lines.append(f"  - Missed Doses: {ctx.meds.missed_doses()}")
    else:
        lines.append("  - Adherence Rate: Unknown (No medication logs found)")
    
    return "\n".join(lines)

async def generate_medgemma_alerts(ctx: EvalContext, tripped_insights: Optional[List[Any]] = None, trigger_type: str = "vitals", existing_insights: list = None, trigger_date: Optional[str] = None) -> Dict[str, Any]:
    """
    Evaluates raw patient metrics using MedGemma to identify active health concerns.
    
    Architecture: Hybrid Deterministic + LLM Engine
    - If `tripped_insights` are provided (triggered by daily vitals rules engine), 
      the LLM focuses *only* on explaining the rules engine's findings (Light Mode).
    - If `trigger_type="labs"`, the LLM performs a full review of all data (Heavy Mode),
      and reconciles its findings against `existing_insights` (Stateful Memory).
      
    Returns a list of dicts that conform to the InsightResult JSON schema.
    """
    if existing_insights is None:
        existing_insights = []
        
    chart_text = format_patient_chart_prompt(
        ctx, 
        include_labs=(trigger_type == "labs"), 
        active_insights=existing_insights
    )
    
    focus_prompt = ""
    if tripped_insights:
        # Vitals Spike Logic: The rules engine already found an anomaly. 
        # MedGemma's job is just to explain the 'Why' clinically.
        tripwire_str = "\n".join([f"- [ID: {i.rule_id}] {i.name} (Severity: {i.severity.value}): {i.message}" for i in tripped_insights])
        focus_prompt = f"""
CRITICAL FOCUS: The deterministic rules engine has just tripped the following anomalies:
{tripwire_str}

Your task is specifically to evaluate these exact anomalies within the context of the patient's full chart. Provide clinical reasoning explaining *why* they occurred based on the other vitals and lab data provided below. Do NOT scan for new alerts, only explain the tripped ones.
CRITICAL INSTRUCTION: For each triggered anomaly, you MUST use its exact [ID] from the list above as the `rule_id` in your JSON output.
"""
    else:
        # Full Review Logic: Used during lab ingest or full periodic scans.
        focus_prompt = "Your task is to review all metrics, baselines, trends, and lab history, and identify any active health concerns or risk flags."
        
        # Stateful Reconciliation: Instruct the LLM to update existing state (resolve vs manage).
        existing_str = "\n".join([f"- [ID: {i.get('rule_id')}] {i.get('name')}: {i.get('message')}" for i in existing_insights])
        focus_prompt += f"""\n\nCRITICAL FOCUS: The patient currently has the following active issues:\n{existing_str}

Please reconcile these existing issues with the new data:
- For ACUTE issues (e.g. fever, infection) that have demonstrably disappeared based on new data, explicitly add their [ID] to the `resolved_insights` array.
- For CHRONIC issues (e.g. diabetes, hypertension) that have returned to normal ranges, DO NOT resolve them. Keep them in `active_insights`, update severity to LOW, rename to 'Controlled...', and KEEP the exact same rule_id.
- DO NOT resolve an issue simply because there is no new data for it today. Only resolve if the fresh data proves the issue is gone.
- CRITICAL INSTRUCTION: You must strictly reuse the exact [ID] from the `existing_insights` if the issue is a continuation or escalation of a previously identified problem. Do NOT invent a new snake_case ID if the underlying clinical issue is the same as an existing active issue."""

    if trigger_date:
        focus_prompt += f"\n\nCRITICAL INSTRUCTION: You are evaluating this patient on {trigger_date}. You must ONLY generate new alerts for anomalies or patterns that are actively present on {trigger_date}. Do NOT generate new alerts for isolated historical spikes or drops that occurred prior to this date. The historical data provided is strictly for establishing context and baselines."
        focus_prompt += f"\n- CUMULATIVE METRICS GUARD: If {trigger_date} is today or in progress, cumulative metrics ({', '.join(sorted(CUMULATIVE_METRICS))}) are incomplete and still accumulating. NEVER treat a low count of steps, calories, or exercise minutes today as a drop, decline, or deficiency."

    focus_prompt += "\n- CLINICAL GUIDELINE: Do not diagnose functional decline, elevated fall risk, or activity decrease based on a single day of low step count. Normal daily variation (charging device, weather, rest day) accounts for single-day fluctuations. Require a sustained drop or immobility over at least 3 consecutive completed days (e.g., Tudor-Locke 2011)."
    
    prompt = f"""You are MedGemma, an advanced clinical reasoning AI model.
Review the following patient clinical chart:

{chart_text}

{focus_prompt}

For each active concern you identify:
1. Assess the severity (LOW, MEDIUM, HIGH) using standard clinical practice guidelines (e.g. ADA for HbA1c, AHA for blood pressure, KDIGO for kidney function).
2. Map it to one of these category values: CARDIAC, METABOLIC, RENAL, RESPIRATORY, HEMATOLOGY, THYROID, NUTRITION, MENTAL_HEALTH, GENERAL.
3. Assign a short, descriptive rule_id in snake_case (e.g., 'hypertension_escalation', 'prediabetes_progression').
4. Write a concise, supportive message explaining the concern. You MUST explicitly state the exact numerical baseline value for any anomalous metric you mention, formatted to a maximum of 1 decimal place (e.g., 'baseline 95.2%'). Do not use vague terms like 'above baseline' without providing the numerical baseline value. Reference specific values and guideline citations where appropriate. If a lab result or reading is from an older historical report (e.g., more than a few months old), explicitly state its date in your message so it is clear it is a historical finding.
5. Populate the evidence array with the exact metrics and values that triggered this alert (e.g. [{{"metric": "bp_systolic", "value": "142"}}]).
"""
    
    # JSON Schema definition strictly enforces the output structure, eliminating the need 
    # for messy regex parsing and guaranteeing the response can be mapped to the DB.
    schema = {
        "type": "OBJECT",
        "properties": {
            "active_insights": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "rule_id": {"type": "STRING"},
                        "name": {"type": "STRING"},
                        "severity": {"type": "STRING"},
                        "category": {"type": "STRING"},
                        "message": {"type": "STRING"},
                        "evidence": {
                            "type": "ARRAY",
                            "items": {
                                "type": "OBJECT",
                                "properties": {
                                    "metric": {"type": "STRING"},
                                    "value": {"type": "STRING"}
                                }
                            }
                        }
                    }
                }
            },
            "resolved_insights": {
                "type": "ARRAY",
                "items": {
                    "type": "STRING"
                }
            }
        }
    }
    
    try:
        # Note: We pass response_schema to the Gemini API, which forces the model's 
        # internal logits to only generate tokens valid within this schema.
        raw_response = await _call_medgemma(prompt, json_mode=True, prefill=False, response_schema=schema)
        
        # Clean markdown wrappers if present (sometimes the model still adds them)
        if "```json" in raw_response:
            raw_response = raw_response.split("```json")[-1].split("```")[0].strip()
            
        parsed = json.loads(raw_response)
        
        # Reconstruct the evidence array back into a dictionary for downstream logic
        for alert in parsed.get("active_insights", []):
            if isinstance(alert.get("evidence"), list):
                # Convert [{"metric": "bp", "value": "142"}] -> {"bp": "142"}
                alert["evidence"] = {item.get("metric", ""): item.get("value") for item in alert["evidence"] if isinstance(item, dict) and "metric" in item}
                
        return parsed
    except Exception as e:
        print(f"MedGemma Diagnostics failed: {e}")
        # Fallback to empty structure so compare endpoint and tripwires do not crash
        return {"active_insights": [], "resolved_insights": []}


def _normalize_insights(insights: List[Any]) -> List[Dict[str, Any]]:
    normalized = []
    for i in insights:
        if isinstance(i, dict):
            normalized.append(i)
        else:
            # Handle objects (like InsightResult)
            sev = getattr(i, "severity", "LOW")
            if hasattr(sev, "value"):
                sev = sev.value
            cat = getattr(i, "category", "GENERAL")
            if hasattr(cat, "value"):
                cat = cat.value
            
            normalized.append({
                "rule_id": getattr(i, "rule_id", getattr(i, "id", "")),
                "name": getattr(i, "name", ""),
                "severity": str(sev),
                "category": str(cat),
                "message": getattr(i, "message", ""),
                "evidence": getattr(i, "evidence", {})
            })
    return normalized


# ═══════════════════════════════════════════════════════════════════
# 2. PARALLEL GENERATION SERVICES
# ═══════════════════════════════════════════════════════════════════

async def generate_medgemma_nudge(insights: Any, patient_name: str = "Ranjit", is_weekly_digest: bool = False, patient_id: str = None) -> Dict[str, Any]:
    """
    Generates a nudge/notification for the user using MedGemma.
    
    This function takes the active insights (usually generated by `generate_medgemma_alerts`)
    and translates the clinical jargon into a warm, empathetic notification for the user.
    
    Args:
        insights: List of active clinical insights (or a raw vitals dict for legacy fallback).
        patient_name: Name of the patient (used to personalize the message).
        is_weekly_digest: If True, instructs the LLM to write a broad summary rather than an immediate alert.
        
    Returns:
        Dict conforming to the Nudge JSON schema (risk_level, nudge_title, nudge_text, why_flagged, action_steps).
    """
    if not insights:
        return {
            "risk_level": "LOW",
            "nudge_title": "All is stable",
            "nudge_text": f"No critical health insights triggered for {patient_name} today. Vitals appear stable.",
            "why_flagged": "No active alerts.",
            "action_steps": "No action needed. Keep up the good work!"
        }

    highest_severity = "LOW"
    aggregated_evidence = {}
    
    if isinstance(insights, dict):
        anomaly_detected = insights.get("ml_anomaly_detected", False)
        systolic = insights.get("bp_systolic", 120.0)
        diastolic = insights.get("bp_diastolic", 80.0)
        heart_rate = insights.get("avg_heart_rate", 72.0)
        
        is_high_risk = anomaly_detected or (systolic is not None and systolic >= 140.0) or (diastolic is not None and diastolic >= 90.0) or (heart_rate is not None and (heart_rate >= 100.0 or heart_rate <= 50.0))
        highest_severity = "HIGH" if is_high_risk else "LOW"
        
        insights_text = f"""Current Vitals:
- Heart Rate: {heart_rate if heart_rate is not None else 72.0:.1f} bpm
- Blood Pressure: {systolic if systolic is not None else 120.0:.1f}/{diastolic if diastolic is not None else 80.0:.1f} mmHg
- Sleep: {insights.get("sleep_hours", 7.0) if insights.get("sleep_hours") is not None else 7.0:.1f} hrs
- Total Steps: {insights.get("total_steps", 0.0) if insights.get("total_steps") is not None else 0.0:.1f}
- Anomaly Detected by ML: {anomaly_detected}"""
        aggregated_evidence = {k: v for k, v in insights.items() if v is not None}
    else:
        insights = _normalize_insights(insights)
        if not insights:
            return {
                "risk_level": "LOW",
                "nudge_title": "All is stable",
                "nudge_text": f"No critical health insights triggered for {patient_name} today. Vitals appear stable.",
                "why_flagged": "No active alerts.",
                "action_steps": "No action needed. Keep up the good work!"
            }
        
        severity_rank = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}
        for i in insights:
            sev = i.get("severity", "LOW")
            if severity_rank.get(sev, 1) > severity_rank.get(highest_severity, 1):
                highest_severity = sev
            
            ev = i.get("evidence", {})
            if isinstance(ev, dict):
                aggregated_evidence.update(ev)
                
        insights_text = "\n".join([
            f"- {i.get('name')} (Risk: {i.get('severity')}): {i.get('message')} [Evidence: {i.get('evidence')}]"
            for i in insights
        ])

    mode_instruction = "Review the following triggered health insights for the patient"
    digest_instruction = ""
    if is_weekly_digest:
        mode_instruction = "Review the following health insights gathered over the PAST WEEK for the patient"
        digest_instruction += " This is a weekly summary digest. Focus on broader trends rather than immediate panic."

    import json
    import os
    pathways_str = ""
    try:
        pathways_file = os.path.join(os.path.dirname(__file__), "insights", "care_pathways.json")
        with open(pathways_file, "r") as f:
            pathways_data = json.load(f).get("care_pathways", {})
            for key, val in pathways_data.items():
                pathways_str += f"- '{key}': {val.get('definition_for_llm', '')}\n"
    except Exception as e:
        pathways_str = "- 'level_7_wellness_maintenance': Default stable pathway."

    prompt = f"""You are MedGemma, a world-class empathetic clinical AI assistant. Your role is to translate complex health data anomalies into clear, actionable, and comforting insights for an elderly user or their caregiver. You must never induce panic, but you must not dilute genuine health concerns.

CONTEXT:
{mode_instruction}, {patient_name}:
{insights_text}

TASK:
Analyze the provided health insights and generate a structured JSON response.

### GUIDELINES & CONSTRAINTS:

1. RISK LEVEL ("risk_level"): 
   Determine the overall Risk Level (LOW, MEDIUM, HIGH) based on the insights. The highest raw severity triggered is {highest_severity}.

2. NUDGE TITLE ("nudge_title"):
   - Constraint: EXACTLY 1 sentence. Short and highly specific.
   - Goal: The user must instantly grasp the core issue at a glance (e.g., "Your heart rate has remained unusually high during sleep over the last 3 days.").

3. NUDGE TEXT ("nudge_text"):
   - Goal: Synthesize the data into a holistic clinical assessment. Bring all the details together.
   - Tone: Warm, reassuring, and extremely simple (8th-grade reading level). No dense medical jargon. {digest_instruction}
   - Clinical Boundary: Clearly explain *why* the data is flagged as a concern. You must NOT make a formal medical diagnosis (e.g., DO NOT say "You have Hypertension"). However, you CAN provide a clinical assessment of what these patterns potentially indicate or lead to (e.g., "These signs can be closely linked with hypertension or sleep apnea").

4. WHY FLAGGED ("why_flagged"):
   Structure a detailed breakdown of the correlated vitals.
   - "summary": Explicitly explain the physiological or behavioral relationship between the anomalous vitals/labs. Connect the dots so the user understands *how* these metrics affect one another.
   - "primary_vitals": Array of objects for the MAJOR acute triggers.
   - "supporting_vitals": Array of objects for historical/supporting factors exacerbating the risk.
   - For each vital object, provide:
     - "name": Human-friendly name (e.g., "Oxygen dipped").
     - "description": What happened (e.g., "Fell below 90% each night").
     - "value": Current anomalous value (e.g., "88%").
     - "usual": Normal baseline (e.g., "96.1%"). Max 1 decimal place. Use strict numbers, no vague phrases.
   - "conclusion": A single concluding sentence tying the summary and vitals together.

5. ACTION STEPS ("action_steps"):
   Provide a structured JSON object with:
   - "title": Short headline.
   - "title_emphasis": Short italicized part of title.
   - "description": Clear, non-clinical explanation of the next step.
   - "selected_pathway": You MUST select the exact key from the pathways catalog below that best fits the triage need:
{pathways_str}

OUTPUT FORMAT:
Return ONLY valid JSON. No markdown backticks, no conversational filler, no reasoning text.
"""
    
    schema = {
        "type": "OBJECT",
        "properties": {
            "risk_level": {"type": "STRING"},
            "nudge_title": {"type": "STRING"},
            "nudge_text": {"type": "STRING"},
            "why_flagged": {
                "type": "OBJECT",
                "properties": {
                    "summary": {"type": "STRING"},
                    "conclusion": {"type": "STRING"},
                    "primary_vitals": {
                        "type": "ARRAY",
                        "items": {
                            "type": "OBJECT",
                            "properties": {
                                "name": {"type": "STRING"},
                                "description": {"type": "STRING"},
                                "value": {"type": "STRING"},
                                "usual": {"type": "STRING"}
                            }
                        }
                    },
                    "supporting_vitals": {
                        "type": "ARRAY",
                        "items": {
                            "type": "OBJECT",
                            "properties": {
                                "name": {"type": "STRING"},
                                "description": {"type": "STRING"},
                                "value": {"type": "STRING"},
                                "usual": {"type": "STRING"}
                            }
                        }
                    }
                }
            },
            "action_steps": {
                "type": "OBJECT",
                "properties": {
                    "title": {"type": "STRING"},
                    "title_emphasis": {"type": "STRING"},
                    "description": {"type": "STRING"},
                    "selected_pathway": {"type": "STRING"}
                }
            }
        }
    }
    
    try:
        res = await _call_medgemma(prompt, json_mode=True, prefill=False, response_schema=schema)
        if "```json" in res:
            res = res.split("```json")[-1].split("```")[0].strip()
        parsed = json.loads(res)
        
        # Resolve CTAs
        try:
            from app.services.insights.cta_resolver import resolve_ctas
            raw_action_steps = parsed.get("action_steps", {})
            resolved_action_steps = resolve_ctas(raw_action_steps, parsed.get("risk_level", "LOW")) if isinstance(raw_action_steps, dict) else resolve_ctas({"description": str(raw_action_steps)}, parsed.get("risk_level", "LOW"))
            parsed["action_steps"] = resolved_action_steps
        except Exception as e:
            print(f"Failed to resolve CTAs: {e}")
            resolved_action_steps = parsed.get("action_steps", {})

        if patient_id:
            try:
                from app.config import settings
                from supabase import create_client
                from datetime import datetime, timezone, timedelta
                supabase = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)

                # Layer 3: 1-Hour Rate Limit with Clinical Escalation Override
                one_hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
                recent_nudges_res = supabase.table("nudge_alerts") \
                    .select("id, risk_level, nudge_title, nudge_text, why_flagged, action_steps, created_at") \
                    .eq("patient_id", patient_id) \
                    .gte("created_at", one_hour_ago) \
                    .order("created_at", desc=True) \
                    .limit(1) \
                    .execute()

                new_risk = (parsed.get("risk_level") or "LOW").upper()
                severity_rank = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}

                if recent_nudges_res.data and len(recent_nudges_res.data) > 0:
                    recent_nudge = recent_nudges_res.data[0]
                    recent_risk = (recent_nudge.get("risk_level") or "LOW").upper()
                    
                    # Check for Clinical Escalation:
                    # If new severity is strictly higher than recent severity OR if new severity is CRITICAL,
                    # bypass the 1-hour cooldown immediately.
                    is_escalation = (
                        severity_rank.get(new_risk, 1) > severity_rank.get(recent_risk, 1)
                        or new_risk == "CRITICAL"
                    )
                    
                    if not is_escalation:
                        print(f"MedGemma Nudge suppressed: Patient {patient_id} already received a {recent_risk} nudge at {recent_nudge.get('created_at')} (< 1h ago). New risk is {new_risk}. Duplicate suppressed.")
                        recent_nudge["suppressed_duplicate"] = True
                        return recent_nudge
                    else:
                        print(f"MedGemma Nudge CLINICAL ESCALATION: Patient {patient_id} escalated from {recent_risk} to {new_risk}! Bypassing 1-hour cooldown.")

                nudge_record = {
                    "patient_id": patient_id,
                    "risk_level": parsed.get("risk_level", "LOW"),
                    "nudge_title": parsed.get("nudge_title", ""),
                    "nudge_text": parsed.get("nudge_text", ""),
                    "why_flagged": parsed.get("why_flagged", ""),
                    "action_steps": resolved_action_steps,
                    "evidence": aggregated_evidence,
                    "source": settings.MEDGEMMA_MODEL_NAME
                }
                res_db = supabase.table("nudge_alerts").insert(nudge_record).execute()
                if res_db.data and len(res_db.data) > 0:
                    parsed["created_at"] = res_db.data[0].get("created_at")
            except Exception as db_err:
                print(f"Failed to save nudge_alert to DB: {db_err}")
                
        # Fallback if DB insert failed or patient_id was missing
        if "created_at" not in parsed:
            from datetime import datetime, timezone
            parsed["created_at"] = datetime.now(timezone.utc).isoformat()
            
        return parsed
    except Exception as e:
        print(f"MedGemma Nudge generation failed: {e}")
        return {
            "risk_level": highest_severity,
            "nudge_title": "Health Alert Detected (MedGemma Fallback)",
            "nudge_text": f"We noticed some changes in {patient_name}'s metrics that may require attention.",
            "why_flagged": f"Insights triggered: {len(insights) if not isinstance(insights, dict) else 1} items.",
            "action_steps": "Please review the detailed metrics and consult a doctor if necessary."
        }



async def generate_medgemma_plan(plan_context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generates a personalized, location-aware daily care plan using MedGemma.
    
    This is the core of the Daily Planning feature. It takes the full clinical context 
    (demographics, today's vitals, active insights, lab trends, and medication adherence) 
    and synthesizes a practical schedule for the patient.
    
    Key Features:
    - Instructs the LLM to provide culturally relevant dietary recommendations (e.g., healthy Indian recipes).
    - Enforces strict formatting constraints (e.g., task string max 4-6 words, separate time property).
    - Utilizes Pydantic for post-generation validation to guarantee the UI won't crash on bad JSON.
    """
    patient = plan_context.get("patient", {})
    vitals_today = plan_context.get("vitals_today", {})
    vitals_history = plan_context.get("vitals_history", [])
    previous_plan = plan_context.get("previous_plan", {})
    insights = _normalize_insights(plan_context.get("active_insights", []))
    lab_alerts = plan_context.get("lab_alerts", [])
    med_adherence = plan_context.get("med_adherence", {})
    correlations = plan_context.get("correlations", [])
    setup_prefs = plan_context.get("setup_prefs", {})
    existing_plan = plan_context.get("existing_plan")
    preferences = plan_context.get("preferences", [])
    symptoms = plan_context.get("symptoms", [])
    historical_insights = plan_context.get("historical_insights", [])
    nutritional_insights = plan_context.get("nutritional_insights", [])

    patient_name = patient.get("name", "Patient")
    patient_age = patient.get("age", 72)
    patient_sex = patient.get("sex", "")
    patient_location = patient.get("location", "India")
    patient_temperature = patient.get("temperature")
    patient_conditions = patient.get("conditions", [])

    # Format memories
    pref_lines = []
    symptom_lines = []
    for pref in preferences:
        pref_lines.append(f"  - {pref.get('constraint_text')}")
    for sym in symptoms:
        symptom_lines.append(f"  - {sym.get('name')} (Status: {sym.get('status')})")
            
    memory_str = "\n".join(pref_lines) if pref_lines else "  - No specific preferences recorded."
    symptom_str = "\n".join(symptom_lines) if symptom_lines else "  - No recent symptoms reported."

    # Formatting alerts
    insights_lines = []
    for i in insights:
        if i.get('is_stale'):
            insights_lines.append(f"  - [STALE/PAUSED] {i.get('name')}: {i.get('message')}")
        else:
            insights_lines.append(f"  - {i.get('name')}: {i.get('message')}")
    insights_str = "\n".join(insights_lines) if insights_lines else "  - None active."
    
    nut_lines = []
    for n in nutritional_insights:
        nut_lines.append(f"  - {n.get('insight_name')}: {n.get('context_data')}")
    nut_insights_str = "\n".join(nut_lines) if nut_lines else "  - None active."
    
    hist_lines = []
    for h in historical_insights:
        hist_lines.append(f"  - {h.get('name')}: {h.get('message')}")
    hist_str = "\n".join(hist_lines) if hist_lines else "  - None overdue."
    
    labs_str = "\n".join([f"  - {l.get('biomarker')}: {l.get('direction')} ({l.get('change_pct'):+.1f}%)" for l in lab_alerts]) if lab_alerts else "  - None active."
    
    rate = med_adherence.get('rate')
    rate = rate if rate is not None else 100
    med_section = f"Adherence: {rate:.0f}% over past 7 days. Missed: {med_adherence.get('missed_count', 0)}."

    # Format vitals history dynamically to include all available metrics
    history_lines = []
    excluded_keys = {"id", "patient_id", "created_at", "updated_at", "date"}
    
    for v in vitals_history[:7]:
        date = v.get("date", "Unknown")
        metrics = []
        
        # Handle BP specifically for standard medical formatting (e.g. BP 120/80)
        if v.get("bp_systolic") is not None and v.get("bp_diastolic") is not None:
            metrics.append(f"BP {v['bp_systolic']}/{v['bp_diastolic']}")
        
        # Process all other dynamic vitals
        for key, val in v.items():
            # Skip excluded keys, BP (if already handled), and None values
            if key in excluded_keys or val is None:
                continue
            if key in {"bp_systolic", "bp_diastolic"} and "BP " + str(v.get("bp_systolic")) + "/" + str(v.get("bp_diastolic")) in metrics:
                continue
            
            # Format the key beautifully: 'avg_heart_rate' -> 'Avg Heart Rate'
            human_key = key.replace("_", " ").title()
            
            # Append special formatting for specific well-known keys if desired
            if key == "sleep_hours":
                metrics.append(f"{human_key} {val}h")
            elif key == "mood_score":
                metrics.append(f"{human_key} {val}/10")
            else:
                metrics.append(f"{human_key} {val}")
                
        metrics_str = ", ".join(metrics) if metrics else "No metrics recorded"
        history_lines.append(f"  - {date}: {metrics_str}")
        
    history_str = "\n".join(history_lines) if history_lines else "  - No history available."

    # Format previous plan (Yesterday)
    prev_lines = []
    for period, tasks in previous_plan.items():
        if isinstance(tasks, list):
            for t in tasks:
                status = "[X]" if t.get("completed") else "[ ]"
                time_str = f" at {t.get('time')}" if t.get("time") else ""
                prev_lines.append(f"  - {period.capitalize()}: {status} {t.get('task')}{time_str}")
    prev_plan_str = "\n".join(prev_lines) if prev_lines else "  - No previous schedule found."
    
    # Format existing pre-planned schedule (Today)
    existing_plan_str = ""
    if existing_plan:
        existing_lines = []
        for period, tasks in existing_plan.items():
            if isinstance(tasks, list):
                for t in tasks:
                    time_str = f" at {t.get('time')}" if t.get("time") else ""
                    existing_lines.append(f"  - {period.capitalize()}: {t.get('task')}{time_str} - {t.get('details', '')}")
        existing_plan_str = "\n".join(existing_lines) if existing_lines else "  - No schedule found."
    
    # Format correlations
    corr_lines = []
    for c in correlations[:3]:
        corr_lines.append(f"  - {c.get('task_category', 'Task')} highly correlates with improved {c.get('metric', 'health')} (r={c.get('correlation', 0):.2f})")
    corr_str = "\n".join(corr_lines) if corr_lines else "  - No clear statistical correlations established yet."
    
    # Format location string
    location_str = patient_location
    if patient_temperature:
        location_str += f" (Current Temp: {patient_temperature}°C)"

    # Format setup preferences
    setup_lines = []
    if setup_prefs:
        if setup_prefs.get("primary_focus"): setup_lines.append(f"Primary Focus: {setup_prefs.get('primary_focus')}")
        if setup_prefs.get("wake_time"): setup_lines.append(f"Wake Time: {setup_prefs.get('wake_time')}")
        if setup_prefs.get("movement_level"): setup_lines.append(f"Movement Level: {setup_prefs.get('movement_level')}")
        if setup_prefs.get("steps_goal"): setup_lines.append(f"Steps Goal: {setup_prefs.get('steps_goal')} steps")
        if setup_prefs.get("diet_type"): setup_lines.append(f"Diet Type: {setup_prefs.get('diet_type')}")
        if setup_prefs.get("health_conditions"): setup_lines.append(f"Health Conditions to Accommodate: {', '.join(setup_prefs.get('health_conditions'))}")
        if setup_prefs.get("evening_activities"): setup_lines.append(f"Evening Wind-Down Preferences: {', '.join(setup_prefs.get('evening_activities'))}")
        #if setup_prefs.get("reminders"): setup_lines.append(f"Reminder Style: {setup_prefs.get('reminders')}")
    setup_str = "\n".join([f"  - {line}" for line in setup_lines]) if setup_lines else "  - No specific preferences provided."

    recent_meals = plan_context.get("recent_meals", [])
    recent_meals_str = ", ".join(recent_meals) if recent_meals else "None"
    
    agreed_actions = plan_context.get("agreed_actions", [])
    suggested_actions = plan_context.get("suggested_actions", [])
    action_lines = []
    if agreed_actions:
        action_lines.append("[AGREED ACTIONS]")
        action_lines.extend([f"- {a.get('description', '')}" for a in agreed_actions])
    if suggested_actions:
        action_lines.append("\n[SUGGESTED ACTIONS]")
        action_lines.extend([f"- {a.get('description', '')}" for a in suggested_actions])
    actions_bullet = "\n".join(action_lines) if action_lines else "No specific coach actions recorded."
    
    try:
        from app.services.plan_schema import get_gemini_schema
        schema_dict = get_gemini_schema()
        schema_str = __import__("json").dumps(schema_dict, indent=2)
    except Exception as e:
        schema_str = "{}"

    if setup_prefs.get("target_calories_user_generated"):
        cals = setup_prefs.get("target_calories_user_generated")
        p = setup_prefs.get("protein_g_user_generated", 0)
        c = setup_prefs.get("carbs_g_user_generated", 0)
        f = setup_prefs.get("fat_g_user_generated", 0)
        pref = setup_prefs.get("diet_preference", "")
        pref_str = f" [{pref}]" if pref else ""
        macro_targets_str = f"Total Calories: {cals} kcal (Protein: {p}g, Carbs: {c}g, Fat: {f}g){pref_str}"
    else:
        macro_targets_str = calculate_daily_macros(patient, setup_prefs)

    if existing_plan:
        prompt = f"""You are MedGemma, a caring clinical guide for eldercare support.
Your task is to ADAPT the patient's pre-planned schedule for TODAY based on their immediate morning health data.

PATIENT: {patient_name}, {patient_age}-year-old {patient_sex or 'patient'}
LOCATION: {location_str}
CONDITIONS: {", ".join(patient_conditions) if patient_conditions else "None specified"}

USER CHAT PREFERENCES (Crucial requests made by the patient to the AI Coach):
{memory_str}

RECENT REPORTED SYMPTOMS (From recent chat logs):
{symptom_str}

PRE-PLANNED SCHEDULE FOR TODAY (Generated previously):
{existing_plan_str}

CARE PLAN ACTIONS (from Coach):
{actions_bullet}

ACUTE MORNING DATA (Immediate Attention Required):
- VITALS TREND:
{history_str}
- ACTIVE CLINICAL ALERTS:
{insights_str}
- ACTIVE NUTRITIONAL INSIGHTS:
{nut_insights_str}
- LAB TRENDS REQUIRING ATTENTION:
{labs_str}
- OVERDUE LABS TO SCHEDULE:
{hist_str}
- MEDICATION STATUS:
{med_section}

INSTRUCTIONS:
1. Review the PRE-PLANNED SCHEDULE. This contains their groceries and meal prep for today.
2. Modify this schedule ONLY IF MEDICALLY NECESSARY based on the ACUTE MORNING DATA, OR if necessary to accommodate the USER CHAT PREFERENCES, OR to alleviate RECENT REPORTED SYMPTOMS (e.g. suggesting ginger tea for nausea, or suggesting extra rest/gentle stretches for joint pain).
3. Example Adaptation: If the pre-plan includes a "30 Min Brisk Walk", but the CLINICAL ALERTS show a "Dangerous Blood Pressure Spike", you MUST replace the walk with "Gentle Stretching" or "Rest" and add a note explaining why.
4. CRITICAL: You MUST explicitly schedule the 'AGREED' care plan actions into the daily schedule. You should also evaluate the 'SUGGESTED' actions and schedule them if they directly help with the patient's ACTIVE SYMPTOMS.
5. CRITICAL: Keep distinct activities (like meals, hygiene, self-care, exercise, and medical tasks) as SEPARATE tasks. Do NOT merge unrelated activities together (e.g., do not combine breakfast and self-care).
6. If you see a [STALE/PAUSED] clinical alert, it means we paused the alert because the underlying data is too old. You MUST seamlessly weave a task into today's schedule (e.g. a short walk for heart rate recovery) to collect fresh data for that metric.
7. If there are overdue labs in the OVERDUE LABS TO SCHEDULE section, you MUST include "Book a lab test" in the daily checklist.
7. If no acute clinical alerts exist, output the PRE-PLANNED SCHEDULE exactly as it is (with any modifications for USER CHAT PREFERENCES), and add a warm, reassuring morning greeting to the summary.
8. Format the response as exact JSON. DO NOT include any markdown wraps (no backticks), greetings, summary notes, or any "Thinking Process" / reasoning text.

EXPECTED JSON SCHEMA:
{schema_str}
"""
    else:
        prompt = f"""You are MedGemma, a caring clinical guide for eldercare support.
Create a personalized daily care plan (morning, afternoon, evening, night) for:

PATIENT: {patient_name}, {patient_age}-year-old {patient_sex or 'patient'}
LOCATION: {location_str}
CONDITIONS: {", ".join(patient_conditions) if patient_conditions else "None specified"}

PATIENT PREFERENCES (Crucial for plan setup):
{setup_str}

USER CHAT PREFERENCES (Crucial requests made by the patient to the AI Coach):
{memory_str}

RECENT REPORTED SYMPTOMS (From recent chat logs):
{symptom_str}

CARE PLAN ACTIONS (from Coach):
{actions_bullet}

NUTRITIONAL TARGETS:
  - {macro_targets_str}

RECENT MEALS (Do NOT repeat these):
  - {recent_meals_str}

RAW VITALS TREND (LAST 7 DAYS):
{history_str}

ACTIVE CLINICAL ALERTS:
{insights_str}

ACTIVE NUTRITIONAL INSIGHTS:
{nut_insights_str}

LAB TRENDS REQUIRING ATTENTION:
{labs_str}

OVERDUE LABS TO SCHEDULE:
{hist_str}

MEDICATION STATUS:
{med_section}

YESTERDAY'S SCHEDULE (Review for continuity and completion and to ensure that there is variety in what you suggest):
{prev_plan_str}

PATIENT HISTORICAL SUCCESS CORRELATIONS (What works for this person):
{corr_str}

INSTRUCTIONS:
1. Write in a warm, comforting tone. Speak like a reassuring family nurse.
2. Analyze the raw vitals for subtle trends (e.g. poor sleep, low mood). Consider the historical success correlations to see what works well for this person and weave those tasks into today's plan to boost their health. Review yesterday's schedule to maintain routine continuity, but introduce gentle variations so it doesn't get repetitive. Address incomplete tasks if relevant.
3. Incorporate the PATIENT PREFERENCES strictly into the schedule. For instance, start the day according to their `Wake Time`, adapt physical tasks to their `Movement Level` and `Steps Goal`, and suggest meals aligned with their `Diet Type`. Include their preferred `Evening Wind-Down Preferences` in the evening/night routines. Center the overall day around their `Primary Focus`. Ensure you honor any specific requests from the USER CHAT PREFERENCES and alleviate any RECENT REPORTED SYMPTOMS.
4. CRITICAL: You MUST explicitly schedule the 'AGREED' care plan actions into the daily schedule. You should also evaluate the 'SUGGESTED' actions and schedule them if they directly help with the patient's ACTIVE SYMPTOMS.
5. CRITICAL: Keep distinct activities (like meals, hygiene, self-care, exercise, and medical tasks) as SEPARATE tasks. Do NOT merge unrelated activities together (e.g., do not combine breakfast and self-care).
6. If you see a [STALE/PAUSED] clinical alert, it means we paused the alert because the underlying data is too old. You MUST seamlessly weave a task into today's schedule (e.g. a short walk for heart rate recovery) to collect fresh data for that metric.
7. If there are overdue labs in the OVERDUE LABS TO SCHEDULE section, you MUST include "Book a lab test" in the daily checklist.
8. CRITICAL: You MUST generate 2-3 tasks for the morning, 2-3 for afternoon, 2-3 for evening, and 2-3 for night. No more than 4 per period.
8. CRITICAL: Provide a specific and descriptive task action in the 'task' property (not more than 1 short sentence) and the time in a separate 'time' property (e.g. '7:30 AM'). Do NOT use the 'Action | Time' format anymore.
9. CRITICAL: Do NOT prescribe specific recipes or full meals. Instead, review the ACTIVE CLINICAL ALERTS for any Nutritional Insights, and schedule 1-2 small, habit-based tasks (e.g., 'Add a boiled egg to breakfast', 'Drink water before lunch') to help close those gaps.
10. CRITICAL: Assign a short, canonical 1-2 word "category" to each task (e.g., 'Walking', 'Meditation', 'Breakfast', 'Relaxation') so similar tasks can be grouped analytically.
11. CRITICAL: Provide "details" for each task. It should capture the why and how of that task in exactly one sentence that is easy to read and follow. Do not list exact macro counts for meals.
12. Format the response as exact JSON. DO NOT include any markdown wraps (no backticks), greetings, summary notes, or any "Thinking Process" / reasoning text.

EXPECTED JSON SCHEMA:
{schema_str}
"""

    try:
        from app.services.plan_schema import get_gemini_schema, DailyPlanResponse
        res = await _call_medgemma(prompt, json_mode=True, prefill=False, response_schema=None)
        result = _clean_json(res)
        
        # ── Pydantic Validation ──
        validated = DailyPlanResponse.model_validate(result).model_dump()
        
        validated["health_context"] = {
            "conditions_addressed": patient_conditions,
            "insights_count": len(insights),
            "lab_alerts_count": len(lab_alerts),
            "med_adherence_rate": med_adherence.get("rate", 100),
            "model_used": "Gemini (gemini-2.5-flash)" if getattr(settings, "FORCE_GEMINI", False) else f"MedGemma ({settings.MEDGEMMA_MODEL_NAME})"
        }
        validated["active_alerts"] = [i.get("name", "") for i in insights[:5]]
        return validated
    except Exception as e:
        print(f"MedGemma Plan generation failed: {e}")
        return {
            "summary": "MedGemma was unable to compile a plan. Please follow standard guidance.",
            "schedule": {"morning": [], "afternoon": [], "evening": [], "night": []}
        }

async def generate_medgemma_summary(patient_id: str, patient_name: str = "your loved one") -> Dict[str, Any]:
    """Generates the 2-sentence morning briefing using MedGemma."""
    print("generate_medgemma_summary: Fetching context...")
    # 1. Fetch patient context
    from app.services.insights.data_fetcher import fetch_patient_context
    ctx = fetch_patient_context(patient_id)
    print("generate_medgemma_summary: Context fetched.")
    
    # Format vitals & alerts summary
    yesterday_vitals = []
    vitals_dict = ctx.vitals._vitals
    
    from datetime import datetime, timedelta, timezone, date
    yesterday_date = (datetime.now(timezone.utc) - timedelta(days=1)).date()
    today_date = datetime.now(timezone.utc).date()
    
    # Vitals classification sets (OVERNIGHT_METRICS, CUMULATIVE_METRICS) imported from app.services.insights.core
    for name, vals in vitals_dict.items():
        if vals:
            today_reading = None
            yesterday_reading = None
            
            for v in vals:
                d_str = str(v.date)
                if isinstance(v.date, str):
                    d_str = v.date.split('T')[0]
                elif isinstance(v.date, date):
                    d_str = str(v.date)

                if d_str == str(today_date):
                    today_reading = v
                elif d_str == str(yesterday_date):
                    yesterday_reading = v

            selected_val = None
            
            if name in CUMULATIVE_METRICS:
                # Strictly use yesterday's full day data
                if yesterday_reading:
                    selected_val = yesterday_reading.value
            elif name in OVERNIGHT_METRICS:
                # Strictly use today's (synced this morning) data. If they didn't wear the watch, it will correctly be None.
                if today_reading:
                    selected_val = today_reading.value
            else:
                # Point-in-time metrics. Use today's if logged this morning, fallback to yesterday
                if today_reading:
                    selected_val = today_reading.value
                elif yesterday_reading:
                    selected_val = yesterday_reading.value

            if selected_val is not None:
                yesterday_vitals.append(f"- {name}: {selected_val}")
                
    vitals_bullet = "\n".join(yesterday_vitals) if yesterday_vitals else "No vital logs recorded yesterday."
    
    # 2. Fetch MedGemma Diagnostics active alerts from DB instead of generating synchronously
    try:
        from app.services.insights.data_fetcher import supabase
        alert_res = supabase.table("active_clinical_insights").select("*").eq("patient_id", patient_id).eq("status", "active").execute()
        alerts = alert_res.data if alert_res.data else []
    except Exception as e:
        print(f"Failed to fetch alerts from DB: {e}")
        alerts = []
        
    if alerts:
        insights_bullet = "\n".join([f"- {a.get('name', 'Alert')}: {a.get('message', '')}" for a in alerts])
    else:
        insights_bullet = "No clinical alerts."
        
    setup_prefs = getattr(ctx, "setup_prefs", {})
    if setup_prefs:
        prefs_lines = [f"- {k.replace('_', ' ').title()}: {v}" for k, v in setup_prefs.items()]
        prefs_bullet = "\n".join(prefs_lines)
    else:
        prefs_bullet = "No specific preferences or goals recorded."
        
    preferences = getattr(ctx, "preferences", [])
    symptoms = getattr(ctx, "symptoms", [])
    mem_lines = []
    if preferences:
        mem_lines.extend([f"- (Preference: {p.get('domain', 'General')}) {p.get('constraint_text', '')}" for p in preferences])
    if symptoms:
        mem_lines.extend([f"- (Symptom) {s.get('name', '')} (Severity: {s.get('severity', '')}, Status: {s.get('status', '')})" for s in symptoms])
        
    if mem_lines:
        memory_bullet = "\n".join(mem_lines)
    else:
        memory_bullet = "No recent conversational context."

    prompt = f"""You are MedGemma, writing a brief, encouraging morning health summary addressed directly to an elderly senior user about how their day went yesterday and how they are doing today.

Here are their logged health metrics for yesterday:
{vitals_bullet}

Clinical findings:
{insights_bullet}

Patient Goals & Setup Preferences:
{prefs_bullet}

Known Patient Context & Recent Memories (from chat):
{memory_bullet}

RULES:
1. Write EXACTLY 2 sentences for the summary. No more.
2. First sentence: A warm recap of how their day went yesterday based on their logged vitals, speaking to them in the second person ("you").
3. Second sentence: A supportive, actionable tip or gentle focus area for them today. Make sure this tip aligns gently with their primary focus, goals, or any feelings/activities they mentioned in the recent memories above.
4. Do NOT use medical jargon, numbers, or symbols in the summary. Translate numbers into words.
5. Create a descriptive headline summarizing the overall briefing in not more than 10 words.
6. Return a JSON object with 'headline' and 'summary' fields. DO NOT output any reasoning.
"""
    schema = {
        "type": "OBJECT",
        "properties": {
            "headline": {"type": "STRING"},
            "summary": {"type": "STRING"}
        }
    }
    
    try:
        raw_response = await _call_medgemma(prompt, json_mode=True, prefill=False, response_schema=schema)
        if "```json" in raw_response:
            raw_response = raw_response.split("```json")[-1].split("```")[0].strip()
        parsed = json.loads(raw_response)
        
        return {
            "headline": parsed.get("headline", "A bright, active day"),
            "summary": parsed.get("summary", ""),
            "model_used": "Gemini (gemini-2.5-flash)" if getattr(settings, "FORCE_GEMINI", False) else f"MedGemma ({settings.MEDGEMMA_MODEL_NAME})"
        }
    except Exception as e:
        print(f"MedGemma Summary generation failed: {e}")
        return {
            "summary": "Hope you have a wonderful day ahead! Remember to stay active and hydrated.",
            "model_used": "MedGemma Fallback"
        }

def _clean_summary(text: str) -> str:
    text = text.strip()
    # If it contains "thought", let's extract the last non-empty paragraph/line
    if "thought" in text.lower():
        paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
        if paragraphs:
            last_p = paragraphs[-1]
            if "thought" in last_p.lower() and len(paragraphs) == 1:
                # Fallback: extract last two sentences
                sentences = [s.strip() for s in last_p.split(".") if s.strip()]
                if len(sentences) >= 2:
                    return sentences[-2] + ". " + sentences[-1] + "."
            return last_p
    return text

# ═══════════════════════════════════════════════════════════════════
# 4.5. MID-DAY & EVENING CHECK-INS
# ═══════════════════════════════════════════════════════════════════

async def generate_midday_checkin(
    patient_id: str, 
    patient_name: str, 
    adherence_text: str, 
    vitals_bullet: str, 
    mood_text: str, 
    patient_conditions: List[str], 
    patient_age: int = None, 
    patient_sex: str = None, 
    setup_prefs: Optional[Dict[str, Any]] = None, 
    preferences: Optional[List[Dict[str, Any]]] = None, 
    symptoms: Optional[List[Dict[str, Any]]] = None,
    nutrition_text: Optional[str] = None
) -> str:
    """
    Generates a mid-day checkin push notification (under 250 characters).
    Focus is to give a warm greeting, acknowledge adherence/vitals, and suggest a micro-action for the afternoon.
    """
    
    # 1. Format Context
    conditions_str = ", ".join(patient_conditions) if patient_conditions else "None recorded"
    age_str = f"{patient_age} years old" if patient_age else "Unknown"
    sex_str = patient_sex.capitalize() if patient_sex else "Unknown"
    
    if setup_prefs:
        prefs_lines = [f"- {k.replace('_', ' ').title()}: {v}" for k, v in setup_prefs.items()]
        prefs_bullet = "\n".join(prefs_lines)
    else:
        prefs_bullet = "No specific preferences or goals recorded."
        
    mem_lines = []
    if preferences:
        mem_lines.extend([f"- (Preference: {p.get('domain', 'General')}) {p.get('constraint_text', '')}" for p in preferences])
    if symptoms:
        mem_lines.extend([f"- (Symptom) {s.get('name', '')} (Severity: {s.get('severity', '')}, Status: {s.get('status', '')})" for s in symptoms])
        
    if mem_lines:
        memory_bullet = "\n".join(mem_lines)
    else:
        memory_bullet = "No recent conversational context."
        
    nutrition_section = nutrition_text if nutrition_text else "No nutrition data logged yet today."
        
    prompt = f"""You are MedGemma, writing a brief, encouraging mid-day check-in addressed directly to an elderly senior user.

Here is their progress so far today:
- Age: {age_str}
- Sex: {sex_str}
- Vitals: {vitals_bullet}
- Mood/Feeling: {mood_text}
- Tasks/Plan: {adherence_text}
- Nutrition Consumed So Far vs Plan Targets:
{nutrition_section}
- Known Chronic Conditions: {conditions_str}

Patient Goals & Setup Preferences:
{prefs_bullet}

Known Patient Context & Recent Memories (from chat):
{memory_bullet}

RULES:
1. Write EXACTLY 2 sentences. No more.
2. First sentence: An encouraging observation about their morning/mid-day progress (e.g. praising tasks done or meals logged so far, or a gentle nudge if missing).
3. Second sentence: A warm, supportive tip to carry them through the afternoon. Consider how their nutrition is tracking against their daily plan targets (e.g. suggesting an afternoon protein boost, fiber-rich snack, or hydration if lagging behind, or celebrating good balance), gently tailored to their known conditions, primary goals, or feelings/activities from recent memories.
4. Do NOT use medical jargon, numbers, or symbols. Translate numbers into words (e.g. use "four thousand" instead of "4000").
5. Return ONLY the 2 sentences as plain text. No JSON, no markdown.
"""
    try:
        summary_text = await _call_medgemma(prompt, json_mode=False)
        return _clean_summary(summary_text)
    except Exception as e:
        print(f"Mid-day checkin generation failed: {e}")
        return "You're doing great today! Keep up the good momentum this afternoon."

async def generate_evening_wind_down(
    patient_id: str, 
    patient_name: str, 
    adherence_text: str, 
    vitals_bullet: str, 
    mood_text: str, 
    patient_conditions: List[str], 
    patient_age: int = None, 
    patient_sex: str = None, 
    setup_prefs: Optional[Dict[str, Any]] = None, 
    preferences: Optional[List[Dict[str, Any]]] = None, 
    symptoms: Optional[List[Dict[str, Any]]] = None,
    nutrition_text: Optional[str] = None
) -> str:
    """
    Generates an evening wind-down push notification (under 250 characters).
    Focus is summarizing the day, celebrating adherence, and giving a calming evening tip.
    """
    # 1. Format Context
    conditions_str = ", ".join(patient_conditions) if patient_conditions else "None recorded"
    age_str = f"{patient_age} years old" if patient_age else "Unknown"
    sex_str = patient_sex.capitalize() if patient_sex else "Unknown"
    
    if setup_prefs:
        prefs_lines = [f"- {k.replace('_', ' ').title()}: {v}" for k, v in setup_prefs.items()]
        prefs_bullet = "\n".join(prefs_lines)
    else:
        prefs_bullet = "No specific preferences or goals recorded."
        
    mem_lines = []
    if preferences:
        mem_lines.extend([f"- (Preference: {p.get('domain', 'General')}) {p.get('constraint_text', '')}" for p in preferences])
    if symptoms:
        mem_lines.extend([f"- (Symptom) {s.get('name', '')} (Severity: {s.get('severity', '')}, Status: {s.get('status', '')})" for s in symptoms])
        
    if mem_lines:
        memory_bullet = "\n".join(mem_lines)
    else:
        memory_bullet = "No recent conversational context."
        
    nutrition_section = nutrition_text if nutrition_text else "No nutrition data logged today."
        
    prompt = f"""You are MedGemma, writing a soothing, encouraging evening wind-down message addressed directly to an elderly senior user.

Here is their full day summary:
- Age: {age_str}
- Sex: {sex_str}
- Vitals: {vitals_bullet}
- Mood/Feeling: {mood_text}
- Tasks/Plan: {adherence_text}
- Daily Nutrition vs Plan Targets:
{nutrition_section}
- Known Chronic Conditions: {conditions_str}

Patient Goals & Setup Preferences:
{prefs_bullet}

Known Patient Context & Recent Memories (from chat):
{memory_bullet}

RULES:
1. Write EXACTLY 2 sentences. No more.
2. First sentence: A warm congratulatory recap celebrating what they achieved today across their activity, tasks, or wholesome nutrition.
3. Second sentence: A soothing tip preparing them for a restful night of sleep, gently tailored to their known conditions, evening routine preferences (e.g. light hydration or herbal tea, reading/meditation), or feelings from recent memories.
4. Do NOT use medical jargon, numbers, or symbols. Translate numbers into words.
5. Return ONLY the 2 sentences as plain text. No JSON, no markdown.
"""
    try:
        summary_text = await _call_medgemma(prompt, json_mode=False)
        return _clean_summary(summary_text)
    except Exception as e:
        print(f"Evening wind-down generation failed: {e}")
        return "You've had a wonderful day. Now it's time to relax and prepare for a restful night's sleep."

# ═══════════════════════════════════════════════════════════════════
# 5. MEDGEMMA HEALTH PERSONA
# ═══════════════════════════════════════════════════════════════════

async def generate_medgemma_persona(patient_id: str, context: dict) -> Dict[str, Any]:
    """
    Generates a qualitative, human-like holistic health persona for a patient.
    This replaces the deterministic health profile and infers preferences from behavior.
    """
    system_instruction = """
You are MedGemma, an expert clinical AI. Your task is to generate a comprehensive, qualitative Health Persona for this patient based on their raw data (vitals, labs, demographics, medications, conditions).
DO NOT act as a diagnostic engine. Do not create new clinical alerts.
Instead, synthesize who this person is, their long-term health trajectory, their short-term health state, and infer their preferences (what they like/dislike based on behavioral clues in their data, e.g. 'likes morning walks' if step count is high, or 'dislikes taking meds' if adherence is low).

Your output MUST be a valid JSON object matching the following schema EXACTLY:
{
  "three_line_profile": "A concise 3-line narrative of who they are and their overall health status.",
  "long_term_health": {
    "good": ["list of positive long-term health trends"],
    "bad": ["list of negative long-term health trends"]
  },
  "short_term_health": {
    "good": ["list of positive short-term health trends"],
    "bad": ["list of negative short-term health trends"]
  },
  "preferences": {
    "likes": ["inferred positive preferences"],
    "dislikes": ["inferred negative preferences"]
  }
}
"""
    
    prompt = f"""{system_instruction}

PATIENT DATA CONTEXT:
{json.dumps(context, indent=2, default=str)}

Generate the Health Persona in JSON format:"""

    schema = {
        "type": "OBJECT",
        "properties": {
            "three_line_profile": {"type": "STRING"},
            "long_term_health": {
                "type": "OBJECT",
                "properties": {
                    "good": {"type": "ARRAY", "items": {"type": "STRING"}},
                    "bad": {"type": "ARRAY", "items": {"type": "STRING"}}
                }
            },
            "short_term_health": {
                "type": "OBJECT",
                "properties": {
                    "good": {"type": "ARRAY", "items": {"type": "STRING"}},
                    "bad": {"type": "ARRAY", "items": {"type": "STRING"}}
                }
            },
            "preferences": {
                "type": "OBJECT",
                "properties": {
                    "likes": {"type": "ARRAY", "items": {"type": "STRING"}},
                    "dislikes": {"type": "ARRAY", "items": {"type": "STRING"}}
                }
            }
        },
        "required": ["three_line_profile", "long_term_health", "short_term_health", "preferences"]
    }

    print(f"DEBUG: Calling MedGemma for Health Persona [Patient: {patient_id}]")
    raw_response = await _call_medgemma(prompt, json_mode=True, response_schema=schema)
    return _clean_json(raw_response)

async def parse_lab_report_to_fhir(file_bytes: bytes, mime_type: str) -> Dict[str, Any]:
    """
    Takes raw bytes of a PDF or Image lab report, and uses Gemini to extract it directly into a FHIR R4 Bundle.
    """
    import base64
    import json
    
    # 1. Encode file
    encoded_file = base64.b64encode(file_bytes).decode("utf-8")
    file_part = {
        "inlineData": {
            "mimeType": mime_type,
            "data": encoded_file
        }
    }
    
    # 2. Strict Flat Extraction schema definition
    flat_extraction_schema = {
        "type": "OBJECT",
        "properties": {
            "report_summary": {"type": "STRING", "description": "A brief, patient-friendly summary of the entire lab report."},
            "report_name": {"type": "STRING", "description": "The overall name of the test or panel (e.g. Complete Blood Count, Lipid Profile). If there are multiple tests, list or combine them."},
            "performer": {"type": "STRING", "description": "Name of the laboratory or testing facility (e.g. Dr. Lal PathLabs)"},
            "collection_date": {"type": "STRING", "description": "The exact date the specimen was drawn/collected (e.g. 2021-05-29). Look for 'Collection Date'. If missing, leave null."},
            "biomarkers": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "test_name": {"type": "STRING", "description": "The exact raw name of the biomarker as written on the report"},
                        "numeric_value": {"type": "NUMBER", "description": "The numeric test result (if applicable)"},
                        "unit": {"type": "STRING", "description": "The UCUM standard unit of measure"},
                        "qualitative_value": {"type": "STRING", "description": "The qualitative test result (e.g. 'Positive', 'Negative', 'Trace', 'O+', 'Present'). Use only if the result is NOT numeric."},
                        "reference_low": {"type": "NUMBER", "description": "The lower bound of the normal reference range. If missing, you MUST output -99999.", "nullable": True},
                        "reference_high": {"type": "NUMBER", "description": "The upper bound of the normal reference range. If missing, you MUST output -99999.", "nullable": True},
                        "explanation": {"type": "STRING", "description": "A detailed, plain English explanation: what this biomarker means, why it matters for us as patients, if the patient's result is high/low/normal, and one thing they can do about it."},
                        "status": {"type": "STRING", "description": "Based on the lab results and reference ranges, categorize this biomarker as either 'within range' or 'out of range'."},
                        "specimen": {"type": "STRING", "description": "The specimen type or system for this test (e.g., 'Serum', 'Plasma', 'Blood', 'Urine', 'CSF'). If not explicitly stated, infer from the report context if obvious, otherwise leave null.", "nullable": True}
                    },
                    "required": ["test_name"]
                }
            }
        },
        "required": ["report_summary", "report_name", "performer", "biomarkers"]
    }
    
    prompt = """You are an expert clinical data extraction AI.
    Your task is to extract the attached laboratory report and output the data precisely according to the flat JSON schema provided.
    
    Requirements:
    1. Extract the overall report summary into `report_summary`.
    2. Extract the overall name of the test/panel into `report_name`.
    3. Identify the laboratory name into `performer`.
    4. Extract the collection date into `collection_date`.
    5. For EACH biomarker tested in the report, create an entry in the `biomarkers` array.
    6. CRITICAL: For each biomarker, extract its exact raw name as it appears on the report into `test_name`. DO NOT attempt to map or generate LOINC codes.
    7. CRITICAL: If a biomarker result is numeric, store it in `numeric_value`. If it is text-based (like 'Positive' or 'Clear'), store it in `qualitative_value`. DO NOT put long explanations in `qualitative_value`!
    8. CRITICAL: The `explanation` field MUST be detailed and structured in plain simple English containing four parts: 1) What the biomarker means. 2) Why it is important for the body. 3) Whether the patient's specific result is high, low, or normal. 4) What one actionable thing they can do about it.
    9. CRITICAL: If the reference range is missing for a biomarker, DO NOT invent a value like 0. You MUST output -99999 for both `reference_low` and `reference_high`.
    10. Compare the value to the reference range and set the `status` field to exactly 'within range' or 'out of range'.
    11. Extract the specimen type into the `specimen` field (e.g., Serum, Urine, Whole Blood). Look at headers or individual test lines.
    """
    
    response_text = await _call_medgemma(
        prompt,
        file_part=file_part,
        json_mode=True,
        response_schema=flat_extraction_schema
    )
    
    flat_data = _clean_json(response_text)
    
    # Map the flat data into a strict FHIR Bundle
    if not flat_data:
        return {}
        
    bundle = {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": []
    }
    
    # 1. Add DiagnosticReport
    report_resource = {
        "resourceType": "DiagnosticReport",
        "status": "final",
        "code": {
            "text": flat_data.get("report_name", "Lab Report")
        },
        "performer": [{"display": flat_data.get("performer", "Unknown")}],
        "presentedForm": [{"title": flat_data.get("report_summary", "Lab Report")}]
    }
    if flat_data.get("collection_date"):
        report_resource["effectiveDateTime"] = flat_data.get("collection_date")
    
    bundle["entry"].append({"resource": report_resource})
    
    # 2. Add Observations and Specimens
    import uuid
    specimen_map = {}
    
    for biomarker in flat_data.get("biomarkers", []):
        test_name = biomarker.get("test_name")
        if not test_name:
            continue
            
        obs_resource = {
            "resourceType": "Observation",
            "status": "final",
            "code": {
                "text": test_name,
                "coding": []
            },
            "presentedForm": [{"title": biomarker.get("explanation", "")}]
        }
        
        specimen_type = biomarker.get("specimen")
        if specimen_type:
            if specimen_type not in specimen_map:
                specimen_uuid = f"urn:uuid:{uuid.uuid4()}"
                specimen_map[specimen_type] = specimen_uuid
                
                specimen_resource = {
                    "resourceType": "Specimen",
                    "type": {
                        "text": specimen_type
                    }
                }
                bundle["entry"].append({
                    "fullUrl": specimen_uuid,
                    "resource": specimen_resource
                })
            
            obs_resource["specimen"] = {
                "reference": specimen_map[specimen_type],
                "display": specimen_type
            }
        
        search_term = f"{test_name} in {specimen_type}" if specimen_type else test_name
        
        # Unit Interceptor
        unit = biomarker.get("unit")
        if unit:
            unit_lower = unit.lower()
            if "%" in unit_lower or "percentage" in unit_lower or "nfr" in unit_lower or "vfr" in unit_lower:
                search_term += " NFr"
            elif any(x in unit_lower for x in ["thou/mm3", "abs", "10*3", "#"]):
                search_term += " # volume"
                
        mapping = get_loinc_mapping(search_term)
        
        # Fallback to Google Search Grounding if not found in Tier 1 Core
        if not mapping:
            mapping = await fallback_grounded_loinc_search(search_term)
            
        loinc = mapping["loinc_code"] if mapping else None
        
        if loinc:
            obs_resource["code"]["coding"].append({
                "system": "http://loinc.org",
                "code": loinc
            })
        
        num_val = biomarker.get("numeric_value")
        if num_val is not None:
            obs_resource["valueQuantity"] = {
                "value": num_val,
                "unit": biomarker.get("unit"),
                "system": "http://unitsofmeasure.org"
            }
            
        qual_val = biomarker.get("qualitative_value")
        if qual_val:
            obs_resource["valueString"] = qual_val
            
        # Determine technical category from the LOINC mapping (fallback to "Other" if unmapped)
        tech_cat = mapping["category"] if mapping else "Other"
        # Determine consumer UI category using our dictionary map
        cons_cat = get_consumer_category(tech_cat)
        
        obs_resource["category"] = [{
            "coding": [
                {"system": "http://terminology.hl7.org/CodeSystem/observation-category", "code": "laboratory", "display": "Laboratory"},
                {"system": "https://zivaa.com/clinical-category", "code": tech_cat, "display": tech_cat},
                {"system": "https://zivaa.com/consumer-category", "code": cons_cat, "display": cons_cat}
            ]
        }]
            
        status = biomarker.get("status")
        if status:
            obs_resource["interpretation"] = [{"text": status}]
            
        ref_low = biomarker.get("reference_low")
        if ref_low is not None and ref_low <= -99990:
            ref_low = None
        ref_high = biomarker.get("reference_high")
        if ref_high is not None and ref_high <= -99990:
            ref_high = None
            
        if ref_low is not None or ref_high is not None:
            ref_range = {}
            if ref_low is not None:
                ref_range["low"] = {"value": ref_low}
            if ref_high is not None:
                ref_range["high"] = {"value": ref_high}
            obs_resource["referenceRange"] = [ref_range]
            
        bundle["entry"].append({"resource": obs_resource})
        
    return bundle

async def generate_category_summary(observations: List[Dict[str, Any]], category_name: str, patient_name: str = "your loved one") -> str:
    """
    Generates a 2-3 sentence holistic summary for a specific lab report category (e.g., Kidney, Liver)
    based on the raw FHIR Observations.
    """
    if not observations:
        return f"No recent data available for the {category_name} category to generate a summary."

    # Format observations for the LLM
    obs_lines = []
    for obs in observations:
        code = obs.get("code", {}).get("text", "Unknown Biomarker")
        val = ""
        if "valueQuantity" in obs:
            vq = obs["valueQuantity"]
            val = f"{vq.get('value', '')} {vq.get('unit', '')}".strip()
        elif "valueString" in obs:
            val = obs["valueString"]
        
        interp = ""
        if "interpretation" in obs and obs["interpretation"]:
            interp = obs["interpretation"][0].get("text", "")
            
        ref_range_str = ""
        if "referenceRange" in obs and obs["referenceRange"]:
            r = obs["referenceRange"][0]
            low = r.get("low", {}).get("value")
            high = r.get("high", {}).get("value")
            if low is not None and high is not None:
                ref_range_str = f" (Ref: {low} - {high})"
                
        status_str = f" - Status: {interp}" if interp else ""
        obs_lines.append(f"- {code}: {val}{ref_range_str}{status_str}")
        
    obs_text = "\n".join(obs_lines)
    
    prompt = f"""You are a gentle, empathetic clinical AI writing a very brief summary of a specific category from a senior patient's lab report.
The patient is referred to as "{patient_name}".

Category: {category_name}
Recent Biomarker Results:
{obs_text}

Task: Write a maximum of 2 sentences summarizing what these specific results mean for their {category_name} health.
- Be encouraging but medically accurate.
- DO NOT use complex medical jargon.
- If everything is normal, reassure them.
- If something is slightly off, mention it gently without causing alarm (e.g., "A few things are slightly out of balance, such as your...").
- Speak directly to the patient (use "your", "you").
- No bullet points, just a short conversational paragraph.
"""
    try:
        summary = await _call_medgemma(prompt, json_mode=False)
        return summary.strip()
    except Exception as e:
        print(f"Error generating category summary for {category_name}: {e}")
        return f"We're still analyzing your {category_name} results. Check back later for a detailed summary."

async def generate_overall_report_summary(
    observations: List[Dict[str, Any]], 
    patient_name: str = "your loved one", 
    performer: str = "Lab",
    report_name: str = "Lab Report"
) -> str:
    """
    Generates a structured, clinical, empathetic summary for an entire lab report
    based on the structured observations.
    Follows a 3-part layout:
    1. Overall Health (Reassurance, normal organ systems)
    2. Areas to Keep an Eye On (Out-of-range markers with plain-English context)
    3. Suggested Questions for Your Doctor (High-yield discussion items)
    """
    if not observations:
        return "Your lab report is ready. Please consult your physician to review your detailed results."

    out_of_range = []
    all_consumer_cats = set()

    for row in observations:
        res = row.get("resource") or row
        name = res.get("code", {}).get("text") or row.get("loinc_code") or "Unknown Test"
        
        # Check interpretation
        interp = ""
        if "interpretation" in res and res["interpretation"]:
            interp = res["interpretation"][0].get("text", "")
            
        val = row.get("value_numeric")
        if val is None and "valueQuantity" in res:
            val = res["valueQuantity"].get("value")
            
        unit = row.get("unit")
        if not unit and "valueQuantity" in res:
            unit = res["valueQuantity"].get("unit", "")
        unit = unit or ""

        ref_low = row.get("reference_low")
        ref_high = row.get("reference_high")
        if (ref_low is None or ref_high is None) and "referenceRange" in res and res["referenceRange"]:
            rr = res["referenceRange"][0]
            if ref_low is None:
                ref_low = rr.get("low", {}).get("value")
            if ref_high is None:
                ref_high = rr.get("high", {}).get("value")

        # Find consumer category
        cat = None
        for c in res.get("category", []):
            for coding in c.get("coding", []):
                if coding.get("system") == "https://zivaa.com/consumer-category":
                    cat = coding.get("display")
                    break
            if cat:
                break
            if c.get("text"):
                cat = c["text"]
                break
        if not cat:
            cat = "General"
        all_consumer_cats.add(cat)

        is_out = False
        if interp and ("out of range" in interp.lower() or "high" in interp.lower() or "low" in interp.lower() or "abnormal" in interp.lower()):
            is_out = True
        elif ref_low is not None and ref_high is not None and val is not None and ref_low > -90000 and ref_high > -90000:
            if val < ref_low or val > ref_high:
                is_out = True

        if is_out:
            ref_str = f"{ref_low} - {ref_high} {unit}".strip() if (ref_low is not None and ref_high is not None and ref_low > -90000) else "Standard Target"
            out_of_range.append({
                "test_name": name,
                "value": f"{val} {unit}".strip() if val is not None else "Out of range",
                "target": ref_str,
                "category": cat
            })

    out_cats = {o["category"] for o in out_of_range}
    normal_cats = sorted([c for c in all_consumer_cats if c not in out_cats and c != "General"])

    out_lines = [f"- {o['test_name']} ({o['category']}): {o['value']} (Target: {o['target']})" for o in out_of_range]
    out_text = "\n".join(out_lines) if out_lines else "None - all biomarkers tested were within normal ranges."
    normal_text = ", ".join(normal_cats) if normal_cats else "None"

    prompt = f"""You are an expert, compassionate clinical AI physician writing a personalized, comprehensive, and reassuring summary of a senior patient's lab report.
The patient's name is {patient_name}.
Report Name / Panel: {report_name}
Laboratory / Performer: {performer}

Summary of Findings:
- Total biomarkers analyzed: {len(observations)}
- Categories completely within normal ranges (healthy & stable): {normal_text}
- Biomarkers outside reference ranges:
{out_text}

Instructions:
Write an informative, beautifully structured summary using clean markdown.
Start directly with `**Overall Health**`. Do NOT include any conversational preamble or greeting (such as "Here is a summary...").
Strictly adhere to this 3-section layout:

**Overall Health**:
Provide 2-3 reassuring sentences giving the big picture for {patient_name}. Specifically acknowledge the vital organ systems that are healthy and functioning well (e.g. mention normal categories like {normal_text}). Keep the tone reassuring and calm—seniors often worry about lab reports.

**Areas to Keep an Eye On**:
Provide 1 clear bullet point per key finding or related cluster of out-of-range markers:
- Use bullet format: `- **[Biomarker/Group Name]**: [Value vs Target]. [Plain-English explanation: why it matters for seniors, whether it is mildly or moderately out of range, and reassurance that minor fluctuations are common.]`
(If nothing is out of range, write: `- All tested biomarkers are within standard target ranges.`)

**Suggested Questions for Your Doctor**:
Provide 2 concrete, thoughtful, and high-yield questions {patient_name} or their family caregiver can bring up at their next appointment with their doctor (e.g. regarding dietary adjustments, vitamin supplementation like Vitamin D3, or whether a routine repeat test in 3 months makes sense).
- Use bullet format: `- [Question 1]`
- Use bullet format: `- [Question 2]`

Do NOT use alarming language. Be medically grounded, warm, and practical.
"""
    try:
        summary = await _call_medgemma(prompt, json_mode=False)
        cleaned = summary.strip()
        if cleaned.startswith("```markdown"):
            cleaned = cleaned[11:]
        if cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()
        
        # Normalize bullets to standard markdown '- '
        normalized_lines = []
        for line in cleaned.split("\n"):
            t = line.strip()
            if t.startswith("• "):
                normalized_lines.append("- " + t[2:])
            elif t.startswith("*   ") or t.startswith("* "):
                normalized_lines.append("- " + t.lstrip("*").strip())
            else:
                normalized_lines.append(line)
        return "\n".join(normalized_lines).strip()
    except Exception as e:
        print(f"Error generating overall report summary: {e}")
        return "Your lab report has been generated. Most of your results have been processed. Please review the detailed categories below or ask your physician."

async def generate_retest_nudge(patient_id: str, patient_name: str, historical_insights: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Generates an administrative nudge reminding the patient to book lab tests for overdue biomarkers."""
    if not historical_insights:
        return {}

    insights_text = "\n".join([
        f"- {i.get('name')} (Last checked: {i.get('updated_at', 'Unknown')}): {i.get('message')}"
        for i in historical_insights
    ])

    prompt = f"""You are MedGemma, a helpful and empathetic administrative assistant for the patient {patient_name}.
The following lab biomarkers are overdue for a re-test (they are marked as historical or stale):

{insights_text}

Task: Write a short, friendly push notification nudge (title and text) gently reminding the patient to book a lab test to get these levels checked. 
- Do NOT cause alarm. Emphasize that this is just routine maintenance to keep their health data up to date.
- Do NOT provide medical diagnoses.
- Keep the title under 6 words.
- Keep the text under 3 sentences.

Output strictly in JSON format:
{{
    "nudge_title": "String",
    "nudge_text": "String"
}}
"""
    try:
        response_data = await _call_medgemma(prompt, json_mode=True)
        return {
            "nudge_title": response_data.get("nudge_title", "Time for a Lab Checkup"),
            "nudge_text": response_data.get("nudge_text", "Some of your lab results are getting a bit old. Consider booking a quick lab test soon to keep your health data up to date.")
        }
    except Exception as e:
        print(f"Error generating retest nudge: {e}")
        return {
            "nudge_title": "Time for a Lab Checkup",
            "nudge_text": "Some of your lab results are getting a bit old. Consider booking a quick lab test soon to keep your health data up to date."
        }
