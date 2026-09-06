from typing import List, Dict, Any, Tuple
from datetime import datetime, timedelta, timezone
import statistics
import json
import math

from app.services.insights.data_fetcher import supabase
from app.services.medgemma_services import _call_medgemma

def clean_task_name(task_string: str) -> str:
    """Removes the time component from a task string (e.g. 'Evening walk | 7:00 PM' -> 'Evening walk')"""
    if not task_string:
        return ""
    if "|" in task_string:
        return task_string.split("|")[0].strip().lower()
    return task_string.strip().lower()

def fetch_history_data(patient_id: str, days: int = 14) -> List[Dict[str, Any]]:
    """Fetches and aligns daily plans and vitals for the last N days."""
    start_date = (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()
    
    def _normalize_date(date_str: str) -> str:
        return date_str.split("T")[0] if date_str else ""

    # Fetch plans
    plans_res = supabase.table("daily_plans").select("date, schedule").eq("patient_id", patient_id).gte("date", start_date).execute()
    plans_by_date = {_normalize_date(row.get("date")): row.get("schedule", {}) for row in (plans_res.data or []) if row.get("date")}
    
    # Fetch vitals
    vitals_res = supabase.table("vitals_daily").select("*").eq("patient_id", patient_id).gte("date", start_date).execute()
    vitals_by_date = {_normalize_date(row.get("date")): row for row in (vitals_res.data or []) if row.get("date")}
    
    # Align data
    aligned_data = []
    # Get all unique dates
    all_dates = set(plans_by_date.keys()).union(set(vitals_by_date.keys()))
    for d in sorted(all_dates):
        schedule = plans_by_date.get(d) or {}
        
        completed_tasks = []
        uncompleted_tasks = []
        for period, tasks in schedule.items():
            if isinstance(tasks, list):
                for task in tasks:
                    task_name = clean_task_name(task.get("task", ""))
                    if not task_name:
                        continue
                        
                    category = task.get("category", task_name)
                    if task.get("completed"):
                        completed_tasks.append(category)
                    else:
                        uncompleted_tasks.append(category)
                        
        vital = vitals_by_date.get(d, {})
        vitals_dict = {}
        for k, v in vital.items():
            if k not in ["patient_id", "date", "id", "created_at", "updated_at"] and isinstance(v, (int, float)) and v is not None:
                vitals_dict[k] = v

        aligned_data.append({
            "date": d,
            "completed_tasks": completed_tasks,
            "uncompleted_tasks": uncompleted_tasks,
            "vitals": vitals_dict
        })
        
    return aligned_data

def is_statistically_significant(task_vals: List[float], base_vals: List[float], lower_is_better: bool = False) -> bool:
    """Calculates a Welch's T-Test for 90% confidence (alpha=0.10 one-tailed) without relying on scipy."""
    n1, n2 = len(task_vals), len(base_vals)
    if n1 < 2 or n2 < 2: return False
        
    mean_task = statistics.mean(task_vals)
    mean_base = statistics.mean(base_vals)
    var_task = statistics.variance(task_vals)
    var_base = statistics.variance(base_vals)
    
    if var_task == 0 and var_base == 0:
        return (mean_base > mean_task) if lower_is_better else (mean_task > mean_base)
        
    # Ensure improvement results in a positive t-statistic
    diff = (mean_base - mean_task) if lower_is_better else (mean_task - mean_base)
    t_stat = diff / math.sqrt((var_task/n1) + (var_base/n2))
    
    # Degrees of freedom (Welch-Satterthwaite equation)
    num = (var_task/n1 + var_base/n2)**2
    den = (var_task/n1)**2 / (n1 - 1) + (var_base/n2)**2 / (n2 - 1)
    df = num / den if den != 0 else 1.0
    
    # Lookup table for one-tailed alpha=0.10 (90% confidence)
    t_table_90 = [
        3.078, 1.886, 1.638, 1.533, 1.476, 1.440, 1.415, 1.397, 1.383, 1.372, # df 1-10
        1.363, 1.356, 1.350, 1.345, 1.341, 1.337, 1.333, 1.330, 1.328, 1.325, # df 11-20
        1.323, 1.321, 1.319, 1.318, 1.316, 1.315, 1.314, 1.313, 1.311, 1.310  # df 21-30
    ]
    idx = int(round(df)) - 1
    critical_t = 3.078 if idx < 0 else (1.282 if idx >= len(t_table_90) else t_table_90[idx])
    
    return t_stat > critical_t

HIGHER_IS_BETTER = {
    "sleep_hours", "mood_score", "total_steps", "distance_meters", 
    "active_calories", "oxygen_sat_avg", "oxygen_sat_min", "avg_speed",
    "sleep_stage_3_hours", "sleep_stage_4_hours"
}

LOWER_IS_BETTER = {
    "blood_glucose", "bp_systolic", "bp_diastolic", "avg_heart_rate", 
    "max_heart_rate", "min_heart_rate", "resting_heart_rate_calculated", 
    "sleep_max_heart_rate", "respiratory_rate_avg", "cough_count_night", 
    "snoring_events_count", "sit_to_stand_seconds", "body_temp_avg"
}

def calculate_task_correlations(history_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Deterministically calculates statistically significant differences in vitals when a task is completed vs missed.

    """
    # Return early if there is no historical data to process
    if not history_data:
        return []
        
    # Dictionary to store vital metrics for days when a task was completed
    # Structure: { task_name: { metric_name: [value1, value2, ...] } }
    task_vitals: Dict[str, Dict[str, List[float]]] = {}
    
    # Dictionary to store vital metrics for days when a task was missed (baseline)
    # Structure: { task_name: { metric_name: [value1, value2, ...] } }
    baseline_vitals: Dict[str, Dict[str, List[float]]] = {}
    
    # Dynamically extract metrics_to_track from the available vitals data
    # We look at the first day that has a "vitals" dictionary
    metrics_to_track = []
    for day in history_data:
        if day.get("vitals"):
            metrics_to_track = list(day["vitals"].keys())
            break
            
    # If no vital metrics are found in any historical day, we can't calculate correlations
    if not metrics_to_track:
        return []
    
    # Initialize dictionaries for all unique categories ever seen (whether completed or uncompleted)
    for day in history_data:
        tasks_done = set(day.get("completed_tasks", []))
        tasks_missed = set(day.get("uncompleted_tasks", []))
        all_tasks = tasks_done.union(tasks_missed)
        
        for task in all_tasks:
            # Skip empty task names
            if not task: continue
            
            # If we haven't seen this task yet, initialize tracking lists for each metric
            if task not in task_vitals:
                task_vitals[task] = {m: [] for m in metrics_to_track}
                baseline_vitals[task] = {m: [] for m in metrics_to_track}

    # Populate the task_vitals and baseline_vitals dictionaries
    for day in history_data:
        tasks_done = set(day.get("completed_tasks", []))
        tasks_missed = set(day.get("uncompleted_tasks", []))
        
        # A task category can't be both done and missed on the same day for correlation purposes.
        # If it is, 'done' takes precedence.
        tasks_missed = tasks_missed - tasks_done
        
        vitals = day.get("vitals", {})
        
        # Record vitals for tasks that were completed on this day
        for task in tasks_done:
            if not task: continue
            for m in metrics_to_track:
                val = vitals.get(m)
                if val is not None:
                    task_vitals[task][m].append(float(val))
                    
        # Record vitals for tasks that were missed on this day (to establish a baseline)
        for task in tasks_missed:
            if not task: continue
            for m in metrics_to_track:
                val = vitals.get(m)
                if val is not None:
                    baseline_vitals[task][m].append(float(val))
                        
    correlations = []
    
    # Analyze the collected data for each task
    for task, metrics in task_vitals.items():
        # Optimization: Only process tasks that were completed at least twice
        # This ensures we are looking at a repeating pattern, not a one-off event
        if all(len(vals) < 2 for vals in metrics.values()):
            continue
            
        for metric in metrics_to_track:
            task_vals = metrics[metric]
            base_vals = baseline_vitals[task][metric]
            
            # We need at least 2 data points for both 'completed' and 'missed' states
            # to make a meaningful comparison
            if len(task_vals) >= 2 and len(base_vals) >= 2:
                # Calculate the average vital value when task is done vs missed
                task_avg = statistics.mean(task_vals)
                base_avg = statistics.mean(base_vals)
                
                # Determine if the task completion led to an improvement
                improvement_pct = 0.0
                improved = False
                
                # For these metrics, a lower value is considered an improvement
                if metric in LOWER_IS_BETTER:
                    if task_avg < base_avg and base_avg != 0:
                        improved = True
                        improvement_pct = ((base_avg - task_avg) / base_avg) * 100
                        is_significant = is_statistically_significant(task_vals, base_vals, lower_is_better=True)
                        
                # For these metrics, a higher value is considered an improvement
                elif metric in HIGHER_IS_BETTER:
                    if task_avg > base_avg and base_avg != 0:
                        improved = True
                        improvement_pct = ((task_avg - base_avg) / base_avg) * 100
                        is_significant = is_statistically_significant(task_vals, base_vals, lower_is_better=False)
                        
                # If there's an improvement and it's statistically significant, record the correlation
                if improved and is_significant:
                    correlations.append({
                        "task": task,
                        "metric": metric,
                        "task_avg": round(task_avg, 2),
                        "baseline_avg": round(base_avg, 2),
                        "improvement_pct": round(improvement_pct, 1)
                    })
                    
    # Sort the final list by highest improvement percent so the most impactful habits are first
    correlations.sort(key=lambda x: x["improvement_pct"], reverse=True)
    return correlations

async def generate_reinforcement_message(patient_id: str, history_data: List[Dict], correlations: List[Dict]) -> Dict[str, Any]:
    """Generates the LLM reinforcement message based on history and deterministic stats."""
    
    if not correlations:
        return {} # No meaningful correlation found
        
    top_correlation = correlations[0]
    
    history_str = json.dumps(history_data, indent=2)
    stats_str = f"Strongest deterministic correlation: When '{top_correlation['task']}' is completed, '{top_correlation['metric']}' improves by {top_correlation['improvement_pct']}% (from {top_correlation['baseline_avg']} to {top_correlation['task_avg']})."
    
    prompt = f"""You are a health coach analyzing patient data to provide positive reinforcement.

RAW DATA (Last 14 Days):
{history_str}

DETERMINISTIC STATS:
{stats_str}

INSTRUCTIONS:
1. Review the data and the statistical correlation.
2. Write a single, highly encouraging sentence highlighting this specific 'Weekly Win'.
3. Frame it positively. Example: 'When you did your evening walk, your blood sugar was much better!'
4. Do not use jargon or exact percentages, make it sound human and encouraging.
5. Format the response as exact JSON:
{{
    "task": "the task name",
    "metric": "the vital metric",
    "message": "Your encouraging sentence here."
}}
"""
    
    schema = {
        "type": "OBJECT",
        "properties": {
            "task": {"type": "STRING"},
            "metric": {"type": "STRING"},
            "message": {"type": "STRING"}
        },
        "required": ["task", "metric", "message"]
    }
    
    try:
        res = await _call_medgemma(prompt, json_mode=True, prefill=False, response_schema=schema)
        if "```json" in res:
            res = res.split("```json")[-1].split("```")[0].strip()
        parsed = json.loads(res)
        
        # Save to DB
        payload = {
            "patient_id": patient_id,
            "date": datetime.now(timezone.utc).date().isoformat(),
            "task_name": parsed.get("task", ""),
            "vital_metric": parsed.get("metric", ""),
            "message": parsed.get("message", "")
        }
        supabase.table("positive_reinforcements").insert(payload).execute()
        return payload
    except Exception as e:
        print(f"Failed to generate reinforcement: {e}")
        return {}
