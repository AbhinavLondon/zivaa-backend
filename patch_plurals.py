import sys

path = r'c:\Users\abhin\Downloads\Zivaa Apps\zivaa-backend\app\services\loinc_dictionary.py'

with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Normalize line endings
content = content.replace('\r\n', '\n')

target = """    abbreviations = {
        "eosinophils": "eosinophil",
        "neutrophils": "neutrophil",
        "lymphocytes": "lymphocyte",
        "monocytes": "monocyte",
        "basophils": "basophil",
        "reticulocytes": "reticulocyte",
        "erythrocytes": "erythrocyte",
        "leukocytes": "leukocyte",
        "s": "serum","""

replacement = """    abbreviations = {
        "red cell": "erythrocyte",
        "white cell": "leukocyte",
        "pcv": "hematocrit",
        "packed cell volume": "hematocrit",
        "rdw-cv": "rdw",
        "eosinophils": "eosinophil",
        "neutrophils": "neutrophil",
        "lymphocytes": "lymphocyte",
        "monocytes": "monocyte",
        "basophils": "basophil",
        "reticulocytes": "reticulocyte",
        "erythrocytes": "erythrocyte",
        "leukocytes": "leukocyte",
        "s": "serum","""

if target in content:
    content = content.replace(target, replacement)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print("Successfully patched new clinical abbreviations into loinc_dictionary.py")
else:
    print("Target string not found in loinc_dictionary.py!")
