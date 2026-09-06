import re

with open('app/api/endpoints/health.py', 'r') as f:
    content = f.read()

replacement = '''        prefs_res = supabase.table('patient_preferences').select('*').eq('patient_id', patient_id).execute()
        symp_res = supabase.table('patient_symptoms').select('*').eq('patient_id', patient_id).execute()
        logs_res = supabase.table('symptom_logs').select('id, symptom_id, severity, status, note, created_at').eq('patient_id', patient_id).order('created_at', desc=True).execute()
        act_res = supabase.table('care_plan_actions').select('*').eq('patient_id', patient_id).execute()
        meds_res = supabase.table('patient_medications').select('*').eq('patient_id', patient_id).execute()
        
        symptoms = symp_res.data or []
        logs = logs_res.data or []
        for s in symptoms:
            s['logs'] = [l for l in logs if l['symptom_id'] == s['id']]
        
        return {
            'preferences': prefs_res.data or [],
            'symptoms': symptoms,
            'actions': act_res.data or [],
            'medications': meds_res.data or []
        }'''

pattern = r"        prefs_res = supabase\.table\('patient_preferences'\)\.select\('\*'\)\.eq\('patient_id', patient_id\)\.execute\(\).*?medications': meds_res\.data or \[\]\n        \}"
new_content = re.sub(pattern, replacement, content, flags=re.DOTALL)

with open('app/api/endpoints/health.py', 'w') as f:
    f.write(new_content)
