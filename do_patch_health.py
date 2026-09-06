import re

file_path = 'app/api/endpoints/health.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

if 'from app.utils.crypto import encrypt_text, decrypt_text' not in content:
    content = content.replace('from fastapi import APIRouter', 'from fastapi import APIRouter\nfrom app.utils.crypto import encrypt_text, decrypt_text')

# Patch get_longevity_plan
old_code = '''        symptoms = symp_res.data or []
        logs = logs_res.data or []
        for s in symptoms:
            s['logs'] = [l for l in logs if l['symptom_id'] == s['id']]
        
        return {
            'preferences': prefs_res.data or [],
            'symptoms': symptoms,
            'actions': act_res.data or [],
            'medications': meds_res.data or []
        }'''

new_code = '''        symptoms = symp_res.data or []
        for s in symptoms:
            if 'name' in s:
                s['name'] = decrypt_text(s['name'])
                
        logs = logs_res.data or []
        for s in symptoms:
            s['logs'] = [l for l in logs if l['symptom_id'] == s['id']]
            
        medications = meds_res.data or []
        for m in medications:
            if 'name' in m:
                m['name'] = decrypt_text(m['name'])
            if 'dose' in m:
                m['dose'] = decrypt_text(m['dose'])
        
        return {
            'preferences': prefs_res.data or [],
            'symptoms': symptoms,
            'actions': act_res.data or [],
            'medications': medications
        }'''
        
content = content.replace(old_code, new_code)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
