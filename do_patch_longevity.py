import re

file_path = 'app/api/endpoints/longevity.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

if 'from app.utils.crypto import encrypt_text, decrypt_text' not in content:
    content = content.replace('from fastapi import APIRouter', 'from fastapi import APIRouter\nfrom app.utils.crypto import encrypt_text, decrypt_text')

# Patch get_longevity_protocols
old_code = '''            if baseline_res.data:
                baseline = baseline_res.data[0]
                # Format to match the expected protocol structure
                return {
                    "patient_id": patient_id,
                    "effective_date": date,
                    "protocols": baseline.get("protocols", [])
                }
            
            return {"date": date, "protocols": []}
            
        return res.data[0]'''

new_code = '''            if baseline_res.data:
                baseline = baseline_res.data[0]
                protocols = baseline.get("protocols", [])
                for p in protocols:
                    for k in ["title", "description", "reasoning", "modification_note"]:
                        if k in p and p[k]:
                            p[k] = decrypt_text(p[k])
                
                # Format to match the expected protocol structure
                return {
                    "patient_id": patient_id,
                    "effective_date": date,
                    "protocols": protocols
                }
            
            return {"date": date, "protocols": []}
            
        data = res.data[0]
        protocols = data.get("protocols", [])
        for p in protocols:
            for k in ["title", "description", "reasoning", "modification_note"]:
                if k in p and p[k]:
                    p[k] = decrypt_text(p[k])
        data["protocols"] = protocols
        return data'''

content = content.replace(old_code, new_code)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
