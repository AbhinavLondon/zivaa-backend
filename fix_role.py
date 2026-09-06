file_path = '../ZivaaSeniorApp/app/src/main/java/com/zivaa/app/data/remote/ZivaaApiService.kt'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace('val sender: String = ""', 'val role: String = ""')

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
