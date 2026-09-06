import sys
import os
import time

sys.path.append(r'c:\Users\abhin\Downloads\Zivaa Apps\zivaa-backend\app\services')
from loinc_dictionary import LOINC_DICTIONARY, normalize_text
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

print("Building TF-IDF corpus...")
start_time = time.time()

all_synonyms = []
synonym_to_loinc = []

for loinc, data in LOINC_DICTIONARY.items():
    for syn in data["synonyms"]:
        norm_syn = normalize_text(syn)
        all_synonyms.append(norm_syn)
        synonym_to_loinc.append(loinc)

vectorizer = TfidfVectorizer(analyzer='word', token_pattern=r'(?u)\b\w+\b') # keep all words
tfidf_matrix = vectorizer.fit_transform(all_synonyms)

print(f"Built TF-IDF matrix in {time.time() - start_time:.2f} seconds")

def test_query(q):
    norm_q = normalize_text(q)
    query_vec = vectorizer.transform([norm_q])
    similarities = cosine_similarity(query_vec, tfidf_matrix).flatten()
    best_idx = similarities.argmax()
    best_score = similarities[best_idx]
    best_loinc = synonym_to_loinc[best_idx]
    best_syn = all_synonyms[best_idx]
    print(f"Query: {q:30} -> {best_loinc} ({best_score:.3f}) [Syn: {best_syn}]")

test_query("Bilirubin Indirect in Serum")
test_query("T3, Total in Serum")
test_query("T4, Total in Serum")
