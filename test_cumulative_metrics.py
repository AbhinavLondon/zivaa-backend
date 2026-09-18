"""
Unit tests verifying root-cause protection for cumulative metrics on in-progress days.
"""

from datetime import date, timedelta
from app.services.insights.core import CUMULATIVE_METRICS, RiskLevel
from app.services.insights.context import MetricValue, VitalsMetric, VitalsContext, LabContext, MedContext, EvalContext
from app.services.insights.baseline import BaselineInfo, PatientBaselineStatus
from app.services.insights.rules.tier2_sensors import WearableHeartFailureRule, FeverInfectionRule
from app.services.insights.rules.tier2_mental_health import DepressionWithdrawalRule
from app.services.insights.rules.tier3_labs import PreDiabetesProgressionRule
from app.services.insights.rules.tier1_mobility import AcuteFunctionalCollapseRule
from app.services.insights.rules.tier1_vitals import FunctionalDeclineRule


def build_test_ctx(metrics_dict: dict, baselines_dict: dict = None, patient_conditions: list = None) -> EvalContext:
    baselines_dict = baselines_dict or {}
    vitals_ctx = VitalsContext(metrics_dict, baselines=baselines_dict)
    labs_ctx = LabContext({})
    meds_ctx = MedContext(adherence_rate=1.0, recent_misses=0)
    baseline_status = PatientBaselineStatus("test-patient", baselines_dict)
    return EvalContext(
        patient_id="test-patient",
        vitals=vitals_ctx,
        labs=labs_ctx,
        meds=meds_ctx,
        baseline_status=baseline_status,
        patient_conditions=patient_conditions or []
    )


def test_vitals_metric_cumulative_vs_non_cumulative():
    today = date.today()
    
    # 1. Cumulative Metric: steps
    steps_data = [
        MetricValue(6000.0, today - timedelta(days=3)),
        MetricValue(5800.0, today - timedelta(days=2)),
        MetricValue(6200.0, today - timedelta(days=1)),
        MetricValue(27.0, today) # Early morning partial data
    ]
    steps_metric = VitalsMetric("steps", steps_data)
    
    # Real-time latest should report current partial count
    assert steps_metric.latest == 27.0, f"Expected 27.0, got {steps_metric.latest}"
    # Completed-day latest must report yesterday's full total
    assert steps_metric.latest_completed == 6200.0, f"Expected 6200.0, got {steps_metric.latest_completed}"
    
    # Trend over 3 days compares completed days (today-3 to today-1: 6000 to 6200 = +3.3%), NOT comparing to 27!
    trend_3d = steps_metric.trend(days=3)
    assert trend_3d.start_value == 6000.0, f"Expected 6000.0 start, got {trend_3d.start_value}"
    assert trend_3d.end_value == 6200.0, f"Expected 6200.0 end, got {trend_3d.end_value}"
    assert trend_3d.percent_change > 0, f"Expected positive trend, got {trend_3d.percent_change}"

    
    # Rolling average must average completed days [5800, 6200] -> 6000.0, NOT diluted by 27!
    avg_3d = steps_metric.rolling_average(days=3)
    assert avg_3d == 6000.0, f"Expected 6000.0 rolling average, got {avg_3d}"
    print("[PASS] VitalsMetric cumulative gating for 'steps' verified.")

    # 2. Non-Cumulative Metric: avg_heart_rate
    hr_data = [
        MetricValue(70.0, today - timedelta(days=3)),
        MetricValue(72.0, today - timedelta(days=2)),
        MetricValue(71.0, today - timedelta(days=1)),
        MetricValue(95.0, today) # Real-time current heart rate
    ]
    hr_metric = VitalsMetric("avg_heart_rate", hr_data)
    
    # Non-cumulative metric incorporates current day
    assert hr_metric.latest == 95.0
    hr_trend = hr_metric.trend(days=3)
    assert hr_trend.end_value == 95.0, f"Expected non-cumulative metric to include today (95.0), got {hr_trend.end_value}"
    print("[PASS] VitalsMetric non-cumulative real-time inclusion verified.")


def test_wearable_heart_failure_rule_with_morning_steps():
    today = date.today()
    rule = WearableHeartFailureRule()
    
    # Scenario matching Shyam on Sept 17:
    # Historical steps ~5800, morning steps = 27
    # Historical RHR 51 bpm -> climbing to 58 bpm
    steps_data = [
        MetricValue(5800.0, today - timedelta(days=3)),
        MetricValue(5850.0, today - timedelta(days=2)),
        MetricValue(5858.0, today - timedelta(days=1)),
        MetricValue(27.0, today)
    ]
    rhr_data = [
        MetricValue(51.0, today - timedelta(days=3)),
        MetricValue(54.0, today - timedelta(days=2)),
        MetricValue(58.3, today - timedelta(days=1)),
        MetricValue(58.3, today)
    ]
    
    ctx = build_test_ctx({"steps": steps_data, "resting_heart_rate": rhr_data})
    result = rule.evaluate(ctx)
    
    # Must NOT trigger because completed steps (5850 -> 5858) did NOT drop >= 15%
    assert not result.triggered, f"WearableHeartFailureRule falsely triggered on partial morning steps! Message: {result.message}"
    print("[PASS] WearableHeartFailureRule safely passes on morning partial steps.")


def test_fever_infection_rule_with_morning_steps():
    today = date.today()
    rule = FeverInfectionRule()
    
    # Patient has fever (38.5C) and HR elevation, but normal historical steps
    steps_data = [
        MetricValue(6000.0, today - timedelta(days=2)),
        MetricValue(6200.0, today - timedelta(days=1)),
        MetricValue(15.0, today) # Morning partial steps
    ]
    bl_steps = BaselineInfo("steps", "established", 6000.0, 500.0, 6000.0, 30, 14)
    bl_hr = BaselineInfo("avg_heart_rate", "established", 70.0, 5.0, 70.0, 30, 14)
    
    ctx = build_test_ctx(
        {
            "steps": steps_data,
            "body_temp": [MetricValue(38.5, today)],
            "avg_heart_rate": [MetricValue(100.0, today)]
        },
        baselines_dict={"steps": bl_steps, "avg_heart_rate": bl_hr}
    )
    result = rule.evaluate(ctx)
    
    # steps_low should be False because latest_completed was 6200.0 (not a drop)
    assert result.evidence.get("steps_low") == False, f"steps_low should be False, got {result.evidence.get('steps_low')}"
    print("[PASS] FeverInfectionRule correctly evaluates completed steps.")


def test_depression_withdrawal_rule_with_morning_steps():
    today = date.today()
    rule = DepressionWithdrawalRule()
    
    # Positive PHQ-2 screen (3/6), morning steps 30
    steps_data = [
        MetricValue(5000.0, today - timedelta(days=2)),
        MetricValue(5200.0, today - timedelta(days=1)),
        MetricValue(30.0, today)
    ]
    bl_steps = BaselineInfo("steps", "established", 5000.0, 500.0, 5000.0, 30, 14)
    
    ctx = build_test_ctx(
        {
            "steps": steps_data,
            "phq2_score": [MetricValue(3.0, today)]
        },
        baselines_dict={"steps": bl_steps}
    )
    result = rule.evaluate(ctx)
    
    # steps_crashed should be False because completed steps (5200) >= baseline (5000)
    assert result.evidence.get("steps_crashed") == False, f"steps_crashed should be False, got {result.evidence.get('steps_crashed')}"
    print("[PASS] DepressionWithdrawalRule correctly evaluates completed steps.")


def test_prediabetes_progression_rule_with_morning_steps():
    today = date.today()
    rule = PreDiabetesProgressionRule()
    
    steps_data = [
        MetricValue(7000.0, today - timedelta(days=2)),
        MetricValue(7200.0, today - timedelta(days=1)),
        MetricValue(45.0, today)
    ]
    bl_steps = BaselineInfo("steps", "established", 7000.0, 600.0, 7000.0, 30, 14)
    
    ctx = build_test_ctx(
        {
            "steps": steps_data,
            "blood_glucose": [MetricValue(110.0, today)]
        },
        baselines_dict={"steps": bl_steps}
    )
    ctx.labs._labs = {
        "4548-4": [{"value": "6.0", "measured_at": today.isoformat(), "reference_low": 4.0, "reference_high": 5.6}]
    }
    result = rule.evaluate(ctx)
    
    assert result.evidence.get("steps_declining") == False, f"steps_declining should be False, got {result.evidence.get('steps_declining')}"
    print("[PASS] PreDiabetesProgressionRule correctly evaluates completed steps.")


def test_acute_functional_collapse_with_morning_minutes():
    today = date.today()
    rule = AcuteFunctionalCollapseRule()
    
    # Normal cadence, yesterday had 45 active mins, today currently has 5 mins at 9 AM
    mins_data = [
        MetricValue(50.0, today - timedelta(days=2)),
        MetricValue(45.0, today - timedelta(days=1)),
        MetricValue(5.0, today) # In-progress morning
    ]
    cadence_data = [
        MetricValue(80.0, today - timedelta(days=1)),
        MetricValue(78.0, today)
    ]
    bl_mins = BaselineInfo("active_movement_minutes", "established", 45.0, 10.0, 45.0, 30, 14)
    bl_cadence = BaselineInfo("avg_cadence_spm", "established", 80.0, 5.0, 80.0, 30, 14)
    
    ctx = build_test_ctx(
        {
            "active_movement_minutes": mins_data,
            "avg_cadence_spm": cadence_data,
            "active_hours_count": [MetricValue(8.0, today - timedelta(days=1)), MetricValue(1.0, today)]
        },
        baselines_dict={"active_movement_minutes": bl_mins, "avg_cadence_spm": bl_cadence}
    )
    result = rule.evaluate(ctx)
    
    # Must NOT trigger collapse because completed minutes (45) was normal
    assert not result.triggered, f"AcuteFunctionalCollapseRule triggered on morning active minutes! Message: {result.message}"
    print("[PASS] AcuteFunctionalCollapseRule safely passes on morning active minutes.")


if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("RUNNING CUMULATIVE METRICS IN-PROGRESS UNIT TESTS")
    print("=" * 70)
    test_vitals_metric_cumulative_vs_non_cumulative()
    test_wearable_heart_failure_rule_with_morning_steps()
    test_fever_infection_rule_with_morning_steps()
    test_depression_withdrawal_rule_with_morning_steps()
    test_prediabetes_progression_rule_with_morning_steps()
    test_acute_functional_collapse_with_morning_minutes()
    print("=" * 70)
    print("ALL CUMULATIVE METRIC IN-PROGRESS UNIT TESTS PASSED!")
    print("=" * 70 + "\n")
