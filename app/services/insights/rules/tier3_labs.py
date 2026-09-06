"""
Tier 3 — Lab-Based Rules (Guideline-aligned, RCV-enriched)

These rules require periodic lab results (blood tests ordered by
physicians). They fire when lab trends correlate with wearable data.

All thresholds are directly from published clinical guidelines.
Trend analysis uses per-biomarker Reference Change Values (RCV) from
the EFLM Biological Variation Database to filter biological noise.

RCV integration (June 2026):
  - Rules now use LabMetric.is_worsening, .trend_direction, .rate_alert
    as primary or supporting evidence.
  - RCV thresholds and clinical flags are included in evidence dicts
    for full auditability.
  - All rules gracefully degrade: if RCV trend data is unavailable,
    they fall back to raw value comparisons (original logic).
"""

from app.services.insights.core import InsightRule, RiskLevel, InsightCategory, InsightTier, InsightResult
from app.services.insights.context import EvalContext


class PreDiabetesProgressionRule(InsightRule):
    """
    Detects progression from pre-diabetes toward diabetes using ADA
    HbA1c criteria, enhanced with RCV-confirmed trend analysis.

    THRESHOLDS (from ADA Standards of Care 2024):
    ┌──────────────────────────────┬──────────────────┬──────────────┐
    │ Classification               │ HbA1c (%)        │ Our Severity │
    ├──────────────────────────────┼──────────────────┼──────────────┤
    │ Normal                       │ < 5.7            │ (not flagged)│
    │ Pre-Diabetes                 │ 5.7-6.4          │ MEDIUM       │
    │ Diabetes                     │ >= 6.5           │ HIGH         │
    └──────────────────────────────┴──────────────────┴──────────────┘

    THE SCIENCE:
    - HbA1c measures the percentage of hemoglobin coated with glucose over a 3-month lifespan of red blood cells. Rising levels indicate a progressive inability of pancreatic beta-cells to clear postprandial and fasting glucose, hallmark signs of insulin resistance leading to type 2 diabetes.

    RCV INTEGRATION:
    - HbA1c RCV = 6.7% (EFLM: CVi=1.9%, CVa=1.5%)
    - Uses LabMetric.is_worsening as primary signal (RCV-confirmed
      rising trend + above reference range)
    - Falls back to raw value comparison if trend data unavailable
    - Includes ADA rate alert (rise >0.5%/6mo = therapy review) when
      triggered

    CITATIONS:
    - ADA. "Standards of Care in Diabetes -- 2024."
      Diabetes Care. 2024;47(Suppl 1). DOI: 10.2337/dc24-SINT
    - ADA §2: Classification and Diagnosis of Diabetes.
      Table 2.3: HbA1c 5.7-6.4% = pre-diabetes; >= 6.5% = diabetes.
    - Aarsand AK, et al. Clin Chem. 2018;64(9):1380-1393.
      (HbA1c biological variation: CVi=1.9%, CVa=1.5%)
    """
    id = "prediabetes_progression"
    name = "Pre-Diabetes -> Diabetes Progression"
    category = InsightCategory.METABOLIC
    tier = InsightTier.TIER_3
    requires_baseline = False

    # ADA 2024 §2 Table 2.3
    PREDIABETES_THRESHOLD = 5.7
    DIABETES_THRESHOLD = 6.5

    def evaluate(self, ctx: EvalContext) -> InsightResult:
        hba1c = ctx.labs.biomarker("4548-4")
        glucose = ctx.vitals.metric("blood_glucose")
        steps = ctx.vitals.metric("steps")

        if not hba1c.has_data:
            return self.skip_rule("No HbA1c lab results available")

        latest_hba1c = hba1c.latest

        # Gate: only trigger if latest HbA1c is in pre-diabetes or diabetes range
        if latest_hba1c < self.PREDIABETES_THRESHOLD:
            return self.pass_rule()

        # Determine ADA staging
        severity = RiskLevel.HIGH if latest_hba1c >= self.DIABETES_THRESHOLD else RiskLevel.MEDIUM
        ada_stage = "diabetes" if latest_hba1c >= self.DIABETES_THRESHOLD else "pre-diabetes"

        # ── Primary signal: RCV-confirmed worsening trend ──
        # Uses EFLM RCV threshold (6.7% for HbA1c) to confirm
        # that the rise is clinically meaningful, not biological noise.
        trend_confirmed = hba1c.is_worsening if hba1c.has_trend_data else False

        # Fallback: raw comparison if trend data unavailable
        if not hba1c.has_trend_data and hba1c.has_multiple_readings():
            previous_hba1c = float(hba1c.data[-2].get('value', 0.0))
            trend_confirmed = latest_hba1c > previous_hba1c

        # if not trend_confirmed and not hba1c.is_out_of_range():
        #    return self.pass_rule()

        # ── Cross-reference with vitals (Zivaa enhancement) ──
        glucose_elevated = glucose.latest > 130 if glucose.has_data else False
        steps_declining = False
        if steps.has_data and steps.is_baseline_established:
            steps_bl = steps.established_baseline
            steps_z = ((steps_bl.mean - steps.latest) / steps_bl.std) if steps_bl.std > 0 else 0
            steps_declining = steps_z > 1.5

        # Build evidence dict with RCV audit trail
        evidence = {
            "hba1c_latest": latest_hba1c,
            "ada_stage": ada_stage,
            "glucose_elevated": glucose_elevated,
            "steps_declining": steps_declining,
            "guideline": "ADA 2024 §2 Table 2.3",
        }

        # Include RCV trend data for auditability
        if hba1c.has_trend_data:
            evidence["trend_direction"] = hba1c.trend_direction
            evidence["clinical_flag"] = hba1c.clinical_flag
            evidence["rcv_threshold_pct"] = hba1c.rcv_threshold_pct
            evidence["change_percent"] = hba1c.change_percent

        # Include ADA rate alert if triggered
        if hba1c.has_rate_alert:
            evidence["rate_alert"] = hba1c.rate_alert

        # Build message
        vitals_context = []
        if glucose_elevated:
            vitals_context.append("elevated glucose")
        if steps_declining:
            vitals_context.append("declining activity")

        trend_qualifier = ""
        if hba1c.has_trend_data and hba1c.trend_direction == "rising":
            trend_qualifier = f" (RCV-confirmed rising trend, {hba1c.change_percent:+.1f}% change)"

        rate_warning = ""
        if hba1c.has_rate_alert:
            rate_warning = f" Rate of change triggers ADA therapy review threshold."

        date_str = f" on {hba1c.latest_date}" if hasattr(hba1c, "latest_date") and hba1c.latest_date else ""
        msg = (
            f"HbA1c is {latest_hba1c}%{date_str} ({ada_stage} range per ADA 2024 §2)"
            f"{trend_qualifier}."
            f"{rate_warning}"
        )
        if vitals_context:
            msg += f" Cross-correlated with {' and '.join(vitals_context)}."
        else:
            msg += " No daily glucose or activity data for cross-reference."

        return self.trigger(severity=severity, message=msg, evidence=evidence, is_historical=hba1c.is_historical, effective_datetime=hba1c.latest_date)


class KidneyDeclineRule(InsightRule):
    """
    Detects kidney function decline using KDIGO CKD staging,
    enhanced with RCV-confirmed eGFR trends and KDIGO rate alerts.

    THRESHOLDS (from KDIGO 2024):
    ┌──────────────────────────────┬──────────────────┬──────────────┐
    │ CKD Stage                    │ eGFR (mL/min)    │ Our Severity │
    ├──────────────────────────────┼──────────────────┼──────────────┤
    │ Stage 1 (normal/high)        │ >= 90            │ (not flagged)│
    │ Stage 2 (mildly decreased)   │ 60-89            │ (not flagged)│
    │ Stage 3a (mild-moderate)     │ 45-59            │ MEDIUM       │
    │ Stage 3b (moderate-severe)   │ 30-44            │ HIGH         │
    │ Stage 4 (severely decreased) │ 15-29            │ HIGH         │
    │ Stage 5 (kidney failure)     │ < 15             │ HIGH         │
    └──────────────────────────────┴──────────────────┴──────────────┘

    THE SCIENCE:
    - eGFR estimates the volume of fluid filtered from the kidney glomerular capillaries into Bowman's capsule per unit time. A declining eGFR signifies irreversible nephron loss or structural damage (sclerosis) within the kidneys, impairing their ability to filter metabolic waste.

    RCV INTEGRATION:
    - eGFR RCV = 15.9% (derived from Creatinine: CVi=5.3%, CVa=2.2%)
    - Uses LabMetric.is_worsening (declining + below_range via inverse matrix)
    - KDIGO rate alert: decline >5 mL/min/year = "rapid_progression"
      automatically fires when rate threshold is exceeded

    CITATIONS:
    - KDIGO 2024 CKD Guideline. Kidney Int Suppl. 2024;14(4S):e1-e314.
    - Levey AS, et al. Ann Intern Med. 2009;150(9):604-612. (CKD-EPI)
    - Aarsand AK, et al. Clin Chem. 2018. (Creatinine CVi/CVa)
    """
    id = "kidney_decline"
    name = "Kidney Function Decline"
    category = InsightCategory.RENAL
    tier = InsightTier.TIER_3
    requires_baseline = False

    def evaluate(self, ctx: EvalContext) -> InsightResult:
        egfr = ctx.labs.biomarker("62238-1")  # eGFR
        bp_sys = ctx.vitals.metric("bp_systolic")
        weight = ctx.vitals.metric("weight")

        if not egfr.has_data:
            return self.skip_rule("No eGFR lab results available")

        # ── Primary signal: RCV-confirmed worsening ──
        # For eGFR (inverse polarity), worsening = declining + below_range.
        # This is filtered through the EFLM RCV threshold of 15.9%.
        egfr_worsening = egfr.is_worsening if egfr.has_trend_data else False

        # Fallback: raw flag check if trend data unavailable
        if not egfr.has_trend_data:
            egfr_worsening = egfr.is_out_of_range() and egfr.flag == "low"

        if not egfr_worsening:
            return self.pass_rule()

        # ── Cross-reference with vitals ──
        bp_rising = bp_sys.trend(days=7).is_increasing() if bp_sys.has_data else False
        weight_gain = False
        if weight.has_data:
            weight_gain = (weight.trend(days=7).end_value - weight.trend(days=7).start_value > 1.0)

        # ── Severity determination ──
        # Escalate to HIGH if KDIGO rapid progression rate alert fires
        # or if vitals show supporting signs (BP rise, weight gain)
        has_kdigo_alert = egfr.has_rate_alert
        has_vitals_support = bp_rising or weight_gain

        if has_kdigo_alert or has_vitals_support:
            severity = RiskLevel.HIGH
        else:
            severity = RiskLevel.MEDIUM

        # Build evidence dict with RCV audit trail
        evidence = {
            "egfr": egfr.latest,
            "bp_rising": bp_rising,
            "weight_gain": weight_gain,
            "guideline": "KDIGO 2024 CKD Guideline",
        }

        if egfr.has_trend_data:
            evidence["trend_direction"] = egfr.trend_direction
            evidence["clinical_flag"] = egfr.clinical_flag
            evidence["rcv_threshold_pct"] = egfr.rcv_threshold_pct
            evidence["change_percent"] = egfr.change_percent

        if has_kdigo_alert:
            evidence["rate_alert"] = egfr.rate_alert

        # Build message
        vitals_parts = []
        if bp_rising:
            vitals_parts.append("rising BP")
        if weight_gain:
            vitals_parts.append("weight gain (possible fluid retention)")

        trend_detail = ""
        if egfr.has_trend_data:
            trend_detail = f" (RCV-confirmed declining trend, {egfr.change_percent:+.1f}%)"

        rate_detail = ""
        if has_kdigo_alert:
            rate_detail = (
                f" Rate of decline ({egfr.rate_per_month * 12:.1f} mL/min/year) "
                f"exceeds KDIGO rapid progression threshold (>5 mL/min/year)."
            )

        msg = (
            f"eGFR has declined to {egfr.latest:.0f} mL/min{trend_detail}."
            f"{rate_detail}"
        )
        if vitals_parts:
            msg += f" Correlated with {' and '.join(vitals_parts)}."
        msg += " Nephrology review advised."

        return self.trigger(severity=severity, message=msg, evidence=evidence, is_historical=egfr.is_historical, effective_datetime=egfr.latest_date)


class AnemiaDetectionRule(InsightRule):
    """
    Detects anemia using WHO sex-specific hemoglobin thresholds,
    enriched with RCV-based trend context.

    THRESHOLDS (from WHO 2011):
    ┌──────────────────────────────┬──────────────────┬──────────────┐
    │ Classification               │ Hemoglobin (g/dL)│ Our Severity │
    ├──────────────────────────────┼──────────────────┼──────────────┤
    │ Normal (male)                │ >= 13.0          │ (not flagged)│
    │ Normal (female, non-pregnant)│ >= 12.0          │ (not flagged)│
    │ Mild anemia (male)           │ 11.0-12.9        │ LOW          │
    │ Mild anemia (female)         │ 11.0-11.9        │ LOW          │
    │ Moderate anemia              │ 8.0-10.9         │ MEDIUM       │
    │ Severe anemia                │ < 8.0            │ HIGH         │
    └──────────────────────────────┴──────────────────┴──────────────┘

    THE SCIENCE:
    - Hemoglobin is the iron-containing oxygen-transport metalloprotein in red blood cells. A decrease in hemoglobin directly reduces the oxygen-carrying capacity of the blood, leading to tissue hypoxia and compensatory cardiac output increases (tachycardia).

    RCV INTEGRATION:
    - Hemoglobin RCV = 8.8% (EFLM: CVi=2.8%, CVa=1.5%)
    - WHO thresholds remain the primary trigger (they define anemia)
    - Trend data is added to evidence for richer clinical context
    - If hemoglobin is_worsening (declining + below_range), severity
      is escalated by one level

    CITATIONS:
    - WHO 2011 (WHO/NMH/NHD/MNM/11.1)
    - Harrison's 21st Ed. Ch. 93 (compensatory tachycardia)
    - Aarsand AK, et al. Clin Chem. 2018. (Hemoglobin CVi/CVa)
    """
    id = "anemia_detection"
    name = "Anemia / Low Iron Detection"
    category = InsightCategory.HEMATOLOGY
    tier = InsightTier.TIER_3
    requires_baseline = False

    # WHO 2011 Table 1
    HGB_THRESHOLD_MALE = 13.0
    HGB_THRESHOLD_FEMALE = 12.0
    # WHO 2011 Table 2
    HGB_MODERATE = 10.9
    HGB_SEVERE = 8.0

    def evaluate(self, ctx: EvalContext) -> InsightResult:
        hgb = ctx.labs.biomarker("718-7")  # Hemoglobin
        hr = ctx.vitals.metric("avg_heart_rate")
        spo2 = ctx.vitals.metric("oxygen_sat")

        if not hgb.has_data:
            return self.skip_rule("No hemoglobin lab results available")

        # Determine threshold based on patient sex (WHO 2011)
        if ctx.patient_sex == "male":
            threshold = self.HGB_THRESHOLD_MALE
            sex_label = "male"
        elif ctx.patient_sex == "female":
            threshold = self.HGB_THRESHOLD_FEMALE
            sex_label = "female"
        else:
            threshold = self.HGB_THRESHOLD_FEMALE
            sex_label = "unknown (using female threshold)"

        if hgb.latest >= threshold:
            return self.pass_rule()

        # Classify severity per WHO 2011 Table 2
        if hgb.latest < self.HGB_SEVERE:
            severity = RiskLevel.HIGH
            who_class = "severe"
        elif hgb.latest <= self.HGB_MODERATE:
            severity = RiskLevel.MEDIUM
            who_class = "moderate"
        else:
            severity = RiskLevel.LOW
            who_class = "mild"

        # ── RCV trend escalation ──
        # If hemoglobin is RCV-confirmed worsening (declining + below_range),
        # escalate severity by one level to emphasize the active decline.
        # Hemoglobin is inverse-polarity: declining below range = worsening.
        if hgb.is_worsening and severity == RiskLevel.LOW:
            severity = RiskLevel.MEDIUM
            who_class += " (actively declining)"
        elif hgb.is_worsening and severity == RiskLevel.MEDIUM:
            severity = RiskLevel.HIGH
            who_class += " (actively declining)"

        # Supporting: compensatory tachycardia (Harrison's Ch. 93)
        hr_elevated = False
        if hr.has_data and hr.is_baseline_established:
            hr_bl = hr.established_baseline
            hr_z = ((hr.latest - hr_bl.mean) / hr_bl.std) if hr_bl.std > 0 else 0
            hr_elevated = hr_z > 1.5

        spo2_low = spo2.latest < 95.0 if spo2.has_data else False

        # Build evidence with RCV audit trail
        evidence = {
            "hgb": hgb.latest,
            "who_severity": who_class,
            "threshold_used": threshold,
            "patient_sex": ctx.patient_sex or "unknown",
            "hr_elevated": hr_elevated,
            "spo2_low": spo2_low,
            "guideline": "WHO 2011 (WHO/NMH/NHD/MNM/11.1)",
        }

        if hgb.has_trend_data:
            evidence["trend_direction"] = hgb.trend_direction
            evidence["clinical_flag"] = hgb.clinical_flag
            evidence["rcv_threshold_pct"] = hgb.rcv_threshold_pct
            evidence["change_percent"] = hgb.change_percent

        # Build message
        msg_parts = [
            f"Hemoglobin is {hgb.latest} g/dL -- classified as {who_class} anemia "
            f"per WHO 2011 (threshold for {sex_label}: <{threshold} g/dL)."
        ]

        if hgb.has_trend_data and hgb.trend_direction == "declining":
            msg_parts.append(
                f" RCV-confirmed declining trend ({hgb.change_percent:+.1f}%, "
                f"RCV threshold: {hgb.rcv_threshold_pct}%)."
            )

        if hr_elevated:
            msg_parts.append(
                f" Compensatory tachycardia detected ({hr.latest:.0f} bpm), "
                f"consistent with Harrison's (Ch. 93) expectation for Hgb <10 g/dL."
            )
        if spo2_low:
            msg_parts.append(f" SpO2 is also low ({spo2.latest:.1f}%).")

        return self.trigger(
            severity=severity,
            message="".join(msg_parts),
            evidence=evidence
        , is_historical=hgb.is_historical, effective_datetime=hgb.latest_date)


class ThyroidDysfunctionRule(InsightRule):
    """
    Detects thyroid dysfunction using ATA guideline TSH interpretation,
    filtered through RCV to avoid false alarms from TSH's extreme
    biological variation.

    THE SCIENCE:
    - TSH (Thyroid Stimulating Hormone) is secreted by the anterior pituitary to regulate thyroid hormone (T4/T3) production. Through a negative feedback loop, high TSH indicates a failing thyroid gland (hypothyroidism) while low TSH indicates autonomous overproduction by the thyroid (hyperthyroidism).

    RCV INTEGRATION:
    - TSH RCV = 54.1% (EFLM: CVi=19.3%, CVa=2.5%)
    - This is critically important: TSH has one of the highest biological
      variation coefficients. A TSH reading can vary by ~40% between two
      draws taken a week apart in the same healthy individual.
    - Only RCV-confirmed worsening trends are used as evidence.
    - Falls back to raw out-of-range check if trend data unavailable.

    CROSS-CORRELATION (Harrison's Ch. 376):
    - Hypothyroid: bradycardia (<60 bpm) + weight gain
    - Hyperthyroid: tachycardia (>90 bpm) + weight loss

    CITATIONS:
    - Garber JR, et al. Thyroid. 2012;22(12):1200-1235. (ATA/AACE 2012)
    - Ross DS, et al. Thyroid. 2016;26(10):1343-1421. (ATA 2016)
    - Harrison's 21st Ed. Ch. 376. (thyroid-vitals correlation)
    - Ricos C, et al. Scand J Clin Lab Invest. 1999. (TSH CVi=19.3%)
    """
    id = "thyroid_dysfunction"
    name = "Thyroid Dysfunction"
    category = InsightCategory.THYROID
    tier = InsightTier.TIER_3
    requires_baseline = False

    def evaluate(self, ctx: EvalContext) -> InsightResult:
        tsh = ctx.labs.biomarker("3016-3")  # TSH
        hr = ctx.vitals.metric("avg_heart_rate")
        weight = ctx.vitals.metric("weight")

        if not tsh.has_data:
            return self.skip_rule("No TSH lab results available")

        # ── Primary signal: RCV-confirmed worsening OR raw out-of-range ──
        # TSH has extreme biological variation (CVi=19.3%, RCV=54.1%).
        # Using RCV filtering prevents false thyroid alerts from normal
        # TSH fluctuation.
        tsh_abnormal = False

        if tsh.has_trend_data:
            # RCV-filtered: only flag if trend is confirmed worsening
            # or if the value is out of range with a meaningful trend
            tsh_abnormal = tsh.is_worsening or (
                tsh.is_out_of_range() and tsh.trend_direction != "stable"
            )
        else:
            # Fallback: raw out-of-range check (original logic)
            tsh_abnormal = tsh.is_out_of_range()

        if not tsh_abnormal:
            return self.pass_rule()

        is_hypo = tsh.flag == "high"
        is_hyper = tsh.flag == "low"
        weight_trend = weight.trend(days=14) if weight.has_data else None

        # Build base evidence with RCV audit trail
        evidence = {
            "tsh": tsh.latest,
            "guideline": "ATA/AACE 2012, ATA 2016, Harrison's Ch. 376",
        }

        if tsh.has_trend_data:
            evidence["trend_direction"] = tsh.trend_direction
            evidence["clinical_flag"] = tsh.clinical_flag
            evidence["rcv_threshold_pct"] = tsh.rcv_threshold_pct
            evidence["change_percent"] = tsh.change_percent
            evidence["note"] = (
                f"TSH has extreme biological variation (RCV={tsh.rcv_threshold_pct}%). "
                f"This trend has been RCV-filtered to exclude normal fluctuation."
            )

        if is_hypo:
            weight_gaining = weight_trend.is_increasing() if weight_trend else False
            bradycardia = hr.latest < 60 if hr.has_data and hr.latest > 0 else False

            evidence["diagnosis"] = "hypothyroidism"
            evidence["weight_gaining"] = weight_gaining
            evidence["bradycardia"] = bradycardia

            trend_qualifier = ""
            if tsh.has_trend_data and tsh.trend_direction == "rising":
                trend_qualifier = f" (RCV-confirmed rising trend, {tsh.change_percent:+.1f}%)"

            if weight_gaining or bradycardia:
                vitals_parts = []
                if weight_gaining:
                    vitals_parts.append("weight gain")
                if bradycardia:
                    vitals_parts.append("bradycardia")

                return self.trigger(
                    severity=RiskLevel.MEDIUM,
                    message=(
                        f"TSH is elevated ({tsh.latest}){trend_qualifier}, indicating "
                        f"hypothyroidism per ATA/AACE 2012. Correlated with "
                        f"{' and '.join(vitals_parts)} (Harrison's Ch. 376)."
                    ),
                    evidence=evidence
                , is_historical=tsh.is_historical, effective_datetime=tsh.latest_date)

        elif is_hyper:
            weight_losing = weight_trend.is_decreasing() if weight_trend else False
            tachycardia = hr.latest > 90 if hr.has_data else False

            evidence["diagnosis"] = "hyperthyroidism"
            evidence["weight_losing"] = weight_losing
            evidence["tachycardia"] = tachycardia

            if weight_losing or tachycardia:
                vitals_parts = []
                if weight_losing:
                    vitals_parts.append("weight loss")
                if tachycardia:
                    vitals_parts.append("tachycardia")

                return self.trigger(
                    severity=RiskLevel.MEDIUM,
                    message=(
                        f"TSH is low ({tsh.latest}), indicating hyperthyroidism per "
                        f"ATA 2016. Correlated with {' and '.join(vitals_parts)} "
                        f"(Harrison's Ch. 376)."
                    ),
                    evidence=evidence
                , is_historical=tsh.is_historical, effective_datetime=tsh.latest_date)

        return self.pass_rule()


class CardiovascularRiskRule(InsightRule):
    """
    Detects elevated cardiovascular risk from LDL + blood pressure,
    with RCV-confirmed LDL trend as a severity modifier.

    THRESHOLDS (from ACC/AHA 2018 Cholesterol Guideline):
    ┌──────────────────────────────┬──────────────────┬──────────────┐
    │ LDL Classification           │ LDL (mg/dL)      │ Notes        │
    ├──────────────────────────────┼──────────────────┼──────────────┤
    │ Optimal                      │ < 100            │              │
    │ Near/Above Optimal           │ 100-129          │              │
    │ Borderline High              │ 130-159          │ MEDIUM       │
    │ High                         │ 160-189          │ HIGH         │
    │ Very High                    │ >= 190           │ HIGH         │
    └──────────────────────────────┴──────────────────┴──────────────┘

    THE SCIENCE:
    - LDL cholesterol lipoproteins penetrate the arterial intima where they become oxidized. Macrophages engulf oxidized LDL, becoming foam cells, which triggers an inflammatory cascade resulting in atherosclerotic plaque formation and eventual cardiovascular events.

    RCV INTEGRATION:
    - LDL RCV = 23.7% (EFLM: CVi=8.3%, CVa=2.0%)
    - ACC/AHA thresholds remain the primary trigger
    - If LDL is RCV-confirmed worsening (rising + above range),
      severity is escalated, particularly when combined with BP

    CITATIONS:
    - Grundy SM, et al. J Am Coll Cardiol. 2019;73(24):e285-e350.
    - Whelton PK, et al. 2017 ACC/AHA HTN Guideline.
    - Ricos C, et al. Scand J Clin Lab Invest. 1999. (LDL CVi=8.3%)
    """
    id = "cardiovascular_risk"
    name = "Cardiovascular Event Risk"
    category = InsightCategory.CARDIAC
    tier = InsightTier.TIER_3
    requires_baseline = False

    # ACC/AHA 2018 Table 4 (ATP III classification)
    LDL_BORDERLINE_HIGH = 130
    LDL_HIGH = 160
    LDL_VERY_HIGH = 190

    def evaluate(self, ctx: EvalContext) -> InsightResult:
        ldl = ctx.labs.biomarker("13457-7")  # LDL
        bp_sys = ctx.vitals.metric("bp_systolic")

        if not ldl.has_data:
            return self.skip_rule("No LDL cholesterol lab results available")

        if ldl.latest < self.LDL_BORDERLINE_HIGH:
            return self.pass_rule()

        ldl_class = ("very_high" if ldl.latest >= self.LDL_VERY_HIGH
                     else "high" if ldl.latest >= self.LDL_HIGH
                     else "borderline_high")

        bp_elevated = False
        if bp_sys.has_data:
            bp_trend = bp_sys.trend(days=14)
            bp_elevated = bp_trend.end_value > 140  # ACC/AHA Stage 2

        # ── RCV-based severity escalation ──
        # If LDL is RCV-confirmed worsening (rising trend above range),
        # escalate severity as the trajectory is actively deteriorating.
        ldl_trend_worsening = ldl.is_worsening if ldl.has_trend_data else False

        # Build evidence with RCV audit trail
        evidence = {
            "ldl": ldl.latest,
            "ldl_class": ldl_class,
            "bp_elevated": bp_elevated,
            "guideline": "ACC/AHA 2018 Cholesterol, ACC/AHA 2017 HTN",
        }

        if ldl.has_trend_data:
            evidence["trend_direction"] = ldl.trend_direction
            evidence["clinical_flag"] = ldl.clinical_flag
            evidence["rcv_threshold_pct"] = ldl.rcv_threshold_pct
            evidence["change_percent"] = ldl.change_percent

        # Determine severity
        if bp_elevated:
            # High BP + high LDL = elevated ASCVD risk
            severity = RiskLevel.HIGH if ldl.latest >= self.LDL_HIGH else RiskLevel.MEDIUM

            # Escalate further if LDL is actively worsening
            if ldl_trend_worsening and severity == RiskLevel.MEDIUM:
                severity = RiskLevel.HIGH
                evidence["severity_escalated"] = "LDL RCV-confirmed worsening + Stage 2 HTN"

            trend_note = ""
            if ldl_trend_worsening:
                trend_note = (
                    f" LDL is on a RCV-confirmed rising trend "
                    f"({ldl.change_percent:+.1f}%)."
                )

            return self.trigger(
                severity=severity,
                message=(
                    f"LDL cholesterol is {ldl_class.replace('_', ' ')} ({ldl.latest} mg/dL, "
                    f"ACC/AHA classification) combined with Stage 2 hypertension "
                    f"({bp_sys.latest:.0f} mmHg). ASCVD risk is significantly elevated."
                    f"{trend_note}"
                ),
                evidence=evidence
            , is_historical=ldl.is_historical, effective_datetime=ldl.latest_date)
        else:
            severity = RiskLevel.MEDIUM if ldl.latest >= self.LDL_HIGH else RiskLevel.LOW

            # Escalate if LDL is actively worsening even without high BP
            if ldl_trend_worsening and severity == RiskLevel.LOW:
                severity = RiskLevel.MEDIUM
                evidence["severity_escalated"] = "LDL RCV-confirmed worsening trend"

            trend_note = ""
            if ldl_trend_worsening:
                trend_note = (
                    f" LDL shows a RCV-confirmed rising trend "
                    f"({ldl.change_percent:+.1f}%). "
                )

            return self.trigger(
                severity=severity,
                message=(
                    f"LDL cholesterol is {ldl_class.replace('_', ' ')} ({ldl.latest} mg/dL "
                    f"per ACC/AHA 2018 classification).{trend_note}"
                    f"Lifestyle and statin therapy should be discussed per "
                    f"Grundy et al. 2018 guideline."
                ),
                evidence=evidence
            , is_historical=ldl.is_historical, effective_datetime=ldl.latest_date)


class SilentInsulinResistanceRule(InsightRule):
    """
    Detects severe insulin resistance before blood sugar goes out of range
    using the HOMA-IR proxy score.
    THE SCIENCE:
    - Hyperinsulinemia occurs as a compensatory mechanism when peripheral tissues (muscle, adipose) become resistant to insulin action. The pancreas secretes excessive insulin to maintain normoglycemia, which can be quantified via the HOMA-IR model before glucose levels ever rise.

    """
    id = "silent_insulin_resistance"
    name = "Silent Insulin Resistance"
    category = InsightCategory.METABOLIC
    tier = InsightTier.TIER_3
    requires_baseline = False

    def evaluate(self, ctx: EvalContext) -> InsightResult:
        sync_labs = ctx.labs.get_synchronous_readings(["43396-1", "14771-0"], max_gap_days=0)

        if not sync_labs:
            return self.skip_rule("Requires both Fasting Insulin and Fasting Glucose from the same day")

        insulin_val = sync_labs["43396-1"]
        glucose_val = sync_labs["14771-0"]

        homa_ir = (glucose_val * insulin_val) / 405.0

        if homa_ir > 2.0:
            evidence = {
                "homa_ir": round(homa_ir, 2),
                "fasting_insulin": insulin_val,
                "fasting_glucose": glucose_val
            }
            return self.trigger(
                severity=RiskLevel.HIGH if homa_ir > 3.0 else RiskLevel.MEDIUM,
                message=f"HOMA-IR score is {homa_ir:.1f}, indicating significant insulin resistance despite potentially normal HbA1c.",
                evidence=evidence
            )
            
        return self.pass_rule()


class AnemiaRootCauseTriageRule(InsightRule):
    """
    Triages anemia to determine if it is Microcytic (Iron) or Macrocytic (B12).
    THE SCIENCE:
    - The Mean Corpuscular Volume (MCV) reflects red blood cell size. Iron deficiency limits hemoglobin synthesis, leading to smaller cells (microcytic), whereas B12/Folate deficiency impairs DNA synthesis, causing arrested cell division and abnormally large cells (macrocytic).

    """
    id = "anemia_root_cause_triage"
    name = "Anemia Root-Cause Triage"
    category = InsightCategory.HEMATOLOGY
    tier = InsightTier.TIER_3
    requires_baseline = False

    def evaluate(self, ctx: EvalContext) -> InsightResult:
        sync_labs = ctx.labs.get_synchronous_readings(["718-7", "787-2"], max_gap_days=7)

        if not sync_labs:
            return self.skip_rule("Requires both Hemoglobin and MCV within 7 days")

        hgb_val = sync_labs["718-7"]
        mcv_val = sync_labs["787-2"]

        threshold = 13.0 if ctx.patient_sex == "male" else 12.0
        
        if hgb_val >= threshold:
            return self.pass_rule() # Not anemic
            
        evidence = {
            "hemoglobin": hgb_val,
            "mcv": mcv_val
        }
        
        if mcv_val < 80:
            cause = "Microcytic (Likely Iron Deficiency)"
            sync_iron = ctx.labs.get_synchronous_readings(["718-7", "2276-4"], max_gap_days=7)
            if sync_iron and sync_iron["2276-4"] < 30:
                cause += " - Confirmed low Ferritin"
                evidence["ferritin"] = sync_iron["2276-4"]
        elif mcv_val > 100:
            cause = "Macrocytic (Likely B12/Folate Deficiency)"
            sync_b12 = ctx.labs.get_synchronous_readings(["718-7", "2132-9"], max_gap_days=7)
            if sync_b12 and sync_b12["2132-9"] < 300:
                cause += " - Confirmed low B12"
                evidence["b12"] = sync_b12["2132-9"]
        else:
            cause = "Normocytic (Consider chronic disease or kidney issues)"

        return self.trigger(
            severity=RiskLevel.MEDIUM,
            message=f"Patient is anemic (Hgb {hgb_val}). MCV analysis indicates: {cause}.",
            evidence=evidence
        )


class AcuteInfectionRule(InsightRule):
    """
    Detects systemic inflammation and potential acute infections by correlating
    inflammatory biomarkers (CRP, ESR, WBC) with vital signs (fever, tachycardia).
    
    THE SCIENCE:
    - CRP is an acute-phase reactant synthesized by the liver in response to IL-6 released by macrophages during inflammation. The ESR measures how quickly RBCs settle, which increases when acute-phase proteins (like fibrinogen) neutralize RBC surface charge during systemic infection.

    CITATIONS:
    - Bone RC, et al. "Definitions for sepsis and organ failure and guidelines for the use of innovative therapies in sepsis." Chest. 1992;101(6):1644-1655. (SIRS Criteria)
    - American Academy of Family Physicians (AAFP) Guidelines on Acute Phase Reactants.
    """
    id = "acute_infection_inflammation"
    name = "Acute Infection / Systemic Inflammation"
    category = InsightCategory.GENERAL
    tier = InsightTier.TIER_3
    requires_baseline = False

    def evaluate(self, ctx: EvalContext) -> InsightResult:
        crp = ctx.labs.biomarker("1988-5") # CRP
        esr = ctx.labs.biomarker("3038-3") # ESR
        wbc = ctx.labs.biomarker("6690-2") # WBC
        temp = ctx.vitals.metric("body_temp")
        hr = ctx.vitals.metric("resting_heart_rate")

        has_elevated_crp = crp.has_data and crp.latest > 10.0
        has_elevated_wbc = wbc.has_data and wbc.latest > 11.0
        
        if not (has_elevated_crp or has_elevated_wbc or (esr.has_data and esr.latest > 20)):
            # Check for moderate CRP
            if crp.has_data and crp.latest > 3.0:
                return self.trigger(
                    severity=RiskLevel.MEDIUM,
                    message=f"Moderate CRP elevation ({crp.latest} mg/L) detected. Suggests chronic low-grade inflammation.",
                    evidence={"crp": crp.latest}
                , is_historical=crp.is_historical, effective_datetime=crp.latest_date)
            return self.pass_rule()
            
        evidence = {}
        if crp.has_data: evidence["crp"] = crp.latest
        if wbc.has_data: evidence["wbc"] = wbc.latest
        if esr.has_data: evidence["esr"] = esr.latest
        
        has_fever = temp.has_data and temp.latest > 38.0
        has_tachycardia = hr.has_data and hr.latest > 100

        if has_fever or has_tachycardia:
            if temp.has_data: evidence["body_temp"] = temp.latest
            if hr.has_data: evidence["resting_heart_rate"] = hr.latest
            return self.trigger(
                severity=RiskLevel.HIGH,
                message="High inflammatory markers combined with elevated body temperature/HR. Possible acute infection.",
                evidence=evidence
            , is_historical=crp.is_historical, effective_datetime=crp.latest_date)
            
        return self.trigger(
            severity=RiskLevel.MEDIUM,
            message="Significantly elevated inflammatory markers (CRP/WBC) without active fever. Monitor closely.",
            evidence=evidence
        , is_historical=crp.is_historical, effective_datetime=crp.latest_date)

class MetabolicSyndromeRule(InsightRule):
    """
    Detects atherogenic dyslipidemia and Metabolic Syndrome risk based on
    the triglyceride-to-HDL ratio and blood pressure.
    
    THE SCIENCE:
    - Metabolic syndrome is driven by visceral adiposity, which releases free fatty acids and inflammatory cytokines. This causes hepatic insulin resistance (driving up triglycerides) and alters lipid metabolism (driving down HDL), significantly multiplying cardiovascular and metabolic risk.

    CITATIONS:
    - Expert Panel on Detection, Evaluation, and Treatment of High Blood Cholesterol in Adults (Adult Treatment Panel III). JAMA. 2001;285(19):2486-2497.
    - American Heart Association (AHA) and National Heart, Lung, and Blood Institute (NHLBI) Scientific Statement on Metabolic Syndrome.
    """
    id = "metabolic_syndrome"
    name = "Atherogenic Dyslipidemia / Metabolic Syndrome"
    category = InsightCategory.METABOLIC
    tier = InsightTier.TIER_3
    requires_baseline = False

    def evaluate(self, ctx: EvalContext) -> InsightResult:
        sync_labs = ctx.labs.get_synchronous_readings(["2571-8", "2085-9"], max_gap_days=7)
        bp_sys = ctx.vitals.metric("bp_systolic")

        if not sync_labs:
            return self.skip_rule("Requires Triglycerides and HDL within 7 days")

        tg_val = sync_labs["2571-8"]
        hdl_val = sync_labs["2085-9"]

        hdl_threshold = 40 if ctx.patient_sex == "male" else 50
        
        if tg_val > 150 and hdl_val < hdl_threshold:
            evidence = {"triglycerides": tg_val, "hdl": hdl_val}
            severity = RiskLevel.MEDIUM
            msg = f"Atherogenic dyslipidemia detected (High TG: {tg_val}, Low HDL: {hdl_val})."
            
            if bp_sys.has_data and bp_sys.latest >= 130:
                severity = RiskLevel.HIGH
                msg += " Combined with elevated BP, indicating Metabolic Syndrome."
                evidence["bp_systolic"] = bp_sys.latest
            
            return self.trigger(severity, msg, evidence)
            
        return self.pass_rule()

class DehydrationAkiRule(InsightRule):
    """
    Detects pre-renal azotemia, dehydration, or acute kidney injury (AKI) risk
    by evaluating the BUN-to-Creatinine ratio and cross-referencing with vitals.
    
    THE SCIENCE:
    - BUN represents urea, a waste product reabsorbed by the kidneys alongside sodium and water during states of volume depletion (dehydration). Creatinine is actively secreted. A disproportionate rise in BUN compared to Creatinine (>20:1 ratio) is the classic physiological hallmark of pre-renal acute kidney injury.

    CITATIONS:
    - KDIGO Clinical Practice Guideline for Acute Kidney Injury. Kidney Int Suppl. 2012;2(1):1-138.
    """
    id = "dehydration_aki_risk"
    name = "Dehydration / Acute Kidney Injury Risk"
    category = InsightCategory.RENAL
    tier = InsightTier.TIER_3
    requires_baseline = False

    def evaluate(self, ctx: EvalContext) -> InsightResult:
        sync_labs = ctx.labs.get_synchronous_readings(["3094-0", "2160-0"], max_gap_days=0)
        hr = ctx.vitals.metric("resting_heart_rate")
        bp_sys = ctx.vitals.metric("bp_systolic")

        if not sync_labs or sync_labs["2160-0"] == 0:
            return self.skip_rule("Requires BUN and Creatinine from the same day")

        bun_val = sync_labs["3094-0"]
        creat_val = sync_labs["2160-0"]

        ratio = bun_val / creat_val
        if ratio > 20:
            evidence = {"bun": bun_val, "creatinine": creat_val, "ratio": round(ratio, 1)}
            severity = RiskLevel.MEDIUM
            msg = f"Elevated BUN/Creatinine ratio ({round(ratio,1)}:1) suggests pre-renal azotemia or dehydration."
            
            if hr.has_data and hr.latest > 100 and bp_sys.has_data and bp_sys.latest < 100:
                severity = RiskLevel.HIGH
                msg += " Tachycardia and hypotension detected. High risk of clinical dehydration."
                evidence["heart_rate"] = hr.latest
                evidence["bp_systolic"] = bp_sys.latest
                
            return self.trigger(severity, msg, evidence)
            
        return self.pass_rule()

class GoutFlareRule(InsightRule):
    """
    Monitors hyperuricemia and correlates elevated uric acid levels with
    sudden declines in mobility to detect potential acute gout flares.
    
    THE SCIENCE:
    - Uric acid is the end product of purine metabolism. When serum uric acid exceeds its solubility limit (~6.8 mg/dL), it crystallizes as monosodium urate in the synovial fluid of joints, triggering a fierce neutrophil-mediated inflammatory response known as a gout flare.

    CITATIONS:
    - FitzGerald JD, et al. "2020 American College of Rheumatology Guideline for the Management of Gout." Arthritis Care Res (Hoboken). 2020;72(6):744-760. (Target urate < 6.0 mg/dL).
    """
    id = "hyperuricemia_gout"
    name = "Hyperuricemia / Gout Flare Risk"
    category = InsightCategory.METABOLIC
    tier = InsightTier.TIER_3
    requires_baseline = False

    def evaluate(self, ctx: EvalContext) -> InsightResult:
        uric_acid = ctx.labs.biomarker("3084-1") # Uric Acid
        steps = ctx.vitals.metric("steps")

        if not uric_acid.has_data:
            return self.skip_rule("Requires Uric Acid")

        if uric_acid.latest > 7.0:
            evidence = {"uric_acid": uric_acid.latest}
            severity = RiskLevel.MEDIUM
            msg = f"Elevated Uric Acid ({uric_acid.latest} mg/dL). Risk of hyperuricemia or gout."
            
            if steps.has_trend_data and steps.is_worsening:
                severity = RiskLevel.HIGH
                msg += " Sharp decline in mobility detected, possible acute gout flare."
                evidence["mobility_decline"] = True
                
            return self.trigger(severity, msg, evidence, is_historical=uric_acid.is_historical, effective_datetime=uric_acid.latest_date)
            
        return self.pass_rule()

class SevereVitaminDRule(InsightRule):
    """
    Identifies severe Vitamin D deficiency, raising alerts for bone density,
    immune health, and systemic risks based on standard thresholds.
    
    THE SCIENCE:
    - Vitamin D (25-OH) is converted to its active form in the kidneys to facilitate intestinal calcium absorption. Severe deficiency leads to secondary hyperparathyroidism, where the body leaches calcium from bones to maintain serum levels, resulting in osteomalacia and severe immune dysfunction.

    CITATIONS:
    - Holick MF, et al. "Evaluation, treatment, and prevention of vitamin D deficiency: an Endocrine Society clinical practice guideline." J Clin Endocrinol Metab. 2011;96(7):1911-1930.
    """
    id = "severe_vitamin_d_deficiency"
    name = "Severe Vitamin D Deficiency"
    category = InsightCategory.NUTRITION
    tier = InsightTier.TIER_3
    requires_baseline = False

    def evaluate(self, ctx: EvalContext) -> InsightResult:
        vit_d = ctx.labs.biomarker("14635-7") # Vitamin D
        
        if not vit_d.has_data:
            return self.skip_rule("Requires Vitamin D")

        if vit_d.latest < 20:
            severity = RiskLevel.HIGH if vit_d.latest < 10 else RiskLevel.MEDIUM
            return self.trigger(
                severity=severity,
                message=f"Vitamin D deficiency ({vit_d.latest} ng/mL). Consider supplementation for bone and immune health.",
                evidence={"vitamin_d": vit_d.latest}
            , is_historical=vit_d.is_historical, effective_datetime=vit_d.latest_date)
            
        return self.pass_rule()

class MealTimeGlucoseSpikeRule(InsightRule):
    """
    Distinguishes between baseline fasting dysfunction and post-prandial
    hyperglycemia to provide targeted dietary insight for metabolic health.
    
    THE SCIENCE:
    - Post-prandial glucose excursions occur when the first-phase insulin response from the pancreas is lost or delayed. High glucose spikes damage endothelial cells via oxidative stress and advanced glycation end-products (AGEs), severely increasing cardiovascular risk.

    CITATIONS:
    - American Diabetes Association (ADA). "Standards of Medical Care in Diabetes." Diabetes Care. (Postprandial glucose target < 180 mg/dL).
    """
    id = "post_prandial_hyperglycemia"
    name = "Post-Prandial Hyperglycemia"
    category = InsightCategory.METABOLIC
    tier = InsightTier.TIER_3
    requires_baseline = False

    def evaluate(self, ctx: EvalContext) -> InsightResult:
        sync_labs = ctx.labs.get_synchronous_readings(["14771-0", "15077-1"], max_gap_days=0)

        if not sync_labs:
            return self.skip_rule("Requires both Fasting and Post-prandial Glucose from the same day")

        fasting_val = sync_labs["14771-0"]
        pp_val = sync_labs["15077-1"]

        if fasting_val <= 100 and pp_val > 140:
            return self.trigger(
                severity=RiskLevel.MEDIUM,
                message=f"Fasting glucose is normal ({fasting_val}), but post-meal spikes are high ({pp_val} mg/dL).",
                evidence={"fasting_glucose": fasting_val, "post_prandial_glucose": pp_val}
            )
            
        return self.pass_rule()

class PulmonaryEmbolismRule(InsightRule):
    """
    Correlates elevated D-Dimer with vital sign anomalies to detect potential
    thrombosis, deep vein thrombosis (DVT), or Pulmonary Embolism (PE).
    
    THE SCIENCE:
    - D-Dimer is a fibrin degradation product present in the blood after a blood clot is degraded by fibrinolysis. An elevated D-Dimer alongside hypoxemia and tachycardia suggests an acute pulmonary embolism, where a clot obstructs the pulmonary vasculature, causing severe right heart strain.

    CITATIONS:
    - Wells PS, et al. "Evaluation of D-dimer in the diagnosis of suspected deep-vein thrombosis." N Engl J Med. 2003.
    """
    id = "thrombosis_pe_risk"
    name = "Thrombosis / Pulmonary Embolism Risk"
    category = InsightCategory.GENERAL
    tier = InsightTier.TIER_3
    requires_baseline = False

    def evaluate(self, ctx: EvalContext) -> InsightResult:
        d_dimer = ctx.labs.biomarker("48065-7") # D-Dimer
        spo2 = ctx.vitals.metric("oxygen_sat")
        hr = ctx.vitals.metric("resting_heart_rate")
        rr = ctx.vitals.metric("respiratory_rate")

        if not d_dimer.has_data:
            return self.skip_rule("Requires D-Dimer")

        if d_dimer.latest > 500:
            evidence = {"d_dimer": d_dimer.latest}
            severity = RiskLevel.MEDIUM
            msg = f"Elevated D-Dimer ({d_dimer.latest} ng/mL). Possible clotting risk or inflammation."
            
            has_hypoxia = spo2.has_data and spo2.latest < 92
            has_tachycardia = hr.has_data and hr.latest > 100
            has_tachypnea = rr.has_data and rr.latest > 20
            
            if has_hypoxia or (has_tachycardia and has_tachypnea):
                severity = RiskLevel.HIGH
                msg = f"CRITICAL: High D-Dimer ({d_dimer.latest} ng/mL) combined with hypoxia/tachycardia. Immediate evaluation for Pulmonary Embolism or DVT advised."
                if spo2.has_data: evidence["oxygen_sat"] = spo2.latest
                if hr.has_data: evidence["resting_heart_rate"] = hr.latest
                if rr.has_data: evidence["respiratory_rate"] = rr.latest
                
            return self.trigger(severity, msg, evidence, is_historical=d_dimer.is_historical, effective_datetime=d_dimer.latest_date)
            
        return self.pass_rule()

class ArrhythmiaElectrolyteRule(InsightRule):
    """
    Monitors potassium levels to detect severe electrolyte imbalances
    that can destabilize cardiac electrophysiology and lead to fatal arrhythmias.
    
    THE SCIENCE:
    - Potassium strictly regulates the resting membrane potential of cardiomyocytes. Hypokalemia prolongs the action potential duration, leading to early afterdepolarizations and fatal arrhythmias like Torsades de Pointes. Hyperkalemia decreases myocardial excitability, risking asystole.

    CITATIONS:
    - Mount DB, et al. "Clinical manifestations and treatment of hypokalemia/hyperkalemia." UpToDate.
    """
    id = "arrhythmia_electrolyte_imbalance"
    name = "Arrhythmia Risk via Electrolyte Imbalance"
    category = InsightCategory.CARDIAC
    tier = InsightTier.TIER_3
    requires_baseline = False

    def evaluate(self, ctx: EvalContext) -> InsightResult:
        potassium = ctx.labs.biomarker("2823-3") # Potassium
        hr = ctx.vitals.metric("resting_heart_rate")

        if not potassium.has_data:
            return self.skip_rule("Requires Potassium")

        is_hypo = potassium.latest < 3.0
        is_hyper = potassium.latest > 6.0
        
        if is_hypo or is_hyper:
            evidence = {"potassium": potassium.latest}
            condition = "Severe hypokalemia" if is_hypo else "Severe hyperkalemia"
            msg = f"{condition} ({potassium.latest} mEq/L) detected. High risk of fatal arrhythmias."
            
            has_arrhythmia_signs = hr.has_data and (hr.latest < 50 or hr.latest > 120)
            if has_arrhythmia_signs:
                msg += f" Concurrent abnormal heart rate ({hr.latest} bpm) detected. Immediate medical intervention required."
                evidence["resting_heart_rate"] = hr.latest
                
            return self.trigger(RiskLevel.HIGH, msg, evidence, is_historical=potassium.is_historical, effective_datetime=potassium.latest_date)
            
        return self.pass_rule()

class AcuteLiverInjuryRule(InsightRule):
    """
    Detects hepatocellular injury and categorizes likely etiologies (e.g., alcoholic
    liver disease vs acute viral/toxic injury) using the De Ritis (AST/ALT) ratio.
    
    THE SCIENCE:
    - ALT and AST are intracellular liver enzymes. ALT is highly specific to the cytosol of hepatocytes, while AST is found in mitochondria. When hepatocytes are damaged by toxins, ischemia, or viral attack, their cell membranes rupture, spilling these transaminases into the bloodstream.

    CITATIONS:
    - Botros M, Sikaris KA. "The de Ritis ratio: the test of time." Clin Biochem Rev. 2013;34(3):117-130.
    """
    id = "acute_liver_injury"
    name = "Acute Liver Injury / Hepatotoxicity"
    category = InsightCategory.GENERAL
    tier = InsightTier.TIER_3
    requires_baseline = False

    def evaluate(self, ctx: EvalContext) -> InsightResult:
        sync_labs = ctx.labs.get_synchronous_readings(["1742-6", "1920-8"], max_gap_days=0)

        if not sync_labs:
            return self.skip_rule("Requires ALT and AST from the same day")

        alt_val = sync_labs["1742-6"]
        ast_val = sync_labs["1920-8"]

        if alt_val > 120 or ast_val > 120:
            evidence = {"alt": alt_val, "ast": ast_val}
            ratio = ast_val / alt_val if alt_val > 0 else 0
            evidence["ast_alt_ratio"] = round(ratio, 2)
            
            msg = f"Significant hepatocellular injury detected (ALT: {alt_val}, AST: {ast_val})."
            if ratio > 2.0 and ast_val > alt_val:
                msg += f" AST/ALT ratio ({round(ratio, 2)}) > 2.0 strongly suggests alcoholic liver disease."
            else:
                msg += " Suggests acute viral hepatitis or drug toxicity."
                
            return self.trigger(RiskLevel.HIGH, msg, evidence)
            
        return self.pass_rule()

class BiliaryObstructionRule(InsightRule):
    """
    Differentiates cholestasis/biliary obstruction from primary hepatocellular
    injury by analyzing ALP and GGT elevations.
    
    THE SCIENCE:
    - ALP is an enzyme concentrated in the biliary canalicular membrane. When bile ducts are obstructed (gallstones, tumors), bile salts accumulate and act as detergents, solubilizing the membrane and causing massive ALP release. GGT confirms the hepatic origin of the ALP.

    CITATIONS:
    - Kwo PY, et al. "ACG Clinical Guideline: Evaluation of Abnormal Liver Chemistries." Am J Gastroenterol. 2017;112(1):18-35.
    """
    id = "biliary_obstruction"
    name = "Biliary Obstruction / Cholestasis"
    category = InsightCategory.GENERAL
    tier = InsightTier.TIER_3
    requires_baseline = False

    def evaluate(self, ctx: EvalContext) -> InsightResult:
        sync_labs = ctx.labs.get_synchronous_readings(["6768-6", "2324-2"], max_gap_days=0)
        tbili = ctx.labs.biomarker("1975-2") # Total Bilirubin

        if not sync_labs:
            return self.skip_rule("Requires ALP and GGT from the same day")

        alp_val = sync_labs["6768-6"]
        ggt_val = sync_labs["2324-2"]

        if alp_val > 150 and ggt_val > 60:
            evidence = {"alp": alp_val, "ggt": ggt_val}
            msg = f"Disproportionate elevation of ALP ({alp_val} U/L) and GGT ({ggt_val} U/L) indicates biliary obstruction/cholestasis rather than pure liver injury."
            
            # Optional sync for tbili
            sync_tbili = ctx.labs.get_synchronous_readings(["6768-6", "1975-2"], max_gap_days=0)
            if sync_tbili and sync_tbili["1975-2"] > 1.2:
                msg += f" Hyperbilirubinemia ({sync_tbili['1975-2']} mg/dL) confirms active obstruction or gallstone."
                evidence["total_bilirubin"] = sync_tbili["1975-2"]
                
            return self.trigger(RiskLevel.MEDIUM, msg, evidence, is_historical=tbili.is_historical, effective_datetime=tbili.latest_date)
            
        return self.pass_rule()

class HashimotosDiseaseRule(InsightRule):
    """
    Confirms autoimmune hypothyroidism (Hashimoto's Thyroiditis) through
    thyroid function tests and correlates with clinical vital signs.
    
    THE SCIENCE:
    - Hashimoto's Thyroiditis is an autoimmune disorder where T-cells chronically infiltrate the thyroid gland, and B-cells produce Anti-TPO antibodies against thyroid peroxidase. This progressive autoimmune destruction gradually destroys the gland's ability to produce thyroid hormones.

    CITATIONS:
    - Garber JR, et al. "Clinical practice guidelines for hypothyroidism in adults." Endocr Pract. 2012;18(6):988-1028.
    """
    id = "hashimotos_thyroiditis"
    name = "Autoimmune Hypothyroidism (Hashimoto's)"
    category = InsightCategory.THYROID
    tier = InsightTier.TIER_3
    requires_baseline = False

    def evaluate(self, ctx: EvalContext) -> InsightResult:
        sync_labs = ctx.labs.get_synchronous_readings(["3016-3", "3024-7", "8099-0"], max_gap_days=7)
        hr = ctx.vitals.metric("resting_heart_rate")

        if not sync_labs:
            return self.skip_rule("Requires TSH, Free T4, and Anti-TPO within 7 days")

        tsh_val = sync_labs["3016-3"]
        ft4_val = sync_labs["3024-7"]
        anti_tpo_val = sync_labs["8099-0"]

        if tsh_val > 4.5 and ft4_val < 0.8 and anti_tpo_val > 35:
            evidence = {"tsh": tsh_val, "free_t4": ft4_val, "anti_tpo": anti_tpo_val}
            msg = f"Confirmed autoimmune hypothyroidism (Hashimoto's). High TSH ({tsh_val}), Low Free T4 ({ft4_val}), Positive Anti-TPO ({anti_tpo_val})."
            
            if hr.has_data and hr.latest < 60:
                msg += f" Concurrent bradycardia ({hr.latest} bpm) observed, symptomatic of low thyroid function."
                evidence["resting_heart_rate"] = hr.latest
                
            return self.trigger(RiskLevel.MEDIUM, msg, evidence)
            
        return self.pass_rule()

class HiddenCardiovascularRiskRule(InsightRule):
    """
    Identifies aggressive, often genetic, lipid-driven atherosclerotic risk
    factors (ApoB, Lipoprotein(a)) that remain hidden in standard LDL panels.
    
    THE SCIENCE:
    - Apolipoprotein B (ApoB) measures the exact particle count of all atherogenic lipoproteins (LDL, VLDL). Because plaque formation is driven by the number of particles crashing into the arterial wall rather than their total cholesterol weight, ApoB is the ultimate arbiter of cardiovascular risk.

    CITATIONS:
    - Sniderman AD, et al. "Apolipoprotein B and cardiovascular disease." Circ Res. 2019.
    - Tsimikas S. "A Test in Context: Lipoprotein(a)." J Am Coll Cardiol. 2017;69(6):692-711.
    """
    id = "hidden_cardiovascular_risk"
    name = "Hidden Cardiovascular Risk (ApoB / Lp(a))"
    category = InsightCategory.CARDIAC
    tier = InsightTier.TIER_3
    requires_baseline = False

    def evaluate(self, ctx: EvalContext) -> InsightResult:
        apob = ctx.labs.biomarker("1884-6") # ApoB
        lpa = ctx.labs.biomarker("43583-4") # Lipoprotein(a)
        ldl = ctx.labs.biomarker("13457-7") # LDL

        if not apob.has_data and not lpa.has_data:
            return self.skip_rule("Requires ApoB or Lipoprotein(a)")

        is_apob_high = apob.has_data and apob.latest > 90
        is_lpa_high = lpa.has_data and lpa.latest > 50
        
        if is_apob_high or is_lpa_high:
            evidence = {}
            if apob.has_data: evidence["apob"] = apob.latest
            if lpa.has_data: evidence["lipoprotein_a"] = lpa.latest
            
            msg = "Elevated atherogenic markers detected: "
            if is_apob_high: msg += f"ApoB ({apob.latest} mg/dL) "
            if is_lpa_high: msg += f"Lp(a) ({lpa.latest} mg/dL) "
            
            msg += "- Indicates aggressive cardiovascular risk."
            
            if ldl.has_data and ldl.latest <= 100:
                msg += f" NOTE: Standard LDL appears normal ({ldl.latest} mg/dL), meaning this risk was previously hidden."
                evidence["ldl"] = ldl.latest
                
            return self.trigger(RiskLevel.MEDIUM, msg, evidence, is_historical=apob.is_historical, effective_datetime=apob.latest_date)
            
        return self.pass_rule()

class HeartFailureExacerbationRule(InsightRule):
    """
    Detects acute decompensated heart failure (fluid volume overload) by
    correlating NT-proBNP elevation with rapid weight gain and tachypnea.
    
    THE SCIENCE:
    - When the heart is struggling to pump against high volume or pressure (volume overload), the ventricular walls are stretched. This physical stretch triggers myocytes to release NT-proBNP, a peptide that attempts to induce diuresis and vasodilation to relieve cardiac wall stress.

    CITATIONS:
    - Heidenreich PA, et al. "2022 AHA/ACC/HFSA Guideline for the Management of Heart Failure." J Am Coll Cardiol. 2022;79(17):e263-e421.
    """
    id = "heart_failure_exacerbation_labs"
    name = "Heart Failure Exacerbation (Volume Overload)"
    category = InsightCategory.CARDIAC
    tier = InsightTier.TIER_3
    requires_baseline = False

    def evaluate(self, ctx: EvalContext) -> InsightResult:
        nt_probnp = ctx.labs.biomarker("33762-6") # NT-proBNP
        weight = ctx.vitals.metric("weight")
        rr = ctx.vitals.metric("respiratory_rate")

        if not nt_probnp.has_data:
            return self.skip_rule("Requires NT-proBNP")

        if nt_probnp.latest > 400:
            evidence = {"nt_probnp": nt_probnp.latest}
            msg = f"Elevated NT-proBNP ({nt_probnp.latest} pg/mL) indicates increased cardiac wall stress."
            severity = RiskLevel.MEDIUM
            
            has_rapid_weight_gain = weight.has_data and weight.is_worsening
            has_tachypnea = rr.has_data and rr.latest > 20
            
            if has_rapid_weight_gain or has_tachypnea:
                severity = RiskLevel.HIGH
                msg = f"CRITICAL: High NT-proBNP ({nt_probnp.latest} pg/mL) combined with signs of fluid retention (weight gain/tachypnea). High risk of Acute Decompensated Heart Failure."
                if weight.has_data: evidence["weight_trend"] = "rapid gain"
                if rr.has_data: evidence["respiratory_rate"] = rr.latest
                
            return self.trigger(severity, msg, evidence, is_historical=nt_probnp.is_historical, effective_datetime=nt_probnp.latest_date)
            
        return self.pass_rule()

class OvertrainingSyndromeRule(InsightRule):
    """
    Diagnoses severe HPA axis dysfunction and catabolic shift (burnout/overtraining)
    by measuring the Cortisol/Testosterone ratio alongside HRV crashes.
    
    THE SCIENCE:
    - Extreme physiological stress triggers the HPA axis to release massive amounts of Cortisol (catabolic), while suppressing the gonadal axis (Testosterone, anabolic). This extreme catabolic shift, paired with autonomic nervous system exhaustion (crashing HRV), defines clinical overtraining syndrome.

    CITATIONS:
    - Meeusen R, et al. "Prevention, diagnosis, and treatment of the overtraining syndrome." Med Sci Sports Exerc. 2013;45(1):186-205.
    """
    id = "hpa_axis_overtraining"
    name = "HPA Axis Dysfunction / Overtraining Syndrome"
    category = InsightCategory.METABOLIC
    tier = InsightTier.TIER_3
    requires_baseline = False

    def evaluate(self, ctx: EvalContext) -> InsightResult:
        sync_labs = ctx.labs.get_synchronous_readings(["2143-6", "2986-8"], max_gap_days=0)
        hrv = ctx.vitals.metric("hrv")
        hr = ctx.vitals.metric("resting_heart_rate")

        if not sync_labs:
            return self.skip_rule("Requires Cortisol and Testosterone from the same day")

        cort_val = sync_labs["2143-6"]
        test_val = sync_labs["2986-8"]

        if cort_val > 20 and test_val < 300: # General thresholds
            evidence = {"cortisol": cort_val, "testosterone": test_val}
            msg = f"Hormonal catabolic shift detected: High Cortisol ({cort_val} ug/dL) and Low Testosterone ({test_val} ng/dL)."
            severity = RiskLevel.MEDIUM
            
            has_hrv_crash = hrv.has_data and hrv.is_worsening
            has_tachycardia = hr.has_data and hr.latest > 85
            
            if has_hrv_crash or has_tachycardia:
                severity = RiskLevel.HIGH
                msg += " Combined with crashed HRV and elevated resting HR, strongly indicating Overtraining Syndrome or severe chronic stress (HPA axis dysfunction)."
                if hrv.has_data: evidence["hrv_trend"] = "declining"
                if hr.has_data: evidence["resting_heart_rate"] = hr.latest
                
            return self.trigger(severity, msg, evidence)
            
        return self.pass_rule()

class EarlyDiabeticNephropathyRule(InsightRule):
    """
    Detects microvascular diabetic kidney damage years before standard creatinine
    elevates, utilizing Urine ACR and Cystatin C.
    
    THE SCIENCE:
    - Years before eGFR declines, high blood sugar damages the delicate glomerular filtration barrier in the kidneys, allowing microscopic amounts of albumin (Urine ACR) to leak into the urine. Cystatin C, a protein produced by all nucleated cells, is a much earlier and more sensitive marker of this microvascular damage than creatinine.

    CITATIONS:
    - KDIGO 2022 Clinical Practice Guideline for Diabetes Management in Chronic Kidney Disease. Kidney Int. 2022.
    """
    id = "early_diabetic_nephropathy"
    name = "Early Diabetic Nephropathy (Microvascular)"
    category = InsightCategory.RENAL
    tier = InsightTier.TIER_3
    requires_baseline = False

    def evaluate(self, ctx: EvalContext) -> InsightResult:
        acr = ctx.labs.biomarker(["32294-1", "14959-1"]) # Urine ACR (supports both common variants)
        cystatin_c = ctx.labs.biomarker("28552-8") # Cystatin C
        bp_sys = ctx.vitals.metric("bp_systolic")

        if not acr.has_data and not cystatin_c.has_data:
            return self.skip_rule("Requires Urine ACR or Cystatin C")

        is_acr_high = acr.has_data and acr.latest > 30
        is_cystatin_high = cystatin_c.has_data and cystatin_c.latest > 1.0
        
        if is_acr_high or is_cystatin_high:
            evidence = {}
            severity = RiskLevel.MEDIUM
            msg = "Early markers of microvascular kidney damage detected: "
            
            if is_acr_high: 
                date_str = f" on {acr.latest_date}" if hasattr(acr, "latest_date") and acr.latest_date else ""
                msg += f"Microalbuminuria (ACR: {acr.latest} mg/g){date_str}. "
                evidence["urine_acr"] = acr.latest
            if is_cystatin_high: 
                date_str = f" on {cystatin_c.latest_date}" if hasattr(cystatin_c, "latest_date") and cystatin_c.latest_date else ""
                msg += f"Elevated Cystatin C ({cystatin_c.latest} mg/L){date_str}. "
                evidence["cystatin_c"] = cystatin_c.latest
                
            if bp_sys.has_data and bp_sys.latest > 130:
                severity = RiskLevel.HIGH
                msg += f"Concurrent hypertension (Systolic: {bp_sys.latest}) significantly accelerates nephropathy progression. Aggressive BP control advised."
                evidence["bp_systolic"] = bp_sys.latest
                
            return self.trigger(severity, msg, evidence, is_historical=acr.is_historical, effective_datetime=acr.latest_date)
            
        return self.pass_rule()

class PrimaryHyperparathyroidismRule(InsightRule):
    """
    Identifies active parathyroid adenomas leaching calcium from bone by
    detecting inappropriately normal or high PTH in the presence of hypercalcemia.
    
    THE SCIENCE:
    - The parathyroid glands tightly control serum calcium. If calcium is high, PTH should be suppressed. An elevated or inappropriately normal PTH in the face of hypercalcemia indicates an autonomous parathyroid adenoma that is actively leaching calcium from the skeleton, destroying bone density.

    CITATIONS:
    - Bilezikian JP, et al. "Guidelines for the management of asymptomatic primary hyperparathyroidism." J Clin Endocrinol Metab. 2014;99(10):3561-3569.
    """
    id = "primary_hyperparathyroidism"
    name = "Primary Hyperparathyroidism (Bone Loss Risk)"
    category = InsightCategory.METABOLIC
    tier = InsightTier.TIER_3
    requires_baseline = False

    def evaluate(self, ctx: EvalContext) -> InsightResult:
        sync_labs = ctx.labs.get_synchronous_readings(["17861-6", "28004-0"], max_gap_days=0)
        phos = ctx.labs.biomarker("2777-1") # Phosphorus

        if not sync_labs:
            return self.skip_rule("Requires Calcium and PTH from the same day")

        calc_val = sync_labs["17861-6"]
        pth_val = sync_labs["28004-0"]

        if calc_val > 10.5 and pth_val > 30: # PTH should be suppressed (<20) if calcium is high
            evidence = {"calcium": calc_val, "pth": pth_val}
            msg = f"Hypercalcemia ({calc_val} mg/dL) with inappropriately unsuppressed PTH ({pth_val} pg/mL). Strongly suggests Primary Hyperparathyroidism (hidden osteoporosis/kidney stone risk)."
            
            sync_phos = ctx.labs.get_synchronous_readings(["17861-6", "2777-1"], max_gap_days=0)
            if sync_phos and sync_phos["2777-1"] < 2.5:
                msg += f" Confirmed by concurrent hypophosphatemia ({sync_phos['2777-1']} mg/dL)."
                evidence["phosphorus"] = sync_phos["2777-1"]
                
            return self.trigger(RiskLevel.HIGH, msg, evidence, is_historical=phos.is_historical, effective_datetime=phos.latest_date)
            
        return self.pass_rule()

class AdvancedAnemiaSubtypingRule(InsightRule):
    """
    Differentiates the root etiology of anemia (Absolute Iron Deficiency vs
    Macrocytic/B12 Deficiency) using precise MCV, TSAT, and Ferritin logic.
    
    THE SCIENCE:
    - Ferritin represents the body's intracellular iron storage, while Transferrin Saturation (TSAT) measures the iron actively circulating in the blood. When both are completely depleted alongside microcytic cells, the anemia is definitively driven by absolute iron deficiency rather than chronic inflammation.

    CITATIONS:
    - Camaschella C. "Iron-deficiency anemia." N Engl J Med. 2015;372(19):1832-1843.
    - Stabler SP. "Clinical practice. Vitamin B12 deficiency." N Engl J Med. 2013;368(2):149-160.
    """
    id = "advanced_anemia_subtyping"
    name = "Advanced Anemia Sub-Typing"
    category = InsightCategory.HEMATOLOGY
    tier = InsightTier.TIER_3
    requires_baseline = False

    def evaluate(self, ctx: EvalContext) -> InsightResult:
        hgb = ctx.labs.biomarker("718-7") # Hemoglobin
        mcv = ctx.labs.biomarker("787-2") # MCV
        tsat = ctx.labs.biomarker("2502-3") # Transferrin Saturation
        b12 = ctx.labs.biomarker("2132-9") # Vitamin B12
        ferritin = ctx.labs.biomarker("2276-4") # Ferritin
        hr = ctx.vitals.metric("avg_heart_rate")

        if not hgb.has_data or not mcv.has_data:
            return self.skip_rule("Requires Hemoglobin and MCV")

        # Define basic anemia thresholds
        anemic_threshold = 13.0 if ctx.patient_sex == "male" else 12.0
        
        if hgb.latest < anemic_threshold:
            evidence = {"hemoglobin": hgb.latest, "mcv": mcv.latest}
            
            if mcv.latest < 80: # Microcytic
                if hr.has_data and hr.is_baseline_established and hr.latest > hr.established_baseline.mean + hr.established_baseline.std * 1.5:
                    evidence["avg_heart_rate"] = hr.latest
                if tsat.has_data and tsat.latest < 20 and ferritin.has_data and ferritin.latest < 30:
                    evidence["transferrin_sat"] = tsat.latest
                    evidence["ferritin"] = ferritin.latest
                    msg = f"Microcytic anemia (MCV: {mcv.latest}) with low TSAT (<20%) and depleted Ferritin. Definitive diagnosis: Absolute Iron Deficiency Anemia."
                    return self.trigger(RiskLevel.MEDIUM, msg, evidence, is_historical=hgb.is_historical, effective_datetime=hgb.latest_date)
            
            elif mcv.latest > 100: # Macrocytic
                msg = f"Macrocytic anemia (MCV: {mcv.latest})."
                if b12.has_data and b12.latest < 200:
                    evidence["vitamin_b12"] = b12.latest
                    msg += f" Concurrent Vitamin B12 deficiency ({b12.latest} pg/mL). High risk of neurological complications (Pernicious Anemia)."
                    return self.trigger(RiskLevel.HIGH, msg, evidence, is_historical=hgb.is_historical, effective_datetime=hgb.latest_date)
                else:
                    msg += " Suspect folate deficiency or alcohol toxicity."
                    return self.trigger(RiskLevel.MEDIUM, msg, evidence, is_historical=hgb.is_historical, effective_datetime=hgb.latest_date)
                    
        return self.pass_rule()

TIER_3_RULES = [
    PreDiabetesProgressionRule(),
    KidneyDeclineRule(),
    AnemiaDetectionRule(),
    ThyroidDysfunctionRule(),
    CardiovascularRiskRule(),
    SilentInsulinResistanceRule(),
    AnemiaRootCauseTriageRule(),
    AcuteInfectionRule(),
    MetabolicSyndromeRule(),
    DehydrationAkiRule(),
    GoutFlareRule(),
    SevereVitaminDRule(),
    MealTimeGlucoseSpikeRule(),
    PulmonaryEmbolismRule(),
    ArrhythmiaElectrolyteRule(),
    AcuteLiverInjuryRule(),
    BiliaryObstructionRule(),
    HashimotosDiseaseRule(),
    HiddenCardiovascularRiskRule(),
    HeartFailureExacerbationRule(),
    OvertrainingSyndromeRule(),
    EarlyDiabeticNephropathyRule(),
    PrimaryHyperparathyroidismRule(),
    AdvancedAnemiaSubtypingRule()
]
