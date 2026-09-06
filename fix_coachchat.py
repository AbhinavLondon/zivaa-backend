import re
with open('../ZivaaSeniorApp/app/src/main/java/com/zivaa/app/data/remote/ZivaaApiService.kt', 'r', encoding='utf-8') as f:
    text = f.read()

text = re.sub(r'data class CoachChatResponse\([^)]+\)', 'data class CoachChatResponse(val patient_id: String? = null, val reply: String = "", val suggested_actions: List<String>? = null, val acuity_level: String? = null, val timestamp: String? = null)', text)

with open('../ZivaaSeniorApp/app/src/main/java/com/zivaa/app/data/remote/ZivaaApiService.kt', 'w', encoding='utf-8') as f:
    f.write(text)
