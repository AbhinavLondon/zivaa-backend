"""
Tier 1 — Mobility & Movement Regularity Rules (Guideline-aligned)

These rules evaluate walking speed (cadence), functional exercise duration,
and diurnal movement fragmentation. In geriatric medicine, ambulatory mobility
is considered the "sixth vital sign" (Studenski et al., JAMA 2011).

All rules include:
- Plain-English clinical explanations for caregivers and clinical teams.
- Structured clinical threshold tables.
- Exact peer-reviewed medical citations (JAMA, The Lancet, BJSM, Age and Ageing).
- Explicit evaluation_mode classification ("realtime" for acute safety vs "batch" for circadian/chronic).
"""

import statistics
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List
import zoneinfo

from app.services.insights.core import (
    InsightRule,
    RiskLevel,
    InsightCategory,
    InsightTier,
    InsightResult,
)
from app.services.insights.context import EvalContext


# ==============================================================================
# RULE 1: Acute Functional Collapse (The Occult Sepsis / Delirium Triad)
# ==============================================================================
class AcuteFunctionalCollapseRule(InsightRule):
    """
    Detects sudden functional collapse indicating acute systemic illness
    (such as occult sepsis, urinary tract infection, pneumonia, or hypokinetic delirium).

    PLAIN-ENGLISH CLINICAL EXPLANATION:
    In older adults, acute infections rarely start with a classic high fever.
    Instead, seniors suddenly slow down, shuffle their feet, barely leave their
    chair or bed, and their resting pulse climbs. If their walking speed drops by
    over 25%, their daily movement cuts in half, and their resting heart rate
    spikes by 10+ beats, this rule sounds an immediate alarm so family or nurses
    can check for fever, confusion, dehydration, or an acute infection.

    CLINICAL THRESHOLDS:
    ┌──────────────────────────────┬──────────────────────────────────────────┬──────────────┐
    │ Clinical Condition           │ Threshold Criteria                       │ Our Severity │
    ├──────────────────────────────┼──────────────────────────────────────────┼──────────────┤
    │ Severe Cadence Drop          │ < 75% of 7-day baseline OR < 55.0 spm    │ (Component)  │
    │ Severe Movement Collapse     │ < 50% of 7-day baseline OR < 10 mins     │ (Component)  │
    │ Resting Tachycardia / Stress │ > baseline + 10 bpm OR >= 90 bpm         │ (Component)  │
    │ Sedentary Confinement        │ <= 4 active hours in day                 │ (Component)  │
    ├──────────────────────────────┼──────────────────────────────────────────┼──────────────┤
    │ ACUTE DETERIORATION TRIAD    │ Low Cadence + Low Movement + Stress/Conf.│ HIGH         │
    └──────────────────────────────┴──────────────────────────────────────────┴──────────────┘

    CITATIONS:
    - Inouye SK, Westendorp RG, Saczynski JS. "Delirium in elderly people."
      The Lancet. 2014;383(9920):911-922.
      DOI: 10.1016/S0140-6736(13)60688-1
      https://doi.org/10.1016/S0140-6736(13)60688-1

    - Studenski S, Perera S, Patel K, et al. "Gait Speed and Survival in Older Adults."
      JAMA. 2011;305(1):50-58.
      DOI: 10.1001/jama.2010.1923
      https://doi.org/10.1001/jama.2010.1923
    """

    id = "acute_functional_collapse"
    name = "Acute Functional Collapse (Occult Infection / Delirium)"
    category = InsightCategory.MOBILITY
    tier = InsightTier.TIER_1
    requires_baseline = True
    evaluation_mode = "realtime"

    def evaluate(self, ctx: EvalContext) -> InsightResult:
        cadence = ctx.vitals.metric("avg_cadence_spm")
        active_mins = ctx.vitals.metric("active_movement_minutes")
        rhr = ctx.vitals.metric("resting_heart_rate")
        active_hours = ctx.vitals.metric("active_hours_count")

        if getattr(cadence, "is_stale", False):
            return self.skip_rule("Cadence data is stale")
        if not cadence.has_data or not active_mins.has_data:
            return self.skip_rule("Requires both walking cadence and active movement minutes")

        # Baseline extraction
        cadence_base = (
            cadence.established_baseline.mean
            if cadence.is_baseline_established
            else cadence.baseline(days=7)
        )
        mins_base = (
            active_mins.established_baseline.mean
            if active_mins.is_baseline_established
            else active_mins.baseline(days=7)
        )

        rhr_base = 0.0
        if rhr.has_data:
            rhr_base = (
                rhr.established_baseline.mean
                if rhr.is_baseline_established
                else rhr.baseline(days=7)
            )

        # 1. Cadence depression check (< 75% of baseline or < 55 spm)
        is_cadence_depressed = (
            (cadence_base > 0 and cadence.latest < cadence_base * 0.75)
            or (cadence.latest > 0 and cadence.latest < 55.0)
        )

        # 2. Movement collapse check (< 50% of baseline or < 10 mins)
        is_movement_plummeted = (
            (mins_base > 0 and active_mins.latest < mins_base * 0.50)
            or (active_mins.latest < 10.0)
        )

        # 3. Physiological stress / Tachycardia (> baseline + 10 bpm or >= 90 bpm)
        has_cardiac_stress = False
        if rhr.has_data and rhr.latest > 0:
            has_cardiac_stress = (
                (rhr_base > 0 and rhr.latest > rhr_base + 10.0)
                or rhr.latest >= 90.0
            )

        # 4. Severe sedentary confinement (<= 4 active hours out of daytime)
        is_sedentary_confinement = (
            active_hours.has_data and active_hours.latest > 0 and active_hours.latest <= 4
        )

        if is_cadence_depressed and is_movement_plummeted and (has_cardiac_stress or is_sedentary_confinement):
            stress_desc = []
            if has_cardiac_stress:
                stress_desc.append(f"elevated resting heart rate of {rhr.latest:.0f} bpm (baseline: {rhr_base:.0f})")
            if is_sedentary_confinement:
                stress_desc.append(f"active in only {active_hours.latest:.0f} hours today")
            stress_str = " and ".join(stress_desc) if stress_desc else "pronounced daytime confinement"

            return self.trigger(
                severity=RiskLevel.HIGH,
                message=(
                    f"Acute mobility decline detected: walking cadence slowed to {cadence.latest:.0f} steps/min "
                    f"(baseline: {cadence_base:.0f} spm) with only {active_mins.latest:.0f} active minutes, accompanied by {stress_str}. "
                    f"Prompt assessment for acute infection, dehydration, or delirium is advised."
                ),
                evidence={
                    "avg_cadence_spm": cadence.latest,
                    "baseline_cadence": cadence_base,
                    "active_movement_minutes": active_mins.latest,
                    "baseline_active_mins": mins_base,
                    "resting_heart_rate": rhr.latest if rhr.has_data else None,
                    "baseline_rhr": rhr_base if rhr.has_data else None,
                    "active_hours_count": active_hours.latest if active_hours.has_data else None,
                    "guideline": "Inouye et al. Lancet 2014; Studenski et al. JAMA 2011",
                },
            )

        return self.pass_rule()


# ==============================================================================
# RULE 2: Cardiopulmonary Decompensation & Desaturation
# ==============================================================================
class CardiopulmonaryDecompensationRule(InsightRule):
    """
    Detects exertional limitation and cardiorespiratory strain indicative of
    early heart failure (CHF) decompensation or COPD exacerbation.

    PLAIN-ENGLISH CLINICAL EXPLANATION:
    When an older heart or lungs begin to struggle (like fluid buildup in early
    heart failure or a bronchitis/COPD flare-up), moving becomes exhausting.
    The senior cuts their walking short and walks much slower to catch their breath.
    If walking speed slows and moving time drops while blood oxygen drops (< 92%)
    or resting heart rate rises, this rule alerts caregivers before severe breathing
    distress occurs.

    CLINICAL THRESHOLDS:
    ┌──────────────────────────────┬──────────────────────────────────────────┬──────────────┐
    │ Clinical Condition           │ Threshold Criteria                       │ Our Severity │
    ├──────────────────────────────┼──────────────────────────────────────────┼──────────────┤
    │ Decreased Movement Volume    │ < 70% of 7-day baseline                  │ (Component)  │
    │ Slowing Stride Speed         │ < baseline - 10.0 steps/min              │ (Component)  │
    │ Oxygen Desaturation          │ SpO2 < 92.0% OR < baseline - 3.0%        │ (Component)  │
    │ Exertional / Resting Pulse   │ Resting HR > baseline + 8 bpm OR >= 95   │ (Component)  │
    ├──────────────────────────────┼──────────────────────────────────────────┼──────────────┤
    │ CARDIOPULMONARY DECOMP       │ Low Volume + Slow Stride + Desat/Tachy   │ HIGH         │
    └──────────────────────────────┴──────────────────────────────────────────┴──────────────┘

    CITATIONS:
    - Chaudhry SI, Wang Y, Concato J, Gill TM, Krumholz HM.
      "Patterns of weight change and symptom onset in patients with heart failure."
      Circulation. 2007;116(14):1549-1554.
      DOI: 10.1161/CIRCULATIONAHA.107.703272
      https://doi.org/10.1161/CIRCULATIONAHA.107.703272

    - British Thoracic Society. "BTS Guideline for Oxygen Use in Adults in Healthcare
      and Emergency Settings." Thorax. 2017;72(Suppl 1):ii1-ii90.
      DOI: 10.1136/thoraxjnl-2016-209729
    """

    id = "cardiopulmonary_decompensation"
    name = "Cardiopulmonary Decompensation & Desaturation"
    category = InsightCategory.MOBILITY
    tier = InsightTier.TIER_1
    requires_baseline = True
    evaluation_mode = "realtime"

    def evaluate(self, ctx: EvalContext) -> InsightResult:
        cadence = ctx.vitals.metric("avg_cadence_spm")
        active_mins = ctx.vitals.metric("active_movement_minutes")
        spo2 = ctx.vitals.metric("oxygen_sat")
        rhr = ctx.vitals.metric("resting_heart_rate")

        if not cadence.has_data or not active_mins.has_data:
            return self.skip_rule("Requires walking cadence and active movement minutes")

        cadence_base = (
            cadence.established_baseline.mean
            if cadence.is_baseline_established
            else cadence.baseline(days=7)
        )
        mins_base = (
            active_mins.established_baseline.mean
            if active_mins.is_baseline_established
            else active_mins.baseline(days=7)
        )

        # 1. Moving duration dropping (> 30% drop)
        is_exertion_dropping = (
            mins_base > 0 and active_mins.latest < mins_base * 0.70
        )

        # 2. Cadence slowing (drop by >= 10 spm from baseline)
        is_cadence_slowing = (
            cadence_base > 0 and cadence.latest < cadence_base - 10.0
        )

        # 3. Cardiopulmonary stress markers (SpO2 desaturation or tachycardia)
        is_desaturating = False
        spo2_base = 97.0
        if spo2.has_data and spo2.latest > 0:
            spo2_base = (
                spo2.established_baseline.mean
                if spo2.is_baseline_established
                else spo2.baseline(days=7)
            )
            is_desaturating = spo2.latest < 92.0 or (spo2_base > 0 and spo2.latest < spo2_base - 3.0)

        is_tachycardic = False
        rhr_base = 70.0
        if rhr.has_data and rhr.latest > 0:
            rhr_base = (
                rhr.established_baseline.mean
                if rhr.is_baseline_established
                else rhr.baseline(days=7)
            )
            is_tachycardic = (rhr_base > 0 and rhr.latest > rhr_base + 8.0) or rhr.latest >= 95.0

        if is_exertion_dropping and is_cadence_slowing and (is_desaturating or is_tachycardic):
            trigger_detail = []
            if is_desaturating:
                trigger_detail.append(f"oxygen saturation dropped to {spo2.latest:.1f}% (baseline: {spo2_base:.1f}%)")
            if is_tachycardic:
                trigger_detail.append(f"resting heart rate elevated at {rhr.latest:.0f} bpm (baseline: {rhr_base:.0f})")
            detail_str = " and ".join(trigger_detail)

            return self.trigger(
                severity=RiskLevel.HIGH,
                message=(
                    f"Possible cardiopulmonary strain: active movement decreased to {active_mins.latest:.0f} mins "
                    f"(baseline: {mins_base:.0f}) with cadence slowing by {cadence_base - cadence.latest:.0f} steps/min, "
                    f"coinciding with {detail_str}. Please check for shortness of breath or swelling."
                ),
                evidence={
                    "avg_cadence_spm": cadence.latest,
                    "baseline_cadence": cadence_base,
                    "active_movement_minutes": active_mins.latest,
                    "baseline_active_mins": mins_base,
                    "oxygen_sat": spo2.latest if spo2.has_data else None,
                    "baseline_spo2": spo2_base if spo2.has_data else None,
                    "resting_heart_rate": rhr.latest if rhr.has_data else None,
                    "baseline_rhr": rhr_base if rhr.has_data else None,
                    "guideline": "Chaudhry et al. Circulation 2007; BTS 2017",
                },
            )

        return self.pass_rule()


# ==============================================================================
# RULE 3: Acute Fall Risk & Gait Instability Under Exhaustion
# ==============================================================================
class AcuteFallRiskExhaustionRule(InsightRule):
    """
    Detects high-risk biomechanical gait patterns (shuffling/cautious cadence)
    compounded by sleep deprivation or severe fragmentation.

    PLAIN-ENGLISH CLINICAL EXPLANATION:
    The most dangerous time for a senior to fall is when they are physically
    exhausted from poor sleep but continue to push through and walk around.
    When feet shuffle (< 60 steps per minute) on tired legs after less than 5 hours
    of sleep, reaction time slows and tripping risk triples. This rule alerts the senior
    and family to clear pathways, turn on bright lights, and avoid rushing.

    CLINICAL THRESHOLDS:
    ┌──────────────────────────────┬──────────────────────────────────────────┬──────────────┐
    │ Metric                       │ Threshold Criteria                       │ Our Severity │
    ├──────────────────────────────┼──────────────────────────────────────────┼──────────────┤
    │ Exposure (Active Walking)    │ Total steps >= 3,000                     │ (Component)  │
    │ Shuffling / Cautious Cadence │ avg_cadence_spm < 60.0 steps/min         │ (Component)  │
    │ Severe Sleep Deficit         │ sleep_hours < 5.0h OR consistency < 65% │ (Component)  │
    ├──────────────────────────────┼──────────────────────────────────────────┼──────────────┤
    │ ACUTE FALL RISK SURGE        │ High Steps + Shuffling Cadence + Sleep <5│ HIGH         │
    └──────────────────────────────┴──────────────────────────────────────────┴──────────────┘

    CITATIONS:
    - American Geriatrics Society & British Geriatrics Society.
      "Summary of the Updated AGS/BGS Clinical Practice Guideline for Prevention
      of Falls in Older Persons." J Am Geriatr Soc. 2011;59(1):148-157.
      DOI: 10.1111/j.1532-5415.2010.03234.x

    - Middleton A, Fritz SL, Lusardi M. "Walking speed: the functional vital sign."
      J Orthop Sports Phys Ther. 2015;45(5):331-337.
      DOI: 10.2519/jospt.2015.0502
    """

    id = "acute_fall_risk_exhaustion"
    name = "Acute Fall Risk & Gait Instability Under Exhaustion"
    category = InsightCategory.MOBILITY
    tier = InsightTier.TIER_1
    requires_baseline = False
    evaluation_mode = "realtime"

    def evaluate(self, ctx: EvalContext) -> InsightResult:
        steps = ctx.vitals.metric("steps")
        cadence = ctx.vitals.metric("avg_cadence_spm")
        sleep = ctx.vitals.metric("sleep_hours")
        sleep_eff = ctx.vitals.metric("sleep_efficiency_pct")

        if not cadence.has_data or not steps.has_data:
            return self.skip_rule("Requires steps and walking cadence data")

        has_exposure = steps.latest >= 3000
        has_shuffling_cadence = 0 < cadence.latest < 60.0

        # Sleep exhaustion markers
        has_sleep_deficit = False
        sleep_desc = ""
        if sleep.has_data and 0 < sleep.latest < 5.0:
            has_sleep_deficit = True
            sleep_desc = f"{sleep.latest:.1f}h sleep"
        elif sleep_eff.has_data and 0 < sleep_eff.latest < 65.0:
            has_sleep_deficit = True
            sleep_desc = f"{sleep_eff.latest:.0f}% sleep efficiency"

        if has_exposure and has_shuffling_cadence and has_sleep_deficit:
            return self.trigger(
                severity=RiskLevel.HIGH,
                message=(
                    f"Elevated fall risk: senior has accumulated {steps.latest:.0f} steps at a cautious, "
                    f"shuffling cadence of {cadence.latest:.0f} steps/min after acute sleep deficit ({sleep_desc}). "
                    f"Ensure walkways are clear, lighting is bright, and supportive footwear is worn."
                ),
                evidence={
                    "total_steps": steps.latest,
                    "avg_cadence_spm": cadence.latest,
                    "sleep_hours": sleep.latest if sleep.has_data else None,
                    "sleep_efficiency_pct": sleep_eff.latest if sleep_eff.has_data else None,
                    "guideline": "AGS/BGS Fall Prevention Guidelines 2011; Middleton et al. JOSPT 2015",
                },
            )

        return self.pass_rule()


# ==============================================================================
# RULE 4: Sedentary Trapping & Circadian Fragmentation (Batch: Evening Cron)
# ==============================================================================
class SedentaryTrappingRule(InsightRule):
    """
    Detects prolonged unbroken sitting and failure to break sedentary behavior
    across the full waking day.

    PLAIN-ENGLISH CLINICAL EXPLANATION:
    Even if someone does a brief morning walk, sitting continuously for the rest
    of the day freezes joints, slows blood circulation, and causes legs to stiffen.
    Healthy aging requires breaking up long periods of sitting. If a senior was
    moving in fewer than 6 hours throughout their entire waking day and had under 20
    minutes of total active time, this rule sends a gentle evening reminder to break
    up sitting with short hourly strolls tomorrow.

    CLINICAL THRESHOLDS:
    ┌──────────────────────────────┬──────────────────────────────────────────┬──────────────┐
    │ Metric                       │ Threshold Criteria                       │ Our Severity │
    ├──────────────────────────────┼──────────────────────────────────────────┼──────────────┤
    │ Daytime Active Hours         │ active_hours_count < 6 hours             │ (Component)  │
    │ Daily Moving Time            │ active_movement_minutes < 20.0 minutes   │ (Component)  │
    ├──────────────────────────────┼──────────────────────────────────────────┼──────────────┤
    │ SEDENTARY TRAPPING           │ < 6 Active Hours + < 20 Active Minutes   │ LOW (Nudge)  │
    └──────────────────────────────┴──────────────────────────────────────────┴──────────────┘

    CITATIONS:
    - Diaz KM, Howard VJ, Montana B, et al. "Patterns of Sedentary Behavior
      and Mortality in U.S. Middle-Aged and Older Adults: A National Cohort Study."
      Annals of Internal Medicine. 2017;167(7):465-475.
      DOI: 10.7326/M17-0212
      https://doi.org/10.7326/M17-0212

    - Chastin SFM, De Craemer M, De Cocker K, et al. "Joint association of total
      daily physical activity and sedentary time with all-cause mortality."
      British Journal of Sports Medicine. 2021;55(22):1277-1285.
      DOI: 10.1136/bjsports-2020-103234
    """

    id = "sedentary_trapping"
    name = "Sedentary Trapping & Circadian Fragmentation"
    category = InsightCategory.MOBILITY
    tier = InsightTier.TIER_1
    requires_baseline = False
    evaluation_mode = "batch"

    def evaluate(self, ctx: EvalContext) -> InsightResult:
        active_hours = ctx.vitals.metric("active_hours_count")
        active_mins = ctx.vitals.metric("active_movement_minutes")

        if not active_hours.has_data or not active_mins.has_data:
            return self.skip_rule("Requires active hours count and active movement minutes")

        if active_hours.latest < 6 and active_mins.latest < 20.0:
            return self.trigger(
                severity=RiskLevel.LOW,
                message=(
                    f"Sedentary pattern noted: movement occurred in only {active_hours.latest:.0f} hours today "
                    f"with {active_mins.latest:.0f} total active minutes. Breaking up sitting with a 2-minute "
                    f"stroll each hour tomorrow will maintain circulation and joint mobility."
                ),
                evidence={
                    "active_hours_count": active_hours.latest,
                    "active_movement_minutes": active_mins.latest,
                    "guideline": "Diaz et al. Ann Intern Med 2017; Chastin et al. BJSM 2021",
                },
            )

        return self.pass_rule()


# ==============================================================================
# RULE 5: EWGSOP2 Sarcopenia & Chronic Frailty Screen (Batch: Nightly Batch)
# ==============================================================================
class EWGSOP2SarcopeniaScreenRule(InsightRule):
    """
    Evaluates 14-day rolling gait velocity to screen for progressive sarcopenia
    and neuromuscular frailty according to European consensus standards.

    PLAIN-ENGLISH CLINICAL EXPLANATION:
    Sarcopenia is the gradual age-related loss of muscle strength and mass.
    International clinical guidelines state that walking slower than 0.8 meters
    per second is a clear sign of physical frailty. In smartwatches, this corresponds
    to an average walking cadence staying below 65 steps per minute. If a senior's
    two-week median walking cadence remains under 65 steps/min alongside low daily
    movement time and step counts, this rule alerts caregivers and recommends leg
    strengthening exercises to rebuild muscle.

    CLINICAL THRESHOLDS (14-Day Rolling Median):
    ┌──────────────────────────────┬──────────────────────────────────────────┬──────────────┐
    │ Metric                       │ Threshold Criteria (14-Day Median)       │ Our Severity │
    ├──────────────────────────────┼──────────────────────────────────────────┼──────────────┤
    │ 14-Day Median Cadence        │ < 65.0 steps/min (corresponds to <0.8m/s)│ (Component)  │
    │ 14-Day Median Active Mins    │ < 20.0 minutes/day                       │ (Component)  │
    │ 14-Day Median Step Volume    │ < 3,500 steps/day                        │ (Component)  │
    ├──────────────────────────────┼──────────────────────────────────────────┼──────────────┤
    │ SARCOPENIA SUSPECTED         │ Cadence <65 + Mins <20 + Steps <3,500    │ MEDIUM       │
    └──────────────────────────────┴──────────────────────────────────────────┴──────────────┘

    CITATIONS:
    - Cruz-Jentoft AJ, Bahat G, Bauer J, et al. (EWGSOP2).
      "Sarcopenia: revised European consensus on definition and diagnosis."
      Age and Ageing. 2019;48(1):16-31.
      DOI: 10.1093/ageing/afy169
      https://doi.org/10.1093/ageing/afy169

    - Fried LP, Tangen CM, Walston J, et al. "Frailty in Older Adults: Evidence
      for a Phenotype." J Gerontol A Biol Sci Med Sci. 2001;56(3):M146-M157.
      DOI: 10.1093/gerona/56.3.m146
    """

    id = "ewgsop2_sarcopenia_screen"
    name = "EWGSOP2 Sarcopenia & Chronic Frailty Screen"
    category = InsightCategory.MOBILITY
    tier = InsightTier.TIER_1
    requires_baseline = False
    evaluation_mode = "batch"

    def evaluate(self, ctx: EvalContext) -> InsightResult:
        cadence = ctx.vitals.metric("avg_cadence_spm")
        active_mins = ctx.vitals.metric("active_movement_minutes")
        steps = ctx.vitals.metric("steps")

        if not cadence.has_data or not active_mins.has_data:
            return self.skip_rule("Requires walking cadence and active movement minutes")

        # 14-day trailing window
        cutoff = datetime.now().date() - timedelta(days=14)
        recent_cadence = [d.value for d in cadence.data if d.date >= cutoff and d.value > 0]
        recent_mins = [d.value for d in active_mins.data if d.date >= cutoff]
        recent_steps = [d.value for d in steps.data if d.date >= cutoff]

        if len(recent_cadence) < 5:
            return self.skip_rule("Need at least 5 days of mobility data in the last 14 days for sarcopenia screening")

        med_cadence = statistics.median(recent_cadence)
        med_mins = statistics.median(recent_mins) if recent_mins else 0.0
        med_steps = statistics.median(recent_steps) if recent_steps else 0.0

        # EWGSOP2 cutpoint: cadence < 65 spm (approx < 0.8 m/s), < 20 mins, < 3500 steps
        if med_cadence < 65.0 and med_mins < 20.0 and med_steps < 3500:
            return self.trigger(
                severity=RiskLevel.MEDIUM,
                message=(
                    f"Chronic low mobility pattern: 14-day median walking cadence is {med_cadence:.0f} steps/min "
                    f"(EWGSOP2 guideline threshold: <65 spm / 0.8 m/s), with median active time of {med_mins:.0f} mins "
                    f"and {med_steps:.0f} steps. Consider evaluating for sarcopenia, joint pain, or prescribing gentle resistance exercises."
                ),
                evidence={
                    "14d_median_cadence_spm": med_cadence,
                    "14d_median_active_minutes": med_mins,
                    "14d_median_steps": med_steps,
                    "sample_days_evaluated": len(recent_cadence),
                    "guideline": "EWGSOP2 (Cruz-Jentoft et al. Age & Ageing 2019); Fried et al. 2001",
                },
            )

        return self.pass_rule()


# ==============================================================================
# RULE 6: Daily Longevity & Vitality Milestone (Batch: Evening / Morning)
# ==============================================================================
class DailyLongevityMilestoneRule(InsightRule):
    """
    Recognizes and reinforces optimal functional vitality and cardiovascular
    reserve in older adults meeting WHO physical activity standards.

    PLAIN-ENGLISH CLINICAL EXPLANATION:
    Positive reinforcement is key to maintaining healthy habits. The World Health
    Organization recommends that seniors get at least 30 minutes of moderate
    activity daily. A brisk cadence of 85+ steps per minute distributed across
    8 or more active hours represents the gold standard of healthy aging, strong
    muscles, and cardiovascular resilience. This rule celebrates that milestone.

    CLINICAL THRESHOLDS:
    ┌──────────────────────────────┬──────────────────────────────────────────┬──────────────┐
    │ Metric                       │ Threshold Criteria                       │ Our Severity │
    ├──────────────────────────────┼──────────────────────────────────────────┼──────────────┤
    │ Brisk Senior Cadence         │ avg_cadence_spm >= 85.0 steps/min        │ (Component)  │
    │ WHO Activity Duration        │ active_movement_minutes >= 30.0 mins     │ (Component)  │
    │ Circadian Distribution       │ active_hours_count >= 8 active hours     │ (Component)  │
    ├──────────────────────────────┼──────────────────────────────────────────┼──────────────┤
    │ VITALITY MILESTONE MET       │ Cadence >=85 + Mins >=30 + Hours >=8     │ LOW (Celebrate)
    └──────────────────────────────┴──────────────────────────────────────────┴──────────────┘

    CITATIONS:
    - Bull FC, Al-Ansari SS, Biddle S, et al. (World Health Organization).
      "World Health Organization 2020 guidelines on physical activity and
      sedentary behaviour." British Journal of Sports Medicine. 2020;54(24):1451-1462.
      DOI: 10.1136/bjsports-2020-102955
      https://doi.org/10.1136/bjsports-2020-102955

    - Tudor-Locke C, Han H, Aguiar EJ, et al. "How fast is fast enough? Walking
      cadence as a practical estimate of intensity in adults."
      British Journal of Sports Medicine. 2018;52(12):776-788.
      DOI: 10.1136/bjsports-2017-097628
    """

    id = "daily_longevity_milestone"
    name = "Daily Longevity & Vitality Milestone"
    category = InsightCategory.MOBILITY
    tier = InsightTier.TIER_1
    requires_baseline = False
    evaluation_mode = "batch"

    def evaluate(self, ctx: EvalContext) -> InsightResult:
        cadence = ctx.vitals.metric("avg_cadence_spm")
        active_mins = ctx.vitals.metric("active_movement_minutes")
        active_hours = ctx.vitals.metric("active_hours_count")

        if not cadence.has_data or not active_mins.has_data or not active_hours.has_data:
            return self.skip_rule("Requires walking cadence, active minutes, and active hours count")

        if cadence.latest >= 85.0 and active_mins.latest >= 30.0 and active_hours.latest >= 8:
            return self.trigger(
                severity=RiskLevel.LOW,
                message=(
                    f"Superb functional vitality today! Achieved a brisk cadence of {cadence.latest:.0f} steps/min "
                    f"(WHO standard: >=85 spm) with {active_mins.latest:.0f} active minutes across {active_hours.latest:.0f} active hours. "
                    f"Outstanding commitment to healthy longevity!"
                ),
                evidence={
                    "avg_cadence_spm": cadence.latest,
                    "active_movement_minutes": active_mins.latest,
                    "active_hours_count": active_hours.latest,
                    "guideline": "WHO 2020 Physical Activity Guidelines; Tudor-Locke et al. BJSM 2018",
                },
            )

        return self.pass_rule()


# Exported rules list for InsightEngine registration
MOBILITY_RULES: List[InsightRule] = [
    AcuteFunctionalCollapseRule(),
    CardiopulmonaryDecompensationRule(),
    AcuteFallRiskExhaustionRule(),
    SedentaryTrappingRule(),
    EWGSOP2SarcopeniaScreenRule(),
    DailyLongevityMilestoneRule(),
]
