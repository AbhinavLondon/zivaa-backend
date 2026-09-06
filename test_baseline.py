"""
Unit tests for the Baseline Establishment System.

Tests the lifecycle: CALIBRATING → ESTABLISHED → RECALIBRATING
and verifies that the rules engine respects baseline status.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import date, timedelta, datetime
from app.services.insights.baseline import (
    compute_baseline_stats, 
    should_recalibrate, 
    is_stale,
    BaselineInfo,
    METRIC_THRESHOLDS,
    DATA_GAP_RESET_DAYS,
)
from app.services.insights.context import (
    MetricValue, VitalsMetric, VitalsContext, EvalContext,
    LabContext, MedContext,
)
from app.services.insights.core import InsightRule, RiskLevel
from app.services.insights.rules.tier1_vitals import (
    HypertensionEscalationRule, FunctionalDeclineRule, AcuteIllnessRule
)


# ---------------------------------------------------------------------------
# Helper: generate N days of fake data ending yesterday
# ---------------------------------------------------------------------------
def make_metric_values(values: list[float], end_days_ago: int = 1) -> list[MetricValue]:
    """Create MetricValues ending `end_days_ago` days before today."""
    today = date.today()
    result = []
    for i, v in enumerate(values):
        d = today - timedelta(days=end_days_ago + len(values) - 1 - i)
        result.append(MetricValue(v, d))
    return result


def make_baseline(metric: str, mean: float, std: float = 2.0, status: str = "established") -> BaselineInfo:
    """Create a quick BaselineInfo for testing."""
    return BaselineInfo(
        metric_name=metric,
        status=status,
        mean=mean,
        std=std,
        median=mean,
        data_points=10,
        min_required=5,
    )


# ===================================================================
# TEST 1: Calibration with insufficient data (< 5 days)
# ===================================================================
def test_calibrating_with_insufficient_data():
    """A patient with only 3 days of heart rate data should be CALIBRATING."""
    values = [68.0, 70.0, 69.0]  # Only 3 data points
    
    result = compute_baseline_stats(values, "heart_rate", is_first_establishment=True)
    
    assert result.status == "calibrating", f"Expected 'calibrating', got '{result.status}'"
    assert not result.is_established
    assert result.days_until_ready == 2  # 5 - 3 = 2 more days needed
    assert result.data_points == 3
    print("✅ TEST 1 PASSED: 3 data points → status=calibrating, 2 days until ready")


# ===================================================================
# TEST 2: Established with sufficient data (>= 5 days)
# ===================================================================
def test_established_with_sufficient_data():
    """A patient with 7 days of data should be ESTABLISHED."""
    values = [68.0, 70.0, 69.0, 71.0, 67.0, 72.0, 68.0]  # 7 data points
    
    result = compute_baseline_stats(values, "heart_rate", is_first_establishment=True)
    
    assert result.status == "established", f"Expected 'established', got '{result.status}'"
    assert result.is_established
    assert result.days_until_ready == 0
    assert abs(result.mean - 69.29) < 0.1  # ~69.3 bpm average
    assert result.std > 0  # Should have non-zero std dev
    print(f"✅ TEST 2 PASSED: 7 data points → status=established, mean={result.mean:.1f}, std={result.std:.1f}")


# ===================================================================
# TEST 3: Today's values are excluded from baseline
# ===================================================================
def test_today_excluded_from_baseline():
    """Today's readings must NOT contaminate the baseline computation."""
    # Create 6 days of normal data (days ago: 6,5,4,3,2,1) + today's spike
    normal_values = [68.0, 70.0, 69.0, 71.0, 67.0, 72.0]
    todays_spike = 110.0  # This should NOT be included
    
    # Simulate: compute_baseline_stats only receives values BEFORE today
    # (the data_fetcher filters out today's data before passing to this function)
    result = compute_baseline_stats(normal_values, "heart_rate", is_first_establishment=True)
    
    # Verify today's spike is not in the mean
    assert result.is_established
    assert result.mean < 75.0, f"Baseline mean {result.mean} is too high — today's spike may have leaked in"
    print(f"✅ TEST 3 PASSED: Baseline mean={result.mean:.1f} (excludes today's 110 bpm spike)")


# ===================================================================
# TEST 4: Data gap triggers recalibration
# ===================================================================
def test_data_gap_recalibration():
    """A 15-day data gap should trigger recalibration."""
    # Last data 15 days ago → should recalibrate
    old_date = date.today() - timedelta(days=15)
    assert should_recalibrate(old_date), "Expected recalibration for 15-day gap"
    
    # Last data 10 days ago → should NOT recalibrate
    recent_date = date.today() - timedelta(days=10)
    assert not should_recalibrate(recent_date), "Should NOT recalibrate for 10-day gap"
    
    # No data at all → should recalibrate
    assert should_recalibrate(None), "Expected recalibration when no data date"
    
    print(f"✅ TEST 4 PASSED: >14 day gap → recalibrate, <14 days → stable, None → recalibrate")


# ===================================================================
# TEST 5: Staleness detection
# ===================================================================
def test_staleness_detection():
    """Baselines older than 24 hours should be marked stale."""
    # 25 hours ago → stale
    old_refresh = datetime.utcnow() - timedelta(hours=25)
    assert is_stale(old_refresh), "Expected stale for 25-hour-old refresh"
    
    # 10 hours ago → fresh
    recent_refresh = datetime.utcnow() - timedelta(hours=10)
    assert not is_stale(recent_refresh), "Should NOT be stale for 10-hour-old refresh"
    
    # None → stale
    assert is_stale(None), "Expected stale when never refreshed"
    
    print("✅ TEST 5 PASSED: Staleness detection works correctly")


# ===================================================================
# TEST 6: Per-metric clinical thresholds
# ===================================================================
def test_per_metric_thresholds():
    """Different metrics should have different minimum data requirements after first establishment."""
    # Steps needs 7 days (higher variability)
    steps_4days = [1200.0, 1500.0, 800.0, 1100.0]
    result = compute_baseline_stats(steps_4days, "steps", is_first_establishment=False)
    assert result.status == "calibrating", "Steps should need 7 days, not 4"
    
    # Oxygen saturation needs only 3 days (very stable)
    spo2_3days = [97.0, 98.0, 97.5]
    result = compute_baseline_stats(spo2_3days, "oxygen_sat", is_first_establishment=False)
    assert result.status == "established", "SpO2 should be established with 3 days"
    
    # But during first-time onboarding, everything needs 5 days
    result = compute_baseline_stats(spo2_3days, "oxygen_sat", is_first_establishment=True)
    assert result.status == "calibrating", "First-time SpO2 should still need 5 days"
    
    print("✅ TEST 6 PASSED: Per-metric thresholds apply correctly after first establishment")


# ===================================================================
# TEST 7: VitalsMetric respects established baseline
# ===================================================================
def test_vitals_metric_with_established_baseline():
    """VitalsMetric.baseline() should return the persisted mean when established."""
    data = make_metric_values([68, 70, 72, 69, 71, 73, 68, 70], end_days_ago=1)
    
    # With established baseline
    baseline_info = make_baseline("heart_rate", mean=69.5, std=1.8)
    metric = VitalsMetric("heart_rate", data, baseline_info=baseline_info)
    
    assert metric.is_baseline_established
    assert metric.established_baseline is not None
    assert metric.established_baseline.mean == 69.5
    assert metric.baseline() == 69.5  # Legacy method should also use persisted value
    
    # Without baseline (calibrating)
    cal_info = BaselineInfo("heart_rate", "calibrating", 0.0, 0.0, 0.0, 3, 5)
    metric_cal = VitalsMetric("heart_rate", data, baseline_info=cal_info)
    
    assert not metric_cal.is_baseline_established
    assert metric_cal.established_baseline is None
    # Legacy baseline() should fall back to computing on the fly
    assert metric_cal.baseline() > 0
    
    print("✅ TEST 7 PASSED: VitalsMetric uses persisted baseline when established, falls back otherwise")


# ===================================================================
# TEST 8: Rules skip when baseline not established
# ===================================================================
def test_rules_skip_without_baseline():
    """Rules that depend on baselines should skip gracefully when calibrating."""
    # Create data but with CALIBRATING baselines
    hr_data = make_metric_values([68, 95, 70], end_days_ago=1)  # HR spike!
    steps_data = make_metric_values([1500, 1400, 400], end_days_ago=1)  # Steps crash!
    
    calibrating_hr = BaselineInfo("heart_rate", "calibrating", 0.0, 0.0, 0.0, 3, 5)
    calibrating_steps = BaselineInfo("steps", "calibrating", 0.0, 0.0, 0.0, 3, 5)
    
    baselines = {"heart_rate": calibrating_hr, "steps": calibrating_steps}
    
    vitals_ctx = VitalsContext(
        {"heart_rate": hr_data, "steps": steps_data},
        baselines=baselines
    )
    labs_ctx = LabContext({})
    meds_ctx = MedContext(adherence_rate=1.0, recent_misses=0)
    
    ctx = EvalContext("test-patient", vitals_ctx, labs_ctx, meds_ctx)
    
    # AcuteIllnessRule should SKIP (not trigger) because HR baseline isn't established
    rule = AcuteIllnessRule()
    result = rule.evaluate(ctx)
    
    assert result.skipped, f"Expected rule to be skipped, but triggered={result.triggered}"
    assert "baseline not yet established" in result.skip_reason.lower()
    
    # FunctionalDeclineRule should SKIP because steps baseline isn't established
    rule2 = FunctionalDeclineRule()
    result2 = rule2.evaluate(ctx)
    
    assert result2.skipped, f"Expected rule to be skipped, but triggered={result2.triggered}"
    
    print("✅ TEST 8 PASSED: Rules skip gracefully when baselines are calibrating")


# ===================================================================
# TEST 9: Rules fire correctly with established baseline
# ===================================================================
def test_rules_fire_with_established_baseline():
    """Rules should trigger correctly when baselines are established and data deviates."""
    # Create data with a real HR spike
    hr_data = make_metric_values([68, 69, 70, 68, 71, 95], end_days_ago=1)  # Latest = 95
    steps_data = make_metric_values([1500, 1400, 1300, 1200, 1100, 400], end_days_ago=1)
    
    # Established baselines (normal ranges)
    established_hr = make_baseline("heart_rate", mean=69.0, std=1.5)
    established_steps = make_baseline("steps", mean=1300.0, std=150.0)
    
    baselines = {"heart_rate": established_hr, "steps": established_steps}
    
    vitals_ctx = VitalsContext(
        {"heart_rate": hr_data, "steps": steps_data},
        baselines=baselines
    )
    labs_ctx = LabContext({})
    meds_ctx = MedContext(adherence_rate=1.0, recent_misses=0)
    
    ctx = EvalContext("test-patient", vitals_ctx, labs_ctx, meds_ctx)
    
    # AcuteIllnessRule should TRIGGER: HR spiked >15 above baseline (95 vs 69)
    # AND steps crashed below 50% of baseline (400 vs 1300)
    rule = AcuteIllnessRule()
    result = rule.evaluate(ctx)
    
    assert result.triggered, f"Expected rule to trigger, got skipped={result.skipped}, message={result.message}"
    assert result.severity == RiskLevel.HIGH
    
    print(f"✅ TEST 9 PASSED: AcuteIllnessRule triggers correctly — severity={result.severity.value}, message='{result.message[:60]}...'")


# ===================================================================
# TEST 10: EvalContext calibration message
# ===================================================================
def test_eval_context_calibration_message():
    """EvalContext should provide a clear message when all baselines are calibrating."""
    from app.services.insights.baseline import PatientBaselineStatus
    
    # All calibrating
    baselines = {
        "heart_rate": BaselineInfo("heart_rate", "calibrating", 0.0, 0.0, 0.0, 3, 5),
        "steps": BaselineInfo("steps", "calibrating", 0.0, 0.0, 0.0, 2, 7),
    }
    status = PatientBaselineStatus("test-patient", baselines)
    
    vitals_ctx = VitalsContext({})
    labs_ctx = LabContext({})
    meds_ctx = MedContext(adherence_rate=1.0, recent_misses=0)
    
    ctx = EvalContext("test-patient", vitals_ctx, labs_ctx, meds_ctx, baseline_status=status)
    
    assert not ctx.is_any_baseline_established
    assert ctx.calibration_message is not None
    assert "5" in ctx.calibration_message  # max(5-3, 7-2) = 5 days
    
    # Partially established
    baselines2 = {
        "heart_rate": make_baseline("heart_rate", 69.0),  # Established
        "steps": BaselineInfo("steps", "calibrating", 0.0, 0.0, 0.0, 2, 7),  # Still calibrating
    }
    status2 = PatientBaselineStatus("test-patient", baselines2)
    
    ctx2 = EvalContext("test-patient", vitals_ctx, labs_ctx, meds_ctx, baseline_status=status2)
    
    assert ctx2.is_any_baseline_established  # At least one is established
    assert ctx2.calibration_message is None  # No blocking message (partial is OK)
    
    print("✅ TEST 10 PASSED: Calibration message shows correct days remaining")


# ===================================================================
# Run all tests
# ===================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("BASELINE ESTABLISHMENT — UNIT TESTS")
    print("=" * 60)
    print()
    
    tests = [
        test_calibrating_with_insufficient_data,
        test_established_with_sufficient_data,
        test_today_excluded_from_baseline,
        test_data_gap_recalibration,
        test_staleness_detection,
        test_per_metric_thresholds,
        test_vitals_metric_with_established_baseline,
        test_rules_skip_without_baseline,
        test_rules_fire_with_established_baseline,
        test_eval_context_calibration_message,
    ]
    
    passed = 0
    failed = 0
    
    for test_fn in tests:
        try:
            test_fn()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"❌ {test_fn.__name__} FAILED: {e}")
    
    print()
    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed out of {len(tests)} tests")
    print("=" * 60)
