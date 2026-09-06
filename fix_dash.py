file_path = '../ZivaaSeniorApp/app/src/main/java/com/zivaa/app/presentation/dashboard/DashboardScreen.kt'
with open(file_path, 'r', encoding='utf-8') as f:
    text = f.read()

# I added Spacer(modifier = Modifier.height(130.dp)) outside the scrolling Column. Let's remove it from there.
text = text.replace('Spacer(modifier = Modifier.height(130.dp))', '')

# Now let's add it INSIDE the scrolling column, right before the "// Gesture Bar"
target = '                // Gesture Bar'
replacement = '                Spacer(modifier = Modifier.height(130.dp))\n                // Gesture Bar'

text = text.replace(target, replacement)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(text)
print("Dashboard fixed!")
