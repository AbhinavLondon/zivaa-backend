file_path = '../ZivaaSeniorApp/app/src/main/java/com/zivaa/app/presentation/dashboard/DashboardScreen.kt'
with open(file_path, 'r', encoding='utf-8') as f:
    text = f.read()

target = 'fontSize = 18.sp'
replacement = 'fontSize = 16.sp'

text = text.replace(target, replacement)
text = text.replace('lineHeight = (18 * 1.14).sp', 'lineHeight = (16 * 1.14).sp')

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(text)
print("Updated Nudge title font size to 16.sp")
