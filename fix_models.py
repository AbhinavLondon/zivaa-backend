import re
with open('../ZivaaSeniorApp/app/src/main/java/com/zivaa/app/data/remote/ZivaaApiService.kt', 'r', encoding='utf-8') as f:
    text = f.read()

text = re.sub(r'data class DeviceRegistrationRequest\([^)]+\)', 'data class DeviceRegistrationRequest(val device_id: String? = null, val token: String? = null, val fcm_token: String? = null, val patient_id: String? = null, val timezone: String? = null)', text)
text = re.sub(r'data class SymptomReplyRequest\([^)]+\)', 'data class SymptomReplyRequest(val patient_id: String? = null, val symptom_id: String? = null, val reply_status: String = "")', text)
text = re.sub(r'data class FoodItemDto\([^)]+\)', 'data class FoodItemDto(val id: String? = null, val meal_type: String? = null, val food_name: String? = null, val name: String? = null, val calories: Int = 0, val protein_g: Int = 0, val carbs_g: Int = 0, val fat_g: Int = 0, val protein: Int = 0, val carbs: Int = 0, val fat: Int = 0)', text)
text = re.sub(r'data class FoodItemResult\([^)]+\)', 'data class FoodItemResult(val name: String = "", val calories: Int = 0, val carbs: Int = 0, val protein: Int = 0, val fat: Int = 0, val protein_g: Int = 0, val carbs_g: Int = 0, val fat_g: Int = 0, val confidence: Double? = null, val serving_size: String? = null)', text)
text = re.sub(r'val meal_quantity: Double\? = null', 'val meal_quantity: Float? = null', text)
text = re.sub(r'data class DailyPlanTask\([^)]+\)', 'data class DailyPlanTask(val task: String, val completed: Boolean = false, val category: String? = null, val time: String? = null, val details: String? = null)', text)
text = re.sub(r'data class NutritionAnalysisResponse\([^)]+\)', 'data class NutritionAnalysisResponse(val meal_name: String? = null, val foods: List<FoodItemResult>? = null, val analysis: String? = null, val error: String? = null)', text)

with open('../ZivaaSeniorApp/app/src/main/java/com/zivaa/app/data/remote/ZivaaApiService.kt', 'w', encoding='utf-8') as f:
    f.write(text)
