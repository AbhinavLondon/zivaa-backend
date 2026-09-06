from datetime import datetime, timezone, timedelta
import json
from collections import defaultdict
from app.services.insights.data_fetcher import supabase
from app.services.medgemma_services import _call_medgemma, _clean_json

def get_patient_macro_targets(patient_id: str) -> dict:
    """Fetch the patient's calculated macro targets from the database."""
    default_targets = {
        "calories_max": 2000,
        "protein_min": 60,
        "carbs_max": 250,
        "fat_max": 70,
        "sodium_max": 2300,
        "fiber_min": 25
    }
    
    try:
        res = supabase.table("patient_plan_setup").select("*").eq("patient_id", patient_id).order("created_at", desc=True).limit(1).execute()
        if res.data:
            setup = res.data[0]
            # Prioritize user-configured targets over system-generated targets
            cals = setup.get("target_calories_user_generated") or setup.get("target_calories_system_generated") or setup.get("target_calories")
            if cals:
                default_targets["calories_max"] = cals
            prot = setup.get("protein_g_user_generated") or setup.get("protein_g_system_generated")
            if prot:
                default_targets["protein_min"] = prot
            carbs = setup.get("carbs_g_user_generated") or setup.get("carbs_g_system_generated")
            if carbs:
                default_targets["carbs_max"] = carbs
            fat = setup.get("fat_g_user_generated") or setup.get("fat_g_system_generated")
            if fat:
                default_targets["fat_max"] = fat
    except Exception as e:
        print(f"Error fetching macro targets for {patient_id}: {e}")
        
    return default_targets

def analyze_weekly_nutrition(patient_id: str) -> dict:
    """
    Fetches the last 7 days of meals for a patient, aggregates macros and micros,
    generates structured deltas vs targets, and identifies culprits.
    """
    seven_days_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    
    result = {
        "status": "success",
        "days_logged": 0,
        "averages": {},
        "gaps": [],
        "culprits": {}
    }
    
    try:
        res = supabase.table("patient_meals").select("*").eq("patient_id", patient_id).gte("logged_at", seven_days_ago).execute()
        meals = res.data or []
    except Exception as e:
        print(f"Error fetching patient meals for nutrition analysis: {e}")
        result["status"] = "error"
        result["error"] = str(e)
        return result
        
    if not meals:
        result["status"] = "no_data"
        return result
        
    num_days_with_logs = len(set([m["logged_at"].split("T")[0] for m in meals]))
    if num_days_with_logs == 0:
        num_days_with_logs = 1 
        
    result["days_logged"] = num_days_with_logs
        
    total_macros = {"calories": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0}
    total_micros = {"sodium_mg": 0, "fiber_g": 0, "potassium_mg": 0, "saturated_fat_g": 0}
    
    food_contributions = defaultdict(lambda: {"calories": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0})
    ingredient_contributions = defaultdict(lambda: {"sodium_mg": 0, "fiber_g": 0, "potassium_mg": 0, "saturated_fat_g": 0})
    
    for meal in meals:
        for macro in total_macros.keys():
            val = meal.get(macro) or 0
            total_macros[macro] += val
            food_contributions[meal.get("food_name", "Unknown")][macro] += val
            
        ingredients_data = meal.get("ingredients_json")
        has_ingredients = False
        if ingredients_data:
            if isinstance(ingredients_data, str):
                try:
                    ingredients = json.loads(ingredients_data)
                except Exception:
                    ingredients = []
            else:
                ingredients = ingredients_data
                
            if isinstance(ingredients, list) and len(ingredients) > 0:
                has_ingredients = True
                for ing in ingredients:
                    ing_name = ing.get("name", "Unknown")
                    for micro in total_micros.keys():
                        val = ing.get(micro) or 0
                        total_micros[micro] += val
                        ingredient_contributions[ing_name][micro] += val
                        
        if not has_ingredients:
            for micro in ["sodium_mg", "fiber_g", "potassium_mg"]:
                val = meal.get(micro) or 0
                total_micros[micro] += val
                ingredient_contributions[meal.get("food_name", "Unknown")][micro] += val
                    
    avg_macros = {k: v / num_days_with_logs for k, v in total_macros.items()}
    avg_micros = {k: v / num_days_with_logs for k, v in total_micros.items()}
    result["averages"] = {**avg_macros, **avg_micros}
    
    targets = get_patient_macro_targets(patient_id)
    
    # Gap Analysis
    if avg_macros["protein_g"] < (targets["protein_min"] * 0.8): # < 80% of target
        result["gaps"].append({
            "type": "protein_deficit",
            "delta": targets["protein_min"] - avg_macros["protein_g"],
            "target": targets["protein_min"],
            "current": avg_macros["protein_g"]
        })
    
    if avg_macros["calories"] > (targets["calories_max"] * 1.1): # > 110% of target
        top_cal = sorted(food_contributions.items(), key=lambda x: x[1]["calories"], reverse=True)[:3]
        result["culprits"]["high_calories"] = [k for k, v in top_cal]
        result["gaps"].append({
            "type": "calorie_surplus",
            "delta": avg_macros["calories"] - targets["calories_max"],
            "target": targets["calories_max"],
            "current": avg_macros["calories"]
        })
        
    if avg_micros["sodium_mg"] > (targets["sodium_max"] * 1.1):
        top_sod = sorted(ingredient_contributions.items(), key=lambda x: x[1]["sodium_mg"], reverse=True)[:3]
        result["culprits"]["high_sodium"] = [k for k, v in top_sod]
        result["gaps"].append({
            "type": "sodium_excess",
            "delta": avg_micros["sodium_mg"] - targets["sodium_max"],
            "target": targets["sodium_max"],
            "current": avg_micros["sodium_mg"]
        })
        
    if avg_micros["fiber_g"] < (targets["fiber_min"] * 0.7):
        result["gaps"].append({
            "type": "fiber_deficit",
            "delta": targets["fiber_min"] - avg_micros["fiber_g"],
            "target": targets["fiber_min"],
            "current": avg_micros["fiber_g"]
        })

    return result

def _get_default_nudge(gap_type: str, primary_gap: dict) -> str:
    """Provides a safe, rule-based fallback nudge if LLM response parsing fails."""
    if gap_type == "protein_deficit":
        return "Try adding a source of lean protein like Greek yogurt, eggs, or lentils to your next meal to help hit your target."
    elif gap_type == "fiber_deficit":
        return "Aim to incorporate a serving of leafy greens, beans, or berries into your diet today for an easy fiber boost."
    elif gap_type == "sodium_excess":
        return "Consider flavoring your meals with fresh herbs or lemon juice rather than adding extra salt today."
    elif gap_type == "calorie_surplus":
        return "Focus on mindful portion sizes and lighter snack options to stay aligned with your daily goals."
    return "Focus on balanced, nutrient-dense whole foods today."

async def evaluate_and_save_nutritional_insights(patient_id: str):
    """
    Runs the weekly nutrition analysis. If there are gaps, uses MedGemma to generate 
    a behavioral nudge and saves it to the active_nutritional_insights table.
    """
    print(f"Evaluating nutritional insights for {patient_id}...")
    analysis = analyze_weekly_nutrition(patient_id)
    
    if analysis.get("status") != "success" or not analysis.get("gaps"):
        # Resolve existing active nutritional insights if the gap is closed
        try:
            supabase.table("active_nutritional_insights").update({"status": "resolved"}).eq("patient_id", patient_id).eq("category", "nutrition").eq("status", "active").execute()
            print(f"No nutritional gaps for {patient_id}. Resolved existing insights.")
        except Exception as e:
            print(f"Error resolving insights for {patient_id}: {e}")
        return
        
    # We have gaps. Let's ask MedGemma to generate a nudge for the most prominent one.
    # To keep it simple, we focus on the first gap in the list.
    primary_gap = analysis["gaps"][0]
    gap_type = primary_gap["type"]
    
    culprit_str = ""
    if gap_type == "calorie_surplus" and "high_calories" in analysis.get("culprits", {}):
        culprit_str = f"Top calorie contributors: {', '.join(analysis['culprits']['high_calories'])}."
    elif gap_type == "sodium_excess" and "high_sodium" in analysis.get("culprits", {}):
        culprit_str = f"Top sodium contributors: {', '.join(analysis['culprits']['high_sodium'])}."
        
    prompt = f"""
You are a supportive, expert behavioral nutritionist.
The patient has a 7-day rolling average dietary gap: {gap_type}.
Current value: {primary_gap['current']:.0f}. Target value: {primary_gap['target']:.0f}.
{culprit_str}

Please generate ONE small, realistic, habit-based nutritional nudge (1-2 sentences max) to help the patient close this gap today.
Do not dictate a full recipe. Focus on a simple behavioral change or ingredient swap.

Return the response as a strict JSON object with a single key "nudge_message".
Example: {{"nudge_message": "Try adding a boiled egg or a scoop of protein powder to your breakfast today to hit your protein goal."}}
"""
    
    try:
        llm_res_text = await _call_medgemma(prompt, json_mode=True)
        llm_res = _clean_json(llm_res_text) if isinstance(llm_res_text, str) else llm_res_text
        
        nudge_message = None
        if isinstance(llm_res, dict):
            nudge_message = llm_res.get("nudge_message")
            
        if not nudge_message:
            nudge_message = _get_default_nudge(gap_type, primary_gap)
            
        # Check if an insight already exists
        existing_res = supabase.table("active_nutritional_insights").select("id, context_data").eq("patient_id", patient_id).eq("rule_id", f"nutrition_{gap_type}").eq("status", "active").execute()
        
        insight_payload = {
            "patient_id": patient_id,
            "rule_id": f"nutrition_{gap_type}",
            "insight_name": f"Nutritional Gap: {gap_type.replace('_', ' ').title()}",
            "severity": "medium",
            "status": "active",
            "category": "nutrition",
            "context_data": nudge_message,
            "data_source": "patient_meals",
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        
        if existing_res.data:
            insight_id = existing_res.data[0]["id"]
            supabase.table("active_nutritional_insights").update({"context_data": nudge_message, "updated_at": datetime.now(timezone.utc).isoformat()}).eq("id", insight_id).execute()
        else:
            supabase.table("active_nutritional_insights").insert(insight_payload).execute()
            
        # Resolve any other active nutritional insights that don't match the current active primary gap
        current_rule_id = f"nutrition_{gap_type}"
        try:
            supabase.table("active_nutritional_insights") \
                .update({"status": "resolved", "updated_at": datetime.now(timezone.utc).isoformat()}) \
                .eq("patient_id", patient_id) \
                .eq("category", "nutrition") \
                .eq("status", "active") \
                .neq("rule_id", current_rule_id) \
                .execute()
        except Exception as e:
            print(f"Warning: Failed to resolve old insights for {patient_id}: {e}")
            
        print(f"Successfully saved nutritional insight for {patient_id}: {gap_type}")
        
    except Exception as e:
        print(f"Failed to generate and save nutritional insight for {patient_id}: {e}")

# For testing
if __name__ == "__main__":
    import asyncio
    asyncio.run(evaluate_and_save_nutritional_insights("test_patient_id"))
