import re
with open('../ZivaaSeniorApp/app/src/main/java/com/zivaa/app/data/remote/ZivaaApiService.kt', 'r', encoding='utf-8') as f:
    text = f.read()

text = re.sub(r'val reply_status: String = ""', 'val reply_status: String', text) # wait, I wrote 'val reply_status: String = ""' earlier... Oh I see, earlier it was 'reply_status: String? = null' and the substitution failed due to syntax error! Let's just fix it completely.
text = re.sub(r'data class SymptomReplyRequest\([^)]+\)', 'data class SymptomReplyRequest(val patient_id: String? = null, val symptom_id: String? = null, val reply_status: String = "")', text)
text = re.sub(r'data class FoodItemDto\([^)]+\)', 'data class FoodItemDto(val id: String = "", val meal_type: String = "", val food_name: String = "", val name: String = "", val calories: Int = 0, val protein_g: Int = 0, val carbs_g: Int = 0, val fat_g: Int = 0, val protein: Int = 0, val carbs: Int = 0, val fat: Int = 0)', text)
text = re.sub(r'data class NutritionAnalysisResponse\([^)]+\)', 'data class NutritionAnalysisResponse(val meal_name: String? = null, val foods: List<FoodItemResult> = emptyList(), val analysis: String? = null, val error: String? = null)', text)

with open('../ZivaaSeniorApp/app/src/main/java/com/zivaa/app/data/remote/ZivaaApiService.kt', 'w', encoding='utf-8') as f:
    f.write(text)
