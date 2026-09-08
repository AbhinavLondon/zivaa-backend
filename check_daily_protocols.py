from app.services.insights.data_fetcher import supabase
import uuid

res = supabase.table('patient_longevity_protocols').select('*').execute()
print(f"Total daily protocols rows found: {len(res.data)}")
for row in res.data:
    row_id = row['id']
    patient_id = row.get('patient_id')
    protocols = row.get('protocols', [])
    modified = False
    new_protocols = []
    for idx, p in enumerate(protocols):
        title = p.get('title') or p.get('baseline_target') or 'Daily Protocol'
        description = p.get('description') or p.get('why_it_matters') or ''
        reasoning = p.get('reasoning') or p.get('why_it_matters') or ''
        category = p.get('category') or 'General'
        pid = p.get('id') or str(uuid.uuid4())
        
        if not p.get('id') or not p.get('title'):
            modified = True
            
        new_protocols.append({
            'id': pid,
            'category': category,
            'title': title,
            'description': description,
            'reasoning': reasoning,
            'is_modified_today': bool(p.get('is_modified_today', False)),
            'modification_note': p.get('modification_note'),
            'is_new_from_coach': bool(p.get('is_new_from_coach', False))
        })
    if modified:
        supabase.table('patient_longevity_protocols').update({'protocols': new_protocols}).eq('id', row_id).execute()
        print(f"Updated daily protocols row {row_id} for patient {patient_id}")
print("Daily check complete.")
