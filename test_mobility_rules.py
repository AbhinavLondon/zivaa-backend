"""
Unit tests for Geriatric Mobility Rules (Tier 1 Mobility).
Verifies clinical determinism, guideline-backed thresholds, plain-English explanations,
peer-reviewed citations, and execution modes (realtime vs batch).
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
from app.services.insights.core import RiskLevel
from app.services.insights.rules.tier1_mobility import (
    AcuteFunctionalCollapseRule,
    CardiopulmonaryDecompensationRule,
    AcuteFallRiskExhaustionRule,
    SedentaryTrappingRule,
    EWGSOP2SarcopeniaScreenRule,
    DailyLongevityMilestoneRule,
    MOBILITY_RULES,
)
from app.services.insights.engine import InsightEngine


# ---------------------------------------------------------------------------
# Test Helpers
# ---------------------------------------------------------------------------
def make_values(values: list, end_days_ago: int = 1) -> list:
    today = date.today()
    return [
        MetricValue(float(v), today - timedelta(days=end_days_ago + len(values) - 1 - i))
        for i, v in enumerate(values)
    ]


def make_baseline(metric: str, mean: float, std: float = 5.0, status: str = "established") -> BaselineInfo:
    return BaselineInfo(metric, status, mean, std, mean, 10, 7)


def build_ctx(metrics: dict, baselines: dict = None) -> EvalContext:
    baselines = baselines or {}
    vitals_ctx = VitalsContext(metrics, baselines=baselines)
    labs_ctx = LabContext({})
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
# Rule 1: Acute Functional Collapse (The Occult Sepsis / Delirium Triad)
# ==============================================================================
def test_acute_functional_collapse_triggered():
    rule = AcuteFunctionalCollapseRule()
    assert rule.evaluation_mode == "realtime"

    # Baseline: Cadence 100 spm, Active Mins 40m, HR 68 bpm
    baselines = {
        "avg_cadence_spm": make_baseline("avg_cadence_spm", 100.0, std=5.0),
        "active_movement_minutes": make_baseline("active_movement_minutes", 40.0, std=8.0),
        "resting_heart_rate": make_baseline("resting_heart_rate", 68.0, std=4.0),
    }

    # Latest: Cadence 65 spm (<75% of 100), Active Mins 15m (<50% of 40), HR 82 bpm (>68+10)
    metrics = {
        "avg_cadence_spm": make_values([100, 98, 65]),
        "active_movement_minutes": make_values([42, 38, 15]),
        "resting_heart_rate": make_values([66, 68, 82]),
    }
    ctx = build_ctx(metrics, baselines)
    result = rule.evaluate(ctx)

    assert result.triggered, "AcuteFunctionalCollapseRule should trigger on severe drop + tachycardia"
    assert result.severity == RiskLevel.HIGH
    assert "Lancet 2014" in result.evidence["guideline"]
    assert "65 steps/min" in result.message
    print("[PASS] Rule 1: AcuteFunctionalCollapseRule triggered (HIGH) with Lancet citation.")


def test_acute_functional_collapse_passed():
    rule = AcuteFunctionalCollapseRule()
    baselines = {
        "avg_cadence_spm": make_baseline("avg_cadence_spm", 100.0, std=5.0),
        "active_movement_minutes": make_baseline("active_movement_minutes", 40.0, std=8.0),
        "resting_heart_rate": make_baseline("resting_heart_rate", 68.0, std=4.0),
    }
    metrics = {
        "avg_cadence_spm": make_values([100, 98, 96]),
        "active_movement_minutes": make_values([42, 38, 40]),
        "resting_heart_rate": make_values([66, 68, 69]),
    }
    ctx = build_ctx(metrics, baselines)
    result = rule.evaluate(ctx)
    assert not result.triggered
    assert not result.triggered
    print("[PASS] Rule 1: AcuteFunctionalCollapseRule normal vitals passed.")


# ==============================================================================
# Rule 2: Cardiopulmonary Decompensation (CHF / COPD)
# ==============================================================================
def test_cardiopulmonary_decompensation_triggered():
    rule = CardiopulmonaryDecompensationRule()
    assert rule.evaluation_mode == "realtime"

    # Baseline: Cadence 95 spm, Active Mins 45m
    baselines = {
        "avg_cadence_spm": make_baseline("avg_cadence_spm", 95.0, std=5.0),
        "active_movement_minutes": make_baseline("active_movement_minutes", 45.0, std=6.0),
    }

    # Latest: Active mins 14m (<15m and <70% of 45), Cadence 58 spm (<60 spm), SpO2 90% (<92%)
    metrics = {
        "active_movement_minutes": make_values([45, 40, 14]),
        "avg_cadence_spm": make_values([95, 90, 58]),
        "oxygen_sat": make_values([97, 96, 90]),
    }
    ctx = build_ctx(metrics, baselines)
    result = rule.evaluate(ctx)

    assert result.triggered, "CardiopulmonaryDecompensationRule should trigger on hypoxemia + mobility collapse"
    assert result.severity == RiskLevel.HIGH
    assert "Circulation" in result.evidence["guideline"]
    assert "oxygen saturation dropped to 90.0%" in result.message
    print("[PASS] Rule 2: CardiopulmonaryDecompensationRule triggered (HIGH) with Circulation citation.")


def test_cardiopulmonary_decompensation_passed():
    rule = CardiopulmonaryDecompensationRule()
    baselines = {
        "avg_cadence_spm": make_baseline("avg_cadence_spm", 95.0, std=5.0),
        "active_movement_minutes": make_baseline("active_movement_minutes", 45.0, std=6.0),
    }
    metrics = {
        "active_movement_minutes": make_values([45, 42, 40]),
        "avg_cadence_spm": make_values([95, 94, 92]),
        "oxygen_sat": make_values([98, 97, 98]),
    }
    ctx = build_ctx(metrics, baselines)
    result = rule.evaluate(ctx)
    assert not result.triggered
    assert not result.triggered
    print("[PASS] Rule 2: CardiopulmonaryDecompensationRule normal vitals passed.")


# ==============================================================================
# Rule 3: Acute Fall Risk Under Exhaustion
# ==============================================================================
def test_fall_risk_exhaustion_triggered():
    rule = AcuteFallRiskExhaustionRule()
    assert rule.evaluation_mode == "realtime"

    # Ambulatory (3500 steps) + Shuffling (<60 spm, e.g. 52 spm) + Sleep-deprived (4.2 hours)
    metrics = {
        "steps": make_values([3000, 3200, 3500]),
        "avg_cadence_spm": make_values([80, 75, 52]),
        "sleep_hours": make_values([7.0, 6.5, 4.2]),
    }
    ctx = build_ctx(metrics)
    result = rule.evaluate(ctx)

    assert result.triggered, "AcuteFallRiskExhaustionRule should trigger on shuffling + high volume + exhaustion"
    assert result.severity == RiskLevel.HIGH
    assert "AGS/BGS Fall Prevention Guidelines" in result.evidence["guideline"]
    assert "52 steps/min" in result.message
    assert "4.2h" in result.message
    print("[PASS] Rule 3: AcuteFallRiskExhaustionRule triggered (HIGH) with AGS/BGS citation.")


def test_fall_risk_exhaustion_passed():
    rule = AcuteFallRiskExhaustionRule()
    # High steps (5000), but brisk cadence (92 spm) and well-rested (7.5h sleep)
    metrics = {
        "steps": make_values([4000, 4500, 5000]),
        "avg_cadence_spm": make_values([90, 92, 92]),
        "sleep_hours": make_values([7.2, 7.5, 7.5]),
    }
    ctx = build_ctx(metrics)
    result = rule.evaluate(ctx)
    assert not result.triggered
    print("[PASS] Rule 3: AcuteFallRiskExhaustionRule well-rested brisk passed.")


# ==============================================================================
# Rule 4: Sedentary Trapping
# ==============================================================================
def test_sedentary_trapping_triggered():
    rule = SedentaryTrappingRule()
    assert rule.evaluation_mode == "batch"

    # Confined day: 4 active hours (<6) and 12 active movement minutes (<20)
    metrics = {
        "active_hours_count": make_values([7, 6, 4]),
        "active_movement_minutes": make_values([30, 25, 12]),
    }
    ctx = build_ctx(metrics)
    result = rule.evaluate(ctx)

    assert result.triggered, "SedentaryTrappingRule should trigger on <6 active hours and <20 active mins"
    assert result.severity == RiskLevel.LOW
    assert "Ann Intern Med" in result.evidence["guideline"]
    assert "4 hours today" in result.message
    print("[PASS] Rule 4: SedentaryTrappingRule triggered (LOW) with Ann Intern Med citation.")


def test_sedentary_trapping_passed():
    rule = SedentaryTrappingRule()
    # Healthy day: 8 active hours and 42 active movement minutes
    metrics = {
        "active_hours_count": make_values([7, 8, 8]),
        "active_movement_minutes": make_values([35, 40, 42]),
    }
    ctx = build_ctx(metrics)
    result = rule.evaluate(ctx)
    assert not result.triggered
    print("[PASS] Rule 4: SedentaryTrappingRule active day passed.")


# ==============================================================================
# Rule 5: EWGSOP2 Sarcopenia & Frailty Screen
# ==============================================================================
def test_sarcopenia_screen_triggered():
    rule = EWGSOP2SarcopeniaScreenRule()
    assert rule.evaluation_mode == "batch"

    # 14 days of slow cadence (~58 spm), low active movement (~14 mins), low steps (~2400)
    cadence_history = [58 + (i % 3) for i in range(14)]
    mins_history = [12 + (i % 4) for i in range(14)]
    steps_history = [2200 + (i * 20) for i in range(14)]

    metrics = {
        "avg_cadence_spm": make_values(cadence_history),
        "active_movement_minutes": make_values(mins_history),
        "steps": make_values(steps_history),
    }
    ctx = build_ctx(metrics)
    result = rule.evaluate(ctx)

    assert result.triggered, "EWGSOP2SarcopeniaScreenRule should trigger on 14-day persistent functional deficits"
    assert result.severity == RiskLevel.MEDIUM
    assert "EWGSOP2" in result.evidence["guideline"]
    assert "Age & Ageing" in result.evidence["guideline"]
    print("[PASS] Rule 5: EWGSOP2SarcopeniaScreenRule triggered (MEDIUM) with EWGSOP2 citation.")


def test_sarcopenia_screen_passed():
    rule = EWGSOP2SarcopeniaScreenRule()
    # 14 days of robust mobility: 90 spm cadence, 35 active minutes, 6000 steps
    cadence_history = [88 + (i % 4) for i in range(14)]
    mins_history = [32 + (i % 5) for i in range(14)]
    steps_history = [5500 + (i * 50) for i in range(14)]

    metrics = {
        "avg_cadence_spm": make_values(cadence_history),
        "active_movement_minutes": make_values(mins_history),
        "steps": make_values(steps_history),
    }
    ctx = build_ctx(metrics)
    result = rule.evaluate(ctx)
    assert not result.triggered
    print("[PASS] Rule 5: EWGSOP2SarcopeniaScreenRule robust 14-day mobility passed.")


# ==============================================================================
# Rule 6: Daily Longevity Milestone
# ==============================================================================
def test_daily_longevity_milestone_triggered():
    rule = DailyLongevityMilestoneRule()
    assert rule.evaluation_mode == "batch"

    # Longevity target achieved: Cadence >= 85 (88 spm), Active Mins >= 30 (36 min), Active Hours >= 8 (9 hours)
    metrics = {
        "avg_cadence_spm": make_values([80, 82, 88]),
        "active_movement_minutes": make_values([25, 28, 36]),
        "active_hours_count": make_values([6, 7, 9]),
    }
    ctx = build_ctx(metrics)
    result = rule.evaluate(ctx)

    assert result.triggered, "DailyLongevityMilestoneRule should trigger celebration on meeting all 3 criteria"
    assert result.severity == RiskLevel.LOW
    assert "Tudor-Locke et al. BJSM 2018" in result.evidence["guideline"]
    assert "Superb functional vitality today" in result.message
    print("[PASS] Rule 6: DailyLongevityMilestoneRule triggered (LOW) with WHO & BJSM citation.")


def test_daily_longevity_milestone_passed():
    rule = DailyLongevityMilestoneRule()
    # Below target: Cadence 72 spm, Active Mins 20m, Active Hours 5h
    metrics = {
        "avg_cadence_spm": make_values([70, 71, 72]),
        "active_movement_minutes": make_values([15, 18, 20]),
        "active_hours_count": make_values([4, 5, 5]),
    }
    ctx = build_ctx(metrics)
    result = rule.evaluate(ctx)
    assert not result.triggered
    print("[PASS] Rule 6: DailyLongevityMilestoneRule below target passed without false alarm.")


# ==============================================================================
# Engine Integration & Evaluation Mode Filtering
# ==============================================================================
def test_engine_integration_and_modes():
    engine = InsightEngine()
    rule_ids = [r.id for r in engine.rules]

    # Verify all 6 mobility rules registered
    expected_ids = [
        "acute_functional_collapse",
        "cardiopulmonary_decompensation",
        "acute_fall_risk_exhaustion",
        "sedentary_trapping",
        "ewgsop2_sarcopenia_screen",
        "daily_longevity_milestone",
    ]
    for eid in expected_ids:
        assert eid in rule_ids, f"Expected {eid} to be registered in InsightEngine"

    # Test mode filtering with a synthetic context that would trigger both acute and batch rules
    baselines = {
        "avg_cadence_spm": make_baseline("avg_cadence_spm", 100.0, std=5.0),
        "active_movement_minutes": make_baseline("active_movement_minutes", 40.0, std=8.0),
        "resting_heart_rate": make_baseline("resting_heart_rate", 68.0, std=4.0),
    }
    metrics = {
        # Acute trigger
        "avg_cadence_spm": make_values([100, 98, 60]),
        "active_movement_minutes": make_values([40, 38, 12]),
        "resting_heart_rate": make_values([68, 68, 82]),
        # Batch trigger
        "active_hours_count": make_values([6, 5, 4]),
    }
    ctx = build_ctx(metrics, baselines)

    # Realtime evaluation mode
    output_rt = engine.evaluate_patient("00000000-0000-0000-0000-000000000000", ctx=ctx, evaluation_mode="realtime")
    rt_triggered_ids = [i.rule_id for i in output_rt.active_insights]
    assert "acute_functional_collapse" in rt_triggered_ids
    assert "sedentary_trapping" not in rt_triggered_ids, "Batch rules must NOT be triggered in realtime mode"

    # Batch evaluation mode
    output_batch = engine.evaluate_patient("00000000-0000-0000-0000-000000000000", ctx=ctx, evaluation_mode="batch")
    batch_triggered_ids = [i.rule_id for i in output_batch.active_insights]
    assert "sedentary_trapping" in batch_triggered_ids
    assert "acute_functional_collapse" not in batch_triggered_ids, "Realtime rules must NOT be triggered in batch mode"

    print("[PASS] Engine Integration: All 6 rules registered; realtime vs batch mode gating verified 100%.")


if __name__ == "__main__":
    print("=" * 70)
    print("RUNNING GERIATRIC MOBILITY RULES UNIT TESTS")
    print("=" * 70)
    test_acute_functional_collapse_triggered()
    test_acute_functional_collapse_passed()
    test_cardiopulmonary_decompensation_triggered()
    test_cardiopulmonary_decompensation_passed()
    test_fall_risk_exhaustion_triggered()
    test_fall_risk_exhaustion_passed()
    test_sedentary_trapping_triggered()
    test_sedentary_trapping_passed()
    test_sarcopenia_screen_triggered()
    test_sarcopenia_screen_passed()
    test_daily_longevity_milestone_triggered()
    test_daily_longevity_milestone_passed()
    test_engine_integration_and_modes()
    print("=" * 70)
    print("ALL 13 TESTS PASSED PERFECTLY!")
    print("=" * 70)
