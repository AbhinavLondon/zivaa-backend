import os
import sys
import asyncio
import json
from datetime import datetime, date, timedelta

# Ensure app path is in path
sys.path.append(os.getcwd())

from app.services.insights.context import EvalContext, VitalsContext, LabContext, MedContext, MetricValue
from app.services.insights.baseline import BaselineInfo, PatientBaselineStatus
from app.services.medgemma_services import generate_medgemma_alerts, generate_medgemma_nudge

def create_mock_eval_context():
    # Today's date
    today = date.today()
    
    # 1. Mock Vitals data with 7 days history
    vitals_data = {}
    
    # Sys BP history: stable around 120, then spikes to 162 today
    vitals_data["bp_systolic"] = [
        MetricValue(118.0, today - timedelta(days=6)),
        MetricValue(122.0, today - timedelta(days=5)),
        MetricValue(120.0, today - timedelta(days=4)),
        MetricValue(121.0, today - timedelta(days=3)),
        MetricValue(123.0, today - timedelta(days=2)),
        MetricValue(125.0, today - timedelta(days=1)),
        MetricValue(162.0, today), # SPIKE
    ]
    
    # Diastolic BP history: stable around 80, then spikes to 95 today
    vitals_data["bp_diastolic"] = [
        MetricValue(78.0, today - timedelta(days=6)),
        MetricValue(82.0, today - timedelta(days=5)),
        MetricValue(80.0, today - timedelta(days=4)),
        MetricValue(81.0, today - timedelta(days=3)),
        MetricValue(79.0, today - timedelta(days=2)),
        MetricValue(81.0, today - timedelta(days=1)),
        MetricValue(95.0, today), # SPIKE
    ]
    
    # Heart Rate history: stable around 65, then spikes to 94 today
    vitals_data["resting_heart_rate"] = [
        MetricValue(63.0, today - timedelta(days=6)),
        MetricValue(67.0, today - timedelta(days=5)),
        MetricValue(65.0, today - timedelta(days=4)),
        MetricValue(64.0, today - timedelta(days=3)),
        MetricValue(66.0, today - timedelta(days=2)),
        MetricValue(68.0, today - timedelta(days=1)),
        MetricValue(94.0, today), # SPIKE
    ]
    vitals_data["heart_rate"] = vitals_data["resting_heart_rate"]
    
    # Steps history: stable around 5500, then crashes to 800 today
    vitals_data["steps"] = [
        MetricValue(5600.0, today - timedelta(days=6)),
        MetricValue(5400.0, today - timedelta(days=5)),
        MetricValue(5800.0, today - timedelta(days=4)),
        MetricValue(5500.0, today - timedelta(days=3)),
        MetricValue(5700.0, today - timedelta(days=2)),
        MetricValue(5200.0, today - timedelta(days=1)),
        MetricValue(800.0, today), # CRASH
    ]
    
    # Sleep history: stable around 7.5 hrs, then crashes to 4.5 today
    vitals_data["sleep_hours"] = [
        MetricValue(7.2, today - timedelta(days=6)),
        MetricValue(7.8, today - timedelta(days=5)),
        MetricValue(7.5, today - timedelta(days=4)),
        MetricValue(7.4, today - timedelta(days=3)),
        MetricValue(7.6, today - timedelta(days=2)),
        MetricValue(7.5, today - timedelta(days=1)),
        MetricValue(4.5, today), # CRASH
    ]
    
    # Exercise minutes: normally 20, today 0
    vitals_data["exercise_minutes"] = [
        MetricValue(20.0, today - timedelta(days=6)),
        MetricValue(25.0, today - timedelta(days=5)),
        MetricValue(20.0, today - timedelta(days=4)),
        MetricValue(15.0, today - timedelta(days=3)),
        MetricValue(30.0, today - timedelta(days=2)),
        MetricValue(20.0, today - timedelta(days=1)),
        MetricValue(0.0, today), # CRASH
    ]

    # 2. Mock Baseline Infos
    baselines = {
        "bp_systolic": BaselineInfo("bp_systolic", "established", 120.0, 5.0, 120.0, 30, 5),
        "bp_diastolic": BaselineInfo("bp_diastolic", "established", 80.0, 3.0, 80.0, 30, 5),
        "resting_heart_rate": BaselineInfo("resting_heart_rate", "established", 65.0, 4.0, 65.0, 30, 5),
        "heart_rate": BaselineInfo("heart_rate", "established", 65.0, 4.0, 65.0, 30, 5),
        "steps": BaselineInfo("steps", "established", 5500.0, 500.0, 5500.0, 30, 7),
        "sleep_hours": BaselineInfo("sleep_hours", "established", 7.5, 0.5, 7.5, 30, 7),
        "exercise_minutes": BaselineInfo("exercise_minutes", "established", 20.0, 5.0, 20.0, 30, 7),
    }
    
    vitals_ctx = VitalsContext(vitals_data, baselines)
    
    # Empty lab context
    labs_ctx = LabContext({}, {})
    
    # 3. Medication adherence: 3 missed doses (adherence rate 57%)
    meds_ctx = MedContext(0.57, 3)
    
    baseline_status = PatientBaselineStatus("mock_patient", baselines)
    
    ctx = EvalContext(
        patient_id="mock_patient",
        vitals=vitals_ctx,
        labs=labs_ctx,
        meds=meds_ctx,
        baseline_status=baseline_status,
        patient_sex="male",
        patient_age=75,
        patient_conditions=["hypertension", "type_2_diabetes"]
    )
    return ctx

async def run_test():
    print("Initializing Mock EvalContext with Multiple Overlapping Anomalies...")
    print("Anomalies introduced:")
    print("  - Blood Pressure: 162/95 mmHg (Baseline: 120/80)")
    print("  - Resting Heart Rate: 94 bpm (Baseline: 65)")
    print("  - Daily Steps: 800 steps (Baseline: 5500, immobility floor: 1000)")
    print("  - Sleep Hours: 4.5 hrs (Baseline: 7.5)")
    print("  - Med Adherence: 57% (3 missed doses)")
    print("  - Chronic Conditions: Hypertension, Type 2 Diabetes")
    print("--------------------------------------------------")
    
    ctx = create_mock_eval_context()
    
    print("\n[STEP 1] Generating MedGemma active insights / alerts...")
    alerts = await generate_medgemma_alerts(ctx)
    print(f"MedGemma Diagnostics Output ({len(alerts)} alerts):")
    print(json.dumps(alerts, indent=2))
    
    print("\n[STEP 2] Generating MedGemma caregiver nudge based on alerts...")
    nudge = await generate_medgemma_nudge(alerts, patient_name="Ranjit")
    print("MedGemma Nudge Output:")
    print(json.dumps(nudge, indent=2))

if __name__ == "__main__":
    asyncio.run(run_test())
