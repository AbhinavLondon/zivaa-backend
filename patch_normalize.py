import sys
import re

path = r'c:\Users\abhin\Downloads\Zivaa Apps\zivaa-backend\app\services\loinc_dictionary.py'

with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# We need to insert the phrase replacements right before punctuation removal
target = """    text = text.lower()
    # Remove punctuation except spaces
    text = re.sub(r'[^\\w\\s]', ' ', text)"""

replacement = """    text = text.lower()
    
    # Pre-punctuation phrase replacements for multi-word or hyphenated clinical terms
    phrase_map = {
        "rdw-cv": "rdw",
        "rdw cv": "rdw",
        "red cell": "erythrocyte",
        "white cell": "leukocyte",
        "packed cell volume": "hematocrit",
        "pcv": "hematocrit"
    }
    for k, v in phrase_map.items():
        # Use regex to only replace whole words
        text = re.sub(r'\\b' + re.escape(k) + r'\\b', v, text)
        
    # Remove punctuation except spaces
    text = re.sub(r'[^\\w\\s]', ' ', text)"""

if target in content:
    content = content.replace(target, replacement)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print("Successfully patched multi-word phrase replacements into normalize_text.")
else:
    print("Target string not found in loinc_dictionary.py!")
