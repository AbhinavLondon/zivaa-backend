import sys
sys.path.append('app/services')
from loinc_dictionary import get_loinc_mapping, get_consumer_category

tests = [
    'Creatinine', 'Urea', 'Uric Acid', 'AST (SGOT)', 'Alkaline Phosphatase (ALP)', 
    'Bilirubin Total', 'Albumin', 'Calcium, Total', 'Sodium', 'Cholesterol, Total', 
    'HDL Cholesterol', 'Glucose Fasting', 'Vitamin B12; Cyanocobalamin', 
    'Vitamin D, 25 Hydroxy', 'TSH', 'HbA1c', 'Hemoglobin', 'Platelet Count'
]

print(f"{'Biomarker':<30} | {'Technical Category':<20} | {'Consumer Category'}")
print("-" * 75)
for t in tests:
    mapping = get_loinc_mapping(t)
    tech_cat = mapping['category'] if mapping else 'Other'
    cons_cat = get_consumer_category(tech_cat)
    print(f"{t:<30} | {tech_cat:<20} | {cons_cat}")
