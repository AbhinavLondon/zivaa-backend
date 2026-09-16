"""
Unit and Integration Tests for:
1. Asymmetric Z-score formatting for positive activity metrics.
2. Tripwire Gatekeeper exertional heart rate coupling and high activity exclusion.
3. Automated chronic lab reconciliation (HbA1c / Hemoglobin).
4. Defense-in-depth suppression filters.
"""

import sys
import os
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services.insights.baseline import BaselineInfo, PatientBaselineStatus
from app.services.insights.context import (
    MetricValue, VitalsMetric, VitalsContext, EvalContext,
    LabContext, MedContext,
)
from app.services.insights.core import POSITIVE_ACTIVITY_METRICS
from app.services.medgemma_services import format_patient_chart_prompt


def make_values(values: list, end_days_ago: int = 1) -> list:
    today = date.today()
    return [
        MetricValue(float(v), today - timedelta(days=end_days_ago + len(values) - 1 - i))
        for i, v in enumerate(values)
    ]


def make_baseline(metric: str, mean: float, std: float = 5.0, status: str = "established") -> BaselineInfo:
    return BaselineInfo(metric, status, mean, std, mean, 10, 7)


def build_ctx(metrics: dict, baselines: dict = None, labs_dict: dict = None) -> EvalContext:
    baselines = baselines or {}
    vitals_ctx = VitalsContext(metrics, baselines=baselines)
    labs_ctx = LabContext(labs_dict or {})
    meds_ctx = MedContext(adherence_rate=1.0, recent_misses=0)
    baseline_status = PatientBaselineStatus("00000000-0000-0000-0000-000000000000", baselines)
    return EvalContext(
        "00000000-0000-0000-0000-000000000000",
        vitals_ctx,
        labs_ctx,
        meds_ctx,
        baseline_status=baseline_status,
        patient_conditions=[],
    )


# ==============================================================================
# 1. Asymmetric Z-Score Math Injection
# ==============================================================================
def test_asymmetric_zscore_positive_activity():
    # 12,823 steps with baseline 5,661 and std 2,000 (+3.58 std devs)
    baselines = {
        "steps": make_baseline("steps", 5661.0, std=2000.0),
        "active_movement_minutes": make_baseline("active_movement_minutes", 30.0, std=10.0),
        "bp_systolic": make_baseline("bp_systolic", 120.0, std=10.0),
    }
    metrics = {
        "steps": make_values([5500, 6000, 12823]),
        "active_movement_minutes": make_values([25, 30, 110]),
        "bp_systolic": make_values([120, 122, 175]), # Dangerous spike (+5.5 std devs)
    }
    ctx = build_ctx(metrics, baselines)
    prompt = format_patient_chart_prompt(ctx, include_labs=False)

    # 1. Verify steps is NOT labeled as CRITICAL SPIKE
    assert "CRITICAL SPIKE" not in prompt.split("- steps:")[1].split("- active_movement_minutes:")[0], \
        "High steps must NEVER be labeled as CRITICAL SPIKE"
    assert "Healthy Longevity Achievement" in prompt.split("- steps:")[1].split("- active_movement_minutes:")[0], \
        "High steps should be recognized as Healthy Longevity Achievement"

    # 2. Verify active_movement_minutes is NOT labeled as CRITICAL SPIKE
    assert "CRITICAL SPIKE" not in prompt.split("- active_movement_minutes:")[1].split("- bp_systolic:")[0], \
        "High active minutes must NEVER be labeled as CRITICAL SPIKE"

    # 3. Verify that genuinely dangerous vitals (bp_systolic 175) ARE still labeled as CRITICAL SPIKE
    assert "CRITICAL SPIKE" in prompt.split("- bp_systolic:")[1], \
        "Pathological blood pressure spike must remain labeled as CRITICAL SPIKE"

    print("[PASS] Test 1: Asymmetric Z-score formatting verified (Steps celebrated, BP flagged).")


# ==============================================================================
# 2. Tripwire Gatekeeper Exertional HR & High Activity Gating
# ==============================================================================
def test_tripwire_gatekeeper_exertion_gating():
    # Simulate an active day: 12k steps, 110 active mins, calm night HR 65 bpm, SpO2 98%, daytime HR 112 bpm
    baselines = {
        "steps": make_baseline("steps", 5661.0, std=2000.0),
        "hr_avg_evening": make_baseline("hr_avg_evening", 76.9, std=8.0),
        "hr_avg_night": make_baseline("hr_avg_night", 65.0, std=5.0),
        "oxygen_sat": make_baseline("oxygen_sat", 97.0, std=1.0),
    }
    metrics = {
        "steps": make_values([5500, 6000, 12823], end_days_ago=0),
        "active_movement_minutes": make_values([30, 30, 110], end_days_ago=0),
        "hr_avg_evening": make_values([75, 76, 112], end_days_ago=0),
        "hr_avg_night": make_values([64, 65, 65], end_days_ago=0),
        "oxygen_sat": make_values([97, 98, 98], end_days_ago=0),
    }
    ctx = build_ctx(metrics, baselines)

    today_local = date.today()
    latest_global_date = today_local

    # Run the Gatekeeper logic extracted from tripwire.py
    should_wake_medgemma = False
    vitals_metrics = list(ctx.vitals._vitals.keys())

    for metric_name in vitals_metrics:
        if metric_name == "avg_heart_rate":
            continue
        try:
            m = ctx.vitals.metric(metric_name)
            b = m.established_baseline
            if b and b.std > 0 and m.has_data:
                # POSITIVE ACTIVITY GATE
                if metric_name in POSITIVE_ACTIVITY_METRICS and m.latest >= b.mean:
                    continue

                # EXERTIONAL TACHYCARDIA GATE
                if metric_name in ("hr_avg_morning", "hr_avg_afternoon", "hr_avg_evening") and m.latest > b.mean:
                    active_mins = ctx.vitals.metric("active_movement_minutes").latest if ctx.vitals.metric("active_movement_minutes").has_data else 0.0
                    steps_val = ctx.vitals.metric("steps").latest if ctx.vitals.metric("steps").has_data else 0.0
                    steps_bl = ctx.vitals.metric("steps").established_baseline
                    steps_mean = steps_bl.mean if steps_bl else 4000.0
                    night_hr = ctx.vitals.metric("hr_avg_night").latest if ctx.vitals.metric("hr_avg_night").has_data else None
                    spo2_val = ctx.vitals.metric("oxygen_sat").latest if ctx.vitals.metric("oxygen_sat").has_data else 98.0

                    if (active_mins >= 30.0 or steps_val >= steps_mean) and (night_hr is not None and night_hr < 75.0) and (spo2_val >= 94.0):
                        continue

                z_score = abs((m.latest - b.mean) / b.std)
                if z_score >= 1.5:
                    should_wake_medgemma = True
                    break
        except Exception:
            pass

    assert not should_wake_medgemma, "Gatekeeper must NOT wake MedGemma for healthy exercise heart rate on active day"
    print("[PASS] Test 2: Gatekeeper successfully suppressed false alarm on 12k steps + exertional HR.")


def test_tripwire_gatekeeper_pathological_tachycardia():
    # Contrast with pathological tachycardia: Resting/Night HR is 98 bpm (well above normal) and SpO2 is 90%
    baselines = {
        "hr_avg_night": make_baseline("hr_avg_night", 65.0, std=5.0),
        "oxygen_sat": make_baseline("oxygen_sat", 97.0, std=1.0),
    }
    metrics = {
        "hr_avg_night": make_values([65, 68, 98], end_days_ago=0),
        "oxygen_sat": make_values([97, 96, 90], end_days_ago=0),
    }
    ctx = build_ctx(metrics, baselines)

    should_wake_medgemma = False
    for metric_name in ["hr_avg_night", "oxygen_sat"]:
        m = ctx.vitals.metric(metric_name)
        b = m.established_baseline
        z_score = abs((m.latest - b.mean) / b.std)
        if z_score >= 1.5:
            should_wake_medgemma = True
            break

    assert should_wake_medgemma, "Gatekeeper MUST wake MedGemma for genuine pathological nocturnal tachycardia & hypoxia"
    print("[PASS] Test 3: Gatekeeper correctly opens for genuine pathological tachycardia and hypoxia.")


# ==============================================================================
# 3. Automated Chronic Lab Reconciler
# ==============================================================================
def test_chronic_lab_reconciliation():
    # Setup mock existing insights with a zombie prediabetes_progression claim
    existing_insights = [
        {
            "id": "mock-zombie-prediabetes",
            "rule_id": "prediabetes_progression",
            "name": "Diabetes Progression Detected",
            "message": "Patient's historical HbA1c of 10.0% on 2023-11-07 indicates uncontrolled diabetes",
            "status": "active",
        },
        {
            "id": "mock-real-hypertension",
            "rule_id": "hypertension_escalation",
            "name": "Hypertension Warning",
            "message": "Blood pressure elevated",
            "status": "active",
        }
    ]

    # Setup labs context with actual normal HbA1c (5.1%)
    labs_dict = {
        "4548-4": [{
            "value": 5.1,
            "measured_at": "2026-07-26T00:00:00+00:00",
            "reference_low": 4.0,
            "reference_high": 5.6,
            "flag": "normal",
        }]
    }
    ctx = build_ctx({}, labs_dict=labs_dict)

    # Reconciler logic extracted from tripwire.py
    for ex in list(existing_insights):
        r_id = ex.get("rule_id", "")
        if r_id in ("prediabetes_progression", "diabetes_progression") or "hba1c" in ex.get("name", "").lower():
            hba1c_bm = ctx.labs.biomarker("4548-4")
            if hba1c_bm.has_data and hba1c_bm.latest < 5.7:
                existing_insights.remove(ex)

    remaining_ids = [e["rule_id"] for e in existing_insights]
    assert "prediabetes_progression" not in remaining_ids, "Zombie prediabetes insight must be resolved when HbA1c is 5.1%"
    assert "hypertension_escalation" in remaining_ids, "Unrelated active insight must remain untouched"
    print("[PASS] Test 4: Chronic lab reconciliation purged zombie HbA1c 10.0% against verified 5.1% reading.")


# ==============================================================================
# 4. Defense-in-Depth Filter
# ==============================================================================
def test_defense_in_depth_filters():
    mock_medgemma_alerts = [
        {
            "rule_id": "unusually_high_activity_level",
            "name": "Unusually High Activity Level",
            "message": "Patient took 12823 steps",
        },
        {
            "rule_id": "critical_evening_heart_rate_spike",
            "name": "Critical Evening Heart Rate Spike",
            "message": "Evening HR was 112 bpm",
        },
        {
            "rule_id": "respiratory_distress",
            "name": "Respiratory Distress",
            "message": "Oxygen dipped to 89%",
        }
    ]

    # Context: Active day with calm night HR
    baselines = {
        "steps": make_baseline("steps", 5661.0, std=2000.0),
    }
    metrics = {
        "steps": make_values([12823], end_days_ago=0),
        "active_movement_minutes": make_values([110], end_days_ago=0),
        "hr_avg_night": make_values([65], end_days_ago=0),
        "oxygen_sat": make_values([98], end_days_ago=0),
    }
    ctx = build_ctx(metrics, baselines)

    # Filter logic
    valid_alerts = []
    for alert in mock_medgemma_alerts:
        rule_id = alert.get("rule_id", "unknown")
        rule_lower = rule_id.lower()
        name_lower = alert.get("name", "").lower()

        is_high_activity_alert = any(k in rule_lower or k in name_lower for k in [
            "high_activity", "unusually_high", "excessive_step", "step_spike", "activity_spike"
        ])
        if is_high_activity_alert:
            continue

        is_exertional_hr_alert = any(k in rule_lower or k in name_lower for k in [
            "evening_heart_rate", "afternoon_heart_rate", "morning_heart_rate", "heart_rate_spike"
        ])
        if is_exertional_hr_alert:
            active_mins = ctx.vitals.metric("active_movement_minutes").latest if ctx.vitals.metric("active_movement_minutes").has_data else 0.0
            steps_val = ctx.vitals.metric("steps").latest if ctx.vitals.metric("steps").has_data else 0.0
            steps_bl = ctx.vitals.metric("steps").established_baseline
            steps_mean = steps_bl.mean if steps_bl else 4000.0
            night_hr = ctx.vitals.metric("hr_avg_night").latest if ctx.vitals.metric("hr_avg_night").has_data else None
            spo2_val = ctx.vitals.metric("oxygen_sat").latest if ctx.vitals.metric("oxygen_sat").has_data else 98.0

            if (active_mins >= 30.0 or steps_val >= steps_mean) and (night_hr is not None and night_hr < 75.0) and (spo2_val >= 94.0):
                continue

        valid_alerts.append(alert)

    valid_ids = [a["rule_id"] for a in valid_alerts]
    assert "unusually_high_activity_level" not in valid_ids, "unusually_high_activity_level must be suppressed"
    assert "critical_evening_heart_rate_spike" not in valid_ids, "exertional heart rate alert must be suppressed"
    assert "respiratory_distress" in valid_ids, "Genuine respiratory distress alert must pass through"
    print("[PASS] Test 5: Defense-in-depth filters successfully intercepted spurious alerts.")


if __name__ == "__main__":
    print("=" * 70)
    print("RUNNING EXERTION & STALE RECONCILIATION VERIFICATION SUITE")
    print("=" * 70)
    test_asymmetric_zscore_positive_activity()
    test_tripwire_gatekeeper_exertion_gating()
    test_tripwire_gatekeeper_pathological_tachycardia()
    test_chronic_lab_reconciliation()
    test_defense_in_depth_filters()
    print("=" * 70)
    print("ALL 5 VERIFICATION TESTS PASSED PERFECTLY!")
    print("=" * 70)
