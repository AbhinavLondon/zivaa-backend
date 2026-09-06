import os

path = r'c:\Users\abhin\Downloads\Zivaa Apps\zivaa-backend\app\services\loinc_dictionary.py'

with open(path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find the marker where the massive dictionary starts
marker_idx = -1
for i, line in enumerate(lines):
    if "# Auto-generated top 20000 common biomarkers" in line:
        marker_idx = i
        break

if marker_idx == -1:
    print("Marker not found!")
    exit(1)

# Extract everything BEFORE the marker
top_lines = lines[:marker_idx]

# Extract everything from the marker to the end
bottom_lines = lines[marker_idx:]

# Rewrite the top lines!
new_top = """import re
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# Tier 1 Core Dictionary
# This dictionary powers Zivaa's core insights (Dehydration, Diabetes, etc.)
"""

# I need to preserve LOINC_DICTIONARY initialization up to the end of normalize_text.
# Actually, I can just grab LOINC_DICTIONARY definition from top_lines.
# Let's find where normalize_text starts and ends.
dict_start = 0
for i, line in enumerate(top_lines):
    if "LOINC_DICTIONARY = {" in line:
        dict_start = i
        break

def_get_loinc = 0
for i, line in enumerate(top_lines):
    if "def get_loinc_mapping" in line:
        def_get_loinc = i
        break

# The part we want to keep is from dict_start to def_get_loinc
middle_part = "".join(top_lines[dict_start:def_get_loinc])

new_get_loinc_mapping = """def get_loinc_mapping(extracted_name: str) -> dict:
    \"\"\"
    Performs a strict/lexical match of the extracted biomarker name against the dictionary using TF-IDF.
    Returns a dict with {"loinc_code": str, "name": str, "category": str} if a match is found.
    Otherwise returns None.
    \"\"\"
    if not extracted_name:
        return None
        
    normalized_query = normalize_text(extracted_name)
    
    # 1. Exact Match first (fastest) on normalized strings
    for loinc, data in LOINC_DICTIONARY.items():
        syns_normalized = [normalize_text(s) for s in data["synonyms"]]
        if normalized_query in syns_normalized:
            return {
                "loinc_code": loinc,
                "name": data["name"],
                "category": data["category"]
            }
            
    # 2. TF-IDF + Cosine Similarity Match (Robust against stop-words)
    # The TF-IDF matrix is computed once at module initialization.
    query_vec = tfidf_vectorizer.transform([normalized_query])
    similarities = cosine_similarity(query_vec, tfidf_matrix).flatten()
    
    best_idx = similarities.argmax()
    best_score = similarities[best_idx]
    
    # Safe threshold for TF-IDF Cosine Similarity
    if best_score >= 0.55:
        best_match_loinc = tfidf_loinc_mapping[best_idx]
        return {
            "loinc_code": best_match_loinc,
            "name": LOINC_DICTIONARY[best_match_loinc]["name"],
            "category": LOINC_DICTIONARY[best_match_loinc]["category"]
        }
            
    return None

"""

# Combine all together
final_content = new_top + middle_part + new_get_loinc_mapping + "".join(bottom_lines)

with open(path, 'w', encoding='utf-8') as f:
    f.write(final_content)
    
print("Successfully replaced top logic!")
