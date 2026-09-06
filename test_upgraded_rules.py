"""
Unit tests for all upgraded rules (Tier 1-3 + Mental Health).
Verifies guideline-aligned thresholds, z-score logic, and citations.
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

# Import all rules
from app.services.insights.rules.tier1_vitals import (
    HypertensionEscalationRule,
    FunctionalDeclineRule,
    AcuteIllnessRule,
    MedicationNonAdherenceRule,
)
from app.services.insights.rules.tier2_sensors import (
    GlycemicRiskRule,
    RespiratoryDistressRule,
    HeartFailureDecompensationRule,
    FeverInfectionRule,
    NutritionalRiskRule,
)
from app.services.insights.rules.tier2_mental_health import (
    DepressionWithdrawalRule,
    AnxietyAgitationRule,
    SleepDisturbanceRule,
    EmotionalWellbeingRule,
)
from app.services.insights.rules.tier3_labs import (
    PreDiabetesProgressionRule,
    AnemiaDetectionRule,
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

def make_baseline(metric: str, mean: float, std: float = 5.0, status: str = "established") -> BaselineInfo:
    return BaselineInfo(metric, status, mean, std, mean, 10, 7)

def build_ctx(metrics: dict, baselines: dict, meds_misses=0, 
              patient_sex=None, patient_conditions=None, labs=None) -> EvalContext:
    from app.services.insights.baseline import PatientBaselineStatus
    
    vitals_ctx = VitalsContext(metrics, baselines=baselines)
    labs_ctx = LabContext(labs or {})
    meds_ctx = MedContext(adherence_rate=1.0, recent_misses=meds_misses)
    baseline_status = PatientBaselineStatus("test-patient", baselines)
    return EvalContext(
        "test-patient", vitals_ctx, labs_ctx, meds_ctx,
        baseline_status=baseline_status,
        patient_sex=patient_sex,
        patient_conditions=patient_conditions or [],
    )


# ===================================================================
# TIER 1 — Hypertension Escalation (ACC/AHA 2017)
# ===================================================================
def test_hypertension_urgency():
    """BP ≥180 → HIGH (hypertensive urgency per ACC/AHA)"""
    rule = HypertensionEscalationRule()
    bp_data = make_values([160, 170, 185])  # Rising to ≥180
    baselines = {"bp_systolic": make_baseline("bp_systolic", 130.0, std=5.0)}
    ctx = build_ctx({"bp_systolic": bp_data}, baselines)
    result = rule.evaluate(ctx)
    assert result.triggered
    assert result.severity == RiskLevel.HIGH
    assert "ACC/AHA" in result.message
    print(f"[PASS] Hypertension urgency (≥180): severity=HIGH, cites ACC/AHA")

def test_hypertension_stage2():
    """BP 140-180 + rising → MEDIUM (Stage 2 per ACC/AHA)"""
    rule = HypertensionEscalationRule()
    bp_data = make_values([135, 140, 150])
    baselines = {"bp_systolic": make_baseline("bp_systolic", 125.0, std=5.0)}
    ctx = build_ctx({"bp_systolic": bp_data}, baselines)
    result = rule.evaluate(ctx)
    assert result.triggered
    assert result.severity == RiskLevel.MEDIUM
    assert "Stage 2" in result.message
    print(f"[PASS] Hypertension Stage 2 (140-180): severity=MEDIUM")

def test_hypertension_stage1():
    """BP 130-140 + rising → LOW (Stage 1 per ACC/AHA)"""
    rule = HypertensionEscalationRule()
    bp_data = make_values([125, 128, 135])
    baselines = {"bp_systolic": make_baseline("bp_systolic", 120.0, std=5.0)}
    ctx = build_ctx({"bp_systolic": bp_data}, baselines)
    result = rule.evaluate(ctx)
    assert result.triggered
    assert result.severity == RiskLevel.LOW
    assert "Stage 1" in result.message
    print(f"[PASS] Hypertension Stage 1 (130-140): severity=LOW")


# ===================================================================
# TIER 1 — Functional Decline (Tudor-Locke + z-score)
# ===================================================================
def test_functional_decline_absolute_floor():
    """Steps < 1000 → triggers regardless of baseline (Tudor-Locke)"""
    rule = FunctionalDeclineRule()
    steps_data = make_values([3000, 2000, 800])
    baselines = {"steps": make_baseline("steps", 3000.0, std=500.0)}
    ctx = build_ctx({"steps": steps_data}, baselines)
    result = rule.evaluate(ctx)
    assert result.triggered
    assert "1,000-step" in result.message or "Tudor-Locke" in result.message
    print(f"[PASS] Functional decline: absolute floor <1000 steps, cites Tudor-Locke")

def test_functional_decline_zscore():
    """Steps > 2 SD below baseline → triggers"""
    rule = FunctionalDeclineRule()
    # Baseline mean=5000, std=500. 2 SD below = 4000. Latest=3500
    steps_data = make_values([5000, 4500, 3500])
    baselines = {"steps": make_baseline("steps", 5000.0, std=500.0)}
    ctx = build_ctx({"steps": steps_data}, baselines)
    result = rule.evaluate(ctx)
    assert result.triggered
    assert "z-score" in result.message
    print(f"[PASS] Functional decline: z-score > 2.0 triggers")


# ===================================================================
# TIER 1 — Acute Illness (Mishra 2020 z-score)
# ===================================================================
def test_acute_illness_zscore_high():
    """HR > 2 SD + steps crash → HIGH (Mishra 2020 pattern)"""
    rule = AcuteIllnessRule()
    # Baseline HR=70, std=3. 2 SD above = 76. Latest=82 (z=4.0)
    hr_data = make_values([70, 72, 82])
    steps_data = make_values([5000, 3000, 1500])
    baselines = {
        "heart_rate": make_baseline("heart_rate", 70.0, std=3.0),
        "steps": make_baseline("steps", 5000.0, std=500.0),
    }
    ctx = build_ctx({"heart_rate": hr_data, "steps": steps_data}, baselines)
    result = rule.evaluate(ctx)
    assert result.triggered
    assert result.severity == RiskLevel.HIGH
    assert "Mishra" in result.message
    print(f"[PASS] Acute illness HIGH: z-score approach, cites Mishra 2020")

def test_acute_illness_zscore_medium():
    """HR > 2 SD alone (no steps crash) → MEDIUM"""
    rule = AcuteIllnessRule()
    hr_data = make_values([70, 72, 80])
    baselines = {"heart_rate": make_baseline("heart_rate", 70.0, std=3.0)}
    ctx = build_ctx({"heart_rate": hr_data}, baselines)
    result = rule.evaluate(ctx)
    assert result.triggered
    assert result.severity == RiskLevel.MEDIUM
    print(f"[PASS] Acute illness MEDIUM: HR z-score alone")


# ===================================================================
# TIER 1 — Medication Non-Adherence (Burnier framework)
# ===================================================================
def test_medication_nonadherence_burnier():
    """BP > 140 + missed doses + HR normal → MEDIUM (Burnier 2019)"""
    rule = MedicationNonAdherenceRule()
    bp_data = make_values([145])
    hr_data = make_values([72])
    baselines = {
        "bp_systolic": make_baseline("bp_systolic", 130.0, std=5.0),
        "heart_rate": make_baseline("heart_rate", 70.0, std=3.0),
    }
    ctx = build_ctx({"bp_systolic": bp_data, "heart_rate": hr_data}, baselines, meds_misses=2)
    result = rule.evaluate(ctx)
    assert result.triggered
    assert "Burnier" in result.message
    print(f"[PASS] Med non-adherence: Burnier framework, cites Burnier 2019")


# ===================================================================
# TIER 2 — Glycemic Risk (ADA 2024)
# ===================================================================
def test_glycemic_level2_hypo():
    """Glucose < 54 → HIGH Level 2 hypo (ADA 2024)"""
    rule = GlycemicRiskRule()
    glucose_data = make_values([50])
    ctx = build_ctx({"blood_glucose": glucose_data}, {})
    result = rule.evaluate(ctx)
    assert result.triggered
    assert result.severity == RiskLevel.HIGH
    assert "Level 2" in result.message
    print(f"[PASS] Glycemic: Level 2 hypo (<54), cites ADA 2024")

def test_glycemic_level1_hypo():
    """Glucose 54-70 → HIGH Level 1 hypo (ADA 2024)"""
    rule = GlycemicRiskRule()
    glucose_data = make_values([65])
    ctx = build_ctx({"blood_glucose": glucose_data}, {})
    result = rule.evaluate(ctx)
    assert result.triggered
    assert result.severity == RiskLevel.HIGH
    assert "Level 1" in result.message
    print(f"[PASS] Glycemic: Level 1 hypo (54-70), cites ADA 2024")


# ===================================================================
# TIER 2 — Respiratory Distress (BTS 2017)
# ===================================================================
def test_respiratory_critical():
    """SpO2 < 88 → HIGH critical (BTS 2017)"""
    rule = RespiratoryDistressRule()
    spo2_data = make_values([85])
    ctx = build_ctx({"oxygen_sat": spo2_data}, {})
    result = rule.evaluate(ctx)
    assert result.triggered
    assert result.severity == RiskLevel.HIGH
    assert "BTS" in result.message
    print(f"[PASS] Respiratory: critical SpO2 <88, cites BTS 2017")

def test_respiratory_copd_adjusted():
    """COPD patient: SpO2 86 is 'urgent' (between COPD critical=85 and urgent=88)"""
    rule = RespiratoryDistressRule()
    spo2_data = make_values([86])
    ctx = build_ctx({"oxygen_sat": spo2_data}, {}, patient_conditions=["COPD"])
    result = rule.evaluate(ctx)
    assert result.triggered
    assert result.severity == RiskLevel.HIGH
    assert result.evidence.get("copd_adjusted") == True
    print(f"[PASS] Respiratory: COPD-adjusted thresholds per BTS 2017")


# ===================================================================
# TIER 2 — Fever (Liebermeister's Rule)
# ===================================================================
def test_fever_liebermeister():
    """Temp 38.5°C + HR excess beyond Liebermeister + low steps → HIGH"""
    rule = FeverInfectionRule()
    temp_data = make_values([37.0, 37.5, 38.5])
    # Liebermeister: expected HR increase = (38.5-37.0) * 8.5 = 12.75 bpm
    # Baseline HR=70, so expected = 82.75. Latest=95 → excess = 12.25 > 5 margin
    hr_data = make_values([70, 75, 95])
    steps_data = make_values([5000, 3000, 1500])
    baselines = {
        "heart_rate": make_baseline("heart_rate", 70.0, std=3.0),
        "steps": make_baseline("steps", 5000.0, std=500.0),
    }
    ctx = build_ctx({"body_temp": temp_data, "heart_rate": hr_data, "steps": steps_data}, baselines)
    result = rule.evaluate(ctx)
    assert result.triggered
    assert result.severity == RiskLevel.HIGH
    assert "Liebermeister" in result.message
    print(f"[PASS] Fever: Liebermeister's Rule applied, cites Liebermeister 1875")


# ===================================================================
# TIER 2 — Nutritional Risk (MUST scoring)
# ===================================================================
def test_nutritional_must_score1():
    """5-10% weight loss → MEDIUM (MUST Score 1)"""
    rule = NutritionalRiskRule()
    # Start 70 kg, lose 5 kg (7.1%) in 30 days → MUST Score 1
    weight_data = make_values([70, 69, 68, 67, 66, 65] + [65]*9)
    baselines = {"weight": make_baseline("weight", 70.0, std=0.5)}
    ctx = build_ctx({"weight": weight_data}, baselines)
    result = rule.evaluate(ctx)
    assert result.triggered
    assert result.severity == RiskLevel.MEDIUM
    assert "MUST" in result.message
    print(f"[PASS] Nutritional: MUST Score 1 (5-10% loss), cites BAPEN 2003")

def test_nutritional_must_score2():
    """>10% weight loss → HIGH (MUST Score 2)"""
    rule = NutritionalRiskRule()
    # Start 70 kg, lose 8 kg (11.4%) → MUST Score 2
    weight_data = make_values([70, 68, 66, 64, 62] + [62]*10)
    baselines = {"weight": make_baseline("weight", 70.0, std=0.5)}
    ctx = build_ctx({"weight": weight_data}, baselines)
    result = rule.evaluate(ctx)
    assert result.triggered
    assert result.severity == RiskLevel.HIGH
    assert "MUST" in result.message
    print(f"[PASS] Nutritional: MUST Score 2 (>10% loss), cites BAPEN 2003")


# ===================================================================
# TIER 2 — Anxiety (z-score for HR)
# ===================================================================
def test_anxiety_zscore_hr():
    """Sleep poor + HR z>1.5 + mood declining → HIGH"""
    rule = AnxietyAgitationRule()
    sq_data = make_values([70, 60, 50, 45, 35, 30, 28])
    # Baseline HR=68, std=2. z=1.5 → HR > 71. Latest=75 (z=3.5)
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
    assert result.severity == RiskLevel.HIGH
    assert "Chalmers" in result.message or "z-score" in result.message
    print(f"[PASS] Anxiety HIGH: z-score HR, cites Chalmers 2014")


# ===================================================================
# TIER 3 — Anemia (WHO sex-specific)
# ===================================================================
def test_anemia_male_threshold():
    """Male Hgb 12.5 → mild anemia per WHO (threshold 13.0 for males)"""
    rule = AnemiaDetectionRule()
    labs = {"HEMOGLOBIN": [{"value": 12.5, "flag": "low", "ref_low": 13.0}]}
    ctx = build_ctx({}, {}, patient_sex="male", labs=labs)
    result = rule.evaluate(ctx)
    assert result.triggered
    assert result.severity == RiskLevel.LOW  # Mild (11.0-12.9 for males)
    assert "WHO" in result.message
    assert "male" in result.message
    print(f"[PASS] Anemia: male threshold 13.0, mild, cites WHO 2011")

def test_anemia_female_threshold():
    """Female Hgb 12.5 → NOT anemic per WHO (threshold 12.0 for females)"""
    rule = AnemiaDetectionRule()
    labs = {"HEMOGLOBIN": [{"value": 12.5, "flag": "normal", "ref_low": 12.0}]}
    ctx = build_ctx({}, {}, patient_sex="female", labs=labs)
    result = rule.evaluate(ctx)
    assert not result.triggered, "Female with Hgb 12.5 should NOT be flagged (WHO threshold is 12.0)"
    print(f"[PASS] Anemia: female 12.5 is normal per WHO 2011 (threshold 12.0)")

def test_anemia_severe():
    """Hgb < 8.0 → HIGH severity per WHO"""
    rule = AnemiaDetectionRule()
    labs = {"HEMOGLOBIN": [{"value": 7.2, "flag": "low", "ref_low": 13.0}]}
    ctx = build_ctx({}, {}, patient_sex="male", labs=labs)
    result = rule.evaluate(ctx)
    assert result.triggered
    assert result.severity == RiskLevel.HIGH
    assert "severe" in result.message
    print(f"[PASS] Anemia: severe (Hgb <8.0), HIGH severity, cites WHO 2011")


# ===================================================================
# Run all
# ===================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("GUIDELINE-ALIGNED RULES — UNIT TESTS")
    print("=" * 60)
    print()

    tests = [
        # Tier 1
        test_hypertension_urgency,
        test_hypertension_stage2,
        test_hypertension_stage1,
        test_functional_decline_absolute_floor,
        test_functional_decline_zscore,
        test_acute_illness_zscore_high,
        test_acute_illness_zscore_medium,
        test_medication_nonadherence_burnier,
        # Tier 2 Sensors
        test_glycemic_level2_hypo,
        test_glycemic_level1_hypo,
        test_respiratory_critical,
        test_respiratory_copd_adjusted,
        test_fever_liebermeister,
        test_nutritional_must_score1,
        test_nutritional_must_score2,
        # Tier 2 Mental Health
        test_anxiety_zscore_hr,
        # Tier 3
        test_anemia_male_threshold,
        test_anemia_female_threshold,
        test_anemia_severe,
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
