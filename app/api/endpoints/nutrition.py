from fastapi import APIRouter, HTTPException, UploadFile, File, status, Body, BackgroundTasks
from pydantic import BaseModel, Field, AliasChoices, computed_field
from typing import List, Optional
import os
import httpx
import base64
import json
import asyncio
from datetime import datetime, timezone
from app.config import settings
from supabase import create_client

# Global cache to persist micronutrients between analyze and log endpoints
# because the mobile frontend drops fields it doesn't recognize.
FOOD_MICRONUTRIENT_CACHE = {}

router = APIRouter()
supabase = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)

class FoodItemResult(BaseModel):
    name: str
    calories: float = 0.0
    protein_g: float = Field(default=0.0, validation_alias=AliasChoices('protein_g', 'protein'))
    carbs_g: float = Field(default=0.0, validation_alias=AliasChoices('carbs_g', 'carbs'))
    fat_g: float = Field(default=0.0, validation_alias=AliasChoices('fat_g', 'fat'))
    sodium_mg: Optional[float] = 0.0
    potassium_mg: Optional[float] = 0.0
    fiber_g: Optional[float] = 0.0
    calcium_mg: Optional[float] = 0.0
    vitamin_k_mcg: Optional[float] = 0.0

    @computed_field
    @property
    def protein(self) -> float:
        return self.protein_g

    @computed_field
    @property
    def carbs(self) -> float:
        return self.carbs_g

    @computed_field
    @property
    def fat(self) -> float:
        return self.fat_g

class NutritionAnalysisResponse(BaseModel):
    meal_name: Optional[str] = None
    foods: List[FoodItemResult]
    analysis: Optional[str] = None
    error: Optional[str] = None

SYSTEM_PROMPT = """You are a master nutritionist and recipe deconstructor.
When the user provides a meal photo, you must break it down into its RAW ingredients and estimate their weights.

First, determine an appropriate overall name for the meal (e.g., "Rajma Chawal", "Grilled Salmon", "Salad").
Then, for each raw ingredient, provide its name, estimated raw weight in grams, and your best dynamic estimate for its calories and macros (as a fallback in case the USDA database misses it).

You MUST return the result strictly as a valid JSON object matching this schema exactly (replace the placeholder numbers with your actual estimated values for that specific food):
{
  "meal_name": "Name of the overall meal",
  "foods": [
    {
       "name": "Name of raw ingredient (e.g., 'raw lentils', 'chicken breast', 'whole wheat flour')",
       "quantity_g": 100,
       "fallback_calories": 350,
       "fallback_protein_g": 25,
       "fallback_carbs_g": 60,
       "fallback_fat_g": 1
    }
  ],
  "analysis": "Your gentle and encouraging analysis of the meal."
}
If the image doesn't contain any recognizable food, return an empty array for 'foods' and provide a gentle message in 'analysis'."""

SYSTEM_PROMPT_TEXT = """You are a master nutritionist and recipe deconstructor.
Analyze the text description of the meal provided and break it down into its RAW ingredients and estimate their weights.

First, determine an appropriate overall name for the meal (e.g., "Rajma Chawal", "Grilled Salmon", "Salad").
Then, for each raw ingredient, provide its name, estimated raw weight in grams, and your best dynamic estimate for its calories and macros (as a fallback in case the USDA database misses it).

You MUST return the result strictly as a valid JSON object matching this schema exactly (replace the placeholder numbers with your actual estimated values for that specific food):
{
  "meal_name": "Name of the overall meal",
  "foods": [
    {
       "name": "Name of raw ingredient (e.g., 'raw lentils', 'chicken breast', 'whole wheat flour')",
       "quantity_g": 100,
       "fallback_calories": 350,
       "fallback_protein_g": 25,
       "fallback_carbs_g": 60,
       "fallback_fat_g": 1
    }
  ],
  "analysis": "Your gentle and encouraging analysis of the meal."
}"""

async def fetch_usda_nutrients(client: httpx.AsyncClient, ingredient_name: str, quantity_g: float, fallback_cals: float=0.0, fallback_prot: float=0.0, fallback_carb: float=0.0, fallback_fat: float=0.0) -> FoodItemResult:
    api_key = settings.USDA_API_KEY
    
    def create_fallback():
        scale = quantity_g / 100.0
        final_name = f"{ingredient_name} ({quantity_g}g)"
        FOOD_MICRONUTRIENT_CACHE[final_name] = {
            "sodium_mg": 0,
            "potassium_mg": 0,
            "fiber_g": 0,
            "calcium_mg": 0,
            "vitamin_k_mcg": 0
        }
        return FoodItemResult(name=final_name, calories=int(round(fallback_cals * scale)), protein_g=int(round(fallback_prot * scale)), carbs_g=int(round(fallback_carb * scale)), fat_g=int(round(fallback_fat * scale)))

    if not api_key:
        return create_fallback()

    url = f"https://api.nal.usda.gov/fdc/v1/foods/search?query={ingredient_name}&api_key={api_key}&pageSize=1"
    try:
        response = await client.get(url, timeout=10.0)
        if response.status_code == 200:
            data = response.json()
            if data.get("foods") and len(data["foods"]) > 0:
                food = data["foods"][0]
                nutrients = food.get("foodNutrients", [])
                
                cals = prot = carb = fat = sod = pot = fib = calc = vitk = 0.0
                
                for n in nutrients:
                    nid = n.get("nutrientId")
                    val = float(n.get("value") or 0.0)
                    if nid in (1008, 2047, 2048): 
                        if cals == 0.0: cals = val
                    elif nid == 1003: prot = val
                    elif nid == 1005: carb = val
                    elif nid == 1004: fat = val
                    elif nid == 1093: sod = val
                    elif nid == 1092: pot = val
                    elif nid == 1079: fib = val
                    elif nid == 1087: calc = val
                    elif nid == 1185: vitk = val
                
                scale = quantity_g / 100.0 if quantity_g > 0 else 1.0
                
                # Gemini's fallbacks are for the TOTAL quantity, so we convert them to per-100g to compare with USDA
                fallback_cals_per_100g = fallback_cals / scale if scale > 0 else fallback_cals
                
                # Sanity check: If USDA calories diverge massively from Gemini's fallback,
                # USDA likely matched the completely wrong food (e.g. "Diet Coke" matching "Diet Roll").
                # Max allowed variance is 50 kcal or 50% of the fallback, whichever is larger.
                max_variance = max(50.0, fallback_cals_per_100g * 0.5)
                
                if abs(cals - fallback_cals_per_100g) > max_variance or (fallback_cals_per_100g < 5 and cals > 20):
                    # USDA match is bad. Reject USDA and use Gemini's fallbacks (which are already scaled!)
                    # We also zero out micronutrients because they belong to the wrong food.
                    final_name = f"{ingredient_name} ({quantity_g}g)"
                    FOOD_MICRONUTRIENT_CACHE[final_name] = {
                        "sodium_mg": 0,
                        "potassium_mg": 0,
                        "fiber_g": 0,
                        "calcium_mg": 0,
                        "vitamin_k_mcg": 0
                    }
                    return FoodItemResult(
                        name=final_name,
                        calories=int(round(fallback_cals)),
                        protein_g=int(round(fallback_prot)),
                        carbs_g=int(round(fallback_carb)),
                        fat_g=int(round(fallback_fat))
                    )
                
                # If USDA completely missed calories despite finding the food, use fallback (converted to per 100g)
                if cals == 0.0: cals = fallback_cals_per_100g
                if prot == 0.0: prot = fallback_prot / scale if scale > 0 else 0
                if carb == 0.0: carb = fallback_carb / scale if scale > 0 else 0
                if fat == 0.0: fat = fallback_fat / scale if scale > 0 else 0

                final_name = f"{ingredient_name} ({quantity_g}g)"
                FOOD_MICRONUTRIENT_CACHE[final_name] = {
                    "sodium_mg": int(round(sod * scale)),
                    "potassium_mg": int(round(pot * scale)),
                    "fiber_g": int(round(fib * scale)),
                    "calcium_mg": int(round(calc * scale)),
                    "vitamin_k_mcg": int(round(vitk * scale))
                }
                
                return FoodItemResult(
                    name=final_name,
                    calories=int(round(cals * scale)),
                    protein_g=int(round(prot * scale)),
                    carbs_g=int(round(carb * scale)),
                    fat_g=int(round(fat * scale)),
                    sodium_mg=int(round(sod * scale)),
                    potassium_mg=int(round(pot * scale)),
                    fiber_g=int(round(fib * scale)),
                    calcium_mg=int(round(calc * scale)),
                    vitamin_k_mcg=int(round(vitk * scale))
                )
    except Exception as e:
        print(f"Error fetching USDA for {ingredient_name}: {e}")
        
    return create_fallback()

async def resolve_foods_via_usda(parsed_foods: list) -> list:
    async with httpx.AsyncClient() as client:
        tasks = []
        for pf in parsed_foods:
            name = pf.get("name", "Unknown")
            raw_qty = str(pf.get("quantity_g", 100.0)).replace("g", "").replace("G", "").replace(" ", "")
            try:
                qty = float(raw_qty)
            except Exception:
                qty = 100.0
                
            fallback_cals = float(pf.get("fallback_calories", 0.0))
            fallback_prot = float(pf.get("fallback_protein_g", 0.0))
            fallback_carb = float(pf.get("fallback_carbs_g", 0.0))
            fallback_fat = float(pf.get("fallback_fat_g", 0.0))
            
            tasks.append(fetch_usda_nutrients(client, name, qty, fallback_cals, fallback_prot, fallback_carb, fallback_fat))
        results = await asyncio.gather(*tasks)
        return list(results)

@router.post("/analyze-meal-photo", response_model=NutritionAnalysisResponse)
async def analyze_meal_photo(file: UploadFile = File(...)):
    def debug_log(msg):
        with open("nutrition_debug.log", "a") as f:
            f.write(f"DEBUG: {msg}\n")
            
    debug_log(f"Received /analyze-meal-photo request with content_type={file.content_type}")
    
    api_key = settings.GEMINI_API_KEY
    if not api_key:
        debug_log("ERROR: Gemini API Key not configured")
        raise HTTPException(status_code=500, detail="Gemini API Key is not configured.")

    try: 
        contents = await file.read()
        debug_log(f"Successfully read file of size {len(contents)} bytes")
    except Exception as e: 
        debug_log(f"ERROR reading file: {e}")
        raise HTTPException(status_code=400, detail="Failed to read the uploaded image.")

    # Detect mime type from magic bytes to prevent Gemini 400 errors from gallery uploads
    mime_type = "image/jpeg"
    if contents.startswith(b'\xff\xd8'):
        mime_type = "image/jpeg"
    elif contents.startswith(b'\x89PNG\r\n\x1a\n'):
        mime_type = "image/png"
    elif contents.startswith(b'RIFF') and contents[8:12] == b'WEBP':
        mime_type = "image/webp"
    elif contents[4:12] == b'ftypheic' or contents[4:12] == b'ftypheix':
        mime_type = "image/heic"
        
    debug_log(f"Detected mime_type: {mime_type}")
    base64_img = base64.b64encode(contents).decode("utf-8")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key={api_key}"
    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": "Analyze this meal photo."}, {"inlineData": {"mimeType": mime_type, "data": base64_img}}]}],
        "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"}
    }
    
    debug_log("Sending payload to Gemini...")
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload, timeout=60.0)
        debug_log(f"Gemini responded with status: {response.status_code}")
        
        if response.status_code == 200:
            try:
                raw_json = response.json()
                text_result = raw_json["candidates"][0]["content"]["parts"][0]["text"].strip()
                debug_log(f"Gemini raw text output: {text_result}")
                
                import re
                
                # Robust extraction of the first balanced JSON object
                start_idx = text_result.find('{')
                if start_idx != -1:
                    brace_count = 0
                    end_idx = -1
                    in_string = False
                    escape_next = False
                    for i in range(start_idx, len(text_result)):
                        c = text_result[i]
                        if escape_next:
                            escape_next = False
                            continue
                        if c == '\\':
                            escape_next = True
                        elif c == '"':
                            in_string = not in_string
                        elif not in_string:
                            if c == '{':
                                brace_count += 1
                            elif c == '}':
                                brace_count -= 1
                                if brace_count == 0:
                                    end_idx = i
                                    break
                    if end_idx != -1:
                        text_result = text_result[start_idx:end_idx+1]
                
                debug_log(f"Extracted JSON string: {text_result}")
                
                parsed = json.loads(text_result)
                debug_log(f"Successfully parsed JSON. Foods count: {len(parsed.get('foods', []))}")
                
                resolved_foods = await resolve_foods_via_usda(parsed.get("foods", []))
                debug_log(f"Successfully resolved USDA nutrients. Final foods: {resolved_foods}")
                
                resp = NutritionAnalysisResponse(
                    meal_name=parsed.get("meal_name"),
                    foods=resolved_foods, 
                    analysis=parsed.get("analysis")
                )
                debug_log("Successfully returning NutritionAnalysisResponse to frontend")
                return resp
            except Exception as e:
                import traceback
                debug_log(f"ERROR parsing AI response: {traceback.format_exc()}")
                return NutritionAnalysisResponse(foods=[], error=f"Failed to parse AI response: {str(e)}")
        else:
            debug_log(f"ERROR Gemini API: {response.text}")
            return NutritionAnalysisResponse(foods=[], error=f"Gemini API Error: {response.status_code}")

class AnalyzeMealTextRequest(BaseModel):
    text: str

@router.post("/analyze-meal-text", response_model=NutritionAnalysisResponse)
async def analyze_meal_text(request: AnalyzeMealTextRequest):
    api_key = settings.GEMINI_API_KEY
    if not api_key:
        raise HTTPException(status_code=500, detail="Gemini API Key is not configured.")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key={api_key}"
    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT_TEXT}]},
        "contents": [{"role": "user", "parts": [{"text": f"Analyze this meal description: {request.text}"}]}],
        "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"}
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload, timeout=60.0)
        if response.status_code == 200:
            try:
                text_result = response.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                import re
                
                # Robust extraction of the first balanced JSON object
                start_idx = text_result.find('{')
                if start_idx != -1:
                    brace_count = 0
                    end_idx = -1
                    in_string = False
                    escape_next = False
                    for i in range(start_idx, len(text_result)):
                        c = text_result[i]
                        if escape_next:
                            escape_next = False
                            continue
                        if c == '\\':
                            escape_next = True
                        elif c == '"':
                            in_string = not in_string
                        elif not in_string:
                            if c == '{':
                                brace_count += 1
                            elif c == '}':
                                brace_count -= 1
                                if brace_count == 0:
                                    end_idx = i
                                    break
                    if end_idx != -1:
                        text_result = text_result[start_idx:end_idx+1]
                
                parsed = json.loads(text_result)
                resolved_foods = await resolve_foods_via_usda(parsed.get("foods", []))
                return NutritionAnalysisResponse(
                    meal_name=parsed.get("meal_name"),
                    foods=resolved_foods, 
                    analysis=parsed.get("analysis")
                )
            except Exception as e:
                import traceback
                with open("nutrition_debug.log", "a") as f:
                    f.write(f"ERROR in analyze_meal_photo: {traceback.format_exc()}\n")
                return NutritionAnalysisResponse(foods=[], error=f"Failed to parse AI response: {str(e)}")
        else:
            with open("nutrition_debug.log", "a") as f:
                f.write(f"Gemini API Error: {response.status_code} - {response.text}\n")
            return NutritionAnalysisResponse(foods=[], error=f"Gemini API Error: {response.status_code}")

class AnalyzeBarcodeRequest(BaseModel):
    barcode: str

@router.post("/analyze-barcode", response_model=NutritionAnalysisResponse)
async def analyze_barcode(request: AnalyzeBarcodeRequest):
    url = f"https://world.openfoodfacts.org/api/v0/product/{request.barcode}.json"
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=10.0)
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == 1:
                    product = data.get("product", {})
                    name = product.get("product_name", "Unknown Food")
                    n = product.get("nutriments", {})
                    
                    def safe_float(val, multiplier=1.0):
                        try:
                            if val is None or val == "": return 0.0
                            return float(str(val).strip().replace("~", "").replace("<", "").replace(">", "")) * multiplier
                        except:
                            return 0.0
                    
                    food_item = FoodItemResult(
                        name=name,
                        calories=safe_float(n.get("energy-kcal_100g", 0)),
                        protein_g=safe_float(n.get("proteins_100g", 0)),
                        carbs_g=safe_float(n.get("carbohydrates_100g", 0)),
                        fat_g=safe_float(n.get("fat_100g", 0)),
                        sodium_mg=safe_float(n.get("sodium_100g", 0), 1000.0),
                        potassium_mg=safe_float(n.get("potassium_100g", 0), 1000.0),
                        fiber_g=safe_float(n.get("fiber_100g", 0)),
                        calcium_mg=safe_float(n.get("calcium_100g", 0), 1000.0),
                        vitamin_k_mcg=safe_float(n.get("vitamin-k_100g", 0), 1000000.0)
                    )
                    return NutritionAnalysisResponse(foods=[food_item], analysis=f"Found product: {name}")
                return NutritionAnalysisResponse(foods=[], error="Barcode not found.")
            return NutritionAnalysisResponse(foods=[], error="Error connecting to Open Food Facts")
    except Exception as e:
        return NutritionAnalysisResponse(foods=[], error=str(e))

class LogMealRequest(BaseModel):
    patient_id: str
    meal_type: str
    meal_name: Optional[str] = "Meal"
    meal_quantity: Optional[float] = 1.0
    logging_method: str
    ai_analysis: Optional[str] = None
    foods: List[FoodItemResult] = Field(default_factory=list, validation_alias=AliasChoices('foods', 'food_items'))
    date: Optional[str] = None

@router.post("/log-meal", status_code=status.HTTP_201_CREATED)
async def log_meal(request: LogMealRequest, background_tasks: BackgroundTasks):
    with open("nutrition_debug.log", "a") as f:
        f.write(f"LOG_MEAL REQUEST: {request.model_dump_json()}\n")
    try:
        total_calories = 0
        total_protein = 0
        total_carbs = 0
        total_fat = 0
        total_sodium = 0
        total_potassium = 0
        total_fiber = 0
        total_calcium = 0
        total_vitamink = 0
        
        ingredients_data = []
        
        for food in request.foods:
            cached_micros = FOOD_MICRONUTRIENT_CACHE.get(food.name, {})
            
            sod = cached_micros.get("sodium_mg") if cached_micros.get("sodium_mg") is not None else food.sodium_mg
            pot = cached_micros.get("potassium_mg") if cached_micros.get("potassium_mg") is not None else food.potassium_mg
            fib = cached_micros.get("fiber_g") if cached_micros.get("fiber_g") is not None else food.fiber_g
            calc = cached_micros.get("calcium_mg") if cached_micros.get("calcium_mg") is not None else food.calcium_mg
            vitk = cached_micros.get("vitamin_k_mcg") if cached_micros.get("vitamin_k_mcg") is not None else food.vitamin_k_mcg
            
            total_calories += food.calories
            total_protein += food.protein_g
            total_carbs += food.carbs_g
            total_fat += food.fat_g
            total_sodium += sod or 0
            total_potassium += pot or 0
            total_fiber += fib or 0
            total_calcium += calc or 0
            total_vitamink += vitk or 0
            
            # Save the full item in the JSON
            ingredient_dict = food.dict()
            ingredient_dict["calories"] = int(round(food.calories * request.meal_quantity))
            ingredient_dict["protein_g"] = int(round(food.protein_g * request.meal_quantity))
            ingredient_dict["carbs_g"] = int(round(food.carbs_g * request.meal_quantity))
            ingredient_dict["fat_g"] = int(round(food.fat_g * request.meal_quantity))
            ingredient_dict["sodium_mg"] = int(round((sod or 0) * request.meal_quantity))
            ingredient_dict["potassium_mg"] = int(round((pot or 0) * request.meal_quantity))
            ingredient_dict["fiber_g"] = int(round((fib or 0) * request.meal_quantity))
            ingredient_dict["calcium_mg"] = int(round((calc or 0) * request.meal_quantity))
            ingredient_dict["vitamin_k_mcg"] = int(round((vitk or 0) * request.meal_quantity))
            ingredients_data.append(ingredient_dict)

        row = {
            "patient_id": request.patient_id,
            "meal_type": request.meal_type,
            "food_name": request.meal_name,
            "quantity": request.meal_quantity,
            "calories": int(round(total_calories * request.meal_quantity)),
            "protein_g": int(round(total_protein * request.meal_quantity)),
            "carbs_g": int(round(total_carbs * request.meal_quantity)),
            "fat_g": int(round(total_fat * request.meal_quantity)),
            "sodium_mg": int(round(total_sodium * request.meal_quantity)),
            "potassium_mg": int(round(total_potassium * request.meal_quantity)),
            "fiber_g": int(round(total_fiber * request.meal_quantity)),
            "calcium_mg": int(round(total_calcium * request.meal_quantity)),
            "vitamin_k_mcg": int(round(total_vitamink * request.meal_quantity)),
            "logging_method": request.logging_method,
            "ai_analysis": request.ai_analysis,
            "ingredients_json": ingredients_data
        }
        
        if request.date:
            try:
                # E.g. "2026-08-31"
                year, month, day = map(int, request.date.split("-"))
                now_utc = datetime.now(timezone.utc)
                # Keep the same exact hour/minute, but adjust the date so it groups correctly on the frontend
                adjusted_dt = now_utc.replace(year=year, month=month, day=day)
                row["logged_at"] = adjusted_dt.isoformat()
            except Exception as e:
                with open("nutrition_debug.log", "a") as f:
                    f.write(f"Error parsing date {request.date}: {e}\n")
        
        supabase.table("patient_meals").insert([row]).execute()
        
        # Trigger real-time evaluation of nutritional insights in background
        try:
            from app.services.insights.nutrition_analyzer import evaluate_and_save_nutritional_insights
            background_tasks.add_task(evaluate_and_save_nutritional_insights, request.patient_id)
        except Exception as e:
            print(f"Failed to queue nutritional insight evaluation: {e}")

        return {"status": "success", "message": f"Logged meal: {request.meal_name}"}
    except Exception as e:
        import traceback
        with open("nutrition_debug.log", "a") as f:
            f.write(f"LOG_MEAL ERROR: {traceback.format_exc()}\n")
        print(f"Error logging meal: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/meals")
async def get_meals(patient_id: str, date: str, timezone_offset: str = "+01:00"):
    try:
        # Pass the timezone offset to the database query instead of hardcoded 'Z' (UTC)
        # This ensures that meals logged at 12:05 AM local time (which might still be 11:05 PM UTC)
        # correctly align with the local date.
        start_time = f"{date}T00:00:00{timezone_offset}"
        end_time = f"{date}T23:59:59{timezone_offset}"
        response = supabase.table("patient_meals").select("*").eq("patient_id", patient_id).gte("logged_at", start_time).lte("logged_at", end_time).execute()
        return response.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/meals/{meal_id}")
async def delete_meal(meal_id: str):
    try:
        supabase.table("patient_meals").delete().eq("id", meal_id).execute()
        return {"status": "success", "message": f"Deleted meal {meal_id}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/insights")
async def get_nutritional_insights(patient_id: str):
    """Fetch active nutritional insights / nudges for a patient."""
    try:
        response = supabase.table("active_nutritional_insights") \
            .select("*") \
            .eq("patient_id", patient_id) \
            .eq("status", "active") \
            .order("created_at", desc=True) \
            .execute()
        return response.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/insights/evaluate")
async def trigger_nutritional_insights_evaluation(patient_id: str, background_tasks: BackgroundTasks):
    """Manually trigger nutritional insight analysis for a patient."""
    try:
        from app.services.insights.nutrition_analyzer import evaluate_and_save_nutritional_insights
        background_tasks.add_task(evaluate_and_save_nutritional_insights, patient_id)
        return {"status": "success", "message": f"Queued nutritional analysis for {patient_id}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
