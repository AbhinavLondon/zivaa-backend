import csv

input_csv = r"C:\Users\abhin\AppData\Local\Temp\bcdbd0e9-8b7e-4ecf-8819-0e3b8cb28d9b_Loinc_2.82.zip.d9b\LoincTableCore\LoincTableCore.csv"
output_py = r"app\services\loinc_dictionary.py"

# Read original file to keep the top part
with open(output_py, 'r', encoding='utf-8') as f:
    content = f.read()

# Find where the auto-generated part starts
split_marker = "# Auto-generated top"
if split_marker in content:
    base_content = content[:content.find(split_marker)]
else:
    base_content = content

with open(input_csv, encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    
    count = 0
    loinc_entries = []
    for row in reader:
        if row.get('STATUS') == 'ACTIVE' and row.get('CLASSTYPE') == '1':
            loinc = row.get('LOINC_NUM')
            name = row.get('LONG_COMMON_NAME', '').replace('"', "'")
            shortname = row.get('SHORTNAME', '').replace('"', "'")
            category = row.get('CLASS', '')
            component = row.get('COMPONENT', '').replace('"', "'")
            system = row.get('SYSTEM', '').replace('"', "'")
            
            synonyms = [shortname or name, name]
            if component and component not in synonyms:
                synonyms.append(component)
            if component and system:
                comp_sys = f"{component} in {system}"
                if comp_sys not in synonyms:
                    synonyms.append(comp_sys)
                    
            synonyms_str = ", ".join(f'"{s}"' for s in synonyms if s)
            
            # Escape strings just in case
            loinc_entries.append(f'    "{loinc}": {{\n        "name": "{shortname or name}",\n        "synonyms": [{synonyms_str}],\n        "category": "{category}"\n    }}')
            count += 1
            if count >= 20000:
                break

with open(output_py, 'w', encoding='utf-8') as f:
    f.write(base_content)
    f.write("# Auto-generated top 20000 common biomarkers\n")
    f.write("LOINC_DICTIONARY.update({\n")
    f.write(",\n".join(loinc_entries))
    f.write("\n})\n")

print(f"Successfully generated {count} LOINC codes.")
