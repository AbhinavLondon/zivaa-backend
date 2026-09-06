from typing import Dict, Any
from app.services.insights.data_fetcher import supabase

def calculate_daily_macros(patient_info: Dict[str, Any], setup_prefs: Dict[str, Any]) -> str:
    """Calculates TDEE and target macros for the patient, and saves to patient_plan_setup."""
    try:
        # 1. Base Metrics
        weight_kg = setup_prefs.get("weight_kg")
        height_inches = setup_prefs.get("height_inches")
        goal_weight_kg = setup_prefs.get("goal_weight_kg")
        
        # Cast to int just to be safe
        age = int(patient_info.get("age") or 70)
        sex = patient_info.get("sex", "male")
        if sex is None:
            sex = "male"
        sex = sex.lower()
        
        # If we don't have basic metrics, fallback gracefully
        if not weight_kg or not height_inches:
            return "Total Calories: ~2000 kcal (Protein: 100g, Carbs: 250g, Fat: 65g)"

        # 2. Mifflin-St Jeor BMR
        height_cm = float(height_inches) * 2.54
        weight_kg = float(weight_kg)
        bmr = (10 * weight_kg) + (6.25 * height_cm) - (5 * age)
        if sex == "female":
            bmr -= 161
        else:
            bmr += 5

        # 3. Activity Multiplier
        movement = (setup_prefs.get("movement_level") or "").lower()
        if "sedentary" in movement:
            activity_multiplier = 1.2
        elif "light" in movement:
            activity_multiplier = 1.375
        elif "active" in movement:
            activity_multiplier = 1.55
        elif "very active" in movement:
            activity_multiplier = 1.725
        else:
            activity_multiplier = 1.375 # Default to light

        tdee = bmr * activity_multiplier

        # 4. Goal Adjustment
        target_calories = tdee
        if goal_weight_kg:
            goal_weight_kg = float(goal_weight_kg)
            if goal_weight_kg < weight_kg:
                target_calories -= 300 # Weight loss
            elif goal_weight_kg > weight_kg:
                target_calories += 300 # Weight gain
        
        # Prevent extreme starvation
        if target_calories < 1200:
            target_calories = 1200
            
        # 5. Macro Splits
        diet_type = (setup_prefs.get("diet_type") or "").lower()
        conditions = [c.lower() for c in setup_prefs.get("health_conditions", [])]
        
        # Default split: 50% Carbs, 20% Protein, 30% Fat
        carb_pct, protein_pct, fat_pct = 0.50, 0.20, 0.30
        
        if "keto" in diet_type:
            carb_pct, protein_pct, fat_pct = 0.05, 0.25, 0.70
        elif "diabetes" in conditions or "diabetic" in diet_type:
            carb_pct, protein_pct, fat_pct = 0.40, 0.25, 0.35
            
        # Grams calculation (Carbs: 4 kcal/g, Protein: 4 kcal/g, Fat: 9 kcal/g)
        carbs_g = (target_calories * carb_pct) / 4
        protein_g = (target_calories * protein_pct) / 4
        fat_g = (target_calories * fat_pct) / 9
        
        cal_int = int(target_calories)
        prot_int = int(protein_g)
        carb_int = int(carbs_g)
        fat_int = int(fat_g)
        
        # 6. Save to Supabase
        patient_id = patient_info.get("id")
        if patient_id:
            try:
                # Update the latest setup record for this patient
                setup_resp = supabase.table("patient_plan_setup") \
                    .select("id") \
                    .eq("patient_id", patient_id) \
                    .order("created_at", desc=True) \
                    .limit(1) \
                    .execute()
                
                if setup_resp.data:
                    latest_setup_id = setup_resp.data[0]["id"]
                    supabase.table("patient_plan_setup") \
                        .update({
                            "target_calories_system_generated": cal_int,
                            "protein_g_system_generated": prot_int,
                            "carbs_g_system_generated": carb_int,
                            "fat_g_system_generated": fat_int
                        }) \
                        .eq("id", latest_setup_id) \
                        .execute()
            except Exception as db_e:
                print(f"Warning: Failed to save macros to supabase: {db_e}")

        return f"Total Calories: {cal_int} kcal (Protein: {prot_int}g, Carbs: {carb_int}g, Fat: {fat_int}g)"
    except Exception as e:
        print(f"Warning: Macro calculation failed: {e}")
        return "Total Calories: ~2000 kcal (Protein: 100g, Carbs: 250g, Fat: 65g)"
