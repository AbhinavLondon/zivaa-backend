import os
import glob

# directories to search
base_dir = '../ZivaaSeniorApp/app/src/main/java/com/zivaa/app/presentation'
for root, dirs, files in os.walk(base_dir):
    for file in files:
        if file.endswith('Screen.kt'):
            path = os.path.join(root, file)
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
                if 'verticalScroll' in content or 'LazyColumn' in content:
                    print(file)
