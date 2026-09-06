file_path = '../ZivaaSeniorApp/app/src/main/java/com/zivaa/app/data/remote/ZivaaApiService.kt'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace('data class CoachChatLog(val id: String? = null, val patient_id: String? = null, val sender: String? = null, val message: String? = null, val created_at: String? = null)', 'data class CoachChatLog(val id: String = "", val patient_id: String = "", val sender: String = "", val message: String = "", val created_at: String = "")')

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
