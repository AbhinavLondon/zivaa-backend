"""
Tier 2 — Mental Health Rules (Validated Instrument–Aligned)

These rules detect depression, anxiety, sleep disturbance, and emotional
wellbeing decline in elderly patients. They use a dual-source strategy:

PRIMARY TRIGGERS — Validated screening instruments:
  - PHQ-2 (Patient Health Questionnaire-2) for depression screening
  - PSQI Item 6 for sleep quality assessment
  - Wearable sleep efficiency (AASM threshold)

SECONDARY / FALLBACK — Proxy vitals (Zivaa-defined):
  - mood_score (1-5), sleep_quality (0-100), steps, heart rate
  - Used for trend monitoring and when validated instruments are
    not yet available (graceful degradation)

ARCHITECTURE:
Each rule checks for the validated instrument FIRST. If available,
it uses the published cutoff for the trigger decision. If not
available (patient hasn't done the questionnaire yet), it falls
back to proxy vitals with an explicit "limitation" flag in the
evidence dict, so downstream consumers know the confidence level.

MODULE-LEVEL CITATIONS:
- American Psychiatric Association. "Diagnostic and Statistical Manual
  of Mental Disorders, Fifth Edition (DSM-5)." 2013.
  (Major Depressive Episode criteria: §296.21-296.36)

- Kroenke K, Spitzer RL, Williams JBW. "The Patient Health
  Questionnaire-2: Validity of a Two-Item Depression Screener."
  Med Care. 2003;41(11):1284-1292.
  DOI: 10.1097/01.MLR.0000093487.78664.3C
  https://pubmed.ncbi.nlm.nih.gov/14583691/

- Buysse DJ, et al. "The Pittsburgh Sleep Quality Index: A New
  Instrument for Psychiatric Practice and Research."
  Psychiatry Res. 1989;28(2):193-213.
  DOI: 10.1016/0165-1781(89)90047-4
  https://pubmed.ncbi.nlm.nih.gov/2748771/

- American Academy of Sleep Medicine (AASM). "International
  Classification of Sleep Disorders, Third Edition (ICSD-3)." 2014.
  (Sleep efficiency < 85% = insomnia criterion)
"""

from app.services.insights.core import InsightRule, RiskLevel, InsightCategory, InsightTier, InsightResult
from app.services.insights.context import EvalContext


class DepressionWithdrawalRule(InsightRule):
    """
    Detects depression / social withdrawal using PHQ-2 as primary
    instrument and proxy vitals as supporting evidence.

    PRIMARY TRIGGER — PHQ-2 (Kroenke 2003):
    ┌──────────────────────────────┬──────────────────┬──────────────┐
    │ PHQ-2 Score                  │ Interpretation   │ Our Severity │
    ├──────────────────────────────┼──────────────────┼──────────────┤
    │ 0-2                          │ Negative screen  │ (not flagged)│
    │ 3-4                          │ Possible MDD     │ MEDIUM       │
    │ 5-6                          │ Probable MDD     │ HIGH         │
    └──────────────────────────────┴──────────────────┴──────────────┘

    Sensitivity: 83%, Specificity: 92% at cutoff ≥ 3 (Kroenke 2003).
    Validated in geriatric populations: Li et al. 2007 (Int J Geriatr
    Psychiatry) confirmed PHQ-2 validity in elderly with sensitivity
    100% and specificity 77% at cutoff ≥ 3.

    SUPPORTING SIGNALS (Zivaa cross-correlation):
    - Activity withdrawal (steps z-score > 2.0) → DSM-5 Criterion A4
    - Sleep disruption (> 2h deviation) → DSM-5 Criterion A4

    FALLBACK (when PHQ-2 not available):
    - Uses mood_score (1-5) with Zivaa-defined threshold (≤ 2).
    - Marked as "unvalidated_fallback" in evidence.

    CITATIONS:
    - Kroenke K, Spitzer RL, Williams JBW. "The Patient Health
      Questionnaire-2: Validity of a Two-Item Depression Screener."
      Med Care. 2003;41(11):1284-1292.
      DOI: 10.1097/01.MLR.0000093487.78664.3C
      https://pubmed.ncbi.nlm.nih.gov/14583691/
      Table 4: PHQ-2 ≥ 3 → sensitivity 83%, specificity 92% for MDD.

    - Li C, Friedman B, Conwell Y, Fiscella K. "Validity of the Patient
      Health Questionnaire 2 (PHQ-2) in identifying major depression in
      older people." J Am Geriatr Soc. 2007;55(4):596-602.
      DOI: 10.1111/j.1532-5415.2007.01103.x
      https://pubmed.ncbi.nlm.nih.gov/17397440/
      (Geriatric validation: sensitivity 100%, specificity 77% at ≥ 3)

    - Löwe B, Kroenke K, Gräfe K. "Detecting and monitoring depression
      with a two-item questionnaire (PHQ-2)."
      J Psychosom Res. 2005;58(2):163-171.
      DOI: 10.1016/j.jpsychores.2004.09.006
      (Responsiveness to change over time)

    - APA. DSM-5. 2013. Major Depressive Episode criteria §296.21-296.36.
      Criterion A1: depressed mood. Criterion A4: psychomotor changes.
    """
    id = "depression_withdrawal"
    name = "Depression / Social Withdrawal Risk"
    category = InsightCategory.MENTAL_HEALTH
    tier = InsightTier.TIER_2

    # PHQ-2 validated cutoffs (Kroenke 2003, Table 4)
    PHQ2_POSSIBLE_MDD = 3   # Sensitivity 83%, Specificity 92%
    PHQ2_PROBABLE_MDD = 5   # Higher specificity

    def evaluate(self, ctx: EvalContext) -> InsightResult:
        phq2 = ctx.vitals.metric("phq2_score")
        mood = ctx.vitals.metric("mood_score")
        steps = ctx.vitals.metric("steps")
        sleep = ctx.vitals.metric("sleep_hours")

        # ── PATH A: PHQ-2 available (validated instrument) ────────────
        if phq2.has_data:
            phq2_score = phq2.latest

            # Collect supporting signals
            steps_crashed = False
            sleep_disrupted = False

            if steps.has_data and steps.is_baseline_established:
                steps_bl = steps.established_baseline
                steps_z = ((steps_bl.mean - steps.latest) / steps_bl.std) if steps_bl.std > 0 else 0
                steps_crashed = steps_z > 2.0

            if sleep.has_data and sleep.is_baseline_established:
                sleep_baseline = sleep.established_baseline.mean
                sleep_disrupted = abs(sleep.latest - sleep_baseline) > 2.0 if sleep_baseline > 0 else False

            if phq2_score >= self.PHQ2_PROBABLE_MDD:
                # PHQ-2 ≥ 5: Probable Major Depressive Disorder
                return self.trigger(
                    severity=RiskLevel.HIGH,
                    message=f"PHQ-2 depression screen is strongly positive (score: {phq2_score}/6, "
                            f"cutoff: ≥{self.PHQ2_PROBABLE_MDD}). Per Kroenke et al. (2003), this indicates "
                            f"probable major depression. Full PHQ-9 assessment and clinical referral recommended.",
                    evidence={
                        "phq2_score": phq2_score,
                        "phq2_cutoff": self.PHQ2_PROBABLE_MDD,
                        "instrument": "PHQ-2 (validated)",
                        "sensitivity": "83%",
                        "specificity": "92%",
                        "steps_crashed": steps_crashed,
                        "sleep_disrupted": sleep_disrupted,
                        "guideline": "Kroenke 2003 (Med Care), Li 2007 (JAGS)"
                    }
                )
            elif phq2_score >= self.PHQ2_POSSIBLE_MDD:
                # PHQ-2 ≥ 3: Positive screen — possible MDD
                severity = RiskLevel.HIGH if (steps_crashed or sleep_disrupted) else RiskLevel.MEDIUM
                return self.trigger(
                    severity=severity,
                    message=f"PHQ-2 depression screen is positive (score: {phq2_score}/6, "
                            f"cutoff: ≥{self.PHQ2_POSSIBLE_MDD}). "
                            f"{'Activity and/or sleep changes support this finding. ' if (steps_crashed or sleep_disrupted) else ''}"
                            f"Per Kroenke et al. (2003), sensitivity is 83% at this cutoff. "
                            f"Consider a full PHQ-9 or clinical evaluation.",
                    evidence={
                        "phq2_score": phq2_score,
                        "phq2_cutoff": self.PHQ2_POSSIBLE_MDD,
                        "instrument": "PHQ-2 (validated)",
                        "steps_crashed": steps_crashed,
                        "sleep_disrupted": sleep_disrupted,
                        "guideline": "Kroenke 2003 (Med Care)"
                    }
                )
            return self.pass_rule()

        # ── PATH B: PHQ-2 not available — fallback to proxy vitals ────
        if not mood.has_data:
            return self.skip_rule("No PHQ-2 or mood score data available. PHQ-2 screening recommended.")
        if not mood.is_baseline_established:
            return self.skip_rule("Mood score baseline not yet established (need 7+ days)")

        mood_baseline = mood.established_baseline.mean
        mood_trend = mood.trend(days=7)
        mood_declining = mood_trend.is_decreasing()
        mood_low = mood.latest <= 2.0

        if not (mood_declining or mood_low):
            return self.pass_rule()

        steps_crashed = False
        sleep_disrupted = False

        if steps.has_data and steps.is_baseline_established:
            steps_bl = steps.established_baseline
            steps_z = ((steps_bl.mean - steps.latest) / steps_bl.std) if steps_bl.std > 0 else 0
            steps_crashed = steps_z > 2.0

        if sleep.has_data and sleep.is_baseline_established:
            sleep_baseline = sleep.established_baseline.mean
            sleep_disrupted = abs(sleep.latest - sleep_baseline) > 2.0 if sleep_baseline > 0 else False

        supporting_count = sum([steps_crashed, sleep_disrupted])

        if mood_low and mood_declining and supporting_count >= 1:
            return self.trigger(
                severity=RiskLevel.HIGH,
                message=f"Mood has been declining over the past week (now {mood.latest:.0f}/5) with "
                        f"reduced activity and disrupted sleep. Note: this uses a non-validated mood "
                        f"scale. PHQ-2 screening is recommended for clinical confirmation.",
                evidence={
                    "mood_latest": mood.latest,
                    "mood_baseline": round(mood_baseline, 1),
                    "steps_crashed": steps_crashed,
                    "sleep_disrupted": sleep_disrupted,
                    "instrument": "mood_score (unvalidated_fallback)",
                    "recommendation": "administer_PHQ2"
                }
            )
        elif mood_low or (mood_declining and supporting_count >= 1):
            return self.trigger(
                severity=RiskLevel.MEDIUM,
                message=f"Mood score is low ({mood.latest:.0f}/5, baseline {mood_baseline:.1f}). "
                        f"PHQ-2 screening recommended for validated depression assessment.",
                evidence={
                    "mood_latest": mood.latest,
                    "mood_baseline": round(mood_baseline, 1),
                    "instrument": "mood_score (unvalidated_fallback)",
                    "recommendation": "administer_PHQ2"
                }
            )

        return self.pass_rule()


class AnxietyAgitationRule(InsightRule):
    """
    Detects anxiety and agitation through physiological markers.

    NOTE: No brief validated anxiety instrument is integrated yet.
    The GAD-2 is documented as the recommended future integration.
    Current detection relies on physiological proxies (HR z-score,
    sleep quality) which are supported by research but do not
    constitute a validated anxiety screening.

    HR THRESHOLD — z-score based (aligned with wearable research):
    - z-score > 1.5 (modest elevation, below illness threshold of 2.0)
    - Fever exclusion: if temp > 37.5°C, HR attributed to illness

    FUTURE WORK — GAD-2 (Kroenke et al. 2007):
    Q1: "Feeling nervous, anxious, or on edge?" (0-3)
    Q2: "Unable to stop or control worrying?" (0-3)
    Score ≥ 3 = positive screen (sensitivity 86%, specificity 83%)

    CITATIONS:
    - Chalmers JA, Quintana DS, Abbott MJ, Kemp AH. "Anxiety Disorders
      are Associated with Reduced Heart Rate Variability: A Meta-Analysis."
      Front Psychiatry. 2014;5:80.
      DOI: 10.3389/fpsyt.2014.00080
      https://www.frontiersin.org/articles/10.3389/fpsyt.2014.00080
      (Meta-analysis of 36 studies: anxiety → reduced HRV, elevated RHR)

    - Spitzer RL, Kroenke K, Williams JBW, Löwe B. "A Brief Measure
      for Assessing Generalized Anxiety Disorder: The GAD-7."
      Arch Intern Med. 2006;166(10):1092-1097.
      DOI: 10.1001/archinte.166.10.1092
      https://jamanetwork.com/journals/jamainternalmedicine/fullarticle/410326

    - Kroenke K, Spitzer RL, Williams JBW, Monahan PO, Löwe B.
      "Anxiety disorders in primary care: prevalence, impairment,
      comorbidity, and detection."
      Ann Intern Med. 2007;146(5):317-325.
      DOI: 10.7326/0003-4819-146-5-200703060-00004
      https://pubmed.ncbi.nlm.nih.gov/17339617/
      (GAD-2 at cutoff ≥ 3: sensitivity 86%, specificity 83%)

    - Pachana NA, et al. "Development and validation of the Geriatric
      Anxiety Inventory." Int Psychogeriatr. 2007;19(1):103-114.
      DOI: 10.1017/S1041610206003504
      (Geriatric-specific anxiety instrument, 20 items)
    """
    id = "anxiety_agitation"
    name = "Anxiety / Agitation Detection"
    category = InsightCategory.MENTAL_HEALTH
    tier = InsightTier.TIER_2

    # z-score threshold for HR elevation (Zivaa-defined)
    HR_Z_THRESHOLD = 1.5

    def evaluate(self, ctx: EvalContext) -> InsightResult:
        sleep_quality = ctx.vitals.metric("sleep_quality")
        hr = ctx.vitals.metric("avg_heart_rate")
        mood = ctx.vitals.metric("mood_score")
        temp = ctx.vitals.metric("body_temp")

        has_sleep_signal = sleep_quality.has_data
        has_hr_signal = hr.has_data and hr.is_baseline_established

        if not has_sleep_signal and not has_hr_signal:
            return self.skip_rule("No sleep quality or heart rate baseline available for anxiety detection")

        # Signal 1: Sleep quality deteriorating
        sleep_poor = False
        if has_sleep_signal:
            sleep_poor = sleep_quality.latest < 40.0

        # Signal 2: HR elevated (z-score, per Chalmers 2014)
        hr_elevated = False
        hr_z = 0
        if has_hr_signal:
            hr_bl = hr.established_baseline
            hr_z = ((hr.latest - hr_bl.mean) / hr_bl.std) if hr_bl.std > 0 else 0
            hr_elevated = hr_z > self.HR_Z_THRESHOLD

            # Differential diagnosis: fever → illness, not anxiety
            if temp.has_data and temp.latest > 37.5:
                hr_elevated = False

        # Signal 3: Mood declining (optional)
        mood_dropping = False
        if mood.has_data:
            mood_trend = mood.trend(days=5)
            mood_dropping = mood_trend.is_decreasing() and mood.latest <= 3.0

        if not (sleep_poor or hr_elevated):
            return self.pass_rule()

        if sleep_poor and hr_elevated and mood_dropping:
            return self.trigger(
                severity=RiskLevel.HIGH,
                message=f"Signs of anxiety detected: poor sleep quality ({sleep_quality.latest:.0f}/100), "
                        f"elevated resting heart rate ({hr.latest:.0f} bpm, z-score: {hr_z:.1f}, "
                        f"per Chalmers 2014 autonomic arousal pattern), and declining mood. "
                        f"GAD-2 screening recommended for validated assessment.",
                evidence={
                    "sleep_quality": sleep_quality.latest if has_sleep_signal else None,
                    "hr_latest": hr.latest if has_hr_signal else None,
                    "hr_z_score": round(hr_z, 2),
                    "mood_dropping": mood_dropping,
                    "instrument": "physiological_proxy (no validated screen)",
                    "recommendation": "administer_GAD2",
                    "guideline": "Chalmers 2014 (Front Psychiatry)"
                }
            )
        elif sleep_poor and hr_elevated:
            return self.trigger(
                severity=RiskLevel.MEDIUM,
                message=f"Sleep quality is poor ({sleep_quality.latest:.0f}/100) and resting heart rate "
                        f"is above personal baseline ({hr.latest:.0f} bpm, z-score: {hr_z:.1f}). "
                        f"Per Chalmers et al. (2014), this combination may indicate anxiety.",
                evidence={
                    "sleep_quality": sleep_quality.latest,
                    "hr_latest": hr.latest,
                    "hr_z_score": round(hr_z, 2),
                    "instrument": "physiological_proxy",
                    "guideline": "Chalmers 2014"
                }
            )
        elif sleep_poor and mood_dropping:
            return self.trigger(
                severity=RiskLevel.MEDIUM,
                message=f"Sleep quality has dropped to {sleep_quality.latest:.0f}/100 alongside a "
                        f"declining mood ({mood.latest:.0f}/5). GAD-2 screening recommended.",
                evidence={
                    "sleep_quality": sleep_quality.latest,
                    "mood_latest": mood.latest,
                    "instrument": "physiological_proxy",
                    "recommendation": "administer_GAD2"
                }
            )

        return self.pass_rule()


class SleepDisturbanceRule(InsightRule):
    """
    Detects chronic sleep disturbance using a 3-tier evidence hierarchy:

    TIER 1 (Strongest) — PSQI Item 6 (Buysse 1989):
    ┌──────────────────────────────┬──────────────────┬──────────────┐
    │ PSQI Item 6 Response         │ Score            │ Our Severity │
    ├──────────────────────────────┼──────────────────┼──────────────┤
    │ "Very good"                  │ 0                │ (not flagged)│
    │ "Fairly good"                │ 1                │ (not flagged)│
    │ "Fairly bad"                 │ 2                │ LOW          │
    │ "Very bad"                   │ 3                │ MEDIUM       │
    └──────────────────────────────┴──────────────────┴──────────────┘

    PSQI Item 6 alone has r = 0.80 correlation with full PSQI global
    score (Buysse 1989). Full PSQI global score > 5 = "poor sleeper".

    TIER 2 (Moderate) — Wearable sleep efficiency (AASM ICSD-3):
    - Sleep efficiency < 85% = insomnia criterion per AASM ICSD-3 (2014)
    - Sleep efficiency = (total_sleep_time / time_in_bed) × 100

    TIER 3 (Fallback) — Zivaa sleep_quality (0-100):
    - Non-validated, used only when Tiers 1-2 are unavailable
    - Marked as "unvalidated_fallback" in evidence

    CITATIONS:
    - Buysse DJ, Reynolds CF, Monk TH, Berman SR, Kupfer DJ. "The
      Pittsburgh Sleep Quality Index: A New Instrument for Psychiatric
      Practice and Research."
      Psychiatry Res. 1989;28(2):193-213.
      DOI: 10.1016/0165-1781(89)90047-4
      https://pubmed.ncbi.nlm.nih.gov/2748771/
      Item 6: "During the past month, how would you rate your sleep
      quality overall?" — scored 0-3.
      Global PSQI > 5 identifies poor sleepers with sensitivity 89.6%
      and specificity 86.5%.

    - American Academy of Sleep Medicine. "International Classification
      of Sleep Disorders, Third Edition (ICSD-3)." 2014.
      Insomnia criterion: sleep efficiency < 85%.
      https://aasm.org/clinical-resources/international-classification-sleep-disorders/

    - Mander BA, Winer JR, Walker MP. "Sleep and Human Aging."
      Neuron. 2017;94(1):19-36.
      DOI: 10.1016/j.neuron.2017.02.004
      https://www.cell.com/neuron/fulltext/S0896-6273(17)30088-0
      (Sleep disruption accelerates cognitive decline in elderly)

    - Shi L, et al. "Sleep disturbances increase the risk of dementia:
      A systematic review and meta-analysis."
      Sleep Med Rev. 2018;40:4-16.
      DOI: 10.1016/j.smrv.2017.06.010
      (Sleep disturbance → 1.68× dementia risk in elderly)
    """
    id = "sleep_disturbance"
    name = "Chronic Sleep Disturbance"
    category = InsightCategory.MENTAL_HEALTH
    tier = InsightTier.TIER_2

    # PSQI Item 6 cutoffs (Buysse 1989)
    PSQI_FAIRLY_BAD = 2
    PSQI_VERY_BAD = 3

    # AASM ICSD-3 insomnia criterion
    SLEEP_EFFICIENCY_THRESHOLD = 85.0

    def evaluate(self, ctx: EvalContext) -> InsightResult:
        psqi = ctx.vitals.metric("psqi_item6")
        sleep_eff = ctx.vitals.metric("sleep_efficiency")
        sleep_quality = ctx.vitals.metric("sleep_quality")
        sleep_hours = ctx.vitals.metric("sleep_hours")

        # ── TIER 1: PSQI Item 6 (validated instrument) ────────────────
        if psqi.has_data:
            psqi_score = psqi.latest

            # Duration irregularity as supporting signal
            duration_detail = ""
            if sleep_hours.has_data and sleep_hours.is_baseline_established:
                sleep_baseline = sleep_hours.established_baseline.mean
                if abs(sleep_hours.latest - sleep_baseline) > 2.0:
                    duration_detail = (f" Sleep duration is also irregular "
                                       f"({sleep_hours.latest:.1f}h vs baseline {sleep_baseline:.1f}h).")

            if psqi_score >= self.PSQI_VERY_BAD:
                return self.trigger(
                    severity=RiskLevel.MEDIUM,
                    message=f"PSQI Item 6 sleep quality is rated 'Very Bad' (score: {psqi_score}/3). "
                            f"Per Buysse et al. (1989), this correlates with a full PSQI global "
                            f"score indicating clinically poor sleep.{duration_detail} "
                            f"Per Shi et al. (2018), sustained poor sleep increases dementia risk 1.68×.",
                    evidence={
                        "psqi_item6": psqi_score,
                        "instrument": "PSQI_Item6 (validated)",
                        "psqi_correlation": "r=0.80 with global PSQI",
                        "guideline": "Buysse 1989 (Psychiatry Res), Shi 2018"
                    }
                )
            elif psqi_score >= self.PSQI_FAIRLY_BAD:
                return self.trigger(
                    severity=RiskLevel.LOW,
                    message=f"PSQI Item 6 sleep quality is rated 'Fairly Bad' (score: {psqi_score}/3). "
                            f"Worth monitoring — per Mander et al. (2017), persistent poor sleep "
                            f"accelerates cognitive decline in elderly patients.{duration_detail}",
                    evidence={
                        "psqi_item6": psqi_score,
                        "instrument": "PSQI_Item6 (validated)",
                        "guideline": "Buysse 1989, Mander 2017"
                    }
                )
            return self.pass_rule()

        # ── TIER 2: Wearable sleep efficiency (AASM ICSD-3) ──────────
        if sleep_eff.has_data:
            if sleep_eff.latest < self.SLEEP_EFFICIENCY_THRESHOLD:
                # Check if it's a sustained pattern
                is_declining = False
                if sleep_eff.is_baseline_established:
                    eff_trend = sleep_eff.trend(days=7)
                    is_declining = eff_trend.is_decreasing()

                severity = RiskLevel.MEDIUM if is_declining else RiskLevel.LOW
                return self.trigger(
                    severity=severity,
                    message=f"Sleep efficiency is {sleep_eff.latest:.0f}%, below the AASM ICSD-3 "
                            f"insomnia criterion of {self.SLEEP_EFFICIENCY_THRESHOLD:.0f}%. "
                            f"{'This has been declining over the past week. ' if is_declining else ''}"
                            f"Per Mander et al. (2017), poor sleep efficiency accelerates "
                            f"cognitive decline in elderly populations.",
                    evidence={
                        "sleep_efficiency": sleep_eff.latest,
                        "aasm_threshold": self.SLEEP_EFFICIENCY_THRESHOLD,
                        "instrument": "wearable_sleep_efficiency (AASM-aligned)",
                        "declining": is_declining,
                        "guideline": "AASM ICSD-3 2014, Mander 2017"
                    }
                )
            return self.pass_rule()

        # ── TIER 3: Fallback — Zivaa sleep_quality (unvalidated) ──────
        if not sleep_quality.has_data:
            return self.skip_rule("No PSQI, sleep efficiency, or sleep quality data available")
        if not sleep_quality.is_baseline_established:
            return self.skip_rule("Sleep quality baseline not yet established (need 7+ days)")

        sq_baseline = sleep_quality.established_baseline.mean
        sq_trend = sleep_quality.trend(days=7)

        quality_crashed = sleep_quality.latest < (sq_baseline - 20) and sleep_quality.latest < 50.0
        quality_declining = sq_trend.is_decreasing() and sq_trend.percent_change < -15

        if not (quality_crashed or quality_declining):
            return self.pass_rule()

        if quality_crashed and quality_declining:
            return self.trigger(
                severity=RiskLevel.MEDIUM,
                message=f"Sleep quality has dropped significantly ({sleep_quality.latest:.0f}/100, "
                        f"baseline {sq_baseline:.0f}). Note: this uses a non-validated scale. "
                        f"PSQI assessment or wearable sleep tracking recommended for clinical confirmation.",
                evidence={
                    "sleep_quality_latest": sleep_quality.latest,
                    "sleep_quality_baseline": round(sq_baseline, 1),
                    "instrument": "sleep_quality_score (unvalidated_fallback)",
                    "recommendation": "administer_PSQI_or_enable_wearable_sleep",
                    "guideline": "Mander 2017, Shi 2018"
                }
            )
        elif quality_crashed or quality_declining:
            return self.trigger(
                severity=RiskLevel.LOW,
                message=f"Sleep quality has dipped to {sleep_quality.latest:.0f}/100 (baseline "
                        f"{sq_baseline:.0f}). PSQI assessment recommended for validated evaluation.",
                evidence={
                    "sleep_quality_latest": sleep_quality.latest,
                    "instrument": "sleep_quality_score (unvalidated_fallback)",
                    "recommendation": "administer_PSQI"
                }
            )

        return self.pass_rule()


class EmotionalWellbeingRule(InsightRule):
    """
    Catches sustained low mood / emotional flatness using PHQ-2 as
    primary instrument and mood_score as fallback.

    Unlike DepressionWithdrawalRule (which checks for a declining trend
    + activity/sleep cross-correlation), this rule catches persistent
    flat low mood that doesn't show recent change — the patient may
    have been low for weeks without a drop, which the trend-based
    rule would miss.

    PRIMARY TRIGGER — PHQ-2 (Kroenke 2003):
    Same cutoffs as DepressionWithdrawalRule:
    - PHQ-2 ≥ 3 = positive screen
    - PHQ-2 ≥ 5 = probable MDD

    NOTE: If PHQ-2 triggers in both this rule and DepressionWithdrawalRule,
    that's intentional — the engine deduplicates by severity, and having
    two rules fire confirms the signal. However, the rules check different
    patterns: DepressionWithdrawalRule requires trend + cross-correlation,
    while this rule catches persistent states.

    FALLBACK:
    - mood_score ≤ 2/5 when baseline > 3/5 (Zivaa-defined, marked as
      "unvalidated_fallback")
    - Statistical: mood < baseline - max(1 SD, 1.0 point)

    CITATIONS:
    - Kroenke K, Spitzer RL, Williams JBW. "The PHQ-2."
      Med Care. 2003;41(11):1284-1292.
      DOI: 10.1097/01.MLR.0000093487.78664.3C
      (Same citation as DepressionWithdrawalRule)

    - Löwe B, Kroenke K, Gräfe K. "Detecting and monitoring depression
      with a two-item questionnaire (PHQ-2)."
      J Psychosom Res. 2005;58(2):163-171.
      DOI: 10.1016/j.jpsychores.2004.09.006
      (PHQ-2 is responsive to change over time — validated for monitoring)

    - Kroenke K, Spitzer RL, Williams JBW. "The PHQ-9: Validity of a
      Brief Depression Severity Measure."
      J Gen Intern Med. 2001;16(9):606-613.
      DOI: 10.1046/j.1525-1497.2001.016009606.x
      https://pubmed.ncbi.nlm.nih.gov/11556941/
      (PHQ-9: follow-up to PHQ-2 positive screen for severity grading)

    - APA. DSM-5. 2013. Criterion A1: "Depressed mood most of the day,
      nearly every day." (Persistent flat low mood pattern)
    """
    id = "emotional_wellbeing"
    name = "Emotional Wellbeing Decline"
    category = InsightCategory.MENTAL_HEALTH
    tier = InsightTier.TIER_2

    PHQ2_POSITIVE = 3
    PHQ2_PROBABLE = 5

    def evaluate(self, ctx: EvalContext) -> InsightResult:
        phq2 = ctx.vitals.metric("phq2_score")
        mood = ctx.vitals.metric("mood_score")

        # ── PATH A: PHQ-2 available (validated) ───────────────────────
        if phq2.has_data:
            phq2_score = phq2.latest

            if phq2_score >= self.PHQ2_PROBABLE:
                return self.trigger(
                    severity=RiskLevel.MEDIUM,
                    message=f"PHQ-2 score is {phq2_score}/6, indicating probable depression "
                            f"(cutoff: ≥{self.PHQ2_PROBABLE}, per Kroenke 2003). This may reflect "
                            f"sustained low emotional wellbeing. Full PHQ-9 and gentle check-in recommended.",
                    evidence={
                        "phq2_score": phq2_score,
                        "instrument": "PHQ-2 (validated)",
                        "guideline": "Kroenke 2003, Löwe 2005"
                    }
                )
            elif phq2_score >= self.PHQ2_POSITIVE:
                return self.trigger(
                    severity=RiskLevel.LOW,
                    message=f"PHQ-2 score is {phq2_score}/6, a positive screen "
                            f"(cutoff: ≥{self.PHQ2_POSITIVE}). This could be a temporary dip, but worth "
                            f"monitoring. Per Löwe et al. (2005), PHQ-2 is responsive to change over time.",
                    evidence={
                        "phq2_score": phq2_score,
                        "instrument": "PHQ-2 (validated)",
                        "guideline": "Kroenke 2003, Löwe 2005"
                    }
                )
            return self.pass_rule()

        # ── PATH B: Fallback — mood_score (unvalidated) ───────────────
        if not mood.has_data:
            return self.skip_rule("No PHQ-2 or mood score data available")
        if not mood.is_baseline_established:
            return self.skip_rule("Mood score baseline not yet established (need 7+ days)")

        mood_baseline = mood.established_baseline.mean
        mood_std = mood.established_baseline.std

        significant_drop = mood.latest < (mood_baseline - max(mood_std, 1.0))
        persistent_low = mood.latest <= 2.0 and mood_baseline > 3.0

        if persistent_low:
            return self.trigger(
                severity=RiskLevel.MEDIUM,
                message=f"Mood has dropped from a baseline of {mood_baseline:.1f}/5 to "
                        f"{mood.latest:.0f}/5. Note: this uses a non-validated mood scale. "
                        f"PHQ-2 screening recommended for clinical confirmation.",
                evidence={
                    "mood_latest": mood.latest,
                    "mood_baseline": round(mood_baseline, 1),
                    "instrument": "mood_score (unvalidated_fallback)",
                    "recommendation": "administer_PHQ2"
                }
            )
        elif significant_drop:
            return self.trigger(
                severity=RiskLevel.LOW,
                message=f"Mood is lower than usual ({mood.latest:.0f}/5, typically {mood_baseline:.1f}). "
                        f"PHQ-2 screening recommended to assess clinical significance.",
                evidence={
                    "mood_latest": mood.latest,
                    "mood_baseline": round(mood_baseline, 1),
                    "drop_amount": round(mood_baseline - mood.latest, 1),
                    "instrument": "mood_score (unvalidated_fallback)",
                    "recommendation": "administer_PHQ2"
                }
            )

        return self.pass_rule()


# ---------------------------------------------------------------------------
# Export all mental health rules
# ---------------------------------------------------------------------------
MENTAL_HEALTH_RULES = [
    DepressionWithdrawalRule(),
    AnxietyAgitationRule(),
    SleepDisturbanceRule(),
    EmotionalWellbeingRule(),
]
