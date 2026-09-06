import asyncio
import os
import sys
import json
from dotenv import load_dotenv

load_dotenv()
sys.path.append('.')

from app.services.insights.data_fetcher import supabase
from app.services.medgemma_services import _call_medgemma

async def normalize_tasks(tasks):
    if not tasks: return {}
    prompt = f"""You are an AI tasked with normalizing variations of the same health tasks into canonical categories.
Given this list of tasks:
{json.dumps(tasks, indent=2)}

Group semantically identical tasks together into short, unified canonical categories (e.g., 'light stroll outdoors' and 'leisurely evening stroll' -> 'Walking', 'calm mind' -> 'Meditation').
Return EXACTLY a JSON dictionary where the keys are the exact raw task names from the list, and the values are the short canonical category names. Do not include markdown formatting or other text.
"""
    try:
        res = await _call_medgemma(prompt, json_mode=True, prefill=False)
        if "```json" in res:
            res = res.split("```json")[-1].split("```")[0].strip()
        mapping = json.loads(res)
        return mapping
    except Exception as e:
        print(f"Failed to normalize tasks: {e}")
        return {t: t for t in tasks}

async def main():
    print("Fetching all daily plans...")
    res = supabase.table("daily_plans").select("id, schedule").execute()
    plans = res.data or []
    print(f"Found {len(plans)} plans.")
    
    all_raw_tasks = set()
    for plan in plans:
        schedule = plan.get("schedule") or {}
        for period, tasks in schedule.items():
            if isinstance(tasks, list):
                for task in tasks:
                    t_name = task.get("task", "")
                    if t_name and "category" not in task:
                        # strip time for normalization mapping
                        t_clean = t_name.split("|")[0].strip().lower()
                        all_raw_tasks.add(t_clean)
                        
    if not all_raw_tasks:
        print("No tasks need categorization.")
        return
        
    print(f"Found {len(all_raw_tasks)} unique un-categorized tasks. Normalizing...")
    mapping = await normalize_tasks(list(all_raw_tasks))
    print(f"Normalized mapping generated: {json.dumps(mapping, indent=2)}")
    
    updates = 0
    for plan in plans:
        schedule = plan.get("schedule") or {}
        changed = False
        for period, tasks in schedule.items():
            if isinstance(tasks, list):
                for task in tasks:
                    if "category" not in task:
                        t_name = task.get("task", "")
                        t_clean = t_name.split("|")[0].strip().lower()
                        cat = mapping.get(t_clean, t_clean)
                        task["category"] = cat
                        changed = True
                        
        if changed:
            print(f"Updating plan {plan['id']}...")
            supabase.table("daily_plans").update({"schedule": schedule}).eq("id", plan["id"]).execute()
            updates += 1
            
    print(f"Migration complete. Updated {updates} plans.")

if __name__ == "__main__":
    asyncio.run(main())
