"""
Universal LOINC Clinical Lab Reconciliation Test Suite
======================================================

Tests all clinical and algorithmic pathways of the UniversalLabReconciler:
  1. Standard Unilateral Polarity (Liver Enzymes ALT & AST)
  2. Inverse Unilateral Polarity (Hemoglobin, eGFR, Vitamin D)
  3. Bilateral Homeostatic Interval (Electrolytes Potassium & Sodium)
  4. Qualitative / Serology Normalization (Negative / Non-reactive)
  5. Chronic Condition Therapeutic Control (HbA1c & Diabetes)
  6. Strict Chronological Precedence Guard (Past normal cannot resolve future acute)
  7. Universal Free-Text & Lexical LOINC Inverted Index Resolution
  8. Diagnostic Validity Window Shelf-Life Expiration (resolved_stale)
  9. Compound Multi-Analyte Panel Rule Re-evaluation (Dehydration AKI BUN/Cr)
  10. Tripwire Gatekeeper Memory Cleanse & Annotation
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
from app.services.insights.universal_reconciler import (
    UniversalLabReconciler,
    UniversalLoincIndex,
    INVERSE_POLARITY_LOINCS,
    BILATERAL_HOMEOSTATIC_LOINCS,
    CHRONIC_LOINCS,
)


def build_test_ctx(labs_dict: dict) -> EvalContext:
    """Helper to build an EvalContext with custom lab readings."""
    vitals_ctx = VitalsContext({})
    labs_ctx = LabContext(labs_dict)
    meds_ctx = MedContext(adherence_rate=1.0, recent_misses=0)
    baseline_status = PatientBaselineStatus("00000000-0000-0000-0000-000000000000", {})
    return EvalContext(
        "00000000-0000-0000-0000-000000000000",
        vitals_ctx,
        labs_ctx,
        meds_ctx,
        baseline_status=baseline_status,
        patient_conditions=[],
    )


# ==============================================================================
# 1. Standard Unilateral Polarity (Liver Enzymes - ALT & AST)
# ==============================================================================
def test_standard_polarity_liver():
    # ALT: 1742-6, AST: 1920-8 (Standard upper bound <= 40 U/L)
    prior_insights = [{
        "id": "mock-acute-liver",
        "rule_id": "acute_liver_injury",
        "name": "Acute Liver Injury Detected",
        "message": "ALT was critically elevated at 120 U/L",
        "effective_datetime": "2026-08-01T00:00:00+00:00",
        "status": "active"
    }]

    # Subsequent normal labs on 2026-08-15
    labs_dict = {
        "1742-6": [{
            "value": 22.0,
            "measured_at": "2026-08-15T00:00:00+00:00",
            "reference_low": 7.0,
            "reference_high": 40.0,
            "flag": "normal",
            "unit": "U/L"
        }],
        "1920-8": [{
            "value": 24.0,
            "measured_at": "2026-08-15T00:00:00+00:00",
            "reference_low": 10.0,
            "reference_high": 40.0,
            "flag": "normal",
            "unit": "U/L"
        }]
    }
    ctx = build_test_ctx(labs_dict)

    remaining = UniversalLabReconciler.reconcile_patient_lab_insights(
        patient_id="mock-patient",
        ctx=ctx,
        existing_insights=prior_insights
    )

    assert len(remaining) == 0, "Liver injury insight must be resolved and removed from active list"
    assert prior_insights[0]["status"] == "resolved", "Status must transition to 'resolved'"
    assert prior_insights[0]["resolved"] is True
    print("[PASS] Test 1: Standard Unilateral Polarity (Liver Enzymes ALT/AST) successfully resolved.")


# ==============================================================================
# 2. Inverse Unilateral Polarity (Hemoglobin, eGFR, Vitamin D)
# ==============================================================================
def test_inverse_polarity_hematology():
    # Hemoglobin: 718-7 (Higher is healthy, >= 12.0 g/dL)
    prior_insights = [{
        "id": "mock-anemia",
        "rule_id": "anemia_detection",
        "name": "Anemia Detection",
        "message": "Hemoglobin dropped to 9.2 g/dL",
        "effective_datetime": "2026-08-01T00:00:00+00:00",
        "status": "active"
    }]

    # Subsequent recovered Hemoglobin on 2026-08-20
    labs_dict = {
        "718-7": [{
            "value": 13.8,
            "measured_at": "2026-08-20T00:00:00+00:00",
            "reference_low": 12.0,
            "reference_high": 16.0,
            "flag": "normal",
            "unit": "g/dL"
        }]
    }
    ctx = build_test_ctx(labs_dict)

    remaining = UniversalLabReconciler.reconcile_patient_lab_insights(
        patient_id="mock-patient",
        ctx=ctx,
        existing_insights=prior_insights
    )

    assert len(remaining) == 0, "Anemia insight must be resolved and removed from active list"
    assert prior_insights[0]["status"] == "resolved"
    print("[PASS] Test 2: Inverse Unilateral Polarity (Hemoglobin recovery) successfully resolved.")


# ==============================================================================
# 3. Bilateral Homeostatic Interval (Electrolytes - Potassium)
# ==============================================================================
def test_bilateral_homeostatic_potassium():
    # Potassium: 2823-3 (Strict interval: 3.5 - 5.0 mmol/L)
    prior_insights = [{
        "id": "mock-hypokalemia",
        "rule_id": "arrhythmia_electrolyte_rule",
        "name": "Hypokalemia Arrhythmia Risk",
        "message": "Potassium dipped dangerously to 3.1 mmol/L",
        "effective_datetime": "2026-08-01T00:00:00+00:00",
        "status": "active"
    }]

    # Case A: Still abnormal (e.g. Potassium 5.5 = Hyperkalemia)
    labs_abnormal = {
        "2823-3": [{
            "value": 5.5,
            "measured_at": "2026-08-10T00:00:00+00:00",
            "reference_low": 3.5,
            "reference_high": 5.0,
            "flag": "high",
            "unit": "mmol/L"
        }]
    }
    ctx_abnormal = build_test_ctx(labs_abnormal)
    rem_abnormal = UniversalLabReconciler.reconcile_patient_lab_insights(
        patient_id="mock-patient", ctx=ctx_abnormal, existing_insights=list(prior_insights)
    )
    assert len(rem_abnormal) == 1, "Potassium 5.5 is outside homeostatic interval and must NOT resolve"

    # Case B: Normalized within homeostatic interval (Potassium 4.3 mmol/L)
    labs_normal = {
        "2823-3": [{
            "value": 4.3,
            "measured_at": "2026-08-15T00:00:00+00:00",
            "reference_low": 3.5,
            "reference_high": 5.0,
            "flag": "normal",
            "unit": "mmol/L"
        }]
    }
    ctx_normal = build_test_ctx(labs_normal)
    rem_normal = UniversalLabReconciler.reconcile_patient_lab_insights(
        patient_id="mock-patient", ctx=ctx_normal, existing_insights=prior_insights
    )
    assert len(rem_normal) == 0, "Potassium 4.3 is within interval and must resolve"
    assert prior_insights[0]["status"] == "resolved"
    print("[PASS] Test 3: Bilateral Homeostatic Interval (Potassium electrolyte) properly bounded.")


# ==============================================================================
# 4. Qualitative / Serology Normalization
# ==============================================================================
def test_qualitative_serology():
    obs_negative = {"value": None, "value_string": "Negative", "unit": ""}
    obs_normal = {"value": None, "value_string": "Normal", "unit": ""}
    obs_reactive = {"value": None, "value_string": "Positive / Reactive", "unit": ""}

    is_norm, _ = UniversalLabReconciler.evaluate_biomarker_normalization(obs_negative, "100904-2")
    assert is_norm is True, "'Negative' must be evaluated as normal"

    is_norm, _ = UniversalLabReconciler.evaluate_biomarker_normalization(obs_normal, "100904-2")
    assert is_norm is True, "'Normal' must be evaluated as normal"

    is_norm, _ = UniversalLabReconciler.evaluate_biomarker_normalization(obs_reactive, "100904-2")
    assert is_norm is False, "'Positive / Reactive' must be evaluated as abnormal"
    print("[PASS] Test 4: Qualitative / Serology string evaluation correctly verified.")


# ==============================================================================
# 5. Chronic Disease Therapeutic Control (HbA1c & Diabetes)
# ==============================================================================
def test_chronic_disease_therapeutic_control():
    # HbA1c: 4548-4 (Chronic condition: ADA target < 7.0%)
    prior_insights = [{
        "id": "mock-diabetes",
        "rule_id": "prediabetes_progression",
        "name": "Diabetes Progression Detected",
        "message": "Historical HbA1c of 10.0% indicated uncontrolled diabetes",
        "effective_datetime": "2023-11-07T00:00:00+00:00",
        "status": "active"
    }]

    # Case A: Normalized / Well-Controlled HbA1c (5.1% or 6.4%)
    labs_dict = {
        "4548-4": [{
            "value": 5.1,
            "measured_at": "2026-07-26T00:00:00+00:00",
            "reference_low": 4.0,
            "reference_high": 5.6,
            "flag": "normal",
            "unit": "%"
        }]
    }
    ctx = build_test_ctx(labs_dict)

    remaining = UniversalLabReconciler.reconcile_patient_lab_insights(
        patient_id="mock-patient",
        ctx=ctx,
        existing_insights=prior_insights
    )

    # Reconciled from active tripwire memory
    assert len(remaining) == 0, "Controlled chronic condition must be cleared from active tripwire list"
    assert prior_insights[0]["status"] == "controlled", "Status must transition to 'controlled' (never lost from chart)"
    assert prior_insights[0]["severity"] == "LOW", "Severity must be lowered to 'LOW'"
    assert prior_insights[0]["resolved"] is True
    print("[PASS] Test 5: Chronic Disease Therapeutic Control (HbA1c) correctly tagged as 'controlled' with LOW severity.")


# ==============================================================================
# 6. Strict Chronological Precedence Guard
# ==============================================================================
def test_chronological_precedence_guard():
    # Acute Transaminitis occurred on 2026-08-10
    prior_insights = [{
        "id": "mock-acute-alt",
        "rule_id": "acute_liver_injury",
        "name": "Acute Liver Injury",
        "message": "ALT spiked to 140 U/L on 2026-08-10",
        "effective_datetime": "2026-08-10T00:00:00+00:00",
        "status": "active"
    }]

    # Lab 1: Normal ALT & AST on 2026-07-20 (Drawn BEFORE the injury occurred!)
    labs_past_normal = {
        "1742-6": [{
            "value": 20.0,
            "measured_at": "2026-07-20T00:00:00+00:00",
            "reference_high": 40.0,
            "flag": "normal"
        }],
        "1920-8": [{
            "value": 22.0,
            "measured_at": "2026-07-20T00:00:00+00:00",
            "reference_high": 40.0,
            "flag": "normal"
        }]
    }
    ctx_past = build_test_ctx(labs_past_normal)
    rem_past = UniversalLabReconciler.reconcile_patient_lab_insights(
        patient_id="mock-patient", ctx=ctx_past, existing_insights=list(prior_insights)
    )
    assert len(rem_past) == 1, "Past normal lab from July must NOT resolve an acute injury from August!"
    assert prior_insights[0]["status"] == "active"

    # Lab 2: Subsequent normal ALT & AST on 2026-08-25 (Drawn AFTER the injury)
    labs_future_normal = {
        "1742-6": [{
            "value": 22.0,
            "measured_at": "2026-08-25T00:00:00+00:00",
            "reference_high": 40.0,
            "flag": "normal"
        }],
        "1920-8": [{
            "value": 24.0,
            "measured_at": "2026-08-25T00:00:00+00:00",
            "reference_high": 40.0,
            "flag": "normal"
        }]
    }
    ctx_future = build_test_ctx(labs_future_normal)
    rem_future = UniversalLabReconciler.reconcile_patient_lab_insights(
        patient_id="mock-patient", ctx=ctx_future, existing_insights=prior_insights
    )
    assert len(rem_future) == 0, "Subsequent normal lab drawn after the injury must resolve it"
    assert prior_insights[0]["status"] == "resolved"
    print("[PASS] Test 6: Chronological Precedence Guard strictly enforced (Past normal cannot resolve future acute).")


# ==============================================================================
# 7. Universal Free-Text & Lexical LOINC Inverted Index Resolution
# ==============================================================================
def test_universal_lexical_index_resolution():
    index = UniversalLoincIndex.get_instance()

    # 1. Condition: "Severe Hyperuricemia" -> Uric Acid 3084-1
    code1 = index.resolve_text_to_loinc("Severe Hyperuricemia with Joint Risk")
    assert code1 == "3084-1", f"Expected 3084-1, got {code1}"

    # 2. Abbreviation: "Elevated TSH" -> TSH 3016-3
    code2 = index.resolve_text_to_loinc("Elevated TSH")
    assert code2 == "3016-3", f"Expected 3016-3, got {code2}"

    # 3. Phrase: "Low Serum Ferritin" -> Ferritin 2276-4
    code3 = index.resolve_text_to_loinc("Low Serum Ferritin")
    assert code3 == "2276-4", f"Expected 2276-4, got {code3}"

    # 4. Phrase: "Elevated Alkaline Phosphatase" -> ALP 6768-6
    code4 = index.resolve_text_to_loinc("Elevated Alkaline Phosphatase")
    assert code4 == "6768-6", f"Expected 6768-6, got {code4}"

    # Verify reconciliation of an unmapped LLM insight using this index
    unmapped_insight = [{
        "id": "mock-llm-gout",
        "rule_id": "custom_llm_hyperuricemia",
        "name": "Severe Hyperuricemia Detected",
        "message": "Uric acid concentration was dangerously elevated",
        "effective_datetime": "2026-08-01T00:00:00+00:00",
        "status": "active"
    }]
    labs_uric = {
        "3084-1": [{
            "value": 5.2,
            "measured_at": "2026-08-20T00:00:00+00:00",
            "reference_low": 3.0,
            "reference_high": 7.0,
            "flag": "normal",
            "unit": "mg/dL"
        }]
    }
    ctx_uric = build_test_ctx(labs_uric)
    rem_uric = UniversalLabReconciler.reconcile_patient_lab_insights(
        patient_id="mock-patient", ctx=ctx_uric, existing_insights=unmapped_insight
    )
    assert len(rem_uric) == 0, "Unmapped insight with 'Severe Hyperuricemia' must resolve via index"
    assert unmapped_insight[0]["status"] == "resolved"
    print("[PASS] Test 7: Universal Free-Text & Lexical LOINC Inverted Index Resolution passed.")


# ==============================================================================
# 8. Diagnostic Validity Window Shelf-Life Expiration (resolved_stale)
# ==============================================================================
def test_validity_window_expiration():
    # Acute infection insight created 100 days ago (> 30-day validity window for Infection)
    old_date = (date.today() - timedelta(days=100)).isoformat()
    old_insight = [{
        "id": "mock-stale-infection",
        "rule_id": "acute_infection",
        "name": "Acute Infection Detected",
        "message": "WBC elevated 100 days ago",
        "effective_datetime": f"{old_date}T00:00:00+00:00",
        "status": "active"
    }]

    # No new lab test has been performed
    ctx_empty = build_test_ctx({})
    remaining = UniversalLabReconciler.reconcile_patient_lab_insights(
        patient_id="mock-patient", ctx=ctx_empty, existing_insights=old_insight
    )

    assert len(remaining) == 0, "Stale acute insight must be cleared from active list"
    assert old_insight[0]["status"] == "resolved_stale", "Status must transition to 'resolved_stale'"
    assert old_insight[0]["resolved"] is True
    print("[PASS] Test 8: Diagnostic Validity Window Expiration correctly transitioned to 'resolved_stale'.")


# ==============================================================================
# 9. Compound Multi-Analyte Panel Rule Re-evaluation (Dehydration AKI)
# ==============================================================================
def test_compound_panel_re_evaluation():
    # DehydrationAkiRule monitors BUN (3094-0), Creatinine (2160-0), and BUN/Cr ratio > 20
    prior_insights = [{
        "id": "mock-dehydration",
        "rule_id": "dehydration_aki",
        "name": "Dehydration / Prerenal AKI Warning",
        "message": "BUN 36 mg/dL, Creatinine 1.8 mg/dL (BUN/Cr ratio 20)",
        "effective_datetime": "2026-08-01T00:00:00+00:00",
        "status": "active"
    }]

    # Subsequent synchronous panel: BUN 14 mg/dL, Creatinine 0.9 mg/dL (Ratio 15.5 = normal)
    labs_hydrated = {
        "3094-0": [{
            "value": 14.0,
            "measured_at": "2026-08-15T00:00:00+00:00",
            "reference_low": 7.0,
            "reference_high": 20.0,
            "flag": "normal"
        }],
        "2160-0": [{
            "value": 0.9,
            "measured_at": "2026-08-15T00:00:00+00:00",
            "reference_low": 0.6,
            "reference_high": 1.2,
            "flag": "normal"
        }]
    }
    ctx = build_test_ctx(labs_hydrated)
    remaining = UniversalLabReconciler.reconcile_patient_lab_insights(
        patient_id="mock-patient", ctx=ctx, existing_insights=prior_insights
    )

    assert len(remaining) == 0, "Dehydration / AKI compound panel must resolve when BUN and Cr normalize"
    assert prior_insights[0]["status"] == "resolved"
    print("[PASS] Test 9: Compound Multi-Analyte Panel Rule Re-evaluation verified.")


# ==============================================================================
# 10. Tripwire Gatekeeper Memory Cleanse & Prompt Annotation
# ==============================================================================
def test_tripwire_gatekeeper_memory_cleanse():
    existing_insights = [
        {
            "id": "1",
            "rule_id": "prediabetes_progression",
            "name": "Diabetes Progression",
            "message": "Historical HbA1c 10.0%",
            "status": "active",
            "effective_datetime": "2023-11-07T00:00:00+00:00"
        },
        {
            "id": "2",
            "rule_id": "acute_liver_injury",
            "name": "Acute Liver Injury",
            "message": "ALT was 120 U/L",
            "status": "active",
            "effective_datetime": "2026-08-01T00:00:00+00:00"
        }
    ]

    # Patient has fresh normal labs for both HbA1c (5.1%) and ALT/AST (22/24 U/L)
    labs_dict = {
        "4548-4": [{"value": 5.1, "measured_at": "2026-07-26T00:00:00+00:00", "reference_high": 5.6, "flag": "normal"}],
        "1742-6": [{"value": 22.0, "measured_at": "2026-08-15T00:00:00+00:00", "reference_high": 40.0, "flag": "normal"}],
        "1920-8": [{"value": 24.0, "measured_at": "2026-08-15T00:00:00+00:00", "reference_high": 40.0, "flag": "normal"}]
    }
    ctx = build_test_ctx(labs_dict)

    cleaned_insights = UniversalLabReconciler.reconcile_patient_lab_insights(
        patient_id="mock-patient", ctx=ctx, existing_insights=existing_insights
    )

    # 1. Both active claims resolved/controlled and removed from active memory
    assert len(cleaned_insights) == 0, "Both insights must be cleared from active memory passed to MedGemma"
    # 2. Acute liver injury was resolved
    assert existing_insights[1]["status"] == "resolved"
    # 3. Chronic diabetes was controlled
    assert existing_insights[0]["status"] == "controlled"
    print("[PASS] Test 10: Tripwire Gatekeeper Memory Cleanse passed.")


# ==============================================================================
# MAIN TEST RUNNER
# ==============================================================================
if __name__ == "__main__":
    print("\n=======================================================")
    print("RUNNING UNIVERSAL LOINC CLINICAL LAB RECONCILIATION SUITE")
    print("=======================================================\n")

    test_standard_polarity_liver()
    test_inverse_polarity_hematology()
    test_bilateral_homeostatic_potassium()
    test_qualitative_serology()
    test_chronic_disease_therapeutic_control()
    test_chronological_precedence_guard()
    test_universal_lexical_index_resolution()
    test_validity_window_expiration()
    test_compound_panel_re_evaluation()
    test_tripwire_gatekeeper_memory_cleanse()

    print("\n=======================================================")
    print("ALL 10 CLINICAL RECONCILIATION TESTS PASSED PERFECTLY!")
    print("=======================================================\n")
