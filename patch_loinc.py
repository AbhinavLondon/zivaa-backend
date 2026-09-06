import sys

path = r'c:\Users\abhin\Downloads\Zivaa Apps\zivaa-backend\app\services\loinc_dictionary.py'

with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Normalize line endings for exact string replacement
content = content.replace('\r\n', '\n')

# Edit 1: Imports
target1 = """import difflib
import re

try:
    from rapidfuzz import fuzz, process
    RAPIDFUZZ_AVAILABLE = True
except ImportError:
    RAPIDFUZZ_AVAILABLE = False"""

replacement1 = """import re
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity"""

if target1 in content:
    content = content.replace(target1, replacement1)
    print("Edit 1 successful.")
else:
    print("Edit 1 failed: Target not found.")

# Edit 2: get_loinc_mapping
target2 = """def get_loinc_mapping(extracted_name: str) -> dict:
    \"\"\"
    Performs a strict/fuzzy match of the extracted biomarker name against the dictionary.
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
            
    # 2. Advanced Token-Set Fuzzy Match (Order Independent)
    best_match_loinc = None
    best_score = 0.0
    
    if RAPIDFUZZ_AVAILABLE:
        for loinc, data in LOINC_DICTIONARY.items():
            for syn in data["synonyms"]:
                syn_normalized = normalize_text(syn)
                
                # token_set_ratio ignores word order perfectly
                score = fuzz.token_set_ratio(normalized_query, syn_normalized)
                
                # Prioritize Tier 1 matches slightly if needed, but for now just take the best score
                if score > best_score:
                    best_score = score
                    best_match_loinc = loinc
                    
        # Cutoff threshold (85 out of 100)
        if best_score >= 85.0 and best_match_loinc:
            return {
                "loinc_code": best_match_loinc,
                "name": LOINC_DICTIONARY[best_match_loinc]["name"],
                "category": LOINC_DICTIONARY[best_match_loinc]["category"]
            }
    else:
        # Fallback to difflib if rapidfuzz isn't installed
        all_synonyms = []
        synonym_to_loinc = {}
        
        for loinc, data in LOINC_DICTIONARY.items():
            for syn in data["synonyms"]:
                syn_normalized = normalize_text(syn)
                all_synonyms.append(syn_normalized)
                synonym_to_loinc[syn_normalized] = loinc
                
        matches = difflib.get_close_matches(normalized_query, all_synonyms, n=1, cutoff=0.85)
        
        if matches:
            best_match = matches[0]
            loinc = synonym_to_loinc[best_match]
            return {
                "loinc_code": loinc,
                "name": LOINC_DICTIONARY[loinc]["name"],
                "category": LOINC_DICTIONARY[loinc]["category"]
            }
            
    return None"""

replacement2 = """def get_loinc_mapping(extracted_name: str) -> dict:
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
            
    return None"""

if target2 in content:
    content = content.replace(target2, replacement2)
    print("Edit 2 successful.")
else:
    print("Edit 2 failed: Target not found.")
    
# Edit 3 was already successful in the previous run, we don't need to re-run it

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print("File successfully saved.")
