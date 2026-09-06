import re

file_path = '../ZivaaSeniorApp/app/src/main/java/com/zivaa/app/data/remote/ZivaaApiService.kt'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

new_endpoint = '''
    @GET("api/v1/coach/chat/history/{patient_id}")
    suspend fun getCoachChatLogs(
        @Path("patient_id") patientId: String
    ): Response<List<com.zivaa.app.data.model.CoachChatLog>>
}'''

if 'getCoachChatLogs' not in content:
    content = content.replace('import retrofit2.http.GET', 'import retrofit2.http.GET\\nimport retrofit2.http.Path')
    content = content[:content.rindex('}')] + new_endpoint
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
