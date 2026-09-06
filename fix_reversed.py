file_path = '../ZivaaSeniorApp/app/src/main/java/com/zivaa/app/presentation/coach/CoachChatViewModel.kt'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace('val historyMessages = logs.map { log ->', 'val historyMessages = logs.reversed().map { log ->')

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
