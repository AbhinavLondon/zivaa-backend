file_path = '../ZivaaSeniorApp/app/src/main/java/com/zivaa/app/presentation/MainActivity.kt'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace(
    'androidx.compose.foundation.layout.Box(modifier = Modifier.fillMaxSize().padding(bottom = paddingValues.calculateBottomPadding())) {',
    'androidx.compose.foundation.layout.Box(modifier = Modifier.fillMaxSize().consumeWindowInsets(paddingValues)) {'
)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
