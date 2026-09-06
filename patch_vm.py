file_path = '../ZivaaSeniorApp/app/src/main/java/com/zivaa/app/presentation/coach/CoachChatViewModel.kt'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace('com.zivaa.app.data.remote.RetrofitClient.apiService.getCoachChatLogs("eq.")', 'com.zivaa.app.data.remote.ZivaaBackendClient.apiService.getCoachChatLogs(patientId)')

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
