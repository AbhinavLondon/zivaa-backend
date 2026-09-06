file_path = '../ZivaaSeniorApp/app/src/main/java/com/zivaa/app/presentation/dashboard/DashboardScreen.kt'
with open(file_path, 'r', encoding='utf-8') as f:
    text = f.read()

target = 'style = ZivaaTheme.typography.cardTitle.copy(fontStyle = FontStyle.Normal, fontSize = 18.sp, lineHeight = (18 * 1.14).sp, letterSpacing = (-0.01).em)'
replacement = 'style = ZivaaTheme.typography.cardTitle.copy(fontStyle = FontStyle.Normal, fontSize = 23.sp, lineHeight = (23 * 1.14).sp, letterSpacing = (-0.01).em)'

# Find the occurrence that comes BEFORE NudgeAlertCard
first_idx = text.find(target)
second_idx = text.find(target, first_idx + 1)

text = text[:first_idx] + text[first_idx:].replace(target, replacement, 1)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(text)
print("Reverted first occurrence.")
