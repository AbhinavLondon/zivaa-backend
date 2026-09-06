import os

base_dir = '../ZivaaSeniorApp/app/src/main/java/com/zivaa/app/presentation'
for root, dirs, files in os.walk(base_dir):
    for file in files:
        if file.endswith('.kt'):
            path = os.path.join(root, file)
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            if 'ClosingLine()' in content:
                print(file)
