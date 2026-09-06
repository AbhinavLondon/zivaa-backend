import asyncio, os, json
from dotenv import load_dotenv
load_dotenv('C:/Users/abhin/Downloads/Zivaa Apps/zivaa-backend/.env')
from app.api.endpoints.fhir import process_fhir_bundle_internal

async def run():
    with open('debug.json', 'r') as f:
        flat_data = json.load(f)
    
    bundle = {
        'resourceType': 'Bundle',
        'type': 'collection',
        'entry': []
    }
    
    report_resource = {
        'resourceType': 'DiagnosticReport',
        'status': 'final',
        'performer': [{'display': flat_data.get('performer', 'Unknown')}],
        'presentedForm': [{'title': flat_data.get('report_summary', 'Lab Report')}]
    }
    if flat_data.get('collection_date'):
        report_resource['effectiveDateTime'] = flat_data.get('collection_date')
    bundle['entry'].append({'resource': report_resource})
    
    for biomarker in flat_data.get('biomarkers', []):
        obs_resource = {
            'resourceType': 'Observation',
            'status': 'final',
            'code': {'text': biomarker.get('test_name'), 'coding': []},
            'presentedForm': [{'title': biomarker.get('explanation', '')}]
        }
        loinc = biomarker.get('loinc_code')
        if loinc:
            obs_resource['code']['coding'].append({'system': 'http://loinc.org', 'code': loinc})
        
        num_val = biomarker.get('numeric_value')
        if num_val is not None:
            obs_resource['valueQuantity'] = {'value': num_val, 'unit': biomarker.get('unit'), 'system': 'http://unitsofmeasure.org'}
            
        qual_val = biomarker.get('qualitative_value')
        # Simulate LLM returning literal "null" string
        if qual_val and qual_val != 'null':
            obs_resource['valueString'] = qual_val
            
        ref_low = biomarker.get('reference_low')
        if ref_low is not None and ref_low <= -99990:
            ref_low = None
        ref_high = biomarker.get('reference_high')
        if ref_high is not None and ref_high <= -99990:
            ref_high = None
            
        if ref_low is not None or ref_high is not None:
            ref_range = {}
            if ref_low is not None: ref_range['low'] = {'value': ref_low}
            if ref_high is not None: ref_range['high'] = {'value': ref_high}
            obs_resource['referenceRange'] = [ref_range]
            
        bundle['entry'].append({'resource': obs_resource})

    print(json.dumps(bundle, indent=2))
    print('Calling process_fhir_bundle_internal...')
    process_fhir_bundle_internal('0c445588-b36c-478f-9be3-2addfc77dc1c', bundle)
    print('Done.')

asyncio.run(run())
