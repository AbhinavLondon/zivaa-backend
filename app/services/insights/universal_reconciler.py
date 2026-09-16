"""
Universal LOINC-Driven Clinical Lab Reconciler
==============================================

OVERVIEW & CLINICAL PURPOSE:
---------------------------
In clinical medicine, laboratory observations are longitudinal and dynamic.
When a patient undergoes diagnostic blood/urine testing, abnormal values
generate clinical insights (e.g. acute kidney injury, transaminitis, elevated
HbA1c, anemia, dyslipidemia, hypokalemia).

Over time, these clinical findings undergo one of three clinical evolutions:
  1. ACUTE RESOLUTION: An acute/reversible finding returns to normal limits
     following medical intervention or physiological recovery (e.g., dehydration
     corrects, liver enzymes recover, electrolytes normalize).
  2. CHRONIC THERAPEUTIC CONTROL: A chronic condition achieves clinical
     stability under long-term therapy (e.g., diabetes HbA1c reaches target,
     hypothyroidism TSH stabilizes on levothyroxine, LDL reaches target on statin).
  3. SHELF-LIFE / VALIDITY EXPIRATION: An acute lab result exceeds its diagnostic
     validity window (e.g., >30-60 days for acute infection/electrolytes, >180 days
     for routine screening) without re-testing, meaning it cannot be treated as an
     active emergency in current evaluations.

Without systematic automated reconciliation, historical abnormalities remain
indefinitely "active" in `active_clinical_insights`. Downstream reasoning models
(e.g., MedGemma in Tripwire or Daily Planning) receive these "zombie" insights,
compounding old diagnostic records with current wearable vitals and generating
catastrophic false alarms (such as diagnosing a cardiac emergency because a
3-year-old HbA1c of 10.0% was paired with a healthy 12,000-step walk).

ARCHITECTURAL PRINCIPLES:
------------------------
This engine provides UNIVERSAL reconciliation across the entire 20,000+
biomarker universe in LOINC_DICTIONARY and any lab in `fhir_observations`:
  - Does NOT rely on hardcoded per-biomarker scripts.
  - Leverages certifying laboratory reference intervals (CLSI EP28-A3c).
  - Evaluates four universal physiological polarity classes:
      a) Standard Unilateral (Upper bound: ALT, AST, BUN, Cr, Trop, Uric Acid)
      b) Inverse Unilateral (Lower bound: Hemoglobin, eGFR, HDL, Vit D, B12, Plt)
      c) Bilateral Homeostatic (Tight physiological interval: K, Na, Ca, Mg, TSH)
      d) Qualitative / Serology (Negative / Non-reactive: Urinalysis, Abs)
  - Enforces strict chronological precedence (lab_date >= insight_date).
  - Re-evaluates compound multi-analyte rules from TIER_3_RULES.
  - Classifies outcomes into:
      * 'resolved' (acute cleared from active memory)
      * 'controlled' (chronic severity lowered to LOW, alerts suppressed)
      * 'resolved_stale' (validity window expired without repeat test)
"""

import re
import math
from typing import List, Dict, Any, Optional, Tuple, Set
from datetime import datetime, date, timezone, timedelta

from app.services.insights.data_fetcher import supabase
from app.services.insights.context import EvalContext
from app.services.loinc_dictionary import (
    LOINC_DICTIONARY,
    CONSUMER_CATEGORY_MAP,
    normalize_text,
    get_loinc_mapping
)


# ==============================================================================
# SECTION 1: CLINICAL POLARITY & CLASSIFICATION REGISTRIES
# ==============================================================================

# Inverse-polarity biomarkers: HIGHER values denote physiological health/recovery.
# Being below range is pathological; rising or reaching reference_low denotes recovery.
# Citations:
# - Hemoglobin: WHO 2011 Haemoglobin Concentrations for Anemia Diagnosis
# - eGFR: KDIGO 2024 Clinical Practice Guideline for CKD Evaluation
# - HDL: ACC/AHA 2018 Cholesterol Guidelines (Cardioprotective lipid)
# - Vitamin D: Endocrine Society 2024 Clinical Practice Guideline
# - Vitamin B12: British Society for Haematology 2014 Guidelines
# - Ferritin: WHO 2020 Guidelines on Serum Ferritin Concentrations
INVERSE_POLARITY_LOINCS: Set[str] = {
    "718-7",        # Hemoglobin (Blood)
    "20509-6",      # Hemoglobin (Mass/volume in Blood)
    "4544-3",       # Hematocrit (Blood)
    "62238-1",      # Estimated GFR (eGFR CKD-EPI)
    "33914-3",      # eGFR (serum/plasma)
    "48642-3",      # eGFR non-black
    "48643-1",      # eGFR black
    "2085-9",       # HDL Cholesterol
    "2132-9",       # Vitamin B12 (Cobalamin)
    "14635-7",      # 25-OH Vitamin D
    "62292-8",      # 25-OH Vitamin D3
    "1989-3",       # 25-OH Vitamin D Total
    "2276-4",       # Serum Ferritin
    "2284-8",       # Serum Folate
    "777-3",        # Platelets count
    "1751-7",       # Serum Albumin
    "2991-8",       # Free Testosterone
}

# Bilateral homeostatic biomarkers: Tight physiological intervals where BOTH
# abnormally low and abnormally high levels represent critical medical hazards.
# Normalization requires: reference_low <= value <= reference_high.
# Citations:
# - Electrolytes: AHA/ACC/HRS 2018 Guidelines for Management of Ventricular Arrhythmias
# - TSH: American Thyroid Association (ATA) 2016 Guidelines
BILATERAL_HOMEOSTATIC_LOINCS: Set[str] = {
    "2823-3",       # Potassium (Serum/Plasma) - Risk: Hypokalemia / Hyperkalemia (Arrhythmia)
    "2951-2",       # Sodium (Serum/Plasma) - Risk: Hyponatremia / Hypernatremia (Seizure/Edema)
    "17861-6",      # Calcium (Serum/Plasma) - Risk: Hypocalcemia / Hypercalcemia (Tetany/Stones)
    "19123-9",      # Magnesium (Serum/Plasma) - Risk: Hypomagnesemia / Hypermagnesemia
    "2075-0",       # Chloride (Serum/Plasma)
    "1963-8",       # Bicarbonate / Total CO2 (Acid-base homeostasis)
    "3016-3",       # Thyroid Stimulating Hormone (TSH) - Risk: Hypo / Hyperthyroidism
    "3024-7",       # Free Thyroxine (FT4)
}

# Chronic / Manageable conditions:
# In geriatric medicine, conditions like Type 2 Diabetes, Primary Hypothyroidism,
# Essential Hypertension, and Chronic Kidney Disease do not simply "disappear".
# When diagnostic markers normalize or reach therapeutic targets, the condition
# is clinically "CONTROLLED" on therapy.
# Marking them 'controlled' with LOW severity preserves medical history in the chart
# while suppressing false emergency alerts in Tripwire & MedGemma.
CHRONIC_LOINCS: Set[str] = {
    "4548-4",       # HbA1c (Diabetes / Prediabetes)
    "3016-3",       # TSH (Hypothyroidism)
    "3024-7",       # Free T4
    "13457-7",      # LDL Cholesterol (Dyslipidemia / Atherosclerosis)
    "2089-1",       # LDL calculated
    "2093-3",       # Total Cholesterol
    "2571-8",       # Triglycerides
    "8098-6",       # Anti-Thyroperoxidase (Hashimoto's)
    "30522-7",      # hs-CRP (Chronic cardiovascular risk)
    "10835-7",      # Lipoprotein (a)
    "14959-1",      # Urine Albumin/Creatinine Ratio (Diabetic Nephropathy)
    "9318-7",       # UACR
    "62238-1",      # eGFR (CKD monitoring)
}

CHRONIC_RULE_IDS: Set[str] = {
    "prediabetes_progression",
    "diabetes_progression",
    "thyroid_dysfunction",
    "cardiovascular_risk",
    "silent_insulin_resistance",
    "hashimotos_disease",
    "hidden_cardiovascular_risk",
    "early_diabetic_nephropathy",
    "metabolic_syndrome",
}

# Category validity shelf-life (days):
# Lab tests have varying temporal validity based on pathophysiological turnover.
# When an insight's age exceeds this shelf-life without repeat verification,
# it is transitioned to 'resolved_stale' to prevent ancient data from polluting vitals.
CATEGORY_VALIDITY_DAYS: Dict[str, int] = {
    "Minerals": 30,         # Acute electrolytes (K, Na, Mg) change within days/weeks
    "Electrolytes": 30,
    "Infection": 30,        # Acute WBC, cultures, procalcitonin resolve rapidly
    "Immune": 45,           # Acute inflammatory flares (CRP, ESR)
    "Inflammation": 45,
    "Cardiac": 45,          # Acute cardiac necrosis/strain (Troponin, BNP)
    "Coagulation": 45,      # PT/INR, D-Dimer
    "Liver": 60,            # Transaminases (ALT, AST)
    "Hepatic": 60,
    "Renal": 90,            # Routine BUN, Creatinine, eGFR
    "Kidney": 90,
    "CBC": 90,              # Red cell turnover ~120 days; reticulocytes 90d
    "Blood": 90,
    "Iron Studies": 90,     # Ferritin, Transferrin
    "Vitamins": 90,         # Vitamin D, B12 repletion monitoring
    "Blood Sugar": 180,     # HbA1c measures 90-120d RBC glycation; ADA recommends 6mo
    "Metabolic": 180,
    "Lipid Profile": 180,   # Routine AHA/ACC lipid monitoring every 6-12 months
    "Heart": 180,
    "Thyroid": 180,         # ATA recommends TSH re-check every 6-12 months once stable
    "Hormones": 180,
    "General Labs": 90,     # Default subacute baseline
}
DEFAULT_VALIDITY_DAYS = 90

# Clinical diagnosis / condition vocabulary mapped directly to primary LOINCs.
# Enables instant lexical recognition when MedGemma, a doctor, or an external system
# writes diagnostic titles like "Severe Hyperuricemia" or "Hypokalemia detected".
CLINICAL_CONDITION_TO_LOINC: Dict[str, str] = {
    "hyperuricemia": "3084-1",       # Uric Acid
    "gout": "3084-1",
    "hyperkalemia": "2823-3",        # Potassium
    "hypokalemia": "2823-3",
    "hypernatremia": "2951-2",       # Sodium
    "hyponatremia": "2951-2",
    "hyperglycemia": "14771-0",      # Glucose
    "hypoglycemia": "14771-0",
    "diabetes": "4548-4",            # HbA1c
    "prediabetes": "4548-4",
    "anemia": "718-7",               # Hemoglobin
    "thrombocytopenia": "777-3",      # Platelets
    "thrombocytosis": "777-3",
    "leukocytosis": "6690-2",        # WBC
    "leukopenia": "6690-2",
    "hypothyroidism": "3016-3",      # TSH
    "hyperthyroidism": "3016-3",
    "tsh": "3016-3",
    "thyrotropin": "3016-3",
    "dyslipidemia": "13457-7",       # LDL
    "hypercholesterolemia": "13457-7",
    "hyperlipidemia": "13457-7",
    "hypertriglyceridemia": "2571-8",# Triglycerides
    "azotemia": "3094-0",            # BUN
    "uremia": "3094-0",
    "hypoalbuminemia": "1751-7",     # Albumin
    "hyperbilirubinemia": "1975-2",   # Bilirubin
    "jaundice": "1975-2",
    "hypocalcemia": "17861-6",       # Calcium
    "hypercalcemia": "17861-6",
    "hypomagnesemia": "19123-9",     # Magnesium
    "hypermagnesemia": "19123-9",
    "nephropathy": "14959-1",        # UACR
    "proteinuria": "14959-1",
    "microalbuminuria": "14959-1",
}


# ==============================================================================
# SECTION 2: UNIVERSAL IN-MEMORY LOINC INVERTED INDEX
# ==============================================================================

class UniversalLoincIndex:
    """
    Singleton In-Memory Inverted Index covering all 20,012 entries in LOINC_DICTIONARY.

    Provides O(1) lexical and phrase lookups:
      1. Pre-indexes all official LOINC names, synonyms, and consumer phrases.
      2. Normalizes tokens (expanding medical abbreviations e.g. pcv -> hematocrit).
      3. Enables sub-phrase and n-gram matching so complex clinical strings like
         "Severe Elevated Serum Potassium with Cardiac Risk" automatically
         resolve to LOINC 2823-3 (Potassium).
      4. Falls back to TF-IDF cosine similarity via get_loinc_mapping() for
         unindexed or ambiguous free-text.
    """
    _instance: Optional['UniversalLoincIndex'] = None
    _exact_index: Dict[str, str] = {}
    _is_initialized: bool = False

    @classmethod
    def get_instance(cls) -> 'UniversalLoincIndex':
        if cls._instance is None:
            cls._instance = cls()
            cls._instance._initialize()
        return cls._instance

    def _initialize(self):
        if self._is_initialized:
            return

        # 1. Index curated clinical conditions FIRST (e.g. hyperuricemia -> 3084-1, tsh -> 3016-3)
        for term, code in CLINICAL_CONDITION_TO_LOINC.items():
            norm = normalize_text(term)
            if norm:
                self._exact_index[norm] = code

        # 2. Index all official dictionary names and synonyms (without overwriting curated terms)
        for code, data in LOINC_DICTIONARY.items():
            names_and_syns = [data.get("name", "")] + data.get("synonyms", [])
            for term in names_and_syns:
                if not term:
                    continue
                norm = normalize_text(term)
                if norm and norm not in self._exact_index:
                    self._exact_index[norm] = code

        self._is_initialized = True

    def resolve_text_to_loinc(self, text: str) -> Optional[str]:
        """
        Resolves arbitrary clinical text, insight title, or message to a canonical LOINC code.
        """
        if not text:
            return None

        norm_query = normalize_text(text)
        if not norm_query:
            return None

        # 1. Exact full-string match (fastest)
        if norm_query in self._exact_index:
            return self._exact_index[norm_query]

        # 2. Check clinical conditions dictionary directly
        words = norm_query.split()
        for w in words:
            if w in CLINICAL_CONDITION_TO_LOINC:
                return CLINICAL_CONDITION_TO_LOINC[w]

        # 3. N-gram / Sub-phrase scan: evaluate multi-word window from largest to smallest
        # E.g., for "elevated serum potassium level":
        # window 3: "elevated serum potassium", "serum potassium level"
        # window 2: "elevated serum", "serum potassium" -> MATCHES 2823-3!
        max_window = min(len(words), 5)
        for length in range(max_window, 0, -1):
            for i in range(len(words) - length + 1):
                subphrase = " ".join(words[i:i + length])
                if subphrase in self._exact_index:
                    return self._exact_index[subphrase]

        # 4. Fall back to TF-IDF cosine similarity
        tfidf_match = get_loinc_mapping(text)
        if tfidf_match and "loinc_code" in tfidf_match:
            return tfidf_match["loinc_code"]

        return None


# ==============================================================================
# SECTION 3: UNIVERSAL CLINICAL LAB RECONCILER CORE ENGINE
# ==============================================================================

class UniversalLabReconciler:
    """
    Universal Clinical Laboratory Reconciliation Engine.

    Executes multi-pathway clinical reconciliation:
      1. Extraction: Resolves any active insight to constituent LOINC code(s).
      2. Chronological Precedence: Verifies repeat lab was collected >= insight date.
      3. Normalization: Evaluates physiological polarity & reference intervals.
      4. Compound Rule Re-eval: Re-runs deterministic Tier 3 rules if applicable.
      5. State Machine: Transitions to 'resolved', 'controlled', or 'resolved_stale'.
    """

    @staticmethod
    def get_index() -> UniversalLoincIndex:
        return UniversalLoincIndex.get_instance()

    # ──────────────────────────────────────────────────────────────────────────
    # Step 1: LOINC Extraction & Linkage Layer
    # ──────────────────────────────────────────────────────────────────────────
    @classmethod
    def resolve_loincs_for_insight(cls, insight: Dict[str, Any]) -> List[str]:
        """
        Extracts or infers all relevant LOINC codes for an active insight.

        Priorities:
          A. Direct metadata: insight['evidence']['loinc_code'] or ['loincs']
          B. Tier 3 Deterministic Rule mapping (from tier3_labs.py)
          C. Universal Inverted Index match on insight['name'] and ['rule_id']
          D. Lexical scan of insight['message']
        """
        loincs: Set[str] = set()

        evidence = insight.get("evidence") or {}
        if isinstance(evidence, dict):
            # Check direct LOINC code keys
            if evidence.get("loinc_code"):
                loincs.add(str(evidence["loinc_code"]))
            if isinstance(evidence.get("loincs"), list):
                for c in evidence["loincs"]:
                    loincs.add(str(c))
            if isinstance(evidence.get("biomarkers"), list):
                for c in evidence["biomarkers"]:
                    loincs.add(str(c))

        # Check known Tier 3 rule IDs
        rule_id = insight.get("rule_id", "")
        rule_loincs = cls._get_loincs_for_rule_id(rule_id)
        for c in rule_loincs:
            loincs.add(c)

        # If LOINCs already identified, return them
        if loincs:
            return list(loincs)

        # Lexical extraction via Universal Loinc Index
        index = cls.get_index()

        # Try insight name
        name_str = insight.get("name", "")
        matched_from_name = index.resolve_text_to_loinc(name_str)
        if matched_from_name:
            loincs.add(matched_from_name)

        # Try rule_id string itself (e.g., "hyperuricemia_alert")
        if not loincs and rule_id:
            cleaned_rule = rule_id.replace("_", " ")
            matched_from_rule = index.resolve_text_to_loinc(cleaned_rule)
            if matched_from_rule:
                loincs.add(matched_from_rule)

        # Try insight message
        if not loincs:
            msg_str = insight.get("message", "")
            matched_from_msg = index.resolve_text_to_loinc(msg_str[:120])
            if matched_from_msg:
                loincs.add(matched_from_msg)

        return list(loincs)

    @classmethod
    def _get_loincs_for_rule_id(cls, rule_id: str) -> List[str]:
        """
        Maps all 24 Tier 3 deterministic rule IDs to their monitored LOINCs.
        """
        rule_map: Dict[str, List[str]] = {
            "prediabetes_progression": ["4548-4"],
            "diabetes_progression": ["4548-4"],
            "kidney_decline": ["62238-1", "33914-3", "2160-0"],
            "anemia_detection": ["718-7", "20509-6"],
            "thyroid_dysfunction": ["3016-3", "3024-7"],
            "cardiovascular_risk": ["13457-7", "2089-1", "2093-3", "2085-9"],
            "silent_insulin_resistance": ["2571-8", "2085-9"],
            "anemia_root_cause_triage": ["2276-4", "2132-9", "2284-8", "787-2"],
            "acute_infection_inflammation": ["6690-2", "1988-5", "30341-2"],
            "acute_infection": ["6690-2", "1988-5", "30341-2"],
            "metabolic_syndrome": ["2571-8", "2085-9", "14771-0"],
            "dehydration_aki_risk": ["3094-0", "22664-7", "2160-0"],
            "dehydration_aki": ["3094-0", "22664-7", "2160-0"],
            "hyperuricemia_gout": ["3084-1"],
            "gout_flare": ["3084-1"],
            "severe_vitamin_d_deficiency": ["62292-8", "1989-3", "14635-7"],
            "severe_vitamin_d": ["62292-8", "1989-3", "14635-7"],
            "post_prandial_hyperglycemia": ["15077-1"],
            "meal_time_glucose_spike": ["15077-1"],
            "thrombosis_pe_risk": ["48065-7"],
            "pulmonary_embolism_rule": ["48065-7"],
            "arrhythmia_electrolyte_imbalance": ["2823-3"],
            "arrhythmia_electrolyte_rule": ["2823-3"],
            "acute_liver_injury": ["1742-6", "1920-8"],
            "biliary_obstruction": ["1975-2", "6768-6"],
            "hashimotos_thyroiditis": ["8098-6"],
            "hashimotos_disease": ["8098-6"],
            "hidden_cardiovascular_risk": ["30522-7", "10835-7"],
            "heart_failure_exacerbation_labs": ["33762-6", "30934-4"],
            "heart_failure_exacerbation": ["33762-6", "30934-4"],
            "hpa_axis_overtraining": ["2143-7", "2991-8"],
            "overtraining_syndrome": ["2143-7", "2991-8"],
            "early_diabetic_nephropathy": ["14959-1", "9318-7"],
            "primary_hyperparathyroidism": ["17861-6", "83112-3", "2731-8"],
            "advanced_anemia_subtyping": ["40443-4", "25007-6"],
        }
        return rule_map.get(rule_id, [])

    # ──────────────────────────────────────────────────────────────────────────
    # Step 2: Universal Biomarker Normalization Evaluator
    # ──────────────────────────────────────────────────────────────────────────
    @classmethod
    def evaluate_biomarker_normalization(
        cls,
        obs: Dict[str, Any],
        loinc: str
    ) -> Tuple[bool, str]:
        """
        Evaluates whether a laboratory observation is clinically normal or controlled.

        Applies:
          1. Qualitative / Serology string evaluation (negative / non-reactive / normal)
          2. Inverse Polarity lower-bound verification (val >= ref_low)
          3. Bilateral Homeostatic interval verification (ref_low <= val <= ref_high)
          4. Special Guideline Targets (e.g. ADA diabetes HbA1c < 7.0%)
          5. Standard Unilateral reference interval verification (val <= ref_high)

        Returns:
          (is_normal_or_controlled, clinical_explanation_string)
        """
        val_numeric = obs.get("value")
        if val_numeric is None:
            val_numeric = obs.get("value_numeric")

        val_string = obs.get("value_string")
        ref_low = obs.get("reference_low")
        ref_high = obs.get("reference_high")
        unit = obs.get("unit", "")
        flag = str(obs.get("flag", "")).lower()

        # ── 1. Qualitative / Serology tests ──
        if val_numeric is None and val_string:
            norm_str = str(val_string).lower().strip()
            negative_indicators = {"negative", "non-reactive", "normal", "absent", "not detected", "nil"}
            if any(ind in norm_str for ind in negative_indicators):
                return True, f"Qualitative finding is non-reactive/normal: '{val_string}'"
            return False, f"Qualitative finding indicates abnormal result: '{val_string}'"

        if val_numeric is None:
            return False, "No numeric or qualitative value present in observation"

        try:
            val = float(val_numeric)
        except (ValueError, TypeError):
            return False, f"Could not parse numeric value: {val_numeric}"

        # ── 2. Special Guideline: HbA1c / Glycemic Management (ADA 2024 §6) ──
        if loinc == "4548-4":
            # ADA 2024 Standards of Care:
            # - Normal non-diabetic: < 5.7%
            # - Pre-diabetes: 5.7 - 6.4%
            # - Diabetes therapeutic target on therapy: < 7.0%
            if val < 5.7:
                return True, f"HbA1c {val}% is within normal non-diabetic range (<5.7% per ADA 2024)"
            elif val < 7.0:
                return True, f"HbA1c {val}% achieves guideline therapeutic control (<7.0% per ADA 2024)"
            else:
                return False, f"HbA1c {val}% exceeds therapeutic glycemic control (>=7.0%)"

        # ── 3. Inverse Polarity (Higher is Healthy / Lower is Pathological) ──
        if loinc in INVERSE_POLARITY_LOINCS:
            # Check laboratory reference lower bound
            if ref_low is not None:
                try:
                    low_f = float(ref_low)
                    if val >= low_f:
                        return True, f"Biomarker value {val} {unit} is >= laboratory lower limit {low_f} {unit}"
                    else:
                        return False, f"Biomarker value {val} {unit} is below reference lower limit {low_f} {unit}"
                except (ValueError, TypeError):
                    pass

            # Guideline defaults if lab omitted ref_low
            if loinc in ("718-7", "20509-6"):  # Hemoglobin WHO threshold (female 12.0, male 13.0)
                if val >= 12.0:
                    return True, f"Hemoglobin {val} g/dL is above WHO anemia threshold (>=12.0 g/dL)"
                return False, f"Hemoglobin {val} g/dL indicates anemia (<12.0 g/dL)"

            if loinc in ("62238-1", "33914-3"):  # eGFR KDIGO threshold (CKD stage 1-2 >= 60)
                if val >= 60.0:
                    return True, f"eGFR {val} mL/min/1.73m2 indicates normal/mild filtration (>=60 per KDIGO 2024)"
                return False, f"eGFR {val} mL/min/1.73m2 indicates kidney function decline (<60)"

            if loinc == "2085-9":  # HDL Cholesterol
                if val >= 40.0:
                    return True, f"HDL {val} mg/dL is cardioprotective (>=40 mg/dL per ACC/AHA 2018)"
                return False, f"HDL {val} mg/dL is below protective threshold (<40 mg/dL)"

            if loinc in ("14635-7", "62292-8", "1989-3"):  # 25-OH Vitamin D
                if val >= 30.0:
                    return True, f"Vitamin D {val} ng/mL is sufficient (>=30 ng/mL per Endocrine Society)"
                return False, f"Vitamin D {val} ng/mL is insufficient (<30 ng/mL)"

            # Fallback: check flag
            if flag in ("normal", "in_range"):
                return True, f"Biomarker value {val} {unit} flagged normal by certifying lab"
            return False, f"Biomarker value {val} {unit} below expected range"

        # ── 4. Bilateral Homeostatic (Strict Physiological Range) ──
        if loinc in BILATERAL_HOMEOSTATIC_LOINCS:
            low_bound = None
            high_bound = None
            if ref_low is not None:
                try: low_bound = float(ref_low)
                except Exception: pass
            if ref_high is not None:
                try: high_bound = float(ref_high)
                except Exception: pass

            # Clinical guideline fallback defaults if lab omitted ranges
            if loinc == "2823-3":  # Potassium
                low_bound = low_bound or 3.5
                high_bound = high_bound or 5.0
            elif loinc == "2951-2":  # Sodium
                low_bound = low_bound or 135.0
                high_bound = high_bound or 145.0
            elif loinc == "19123-9":  # Magnesium
                low_bound = low_bound or 1.7
                high_bound = high_bound or 2.2
            elif loinc == "17861-6":  # Calcium
                low_bound = low_bound or 8.5
                high_bound = high_bound or 10.2
            elif loinc == "3016-3":  # TSH
                low_bound = low_bound or 0.4
                high_bound = high_bound or 4.0

            if low_bound is not None and high_bound is not None:
                if low_bound <= val <= high_bound:
                    return True, f"Electrolyte/hormone {val} {unit} within homeostatic interval [{low_bound}, {high_bound}]"
                return False, f"Electrolyte/hormone {val} {unit} outside safe homeostatic interval [{low_bound}, {high_bound}]"

        # ── 5. Standard Unilateral / General Biomarker (Upper Bound / Interval) ──
        low_bound = None
        high_bound = None
        if ref_low is not None:
            try: low_bound = float(ref_low)
            except Exception: pass
        if ref_high is not None:
            try: high_bound = float(ref_high)
            except Exception: pass

        # Both bounds available: standard interval
        if low_bound is not None and high_bound is not None:
            if low_bound <= val <= high_bound:
                return True, f"Value {val} {unit} is within reference interval [{low_bound}, {high_bound}]"
            return False, f"Value {val} {unit} is outside reference interval [{low_bound}, {high_bound}]"

        # Only upper bound available (e.g. ALT <= 40, hs-CRP <= 3.0)
        if high_bound is not None:
            if val <= high_bound:
                return True, f"Value {val} {unit} is <= upper reference limit {high_bound} {unit}"
            return False, f"Value {val} {unit} exceeds upper reference limit {high_bound} {unit}"

        # Only lower bound available
        if low_bound is not None:
            if val >= low_bound:
                return True, f"Value {val} {unit} is >= lower reference limit {low_bound} {unit}"
            return False, f"Value {val} {unit} is below lower reference limit {low_bound} {unit}"

        # If no reference range on report, rely on flag
        if flag in ("normal", "in_range"):
            return True, f"Value {val} {unit} flagged normal by laboratory"

        return False, f"Value {val} {unit} cannot be verified normal (no reference range or flagged abnormal)"

    # ──────────────────────────────────────────────────────────────────────────
    # Step 3: Main Patient Insight Reconciliation Loop
    # ──────────────────────────────────────────────────────────────────────────
    @classmethod
    def reconcile_patient_lab_insights(
        cls,
        patient_id: str,
        ctx: EvalContext,
        existing_insights: Optional[List[Dict[str, Any]]] = None
    ) -> List[Dict[str, Any]]:
        """
        Scans all active clinical insights for a patient and reconciles them against
        the patient's complete laboratory history.

        Args:
          patient_id: Supabase UUID of the patient.
          ctx: EvalContext containing vitals, labs, medications, and demographics.
          existing_insights: Optional in-memory list (from tripwire.py). If None,
                             fetched directly from `active_clinical_insights`.

        Returns:
          Updated list of active clinical insights (with resolved/stale items removed
          and chronic controlled items properly tagged).
        """
        # 1. Fetch active insights if not supplied
        if existing_insights is None:
            res = supabase.table("active_clinical_insights") \
                .select("*") \
                .eq("patient_id", patient_id) \
                .neq("status", "resolved") \
                .neq("status", "resolved_stale") \
                .execute()
            insights = res.data or []
        else:
            insights = list(existing_insights)

        if not insights:
            return []

        today = date.today()
        insights_to_remove = []

        # Load registered Tier 3 rule instances for compound rule re-evaluation
        tier3_rule_dict = {}
        try:
            from app.services.insights.rules.tier3_labs import TIER_3_RULES
            for r in TIER_3_RULES:
                tier3_rule_dict[r.id] = r
                
            # Register common rule ID aliases so historical insights resolve cleanly
            aliases = {
                "dehydration_aki": "dehydration_aki_risk",
                "acute_infection": "acute_infection_inflammation",
                "arrhythmia_electrolyte_rule": "arrhythmia_electrolyte_imbalance",
                "gout_flare": "hyperuricemia_gout",
                "severe_vitamin_d": "severe_vitamin_d_deficiency",
                "meal_time_glucose_spike": "post_prandial_hyperglycemia",
                "pulmonary_embolism_rule": "thrombosis_pe_risk",
                "hashimotos_disease": "hashimotos_thyroiditis",
                "heart_failure_exacerbation": "heart_failure_exacerbation_labs",
                "overtraining_syndrome": "hpa_axis_overtraining",
            }
            for alias_id, canonical_id in aliases.items():
                if canonical_id in tier3_rule_dict:
                    tier3_rule_dict[alias_id] = tier3_rule_dict[canonical_id]
        except Exception as e:
            print(f"UniversalLabReconciler: Could not import TIER_3_RULES: {e}")

        for insight in insights:
            insight_id = insight.get("id")
            rule_id = insight.get("rule_id", "")
            name = insight.get("name", "")

            # Determine insight reference date
            # Uses effective_datetime if available, falling back to created_at
            insight_date = cls._extract_insight_date(insight)

            # Extract associated LOINC codes for this insight
            loincs = cls.resolve_loincs_for_insight(insight)
            if not loincs and rule_id not in tier3_rule_dict:
                # Not a lab-based insight (e.g. step decline, sleep issue); skip
                continue

            # Determine if chronic condition
            is_chronic = (
                rule_id in CHRONIC_RULE_IDS or
                any(c in CHRONIC_LOINCS for c in loincs) or
                insight.get("category", "").upper() in ("METABOLIC", "LIPID", "THYROID")
            )

            # Determine category validity window
            category = cls._get_category_for_loincs_or_rule(loincs, rule_id)
            validity_days = CATEGORY_VALIDITY_DAYS.get(category, DEFAULT_VALIDITY_DAYS)

            # ── PATHWAY A: Compound Multi-Analyte Rule Re-evaluation ──
            # If this insight was generated by a Tier 3 rule and fresh labs exist:
            # Re-evaluate the rule directly.
            rule_passed = False
            rule_eval_msg = ""
            if rule_id in tier3_rule_dict:
                rule_inst = tier3_rule_dict[rule_id]
                # Check if patient has any lab for this rule newer than the insight date
                has_subsequent_labs = cls._has_fresh_labs_for_rule(ctx, loincs, insight_date)
                if has_subsequent_labs:
                    # Clinical Guard: Ensure fresh constituent labs are not out-of-range
                    # (Prevents rules with extreme crisis thresholds from resolving when labs are still abnormal)
                    any_constituent_abnormal = False
                    for loinc in loincs:
                        metric = ctx.labs.biomarker(loinc)
                        if metric.has_data:
                            latest_reading = metric.data[-1]
                            obs_date = cls._parse_date(latest_reading.get("measured_at"))
                            if obs_date and (not insight_date or obs_date >= insight_date):
                                is_norm, _ = cls.evaluate_biomarker_normalization(latest_reading, loinc)
                                if not is_norm:
                                    any_constituent_abnormal = True
                                    break

                    if not any_constituent_abnormal:
                        try:
                            eval_res = rule_inst.evaluate(ctx)
                            # Rule evaluated with data and passed (did not trigger and was not skipped)
                            if not eval_res.triggered and not eval_res.skipped:
                                rule_passed = True
                                rule_eval_msg = f"Rule '{rule_id}' re-evaluated with fresh labs and passed clinical criteria."
                        except Exception as e:
                            print(f"UniversalLabReconciler: Error re-evaluating rule {rule_id}: {e}")

            if rule_passed:
                cls._apply_reconciliation(
                    insight=insight,
                    patient_id=patient_id,
                    is_chronic=is_chronic,
                    reason=rule_eval_msg,
                    status_override="controlled" if is_chronic else "resolved"
                )
                insights_to_remove.append(insight)
                continue

            # ── PATHWAY B: Universal Single/Multi-Analyte Normalization ──
            # Check individual LOINC observations in patient's lab context
            all_loincs_normalized = True
            normalization_explanations = []
            has_evaluated_any_loinc = False
            latest_lab_date = None

            for loinc in loincs:
                metric = ctx.labs.biomarker(loinc)
                if not metric.has_data:
                    all_loincs_normalized = False
                    break

                # Get the latest observation for this LOINC
                latest_reading = metric.data[-1]
                measured_at_str = latest_reading.get("measured_at", "")
                obs_date = cls._parse_date(measured_at_str)

                # Strict Chronological Precedence Guard:
                # An old test drawn BEFORE the abnormal insight cannot resolve it!
                if insight_date and obs_date and obs_date < insight_date:
                    all_loincs_normalized = False
                    break

                # Track latest lab date for validity check
                if obs_date:
                    if latest_lab_date is None or obs_date > latest_lab_date:
                        latest_lab_date = obs_date

                # Evaluate normalization
                is_norm, expl = cls.evaluate_biomarker_normalization(latest_reading, loinc)
                if is_norm:
                    has_evaluated_any_loinc = True
                    loinc_name = LOINC_DICTIONARY.get(loinc, {}).get("name", loinc)
                    normalization_explanations.append(f"{loinc_name}: {expl}")
                else:
                    all_loincs_normalized = False
                    break

            # If all constituent LOINCs are verified normal/controlled on subsequent labs:
            if all_loincs_normalized and has_evaluated_any_loinc:
                resolution_summary = "; ".join(normalization_explanations)
                cls._apply_reconciliation(
                    insight=insight,
                    patient_id=patient_id,
                    is_chronic=is_chronic,
                    reason=resolution_summary,
                    status_override="controlled" if is_chronic else "resolved"
                )
                insights_to_remove.append(insight)
                continue

            # ── PATHWAY C: Diagnostic Validity Shelf-Life Expiration ──
            # If an acute lab insight has had no re-testing and its age exceeds
            # the category validity window:
            if not is_chronic and insight_date:
                age_days = (today - insight_date).days
                if age_days > validity_days:
                    stale_msg = (
                        f"Diagnostic validity window ({validity_days} days for {category}) "
                        f"expired without recurrence (insight age: {age_days} days). Auto-archived."
                    )
                    cls._apply_reconciliation(
                        insight=insight,
                        patient_id=patient_id,
                        is_chronic=False,
                        reason=stale_msg,
                        status_override="resolved_stale"
                    )
                    insights_to_remove.append(insight)
                    continue

        # Remove reconciled items from the active in-memory list
        for item in insights_to_remove:
            if item in insights:
                insights.remove(item)

        return insights

    # ──────────────────────────────────────────────────────────────────────────
    # Step 4: Real-Time Ingestion Trigger Hook
    # ──────────────────────────────────────────────────────────────────────────
    @classmethod
    def reconcile_on_new_observations(
        cls,
        patient_id: str,
        observations: List[Dict[str, Any]]
    ):
        """
        Fast-path real-time hook executed immediately upon PDF lab report upload.
        Reconciles any active clinical insights matching the newly ingested LOINCs.
        """
        if not observations:
            return

        try:
            from app.services.insights.data_fetcher import fetch_patient_context
            ctx = fetch_patient_context(patient_id)
            cls.reconcile_patient_lab_insights(patient_id, ctx)
        except Exception as e:
            print(f"UniversalLabReconciler: Error during real-time lab upload reconciliation: {e}")

    # ──────────────────────────────────────────────────────────────────────────
    # Internal Helper Methods
    # ──────────────────────────────────────────────────────────────────────────
    @classmethod
    def _apply_reconciliation(
        cls,
        insight: Dict[str, Any],
        patient_id: str,
        is_chronic: bool,
        reason: str,
        status_override: str
    ):
        """
        Updates Supabase database record and updates insight dict in-place.
        """
        insight_id = insight.get("id")
        rule_id = insight.get("rule_id", "unknown_rule")
        now_iso = datetime.now(timezone.utc).isoformat()

        if status_override == "controlled":
            update_payload = {
                "status": "controlled",
                "severity": "LOW",
                "resolved": True,
                "updated_at": now_iso
            }
            print(f"UniversalLabReconciler: Chronic condition '{rule_id}' marked CONTROLLED ({reason}).")
        elif status_override == "resolved_stale":
            update_payload = {
                "status": "resolved_stale",
                "resolved": True,
                "updated_at": now_iso
            }
            print(f"UniversalLabReconciler: Stale insight '{rule_id}' ARCHIVED ({reason}).")
        else:
            update_payload = {
                "status": "resolved",
                "resolved": True,
                "updated_at": now_iso
            }
            print(f"UniversalLabReconciler: Acute insight '{rule_id}' RESOLVED ({reason}).")

        # Update Supabase active_clinical_insights if valid UUID
        if insight_id and cls._is_valid_uuid(insight_id):
            try:
                supabase.table("active_clinical_insights") \
                    .update(update_payload) \
                    .eq("id", insight_id) \
                    .execute()
            except Exception as e:
                print(f"UniversalLabReconciler: Database update failed for insight {insight_id}: {e}")

        # Update in-memory dict
        insight.update(update_payload)

    @staticmethod
    def _is_valid_uuid(val: str) -> bool:
        """Checks if a string is a valid UUID to avoid PostgreSQL casting errors on mock IDs."""
        try:
            import uuid
            uuid.UUID(str(val))
            return True
        except (ValueError, TypeError):
            return False

    @classmethod
    def _extract_insight_date(cls, insight: Dict[str, Any]) -> Optional[date]:
        """
        Extracts the clinical reference date of an insight.
        Prefers effective_datetime, falls back to created_at.
        """
        eff_dt = insight.get("effective_datetime")
        if eff_dt:
            parsed = cls._parse_date(eff_dt)
            if parsed:
                return parsed

        created_dt = insight.get("created_at")
        if created_dt:
            return cls._parse_date(created_dt)

        return None

    @classmethod
    def _parse_date(cls, date_str: Optional[str]) -> Optional[date]:
        """
        Safely parses ISO date/datetime string into a date object.
        """
        if not date_str:
            return None
        try:
            # Handle YYYY-MM-DD prefix
            clean = str(date_str)[:10]
            return date.fromisoformat(clean)
        except Exception:
            return None

    @classmethod
    def _has_fresh_labs_for_rule(
        cls,
        ctx: EvalContext,
        loincs: List[str],
        insight_date: Optional[date]
    ) -> bool:
        """
        Checks if at least one monitored LOINC for a rule has data collected
        on or after the insight date.
        """
        if not insight_date:
            return True

        for loinc in loincs:
            metric = ctx.labs.biomarker(loinc)
            if metric.has_data:
                latest_reading = metric.data[-1]
                obs_date = cls._parse_date(latest_reading.get("measured_at"))
                if obs_date and obs_date >= insight_date:
                    return True
        return False

    @classmethod
    def _get_category_for_loincs_or_rule(
        cls,
        loincs: List[str],
        rule_id: str
    ) -> str:
        """
        Resolves the clinical consumer category for a group of LOINCs or rule ID.
        """
        if loincs:
            first_code = loincs[0]
            raw_cat = LOINC_DICTIONARY.get(first_code, {}).get("category", "")
            consumer_cat = CONSUMER_CATEGORY_MAP.get(raw_cat, raw_cat)
            if consumer_cat:
                return consumer_cat

        if "liver" in rule_id or "hepatic" in rule_id or "biliary" in rule_id:
            return "Liver"
        if "kidney" in rule_id or "renal" in rule_id or "nephropathy" in rule_id or "aki" in rule_id:
            return "Kidney"
        if "diabetes" in rule_id or "glucose" in rule_id or "prediabetes" in rule_id:
            return "Blood Sugar"
        if "thyroid" in rule_id or "hashimotos" in rule_id:
            return "Thyroid"
        if "cardiac" in rule_id or "cardiovascular" in rule_id or "lipid" in rule_id:
            return "Heart"
        if "electrolyte" in rule_id or "arrhythmia" in rule_id:
            return "Minerals"
        if "infection" in rule_id:
            return "Infection"
        if "anemia" in rule_id:
            return "Blood"

        return "General Labs"
