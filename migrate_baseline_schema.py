from app.services.insights.data_fetcher import supabase
import uuid

res = supabase.table('patient_longevity_baselines').select('*').execute()
print(f"Total baselines found: {len(res.data)}")
updated_count = 0
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
        
        if 'baseline_target' in p or 'why_it_matters' in p or not p.get('id') or not p.get('title'):
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
        supabase.table('patient_longevity_baselines').update({'protocols': new_protocols}).eq('id', row_id).execute()
        updated_count += 1
        print(f"Updated baseline row {row_id} for patient {patient_id}")

print(f"Done. Updated {updated_count} rows.")
