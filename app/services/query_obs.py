import sys
import os
sys.path.append(r'c:\Users\abhin\Downloads\Zivaa Apps\zivaa-backend')
from app.services.insights.data_fetcher import supabase

ids = [
    '326eb08e-e3e8-4da0-86bb-56169eaef74a',
    '0ac6ca5a-6d2b-4d77-bef9-a7c6b765d539'
]

for oid in ids:
    try:
        res = supabase.table('fhir_observations').select('*').eq('id', oid).execute()
        if res.data:
            row = res.data[0]
            name = row.get('resource', {}).get('code', {}).get('text', 'UNKNOWN')
            val = row.get('resource', {}).get('valueQuantity', {})
            unit = val.get('unit', '')
            loinc = row.get('loinc_code')
            print(f"ID: {oid} | Name: {name} | Unit: {unit} | LOINC: {loinc}")
        else:
            print(f"ID: {oid} not found in fhir_observations")
    except Exception as e:
        print(f"Error querying {oid}:", e)
