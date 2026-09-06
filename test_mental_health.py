"""
Unit tests for validated mental health rules — PHQ-2, PSQI Item 6, and fallbacks.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import date, timedelta
from app.services.insights.baseline import BaselineInfo
from app.services.insights.context import (
    MetricValue, VitalsMetric, VitalsContext, EvalContext,
    LabContext, MedContext,
)
from app.services.insights.core import RiskLevel

from app.services.insights.rules.tier2_mental_health import (
    DepressionWithdrawalRule,
    AnxietyAgitationRule,
    SleepDisturbanceRule,
    EmotionalWellbeingRule,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def make_values(values: list, end_days_ago: int = 1) -> list:
    today = date.today()
    return [
        MetricValue(float(v), today - timedelta(days=end_days_ago + len(values) - 1 - i))
        for i, v in enumerate(values)
    ]

def make_baseline(metric: str, mean: float, std: float = 5.0) -> BaselineInfo:
    return BaselineInfo(metric, "established", mean, std, mean, 10, 7)

def build_ctx(metrics: dict, baselines: dict) -> EvalContext:
    from app.services.insights.baseline import PatientBaselineStatus
    vitals_ctx = VitalsContext(metrics, baselines=baselines)
    labs_ctx = LabContext({})
    meds_ctx = MedContext(adherence_rate=1.0, recent_misses=0)
    baseline_status = PatientBaselineStatus("test-patient", baselines)
    return EvalContext("test-patient", vitals_ctx, labs_ctx, meds_ctx, baseline_status=baseline_status)


# ===================================================================
# DEPRESSION — PHQ-2 path
# ===================================================================
def test_depression_phq2_probable():
    """PHQ-2 ≥ 5 → HIGH (probable MDD per Kroenke 2003)"""
    rule = DepressionWithdrawalRule()
    phq2_data = make_values([5])
    ctx = build_ctx({"phq2_score": phq2_data}, {})
    result = rule.evaluate(ctx)
    assert result.triggered
    assert result.severity == RiskLevel.HIGH
    assert "PHQ-2" in result.message
    assert "Kroenke" in result.message
    assert result.evidence.get("instrument") == "PHQ-2 (validated)"
    print("[PASS] Depression PHQ-2 ≥5: HIGH, probable MDD, cites Kroenke 2003")

def test_depression_phq2_possible():
    """PHQ-2 3-4 → MEDIUM (positive screen per Kroenke 2003)"""
    rule = DepressionWithdrawalRule()
    phq2_data = make_values([3])
    ctx = build_ctx({"phq2_score": phq2_data}, {})
    result = rule.evaluate(ctx)
    assert result.triggered
    assert result.severity == RiskLevel.MEDIUM
    assert "PHQ-2" in result.message
    assert result.evidence.get("phq2_cutoff") == 3
    print("[PASS] Depression PHQ-2 3-4: MEDIUM, positive screen")

def test_depression_phq2_possible_with_activity_crash():
    """PHQ-2 = 3 + steps crashed → HIGH (escalated by supporting evidence)"""
    rule = DepressionWithdrawalRule()
    phq2_data = make_values([3])
    steps_data = make_values([5000, 4000, 1500])
    baselines = {"steps": make_baseline("steps", 5000.0, std=500.0)}
    ctx = build_ctx({"phq2_score": phq2_data, "steps": steps_data}, baselines)
    result = rule.evaluate(ctx)
    assert result.triggered
    assert result.severity == RiskLevel.HIGH  # Escalated by supporting signal
    print("[PASS] Depression PHQ-2=3 + activity crash: HIGH (escalated)")

def test_depression_phq2_negative():
    """PHQ-2 < 3 → no trigger"""
    rule = DepressionWithdrawalRule()
    phq2_data = make_values([2])
    ctx = build_ctx({"phq2_score": phq2_data}, {})
    result = rule.evaluate(ctx)
    assert not result.triggered
    print("[PASS] Depression PHQ-2 < 3: negative screen, no trigger")


# ===================================================================
# DEPRESSION — Fallback (mood_score, unvalidated)
# ===================================================================
def test_depression_fallback_high():
    """No PHQ-2, mood ≤2 + declining + steps crashed → HIGH with fallback flag"""
    rule = DepressionWithdrawalRule()
    mood_data = make_values([4, 3, 3, 2, 2, 2, 1])
    steps_data = make_values([5000, 4000, 3000, 2500, 2000, 1500, 800])
    baselines = {
        "mood_score": make_baseline("mood_score", 3.5, std=0.5),
        "steps": make_baseline("steps", 5000.0, std=500.0),
    }
    ctx = build_ctx({"mood_score": mood_data, "steps": steps_data}, baselines)
    result = rule.evaluate(ctx)
    assert result.triggered
    assert result.severity == RiskLevel.HIGH
    assert "unvalidated" in result.evidence.get("instrument", "").lower() or \
           "fallback" in result.evidence.get("instrument", "").lower()
    assert result.evidence.get("recommendation") == "administer_PHQ2"
    print("[PASS] Depression fallback: HIGH, labeled as unvalidated, recommends PHQ-2")

def test_depression_fallback_medium():
    """No PHQ-2, mood ≤2 alone → MEDIUM with recommendation"""
    rule = DepressionWithdrawalRule()
    mood_data = make_values([3, 3, 3, 2, 2, 2, 2])
    baselines = {"mood_score": make_baseline("mood_score", 3.5, std=0.5)}
    ctx = build_ctx({"mood_score": mood_data}, baselines)
    result = rule.evaluate(ctx)
    assert result.triggered
    assert result.severity == RiskLevel.MEDIUM
    assert result.evidence.get("recommendation") == "administer_PHQ2"
    print("[PASS] Depression fallback MEDIUM: recommends PHQ-2")


# ===================================================================
# SLEEP — PSQI Item 6 path
# ===================================================================
def test_sleep_psqi_very_bad():
    """PSQI Item 6 = 3 (Very Bad) → MEDIUM (Buysse 1989)"""
    rule = SleepDisturbanceRule()
    psqi_data = make_values([3])
    ctx = build_ctx({"psqi_item6": psqi_data}, {})
    result = rule.evaluate(ctx)
    assert result.triggered
    assert result.severity == RiskLevel.MEDIUM
    assert "PSQI" in result.message
    assert "Buysse" in result.message
    assert result.evidence.get("instrument") == "PSQI_Item6 (validated)"
    print("[PASS] Sleep PSQI Item 6 = 3 (Very Bad): MEDIUM, cites Buysse 1989")

def test_sleep_psqi_fairly_bad():
    """PSQI Item 6 = 2 (Fairly Bad) → LOW"""
    rule = SleepDisturbanceRule()
    psqi_data = make_values([2])
    ctx = build_ctx({"psqi_item6": psqi_data}, {})
    result = rule.evaluate(ctx)
    assert result.triggered
    assert result.severity == RiskLevel.LOW
    assert "PSQI" in result.message
    print("[PASS] Sleep PSQI Item 6 = 2 (Fairly Bad): LOW")

def test_sleep_psqi_good():
    """PSQI Item 6 = 1 (Fairly Good) → no trigger"""
    rule = SleepDisturbanceRule()
    psqi_data = make_values([1])
    ctx = build_ctx({"psqi_item6": psqi_data}, {})
    result = rule.evaluate(ctx)
    assert not result.triggered
    print("[PASS] Sleep PSQI Item 6 = 1 (Fairly Good): no trigger")


# ===================================================================
# SLEEP — Wearable sleep efficiency path (AASM ICSD-3)
# ===================================================================
def test_sleep_efficiency_below_aasm():
    """Sleep efficiency < 85% → triggers with AASM citation"""
    rule = SleepDisturbanceRule()
    # No PSQI, but has sleep_efficiency
    eff_data = make_values([82])
    ctx = build_ctx({"sleep_efficiency": eff_data}, {})
    result = rule.evaluate(ctx)
    assert result.triggered
    assert "AASM" in result.message or "85" in result.message
    assert result.evidence.get("aasm_threshold") == 85.0
    print("[PASS] Sleep efficiency < 85%: triggers with AASM ICSD-3 citation")

def test_sleep_efficiency_normal():
    """Sleep efficiency ≥ 85% → no trigger"""
    rule = SleepDisturbanceRule()
    eff_data = make_values([90])
    ctx = build_ctx({"sleep_efficiency": eff_data}, {})
    result = rule.evaluate(ctx)
    assert not result.triggered
    print("[PASS] Sleep efficiency ≥ 85%: no trigger")


# ===================================================================
# SLEEP — Fallback (sleep_quality, unvalidated)
# ===================================================================
def test_sleep_fallback():
    """No PSQI, no efficiency → falls back to sleep_quality with recommendation"""
    rule = SleepDisturbanceRule()
    sq_data = make_values([65, 60, 55, 45, 35, 30, 28])
    baselines = {"sleep_quality": make_baseline("sleep_quality", 65.0, std=5.0)}
    ctx = build_ctx({"sleep_quality": sq_data}, baselines)
    result = rule.evaluate(ctx)
    assert result.triggered
    assert "unvalidated" in result.evidence.get("instrument", "").lower() or \
           "fallback" in result.evidence.get("instrument", "").lower()
    assert "PSQI" in result.evidence.get("recommendation", "")
    print("[PASS] Sleep fallback: triggers with unvalidated label, recommends PSQI")


# ===================================================================
# WELLBEING — PHQ-2 path
# ===================================================================
def test_wellbeing_phq2_probable():
    """PHQ-2 ≥ 5 → MEDIUM (persistent low wellbeing)"""
    rule = EmotionalWellbeingRule()
    phq2_data = make_values([5])
    ctx = build_ctx({"phq2_score": phq2_data}, {})
    result = rule.evaluate(ctx)
    assert result.triggered
    assert result.severity == RiskLevel.MEDIUM
    assert "PHQ-2" in result.message
    assert result.evidence.get("instrument") == "PHQ-2 (validated)"
    print("[PASS] Wellbeing PHQ-2 ≥ 5: MEDIUM, validated instrument")

def test_wellbeing_phq2_positive():
    """PHQ-2 = 3-4 → LOW"""
    rule = EmotionalWellbeingRule()
    phq2_data = make_values([4])
    ctx = build_ctx({"phq2_score": phq2_data}, {})
    result = rule.evaluate(ctx)
    assert result.triggered
    assert result.severity == RiskLevel.LOW
    print("[PASS] Wellbeing PHQ-2 3-4: LOW")


# ===================================================================
# WELLBEING — Fallback
# ===================================================================
def test_wellbeing_fallback():
    """No PHQ-2, persistent low mood → MEDIUM with recommendation"""
    rule = EmotionalWellbeingRule()
    mood_data = make_values([4, 3, 3, 2, 2, 2, 2])
    baselines = {"mood_score": make_baseline("mood_score", 4.0, std=0.5)}
    ctx = build_ctx({"mood_score": mood_data}, baselines)
    result = rule.evaluate(ctx)
    assert result.triggered
    assert result.evidence.get("recommendation") == "administer_PHQ2"
    print("[PASS] Wellbeing fallback: recommends PHQ-2")


# ===================================================================
# ANXIETY — physiological proxy with GAD-2 recommendation
# ===================================================================
def test_anxiety_recommends_gad2():
    """Anxiety rule fires with recommendation for GAD-2"""
    rule = AnxietyAgitationRule()
    sq_data = make_values([70, 60, 50, 45, 35, 30, 28])
    hr_data = make_values([68, 70, 72, 73, 74, 75, 75])
    mood_data = make_values([4, 3, 3, 3, 2, 2, 2])
    baselines = {
        "sleep_quality": make_baseline("sleep_quality", 65.0, std=5.0),
        "heart_rate": make_baseline("heart_rate", 68.0, std=2.0),
        "mood_score": make_baseline("mood_score", 3.5, std=0.5),
    }
    ctx = build_ctx({
        "sleep_quality": sq_data, "heart_rate": hr_data, "mood_score": mood_data
    }, baselines)
    result = rule.evaluate(ctx)
    assert result.triggered
    assert result.evidence.get("recommendation") == "administer_GAD2"
    assert "Chalmers" in result.message or "GAD-2" in result.message
    print("[PASS] Anxiety: physiological proxy, recommends GAD-2, cites Chalmers 2014")


# ===================================================================
# Run all
# ===================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("VALIDATED MENTAL HEALTH RULES — UNIT TESTS")
    print("=" * 60)
    print()

    tests = [
        # Depression — PHQ-2
        test_depression_phq2_probable,
        test_depression_phq2_possible,
        test_depression_phq2_possible_with_activity_crash,
        test_depression_phq2_negative,
        # Depression — Fallback
        test_depression_fallback_high,
        test_depression_fallback_medium,
        # Sleep — PSQI Item 6
        test_sleep_psqi_very_bad,
        test_sleep_psqi_fairly_bad,
        test_sleep_psqi_good,
        # Sleep — Wearable efficiency
        test_sleep_efficiency_below_aasm,
        test_sleep_efficiency_normal,
        # Sleep — Fallback
        test_sleep_fallback,
        # Wellbeing — PHQ-2
        test_wellbeing_phq2_probable,
        test_wellbeing_phq2_positive,
        # Wellbeing — Fallback
        test_wellbeing_fallback,
        # Anxiety
        test_anxiety_recommends_gad2,
    ]

    passed = 0
    failed = 0

    for test_fn in tests:
        try:
            test_fn()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"[FAIL] {test_fn.__name__}: {e}")

    print()
    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed out of {len(tests)} tests")
    print("=" * 60)
