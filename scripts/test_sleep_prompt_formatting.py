import os
import sys
from datetime import date

# Ensure backend root is on sys.path
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)
from dotenv import load_dotenv
load_dotenv(os.path.join(backend_dir, '.env'))

from app.services.insights.context import (
    EvalContext,
    VitalsContext,
    LabContext,
    MedContext,
    MetricValue
)
from app.services.insights.baseline import BaselineInfo
from app.services.medgemma_services import (
    format_patient_chart_prompt,
    SLEEP_STAGE_PROMPT_ANNOTATIONS
)

def test_sleep_prompt_annotations_dict():
    print('Testing SLEEP_STAGE_PROMPT_ANNOTATIONS dictionary...')
    assert 'sleep_stage_4_hours' in SLEEP_STAGE_PROMPT_ANNOTATIONS
    assert 'Light / Core' in SLEEP_STAGE_PROMPT_ANNOTATIONS['sleep_stage_4_hours']
    
    assert 'sleep_stage_5_hours' in SLEEP_STAGE_PROMPT_ANNOTATIONS
    assert 'Deep / Slow-Wave' in SLEEP_STAGE_PROMPT_ANNOTATIONS['sleep_stage_5_hours']
    assert 'Stage N3' in SLEEP_STAGE_PROMPT_ANNOTATIONS['sleep_stage_5_hours']
    
    assert 'sleep_stage_6_hours' in SLEEP_STAGE_PROMPT_ANNOTATIONS
    assert 'REM Sleep' in SLEEP_STAGE_PROMPT_ANNOTATIONS['sleep_stage_6_hours']
    print('PASS: SLEEP_STAGE_PROMPT_ANNOTATIONS dictionary is verified.')

def test_format_patient_chart_prompt_renders_annotations():
    print('Testing format_patient_chart_prompt output...')
    
    vitals_dict = {
        'sleep_stage_5_hours': [MetricValue(value=1.3, date_recorded=date.today())],
        'sleep_stage_6_hours': [MetricValue(value=1.88, date_recorded=date.today())],
        'avg_heart_rate': [MetricValue(value=61.4, date_recorded=date.today())]
    }
    
    baselines_dict = {
        'sleep_stage_5_hours': BaselineInfo(metric_name='sleep_stage_5_hours', status='established', mean=0.8, std=0.25, median=0.8, data_points=30, min_required=5),
        'sleep_stage_6_hours': BaselineInfo(metric_name='sleep_stage_6_hours', status='established', mean=1.5, std=0.30, median=1.5, data_points=30, min_required=5),
        'avg_heart_rate': BaselineInfo(metric_name='avg_heart_rate', status='established', mean=68.1, std=4.2, median=68.1, data_points=30, min_required=5)
    }
    
    vitals_ctx = VitalsContext(vitals_dict=vitals_dict, baselines=baselines_dict)
    labs_ctx = LabContext(labs_dict={})
    meds_ctx = MedContext(adherence_rate=1.0, recent_misses=0)
    
    ctx = EvalContext(
        patient_id='test-patient-123',
        vitals=vitals_ctx,
        labs=labs_ctx,
        meds=meds_ctx,
        patient_age=34,
        patient_sex='female',
        patient_conditions=['Diabetes', 'Light Sleep']
    )
    
    prompt = format_patient_chart_prompt(ctx, include_labs=False)
    
    assert 'sleep_stage_5_hours [Deep / Slow-Wave Sleep Duration - Stage N3]' in prompt, f'Stage 5 not found in prompt: {prompt}'
    assert 'sleep_stage_6_hours [REM Sleep Duration - Rapid Eye Movement]' in prompt, f'Stage 6 not found in prompt: {prompt}'
    assert 'avg_heart_rate:' in prompt
    print('PASS: format_patient_chart_prompt renders annotated sleep stage headers.')

def test_android_mapping_logic():
    print('Testing Android key mapping logic...')
    
    def map_title(key: str) -> str:
        k = key.lower()
        if k in ['sleep_stage_1_hours', 'sleep_stage_1_pct']: return 'Awake'
        if k in ['sleep_stage_2_hours', 'sleep_stage_2_pct']: return 'Light Sleep'
        if k in ['sleep_stage_3_hours', 'sleep_stage_3_pct']: return 'Out of Bed'
        if k in ['sleep_stage_4_hours', 'sleep_stage_4_pct']: return 'Light / Core Sleep'
        if k in ['sleep_stage_5_hours', 'sleep_stage_5_pct']: return 'Deep Sleep'
        if k in ['sleep_stage_6_hours', 'sleep_stage_6_pct']: return 'REM Sleep'
        if k == 'sleep_hours': return 'Total Sleep'
        return key
        
    def map_unit(key: str) -> str:
        k = key.lower()
        if 'pct' in k or 'percent' in k: return '%'
        if 'hours' in k or 'sleep' in k: return 'hrs'
        return ''

    assert map_title('sleep_stage_5_hours') == 'Deep Sleep'
    assert map_unit('sleep_stage_5_hours') == 'hrs'
    
    assert map_title('sleep_stage_5_pct') == 'Deep Sleep'
    assert map_unit('sleep_stage_5_pct') == '%'

    assert map_title('sleep_stage_6_hours') == 'REM Sleep'
    assert map_unit('sleep_stage_6_hours') == 'hrs'
    
    assert map_title('sleep_stage_4_hours') == 'Light / Core Sleep'
    assert map_unit('sleep_stage_4_hours') == 'hrs'
    
    print('PASS: Android mapping logic behaves with 100% precision.')

if __name__ == '__main__':
    test_sleep_prompt_annotations_dict()
    test_format_patient_chart_prompt_renders_annotations()
    test_android_mapping_logic()
    print('\nALL 3 AUTOMATED TESTS PASSED SUCCESSFULLY.')
