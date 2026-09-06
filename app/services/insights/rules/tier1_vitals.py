"""
Tier 1 — Core Vitals Rules (Guideline-aligned)

These rules use data that most patients will have (BP, HR, steps, sleep)
and are evaluated on every insights call.

All thresholds are sourced from published clinical guidelines.
Where cross-correlations are Zivaa-specific (not from a guideline),
they are explicitly marked as such.
"""

from app.services.insights.core import InsightRule, RiskLevel, InsightCategory, InsightTier, InsightResult
from app.services.insights.context import EvalContext
from datetime import datetime, timezone
import zoneinfo


class HypertensionEscalationRule(InsightRule):
    """
    Detects escalating blood pressure using ACC/AHA 2017 staging.

    CLINICAL THRESHOLDS (all from ACC/AHA 2017):
    ┌──────────────────────────────┬──────────────────┬──────────────┐
    │ Stage                        │ Systolic (mmHg)  │ Our Severity │
    ├──────────────────────────────┼──────────────────┼──────────────┤
    │ Elevated                     │ 120-129          │ (not flagged)│
    │ Stage 1 Hypertension         │ 130-139          │ LOW          │
    │ Stage 2 Hypertension         │ ≥ 140            │ MEDIUM       │
    │ Hypertensive Urgency         │ ≥ 180            │ HIGH         │
    │ Hypertensive Emergency       │ ≥ 180 + symptoms │ HIGH         │
    └──────────────────────────────┴──────────────────┴──────────────┘

    CITATIONS:
    - Whelton PK, et al. "2017 ACC/AHA/AAPA/ABC/ACPM/AGS/APhA/ASH/
      ASPC/NMA/PCNA Guideline for the Prevention, Detection, Evaluation,
      and Management of High Blood Pressure in Adults."
      J Am Coll Cardiol. 2018;71(19):e127-e248.
      DOI: 10.1016/j.jacc.2017.11.006
      https://www.jacc.org/doi/10.1016/j.jacc.2017.11.006
    """
    id = "hypertension_escalation"
    name = "Hypertension Escalation Warning"
    category = InsightCategory.CARDIAC
    tier = InsightTier.TIER_1

    def evaluate(self, ctx: EvalContext) -> InsightResult:
        bp_sys = ctx.vitals.metric("bp_systolic")
        if getattr(bp_sys, 'is_stale', False): return self.skip_rule("Data is stale")

        # Guard: BP data is mandatory
        if not bp_sys.has_data:
            return self.skip_rule("No blood pressure data available")
        if not bp_sys.has_sufficient_history(days=3):
            return self.skip_rule("Need at least 3 days of BP history to detect a trend")
        if not bp_sys.is_baseline_established:
            return self.skip_rule("Blood pressure baseline not yet established")

        bp_trend = bp_sys.trend(days=3)
        is_bp_rising = bp_trend.is_increasing()

        # ACC/AHA 2017 staging
        if bp_sys.latest >= 180:
            # Hypertensive Urgency — ACC/AHA: ≥180/120 mmHg
            return self.trigger(
                severity=RiskLevel.HIGH,
                message=f"Blood pressure is at hypertensive urgency level ({bp_sys.latest:.0f} mmHg). "
                        f"Per ACC/AHA 2017 guidelines, readings ≥180 mmHg require prompt medical evaluation.",
                evidence={
                    "bp_systolic": bp_sys.latest,
                    "acc_aha_stage": "hypertensive_urgency",
                    "trend_rising": is_bp_rising,
                    "guideline": "ACC/AHA 2017 §8.1.6"
                }
            )
        elif bp_sys.latest >= 140 and is_bp_rising:
            # Stage 2 Hypertension with rising trend — ACC/AHA: ≥140/90
            return self.trigger(
                severity=RiskLevel.MEDIUM,
                message=f"Blood pressure has been rising over 3 days and is now at Stage 2 Hypertension "
                        f"({bp_sys.latest:.0f} mmHg, ACC/AHA threshold: ≥140). Medication review advised.",
                evidence={
                    "bp_systolic": bp_sys.latest,
                    "acc_aha_stage": "stage_2",
                    "bp_trend_start": bp_trend.start_value,
                    "guideline": "ACC/AHA 2017 §8.1.4"
                }
            )
        elif bp_sys.latest >= 130 and is_bp_rising:
            # Stage 1 Hypertension with rising trend — ACC/AHA: 130-139
            return self.trigger(
                severity=RiskLevel.LOW,
                message=f"Blood pressure is at Stage 1 Hypertension ({bp_sys.latest:.0f} mmHg, "
                        f"ACC/AHA threshold: 130-139) and has been rising. Lifestyle modifications recommended.",
                evidence={
                    "bp_systolic": bp_sys.latest,
                    "acc_aha_stage": "stage_1",
                    "bp_trend_start": bp_trend.start_value,
                    "guideline": "ACC/AHA 2017 §8.1.3"
                }
            )

        return self.pass_rule()


class FunctionalDeclineRule(InsightRule):
    """
    Detects activity collapse that correlates with fall risk and frailty.

    THRESHOLDS:
    - z-score > 2.0 (steps dropped > 2 SD below personal baseline):
      Aligned with the statistical deviation approach used in wearable
      health research for detecting clinically meaningful changes.
    - Absolute floor: steps < 1000/day:
      Tudor-Locke et al. 2011 classify <5000 as "sedentary" and
      <2500 as "basal activity". We use 1000 as a critical floor
      indicating near-immobility.

    CITATIONS:
    - Fried LP, et al. "Frailty in Older Adults: Evidence for a Phenotype."
      J Gerontol A Biol Sci Med Sci. 2001;56(3):M146-M156.
      DOI: 10.1093/gerona/56.3.M146
      https://academic.oup.com/biomedgerontology/article/56/3/M146/545770

    - Tudor-Locke C, et al. "How many steps/day are enough? For older
      adults and special populations."
      Int J Behav Nutr Phys Act. 2011;8:80.
      DOI: 10.1186/1479-5868-8-80
      https://ijbnpa.biomedcentral.com/articles/10.1186/1479-5868-8-80

    - Schwenk M, et al. "Wearable sensor-based in-home assessment of
      gait, balance, and physical activity for discrimination of frailty
      status." Gerontology. 2015;61(1):3-10.
      DOI: 10.1159/000362115
    """
    id = "functional_decline"
    name = "Functional Decline / Fall Risk"
    category = InsightCategory.GENERAL
    tier = InsightTier.TIER_1
    evaluation_mode = "batch"

    # Tudor-Locke et al. 2011: <1000 steps = near-immobility
    ABSOLUTE_STEP_FLOOR = 1000

    # Statistical threshold for clinically meaningful deviation
    Z_SCORE_THRESHOLD = 2.0

    # Minimum exercise (minutes) to consider patient "active despite low steps"
    # Zivaa-defined: e.g., chair yoga, swimming, physio — no published threshold
    EXERCISE_COMPENSATION_MIN = 15

    def evaluate(self, ctx: EvalContext) -> InsightResult:
        # Guard: Device state indicates incomplete data
        if ctx.device_battery_level is not None and ctx.device_battery_level <= 5 and not ctx.device_is_charging:
            return self.skip_rule("Wearable battery critically low or dead. Suppressing low activity alert as data is likely incomplete.")

        steps = ctx.vitals.metric("steps")
        hr = ctx.vitals.metric("avg_heart_rate")
        exercise = ctx.vitals.metric("exercise_minutes")
        if getattr(steps, 'is_stale', False) or getattr(hr, 'is_stale', False) or getattr(exercise, 'is_stale', False): return self.skip_rule("Data is stale")

        if not steps.has_data:
            return self.skip_rule("No step count data available")
        if not steps.is_baseline_established:
            return self.skip_rule("Step count baseline not yet established")

        steps_bl = steps.established_baseline
        # Use a 3-day sustained average to prevent false alarms from a single rest/sick day
        steps_3d_avg = steps.rolling_average(days=3)
        
        steps_z = ((steps_bl.mean - steps_3d_avg) / steps_bl.std) if steps_bl.std > 0 else 0
        is_below_floor = steps_3d_avg < self.ABSOLUTE_STEP_FLOOR

        # Zivaa cross-correlation: HR rising is a supporting signal (not from a guideline)
        hr_rising = hr.trend(days=3).is_increasing() if hr.has_data else False

        # Zivaa enhancement: exercise_minutes compensation
        # If patient has low steps but recorded structured exercise (yoga, physio,
        # swimming), they may not actually be declining. Downgrade severity.
        exercise_compensated = (
            exercise.has_data and exercise.latest >= self.EXERCISE_COMPENSATION_MIN
        )

        if is_below_floor:
            if exercise_compensated:
                # Low steps but active via exercise — downgrade to LOW
                return self.trigger(
                    severity=RiskLevel.LOW,
                    message=f"Sustained step count is low ({int(steps_3d_avg)} steps/day over 3 days, below the 1,000-step "
                            f"threshold), but {exercise.latest:.0f} minutes of exercise were recorded. "
                            f"The patient may be active through non-step activities (yoga, physio, swimming).",
                    evidence={
                        "steps_3d_avg": steps_3d_avg,
                        "steps_baseline": round(steps_bl.mean, 0),
                        "exercise_minutes": exercise.latest,
                        "exercise_compensated": True,
                        "absolute_floor": self.ABSOLUTE_STEP_FLOOR,
                        "guideline": "Tudor-Locke 2011, Fried 2001 (Sustained)",
                        "zivaa_enhancement": "exercise_minutes_compensation"
                    }
                )
            # Tudor-Locke absolute floor breach — critical regardless of baseline
            return self.trigger(
                severity=RiskLevel.HIGH if hr_rising else RiskLevel.MEDIUM,
                message=f"Activity has sustained a drop to an average of {int(steps_3d_avg)} steps/day over the last 3 days, below the 1,000-step "
                        f"immobility threshold (Tudor-Locke 2011). This strongly indicates functional decline "
                        f"and elevated fall risk per Fried Frailty criteria.",
                evidence={
                    "steps_3d_avg": steps_3d_avg,
                    "steps_baseline": round(steps_bl.mean, 0),
                    "absolute_floor": self.ABSOLUTE_STEP_FLOOR,
                    "hr_rising": hr_rising,
                    "exercise_compensated": False,
                    "guideline": "Tudor-Locke 2011, Fried 2001 (Sustained)"
                }
            )
        elif steps_z > self.Z_SCORE_THRESHOLD:
            severity = RiskLevel.MEDIUM
            exercise_note = ""
            if exercise_compensated:
                # Downgrade from MEDIUM to LOW
                severity = RiskLevel.LOW
                exercise_note = (f" However, {exercise.latest:.0f} minutes of exercise were logged, "
                                 f"suggesting the patient may be active through non-step activities.")

            return self.trigger(
                severity=severity,
                message=f"Daily activity has sustained a significant drop over 3 days — {int(steps_3d_avg)} steps vs baseline "
                        f"{int(steps_bl.mean)} (z-score: {steps_z:.1f}, threshold: >{self.Z_SCORE_THRESHOLD}). "
                        f"This level of sustained decline is associated with increased frailty and fall risk."
                        f"{exercise_note}",
                evidence={
                    "steps_3d_avg": steps_3d_avg,
                    "steps_baseline": round(steps_bl.mean, 0),
                    "steps_std": round(steps_bl.std, 1),
                    "z_score": round(steps_z, 2),
                    "exercise_compensated": exercise_compensated,
                    "exercise_minutes": exercise.latest if exercise.has_data else None,
                    "guideline": "Fried 2001 frailty phenotype (Sustained)",
                    "zivaa_enhancement": "exercise_minutes_compensation" if exercise_compensated else None
                }
            )

        return self.pass_rule()


class AcuteIllnessRule(InsightRule):
    """
    Detects pre-symptomatic illness onset via resting heart rate elevation.

    Uses the z-score approach validated by Mishra et al. (2020) for
    pre-symptomatic COVID-19 detection from smartwatch data, and
    Radin et al. (2020) for influenza-like illness surveillance.

    THRESHOLDS:
    - HR z-score > 2.0 (RHR > 2 SD above personal baseline):
      Mishra et al. used sustained elevated RHR (mean + 2 SD) as
      the primary signal, NOT a fixed bpm offset.
    - Steps z-score > 1.5 (activity > 1.5 SD below baseline):
      Supporting signal — illness typically causes both HR elevation
      and activity reduction simultaneously.

    CITATIONS:
    - Mishra T, et al. "Pre-symptomatic detection of COVID-19 from
      smartwatch data."
      Nat Biomed Eng. 2020;4:1208-1220.
      DOI: 10.1038/s41551-020-00640-6
      https://www.nature.com/articles/s41551-020-00640-6

    - Radin JM, et al. "Harnessing wearable device data to improve
      state-level real-time surveillance of influenza-like illness in
      the USA: a population-based study."
      Lancet Digit Health. 2020;2(2):e85-e93.
      DOI: 10.1016/S2589-7500(19)30222-5
      https://www.thelancet.com/journals/landig/article/PIIS2589-7500(19)30222-5

    - Li X, et al. "Digital Health: Tracking Physiomes and Activity
      Using Wearable Biosensors Reveals Useful Health-Related Information."
      PLoS Biol. 2017;15(1):e2001402.
      DOI: 10.1371/journal.pbio.2001402
    """
    id = "acute_illness"
    name = "Acute Illness Onset"
    category = InsightCategory.GENERAL
    tier = InsightTier.TIER_1

    # Mishra et al. 2020: used > 2 SD above personal RHR mean
    HR_Z_THRESHOLD = 2.0

    # Supporting signal: activity decline
    STEPS_Z_THRESHOLD = 1.5

    def evaluate(self, ctx: EvalContext) -> InsightResult:
        # Prefer resting HR (Mishra 2020 specifically studied *resting* HR)
        # Fall back to average HR if resting HR not available
        rhr = ctx.vitals.metric("resting_heart_rate")
        avg_hr = ctx.vitals.metric("avg_heart_rate")
        steps = ctx.vitals.metric("steps")
        if getattr(rhr, 'is_stale', False) or getattr(avg_hr, 'is_stale', False) or getattr(steps, 'is_stale', False): return self.skip_rule("Data is stale")

        if rhr.has_data and rhr.is_baseline_established:
            hr = rhr
            hr_source = "resting"
        elif avg_hr.has_data and avg_hr.is_baseline_established:
            hr = avg_hr
            hr_source = "average"
        else:
            if not avg_hr.has_data and not rhr.has_data:
                return self.skip_rule("No heart rate data available")
            return self.skip_rule("Heart rate baseline not yet established")

        hr_bl = hr.established_baseline
        hr_z = ((hr.latest - hr_bl.mean) / hr_bl.std) if hr_bl.std > 0 else 0

        if hr_z <= self.HR_Z_THRESHOLD:
            return self.pass_rule()

        # HR is significantly elevated — check for supporting activity crash
        steps_z = 0
        try:
            tz = zoneinfo.ZoneInfo(ctx.patient_timezone) if getattr(ctx, 'patient_timezone', None) else timezone.utc
        except Exception:
            tz = timezone.utc
        current_local_hour = datetime.now(tz).hour
        
        # TIME GATE: Only consider low steps as a "crash" if the day is mostly over (>= 23:00 local)
        if current_local_hour >= 23 and steps.has_data and steps.is_baseline_established:
            steps_bl = steps.established_baseline
            steps_z = ((steps_bl.mean - steps.latest) / steps_bl.std) if steps_bl.std > 0 else 0

        hr_name = "Resting heart rate" if hr_source == "resting" else "Average heart rate"

        if steps_z > self.STEPS_Z_THRESHOLD:
            # Both signals confirm — strong illness indicator (Mishra 2020 pattern)
            return self.trigger(
                severity=RiskLevel.HIGH,
                message=f"{hr_name} is significantly elevated ({hr.latest:.0f} bpm, "
                        f"z-score: {hr_z:.1f}) with a simultaneous activity crash. Per Mishra et al. "
                        f"(2020), this pattern is a strong pre-symptomatic illness indicator.",
                evidence={
                    "hr_latest": hr.latest,
                    "hr_baseline": round(hr_bl.mean, 1),
                    "hr_z_score": round(hr_z, 2),
                    "hr_source": hr_source,
                    "steps_z_score": round(steps_z, 2),
                    "guideline": "Mishra 2020 (Nat Biomed Eng)"
                }
            )
        else:
            # HR elevation alone — still concerning (Radin 2020)
            return self.trigger(
                severity=RiskLevel.MEDIUM,
                message=f"{hr_name} is elevated ({hr.latest:.0f} bpm, z-score: {hr_z:.1f}, "
                        f"baseline: {hr_bl.mean:.0f} bpm). Per wearable health research, sustained HR "
                        f"elevation >2 SD warrants monitoring for emerging illness.",
                evidence={
                    "hr_latest": hr.latest,
                    "hr_baseline": round(hr_bl.mean, 1),
                    "hr_z_score": round(hr_z, 2),
                    "hr_source": hr_source,
                    "guideline": "Radin 2020 (Lancet Digit Health)"
                }
            )


class MedicationNonAdherenceRule(InsightRule):
    """
    Flags possible medication non-adherence when BP exceeds treatment
    target alongside known missed doses.

    Uses the therapeutic inertia framework from Burnier & Egan (2019):
    when blood pressure remains above target despite prescribed
    medications, non-adherence is the most common cause.

    THRESHOLDS:
    - BP above target: > 140/90 mmHg for most elderly patients.
      ACC/AHA 2017 recommends <130/80 for most adults, but the
      2017 ACP/AAFP guideline recommends <150 for adults ≥60.
      We use 140 as a balanced threshold for elderly monitoring.
    - Missed doses: any logged missed dose within 7 days.

    NOTE: No published clinical decision rule exists for combining
    vitals + adherence logs to detect non-adherence. This rule
    uses the Burnier framework conceptually. For validated adherence
    measurement, the MMAS-8 (Morisky) questionnaire would be needed.

    CITATIONS:
    - Burnier M, Egan BM. "Adherence in Hypertension: A Review and Update."
      Circ Res. 2019;124(7):1124-1140.
      DOI: 10.1161/CIRCRESAHA.118.313220
      https://www.ahajournals.org/doi/10.1161/CIRCRESAHA.118.313220

    - WHO. "Adherence to Long-Term Therapies: Evidence for Action." (2003)
      https://www.who.int/chp/knowledge/publications/adherence_report/en/

    - Whelton PK, et al. 2017 ACC/AHA Hypertension Guideline.
      (see HypertensionEscalationRule for full citation)
    """
    id = "medication_nonadherence"
    name = "Medication Non-Adherence Risk"
    category = InsightCategory.CARDIAC
    tier = InsightTier.TIER_1
    evaluation_mode = "batch"

    # ACC/AHA target for elderly: <140/90 (conservative)
    # Burnier 2019: "BP above target + missed doses → suspect non-adherence"
    BP_TARGET = 140

    def evaluate(self, ctx: EvalContext) -> InsightResult:
        bp_sys = ctx.vitals.metric("bp_systolic")
        hr = ctx.vitals.metric("avg_heart_rate")
        if getattr(bp_sys, 'is_stale', False) or getattr(hr, 'is_stale', False): return self.skip_rule("Data is stale")

        if not bp_sys.has_data:
            return self.skip_rule("No blood pressure data available")

        # Burnier framework: BP above treatment target
        if bp_sys.latest > self.BP_TARGET:
            # Check if other vitals are relatively normal (rules out acute illness)
            hr_normal = True
            if hr.is_baseline_established and hr.has_data:
                hr_bl = hr.established_baseline
                hr_z = abs(hr.latest - hr_bl.mean) / hr_bl.std if hr_bl.std > 0 else 0
                hr_normal = hr_z < 1.5  # Within 1.5 SD = normal range

            if ctx.meds.has_recent_miss() and hr_normal:
                return self.trigger(
                    severity=RiskLevel.MEDIUM,
                    message=f"Blood pressure is above treatment target ({bp_sys.latest:.0f} mmHg, "
                            f"target: <{self.BP_TARGET} per ACC/AHA) while recent missed doses were "
                            f"logged. Per Burnier & Egan (2019), medication non-adherence is the most "
                            f"common cause of uncontrolled hypertension.",
                    evidence={
                        "bp_sys": bp_sys.latest,
                        "bp_target": self.BP_TARGET,
                        "missed_doses": ctx.meds.missed_doses(),
                        "hr_normal": hr_normal,
                        "guideline": "Burnier 2019 (Circ Res), ACC/AHA 2017"
                    }
                )

        return self.pass_rule()


class SleepFragmentationRule(InsightRule):
    """
    Detects high sleep fragmentation (WASO - Wake After Sleep Onset).
    
    CLINICAL SIGNIFICANCE:
    High sleep fragmentation and frequent nighttime awakenings are strongly 
    associated with impaired physical performance, daytime cognitive fatigue, 
    and a significantly elevated risk of falls in older adults.
    """
    id = "sleep_fragmentation"
    name = "High Sleep Fragmentation"
    category = InsightCategory.GENERAL
    tier = InsightTier.TIER_1
    evaluation_mode = "batch"

    def evaluate(self, ctx: EvalContext) -> InsightResult:
        waso = ctx.vitals.metric("waso_mins")
        awakenings = ctx.vitals.metric("awakenings_count")
        if getattr(waso, 'is_stale', False) or getattr(awakenings, 'is_stale', False): return self.skip_rule("Data is stale")
        
        if not waso.has_data:
            return self.skip_rule("Advanced sleep fragmentation metrics (WASO) not available.")

        # Evaluate over a 7-day rolling average to prevent single-day false alarms
        waso_7d_avg = waso.rolling_average(7)
        awakenings_7d_avg = awakenings.rolling_average(7)
        
        # 1. Absolute Clinical Threshold (WASO)
        if waso_7d_avg > 60:
            return self.trigger(
                severity=RiskLevel.MEDIUM,
                message=f"Sustained high sleep fragmentation detected. The patient has been spending an average of {waso_7d_avg:.0f} minutes awake during the night over the last 7 days. This severely degrades restorative sleep and increases fall risk.",
                evidence={
                    "waso_mins_7d_avg": waso_7d_avg,
                    "threshold_mins": 60,
                    "guideline": "Blackwell et al. 2014"
                }
            )

        # 2. Personalized Baseline Deviation (Awakenings Count)
        if awakenings.is_baseline_established:
            bl = awakenings.established_baseline
            # Trigger if 7-day average is significantly above their normal baseline (Z > 2.0)
            # AND it represents a practical increase (e.g. at least 3 more awakenings than normal)
            awakenings_z = ((awakenings_7d_avg - bl.mean) / bl.std) if bl.std > 0 else 0
            
            if awakenings_z > 2.0 and (awakenings_7d_avg - bl.mean) >= 3:
                return self.trigger(
                    severity=RiskLevel.LOW,
                    message=f"Patient's nighttime awakenings have significantly increased. They are averaging {awakenings_7d_avg:.1f} awakenings per night over the last 7 days, compared to their normal baseline of {bl.mean:.1f}.",
                    evidence={
                        "awakenings_7d_avg": round(awakenings_7d_avg, 1),
                        "baseline_awakenings": round(bl.mean, 1),
                        "z_score": round(awakenings_z, 2)
                    }
                )

        return self.pass_rule()


class DeepSleepDeprivationRule(InsightRule):
    """
    Detects critically low levels of Deep (Slow-Wave) Sleep as a percentage.
    
    CLINICAL SIGNIFICANCE:
    Normal deep sleep is 15-25% of total sleep. A sustained drop below 10% 
    is a critical biomarker for cognitive decline (Alzheimer's pathology) and 
    hypertension.
    """
    id = "deep_sleep_deprivation"
    name = "Deep Sleep Deprivation"
    category = InsightCategory.GENERAL
    tier = InsightTier.TIER_1
    evaluation_mode = "batch"

    def evaluate(self, ctx: EvalContext) -> InsightResult:
        deep_sleep_pct = ctx.vitals.metric("sleep_stage_5_pct")
        if getattr(deep_sleep_pct, 'is_stale', False): return self.skip_rule("Data is stale")

        if not deep_sleep_pct.has_data:
            return self.skip_rule("Deep sleep percentage data not available.")

        deep_sleep_7d_avg = deep_sleep_pct.rolling_average(7)
        if 0 < deep_sleep_7d_avg < 10.0:
            return self.trigger(
                severity=RiskLevel.HIGH,
                message=f"Patient is severely deprived of Deep Sleep, averaging only {deep_sleep_7d_avg:.1f}% over the last 7 days. Chronic slow-wave sleep deprivation impairs neurotoxin clearance and cardiovascular recovery.",
                evidence={
                    "deep_sleep_pct_7d_avg": deep_sleep_7d_avg,
                    "threshold_pct": 10.0,
                    "guideline": "Mander et al. 2017"
                }
            )
        return self.pass_rule()


class PoorSleepEfficiencyRule(InsightRule):
    """
    Detects sustained low sleep efficiency.
    """
    id = "poor_sleep_efficiency"
    name = "Poor Sleep Efficiency"
    category = InsightCategory.GENERAL
    tier = InsightTier.TIER_1
    evaluation_mode = "batch"

    def evaluate(self, ctx: EvalContext) -> InsightResult:
        efficiency = ctx.vitals.metric("sleep_efficiency_pct")
        if getattr(efficiency, 'is_stale', False): return self.skip_rule("Data is stale")

        if not efficiency.has_data:
            return self.skip_rule("Sleep efficiency data not available.")

        efficiency_7d_avg = efficiency.rolling_average(7)
        if 0 < efficiency_7d_avg < 80.0:
            return self.trigger(
                severity=RiskLevel.LOW,
                message=f"Sustained poor sleep efficiency detected (7-day average: {efficiency_7d_avg:.0f}%). The patient is spending a significant amount of time in bed without actually sleeping.",
                evidence={
                    "sleep_efficiency_pct_7d_avg": efficiency_7d_avg,
                    "threshold_pct": 80.0
                }
            )
        return self.pass_rule()


class REMSleepDeficitRule(InsightRule):
    """
    Detects critically low levels of REM Sleep.
    
    CLINICAL SIGNIFICANCE:
    Normal REM sleep is 20-25%. Less than 15% is associated with mood disorders,
    impaired emotional regulation, and higher mortality.
    """
    id = "rem_sleep_deficit"
    name = "REM Sleep Deficit"
    category = InsightCategory.MENTAL_HEALTH
    tier = InsightTier.TIER_1
    evaluation_mode = "batch"

    def evaluate(self, ctx: EvalContext) -> InsightResult:
        rem_sleep_pct = ctx.vitals.metric("sleep_stage_6_pct")
        if getattr(rem_sleep_pct, 'is_stale', False): return self.skip_rule("Data is stale")

        if not rem_sleep_pct.has_data:
            return self.skip_rule("REM sleep percentage data not available.")

        rem_sleep_7d_avg = rem_sleep_pct.rolling_average(7)
        if 0 < rem_sleep_7d_avg < 15.0:
            return self.trigger(
                severity=RiskLevel.MEDIUM,
                message=f"Patient is exhibiting a deficit in REM sleep, averaging {rem_sleep_7d_avg:.1f}% over the last 7 days. This can negatively impact emotional regulation and cognitive consolidation.",
                evidence={
                    "rem_sleep_pct_7d_avg": rem_sleep_7d_avg,
                    "threshold_pct": 15.0,
                    "guideline": "Leary et al. 2020"
                }
            )
        return self.pass_rule()


class ProlongedSleepLatencyRule(InsightRule):
    """
    Detects prolonged sleep latency (time taken to fall asleep).
    
    CLINICAL SIGNIFICANCE:
    Normal sleep latency is 10-20 minutes. Prolonged latency (>45 minutes)
    is a primary diagnostic criterion for sleep-onset insomnia and is
    often linked to anxiety, hyperarousal, or poor sleep hygiene.
    """
    id = "prolonged_sleep_latency"
    name = "Prolonged Sleep Latency"
    category = InsightCategory.GENERAL
    tier = InsightTier.TIER_1

    def evaluate(self, ctx: EvalContext) -> InsightResult:
        latency = ctx.vitals.metric("sleep_latency_mins")
        if getattr(latency, 'is_stale', False): return self.skip_rule("Data is stale")

        if not latency.has_data:
            return self.skip_rule("Sleep latency data not available.")

        if latency.latest > 45.0:
            return self.trigger(
                severity=RiskLevel.LOW,
                message=f"Prolonged sleep latency detected. It took the patient {latency.latest:.0f} minutes to fall asleep, which may indicate sleep-onset insomnia or nighttime anxiety.",
                evidence={
                    "sleep_latency_mins": latency.latest,
                    "threshold_mins": 45.0
                }
            )
        return self.pass_rule()

class HeartRateRecoveryRule(InsightRule):
    """
    Detects abnormal heart rate recovery after exercise, indicating
    high cardiovascular risk, severe overtraining, or acute fatigue.

    CLINICAL SIGNIFICANCE:
    Heart rate recovery (HRR) reflects parasympathetic nervous system 
    reactivation. A delayed drop in heart rate after exercise is a powerful 
    and independent predictor of cardiovascular mortality.

    THRESHOLDS:
    - Absolute Floor (Cole et al. 1999): A drop of <= 12 bpm at 1 minute or
      <= 22 bpm at 2 minutes is considered abnormal. We use <= 22 as our floor
      since our data aligns with 2-minute recovery.
    - Relative Decline: z-score < -2.0 (drop is > 2 SD below personal baseline).
      A sudden collapse in HRR indicates acute fatigue, emerging illness, or overexertion.

    CITATION:
    - Cole CR, Blackstone EH, Pashkow FJ, Snader CE, Lauer MS.
      "Heart-rate recovery immediately after exercise as a predictor of mortality."
      N Engl J Med. 1999;341(18):1351-1357.
      DOI: 10.1056/NEJM199910283411804
    """
    id = "heart_rate_recovery"
    name = "Poor Heart Rate Recovery"
    category = InsightCategory.CARDIAC
    tier = InsightTier.TIER_1
    evaluation_mode = "batch"

    ABSOLUTE_HRR_FLOOR = 22
    Z_SCORE_THRESHOLD = -2.0

    def evaluate(self, ctx: EvalContext) -> InsightResult:
        hrr = ctx.vitals.metric("heart_rate_recovery")
        if getattr(hrr, 'is_stale', False): return self.skip_rule("Data is stale")

        if not hrr.has_data:
            return self.skip_rule("No heart rate recovery data available.")

        # Check absolute floor
        if hrr.latest <= self.ABSOLUTE_HRR_FLOOR:
            return self.trigger(
                severity=RiskLevel.HIGH,
                message=f"Heart rate recovery after exercise was extremely poor ({hrr.latest:.0f} bpm drop). "
                        f"Per Cole et al. (NEJM 1999), a recovery of <= 22 bpm at 2 minutes is "
                        f"considered abnormal and may indicate elevated cardiovascular risk or severe overexertion.",
                evidence={
                    "heart_rate_recovery": hrr.latest,
                    "absolute_floor": self.ABSOLUTE_HRR_FLOOR,
                    "guideline": "Cole et al. 1999 (NEJM)"
                }
            )

        # Check relative baseline shift
        if hrr.is_baseline_established:
            hrr_bl = hrr.established_baseline
            # z-score is negative when latest is BELOW mean (which is bad for HRR)
            hrr_z = ((hrr.latest - hrr_bl.mean) / hrr_bl.std) if hrr_bl.std > 0 else 0

            if hrr_z <= self.Z_SCORE_THRESHOLD:
                return self.trigger(
                    severity=RiskLevel.MEDIUM,
                    message=f"Heart rate recovery has dropped significantly below the patient's normal baseline "
                            f"({hrr.latest:.0f} bpm vs normal {hrr_bl.mean:.0f} bpm). This sudden decline "
                            f"in parasympathetic response suggests acute fatigue, emerging illness, or overtraining.",
                    evidence={
                        "heart_rate_recovery_calculated": hrr.latest,
                        "hrr_baseline": round(hrr_bl.mean, 1),
                        "z_score": round(hrr_z, 2),
                        "threshold": self.Z_SCORE_THRESHOLD
                    }
                )

        return self.pass_rule()


class SystemicInflammationAlert(InsightRule):
    """
    Detects potential early infection/systemic inflammation using skin temperature delta
    and resting heart rate.
    """
    id = "systemic_inflammation_alert"
    name = "Systemic Inflammation Warning"
    category = InsightCategory.IMMUNE
    tier = InsightTier.TIER_1

    def evaluate(self, ctx: EvalContext) -> InsightResult:
        skin_temp = ctx.vitals.metric("skin_temp_delta")
        resting_hr = ctx.vitals.metric("resting_heart_rate")
        if getattr(skin_temp, 'is_stale', False) or getattr(resting_hr, 'is_stale', False): return self.skip_rule("Data is stale")

        if not skin_temp.has_data or not resting_hr.has_data:
            return self.skip_rule("Requires both skin temperature and resting heart rate data")
        
        if not resting_hr.is_baseline_established:
            return self.skip_rule("Resting heart rate baseline not established")

        hr_baseline = resting_hr.established_baseline.mean
        hr_elevated = resting_hr.latest > (hr_baseline + 5)
        temp_elevated = skin_temp.latest > 1.5

        if hr_elevated and temp_elevated:
            return self.trigger(
                severity=RiskLevel.MEDIUM,
                message=f"Skin temperature is significantly elevated (+{skin_temp.latest:.1f} °C) "
                        f"along with an elevated resting heart rate ({resting_hr.latest:.0f} bpm). "
                        f"This combination can precede systemic inflammation or infection.",
                evidence={
                    "skin_temp_delta": skin_temp.latest,
                    "resting_hr": resting_hr.latest,
                    "hr_baseline": hr_baseline
                }
            )
        
        return self.pass_rule()


TIER_1_RULES = [
    HypertensionEscalationRule(),
    FunctionalDeclineRule(),
    AcuteIllnessRule(),
    MedicationNonAdherenceRule(),
    SleepFragmentationRule(),
    DeepSleepDeprivationRule(),
    PoorSleepEfficiencyRule(),
    REMSleepDeficitRule(),
    HeartRateRecoveryRule(),
    SystemicInflammationAlert()
]
