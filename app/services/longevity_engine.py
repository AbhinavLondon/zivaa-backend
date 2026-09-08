import os
import json
import httpx
from datetime import datetime, timezone, timedelta
from app.config import settings
from app.services.insights.data_fetcher import fetch_patient_context, supabase
from app.services.insights.nutrition_analyzer import analyze_weekly_nutrition
import uuid

WEEKLY_STRATEGIST_PROMPT = """You are Zivaa’s Chief Longevity Expert and Functional Medicine Doctor. 
Your goal is to design a strategic, long-term health protocol for the patient. 
Do not generate a rigid hourly schedule. Instead, generate up to 10 high-impact, daily habits that target the root causes of their clinical alerts, lab trends, and reported symptoms.

--- PATIENT PROFILE ---
Name: {patient_name}
Age: {patient_age}, Sex: {patient_sex}
Conditions: {conditions_str}

--- CLINICAL ROOT CAUSE DATA ---
Active Health Alerts:
{insights_str}

Lab Biomarker Trends:
{labs_str}

Overdue Labs to Schedule:
{overdue_labs_str}

Recent Food Log Analysis:
{nutrition_analysis_str}

--- CONVERSATIONAL MEMORY ---
Permanent Preferences:
{preferences_str}

Recent Symptoms:
{symptoms_str}

Recent Lifestyle Updates:
{lifestyle_str}

Agreed Actions (The patient explicitly agreed to these with the AI Coach):
{agreed_actions_str}

Suggested Actions (The coach suggested these, but patient didn't commit):
{suggested_actions_str}

Adherence Feedback:
{adherence_str}

--- EXISTING BASELINE HABITS & ADHERENCE ---
{baseline_str}

--- INSTRUCTIONS ---
1. MANDATORY: You MUST include any items found in the "Agreed Actions" list as active protocols. Do not invent new solutions for those specific issues.
2. MANDATORY: If there are items in "Overdue Labs to Schedule", you MUST create a specific habit focused on scheduling and completing those lab tests (e.g., "Schedule Lab Appointment this week").
3. Synthesize the Clinical Data and Symptoms to generate additional high-impact daily habits.
4. Keep the "title" short and actionable (e.g., "Take 500mg Magnesium", "Book Lab Test").
5. Keep the "reasoning" extremely personalized, referencing their exact data.
6. Categorize each protocol strictly as one of: ["Nutrition", "Supplement", "Mobility", "Sleep", "Mind", "Diagnostics", "Lifestyle"].
7. For existing habits from the baseline, you must choose a mutation type:
   - "RETAINED": Keep as is.
   - "ESCALATED": Make harder (if adherence is high).
   - "DE-ESCALATED": Make easier (if adherence is low).
   - "GRADUATED": Remove from checklist because it has become an automatic lifestyle habit (if 100% adherence over long term).
   - "DROPPED": Remove completely (if no longer clinically relevant).
7. For completely new habits, use mutation type "NEW". (Limit to max 1-2 NEW habits per week).
8. If mutating or retaining an existing habit, you MUST include its exact `previous_id`. If it's a NEW habit, DO NOT output a `previous_id`.
9. Return the result as a strict JSON array. DO NOT output any markdown, backticks, or reasoning text outside of the JSON array.

--- EXPECTED JSON OUTPUT SCHEMA ---
[
  {{
    "previous_id": "String (Required if not NEW)",
    "mutation_type": "String (RETAINED, ESCALATED, DE-ESCALATED, NEW)",
    "category": "String",
    "title": "String (Descriptive but concise, e.g. '10-min Walk for Mobility', 'Log Lunch for Diet')",
    "description": "String (Detailed instruction)",
    "reasoning": "String (Why we are doing this, referencing their data and adherence if escalated/de-escalated)",
    "linked_asset_id": null
  }}
]
"""

DAILY_GENERATOR_PROMPT = """You are an Adaptability Filter for the patient's daily Longevity Protocols.
Your job is to take their baseline strategic protocols, review their immediate short-term context (today's vitals) against their Official Established Baselines, and output the final protocol checklist for TODAY.

--- BASELINE PROTOCOLS ---
{baseline_protocols}

--- IMMEDIATE CONTEXT (TODAY VS OFFICIAL BASELINE) ---
{vitals_str}

New Agreed Actions (Since yesterday):
{new_actions_str}

--- INSTRUCTIONS ---
1. You MUST include ALL baseline protocols.
2. Compare today's vitals to their Official Baseline. If today's vitals indicate a significant deviation or problem (e.g., terrible sleep compared to their baseline), you may downgrade or modify a baseline protocol (e.g., change high-intensity cardio to a 10-minute stretch). If you do this, set "is_modified_today": true and explain why in "modification_note". NOTE: Do not overreact if the baseline is "calibrating".
3. If there are New Agreed Actions, add them to the array and set "is_new_from_coach": true.
4. Output strict JSON array. DO NOT output markdown.

--- EXPECTED JSON OUTPUT SCHEMA ---
[
  {{
    "id": "String (generate a unique uuid4 for tracking)",
    "category": "String",
    "title": "String (Descriptive but concise, e.g. '10-min Walk for Mobility', 'Log Lunch for Diet')",
    "description": "String",
    "reasoning": "String",
    "is_modified_today": Boolean,
    "modification_note": "String (Empty if false, filled if true)",
    "is_new_from_coach": Boolean
  }}
]
"""

async def generate_weekly_strategy(patient_id: str):
    """Generates the baseline longevity strategy and stores it in the baselines table."""
    print(f"Generating Weekly Longevity Strategy for {patient_id}...")
    context = fetch_patient_context(patient_id)
    if not context:
        return
        
    if not context.preferences and not context.symptoms and not context.agreed_actions and not context.suggested_actions:
        print(f"Cold start detected for {patient_id}. Generating Onboarding Baseline...")
        onboarding_baseline = [
            {
                "id": str(uuid.uuid4()),
                "category": "App Setup",
                "title": "Familiarize yourself with the Zivaa AI Coach",
                "description": "Spend 5 minutes chatting with the AI Coach and tell it about your primary health goals.",
                "reasoning": "The coach is your primary interface for sharing symptoms and preferences. The more it knows, the better your Longevity Plan gets.",
                "is_modified_today": False,
                "modification_note": None,
                "is_new_from_coach": False
            },
            {
                "id": str(uuid.uuid4()),
                "category": "Nutrition",
                "title": "Establish your dietary baseline",
                "description": "Log what you ate for breakfast or lunch today.",
                "reasoning": "We need to understand your current eating habits to suggest meaningful nutritional improvements.",
                "is_modified_today": False,
                "modification_note": None,
                "is_new_from_coach": False
            },
            {
                "id": str(uuid.uuid4()),
                "category": "Mobility",
                "title": "Assess your current physical activity level",
                "description": "Sync your smartwatch or wearable device if you have one, or log a short walk.",
                "reasoning": "Mobility is a core pillar of longevity. A quick assessment helps us tailor safe exercises.",
                "is_modified_today": False,
                "modification_note": None,
                "is_new_from_coach": False
            }
        ]
        
        supabase.table("patient_longevity_baselines").update({"is_active": False}).eq("patient_id", patient_id).execute()
        supabase.table("patient_longevity_baselines").insert({
            "patient_id": patient_id,
            "protocols": onboarding_baseline,
            "is_active": True
        }).execute()
        print(f"Successfully saved Onboarding Baseline for {patient_id}")
        return

    res_patient = supabase.table("patients").select("full_name").eq("id", patient_id).execute()
    patient_name = "Patient"
    if res_patient.data and "full_name" in res_patient.data[0]:
        patient_name = res_patient.data[0]["full_name"]
        
    nutrition_analysis = analyze_weekly_nutrition(patient_id)
    
    # 1. Fetch Existing Baseline
    baseline_res = supabase.table("patient_longevity_baselines").select("*").eq("patient_id", patient_id).eq("is_active", True).execute()
    existing_baseline = baseline_res.data[0]["protocols"] if baseline_res.data else []
    baseline_str = json.dumps(existing_baseline)
    
    # 2. Calculate Adherence
    adherence_str = "No adherence data available for last week."
    if existing_baseline:
        seven_days_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
        completions_res = supabase.table("longevity_protocol_completions").select("protocol_id").eq("patient_id", patient_id).gte("completed_on", seven_days_ago).execute()
        
        if completions_res.data:
            adherence_counts = {}
            for row in completions_res.data:
                pid = row["protocol_id"]
                adherence_counts[pid] = adherence_counts.get(pid, 0) + 1
                
            adherence_lines = []
            for habit in existing_baseline:
                pid = habit.get("id")
                count = adherence_counts.get(pid, 0)
                adherence_lines.append(f"- Habit '{habit.get('title')}': Completed {count}/7 days.")
            adherence_str = "\n".join(adherence_lines)
    
    agreed_actions = [a["description"] for a in context.agreed_actions]
    suggested_actions = [a["description"] for a in context.suggested_actions]
    
    # Fetch historical insights for overdue labs
    hist_resp = supabase.table("active_clinical_insights").select("name, message").eq("patient_id", patient_id).eq("status", "historical").execute()
    overdue_labs = [f"{h['name']}: {h['message']}" for h in hist_resp.data] if hist_resp.data else []
    
    prompt = WEEKLY_STRATEGIST_PROMPT.format(
        patient_name=patient_name,
        patient_age=context.patient_age,
        patient_sex=context.patient_sex,
        conditions_str=json.dumps(context.patient_conditions or []),
        insights_str=json.dumps(context.active_insights or []),
        labs_str=json.dumps(context.labs.history if hasattr(context.labs, "history") else []),
        overdue_labs_str=json.dumps(overdue_labs),
        nutrition_analysis_str=nutrition_analysis,
        preferences_str=json.dumps([p.get("constraint_text") for p in context.preferences]),
        symptoms_str=json.dumps([f"{s.get('name')} ({s.get('severity')})" for s in context.symptoms]),
        lifestyle_str="[]",
        agreed_actions_str=json.dumps(agreed_actions),
        suggested_actions_str=json.dumps(suggested_actions),
        adherence_str=adherence_str,
        baseline_str=baseline_str
    )
    
    api_key = os.environ.get("GEMINI_API_KEY", settings.GEMINI_API_KEY)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key={api_key}"
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2}
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload, timeout=60.0)
        if response.status_code == 200:
            data = response.json()
            raw_text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
            
            if raw_text.startswith("```json"):
                raw_text = raw_text.split("```json")[-1].split("```")[0].strip()
            elif raw_text.startswith("```"):
                raw_text = raw_text.split("```")[-1].split("```")[0].strip()
                
            try:
                parsed = json.loads(raw_text)
                
                final_protocols = []
                for p in parsed:
                    # Filter out DROPPED or GRADUATED habits from the active checklist
                    mutation = p.get("mutation_type", "NEW")
                    if mutation in ["DROPPED", "GRADUATED"]:
                        continue
                        
                    # Handle IDs
                    if mutation == "NEW" or not p.get("previous_id"):
                        p["id"] = str(uuid.uuid4())
                    else:
                        p["id"] = p["previous_id"]
                        
                    # Clean up fields for storage
                    p.pop("previous_id", None)
                    p.pop("mutation_type", None)
                    
                    final_protocols.append(p)
                
                # 3. Save to patient_longevity_baselines
                # Deactivate old baseline
                supabase.table("patient_longevity_baselines").update({"is_active": False}).eq("patient_id", patient_id).execute()
                
                # Insert new baseline
                supabase.table("patient_longevity_baselines").insert({
                    "patient_id": patient_id,
                    "protocols": final_protocols,
                    "is_active": True
                }).execute()
                print(f"Successfully saved new Longevity Baseline for {patient_id}")
                
                # Trigger daily generation immediately after baseline is created
                await generate_daily_protocols(patient_id)
            except Exception as e:
                print(f"Error parsing Weekly Strategist JSON: {e}")
                print(raw_text)
        else:
            print(f"Weekly Strategist LLM Error: {response.text}")


async def generate_daily_protocols(patient_id: str):
    """Adapts the baseline strategy for TODAY and saves it to patient_longevity_protocols."""
    print(f"Generating Daily Longevity Checklist for {patient_id}...")
    
    # 1. Get Baseline
    mem_res = supabase.table("patient_longevity_baselines").select("protocols").eq("patient_id", patient_id).eq("is_active", True).execute()
    if not mem_res.data:
        print("No baseline found. Running Weekly Strategist first.")
        await generate_weekly_strategy(patient_id)
        return
        
    baseline_data = mem_res.data[0]["protocols"]
    
    # Check if this is an Onboarding Baseline
    is_onboarding = False
    if baseline_data and len(baseline_data) > 0:
        first_item = baseline_data[0]
        if first_item.get("category") == "App Setup" and (
            "AI Coach" in first_item.get("title", "") or "AI Coach" in first_item.get("baseline_target", "")
        ):
            is_onboarding = True
            
    if is_onboarding:
        print(f"Onboarding Baseline detected for {patient_id}. Skipping Daily LLM generation.")
        daily_protocols = []
        for p in baseline_data:
            title = p.get("title") or p.get("baseline_target") or "Habit"
            category = p.get("category", "General")
            description = p.get("description") or p.get("why_it_matters") or ""
            reasoning = p.get("reasoning") or p.get("why_it_matters") or ""
            protocol_id = p.get("id") or str(uuid.uuid4())
            daily_protocols.append({
                "id": protocol_id,
                "category": category,
                "title": title,
                "description": description,
                "reasoning": reasoning,
                "is_modified_today": False,
                "modification_note": None,
                "is_new_from_coach": False
            })
        
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        supabase.table("patient_longevity_protocols").upsert({
            "patient_id": patient_id,
            "effective_date": today_str,
            "protocols": daily_protocols,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }, on_conflict="patient_id, effective_date").execute()
        return
        
    baseline_protocols = json.dumps(baseline_data)
    
    # 2. Get immediate context (Vitals & New Agreed Actions from last 24h)
    twenty_four_hours_ago = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    
    # Query the aggregated vitals_daily view for JUST today/most recent day
    vitals_res = supabase.table("vitals_daily").select("*").eq("patient_id", patient_id).order("date", desc=True).limit(1).execute()
    
    if vitals_res.data:
        today_vitals = vitals_res.data[0]
        
        from app.services.insights.baseline import fetch_stored_baselines
        stored_baselines = fetch_stored_baselines(patient_id)
        
        context_lines = ["Today's Vitals vs Official Baselines:"]
        for key, val in today_vitals.items():
            if val is not None and key not in ("patient_id", "date", "id"):
                baseline_info = stored_baselines.get(key)
                if baseline_info:
                    b_mean = baseline_info.get("baseline_mean")
                    status = baseline_info.get("status", "calibrating")
                    if b_mean is not None:
                        # try to format as float if it's numeric
                        try:
                            context_lines.append(f"- {key}: {val} (Baseline: {float(b_mean):.2f} [{status}])")
                        except:
                            context_lines.append(f"- {key}: {val} (Baseline: {b_mean} [{status}])")
                    else:
                        context_lines.append(f"- {key}: {val} (Baseline: None [{status}])")
                else:
                    context_lines.append(f"- {key}: {val} (No baseline tracked)")
        
        vitals_context = "\n".join(context_lines)
    else:
        vitals_context = "No recent vitals available."
    
    actions_res = supabase.table("care_plan_actions").select("description").eq("patient_id", patient_id).eq("status", "Agreed").gte("created_at", twenty_four_hours_ago).execute()
    new_actions_str = json.dumps([r["description"] for r in (actions_res.data or [])])
    
    prompt = DAILY_GENERATOR_PROMPT.format(
        baseline_protocols=baseline_protocols,
        vitals_str=vitals_context,
        new_actions_str=new_actions_str
    )
    
    api_key = os.environ.get("GEMINI_API_KEY", settings.GEMINI_API_KEY)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key={api_key}"
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1}
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload, timeout=60.0)
        if response.status_code == 200:
            data = response.json()
            raw_text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
            
            if raw_text.startswith("```json"):
                raw_text = raw_text.split("```json")[-1].split("```")[0].strip()
            elif raw_text.startswith("```"):
                raw_text = raw_text.split("```")[-1].split("```")[0].strip()
                
            try:
                parsed = json.loads(raw_text)
                
                # Ensure each has a UUID
                for p in parsed:
                    if "id" not in p or not p["id"] or p["id"].startswith("String"):
                        p["id"] = str(uuid.uuid4())
                        
                today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                
                # Upsert into daily table
                # Supabase handles unique(patient_id, effective_date) via upsert
                # Need to use postgrest upsert correctly
                supabase.table("patient_longevity_protocols").upsert({
                    "patient_id": patient_id,
                    "effective_date": today_str,
                    "protocols": parsed,
                    "updated_at": datetime.now(timezone.utc).isoformat()
                }, on_conflict="patient_id, effective_date").execute()
                
                print(f"Successfully generated Daily Longevity Checklist for {patient_id} for {today_str}")
            except Exception as e:
                print(f"Error parsing Daily Generator JSON: {e}")
                print(raw_text)
        else:
            print(f"Daily Generator LLM Error: {response.text}")


