import sys

path = r'c:\Users\abhin\Downloads\Zivaa Apps\zivaa-backend\app\services\loinc_dictionary.py'

with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

target = """    phrase_map = {
        "rdw-cv": "rdw",
        "rdw cv": "rdw",
        "red cell": "erythrocyte",
        "white cell": "leukocyte",
        "packed cell volume": "hematocrit",
        "pcv": "hematocrit",
        "whole blood": "blood",
        "vitamin d 25 hydroxy": "25 hydroxyvitamin d3",
        "vitamin d  25 hydroxy": "25 hydroxyvitamin d3"
    }"""

replacement = """    phrase_map = {
        "rdw-cv": "rdw",
        "rdw cv": "rdw",
        "red cell": "erythrocyte",
        "white cell": "leukocyte",
        "packed cell volume": "hematocrit",
        "pcv": "hematocrit",
        "whole blood": "blood",
        "vitamin d, 25 hydroxy": "25 hydroxyvitamin d3",
        "vitamin d 25 hydroxy": "25 hydroxyvitamin d3"
    }"""

if target in content:
    content = content.replace(target, replacement)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print("Successfully patched vitamin d comma into phrase_map.")
else:
    print("Target string not found!")
