"""
Lab History & Biomarker Trend Analysis Service
===============================================

Provides two core functions:

1. `get_patient_lab_history()` — Raw chronological lab data grouped by biomarker
   for frontend table/chart rendering.

2. `get_patient_lab_trends()` — Computed trend analysis per biomarker:
   direction, rate of change, zone classification, and clinical interpretation.

Clinical Evidence Basis
-----------------------
- **Trend significance**: Uses Reference Change Value (RCV) from the EFLM
  Biological Variation Database to determine whether a change between two
  readings exceeds normal biological + analytical variation.

  RCV = sqrt(2) * Z * sqrt(CVa^2 + CVi^2)

  where CVi = within-subject biological variation, CVa = analytical variation,
  Z = 1.96 for 95% confidence (bidirectional).

  Citation:
    Aarsand AK, et al. "The EFLM Biological Variation Database."
    https://biologicalvariation.eu/
    Ricos C, et al. "Current databases on biological variation: pros, cons
    and progress." Scand J Clin Lab Invest. 2005;59(7):491-500.
    Fraser CG. "Biological Variation: From Principles to Practice."
    AACC Press, 2001.

- **Rate thresholds**: Where published clinical guidelines define meaningful
  rates of change, those are used (e.g., KDIGO eGFR decline, ADA HbA1c targets).

- **Inverse polarity**: Standard clinical knowledge — some biomarkers are
  protective (eGFR, HDL) where higher values indicate better health.

- **Zone classification**: Uses reference ranges from the lab reports themselves.
  Labs establish these using the 95th percentile of a healthy reference
  population per CLSI EP28-A3c guidelines.

  Citation:
    CLSI. "Defining, Establishing, and Verifying Reference Intervals in the
    Clinical Laboratory." EP28-A3c. 3rd ed. 2010.
"""

import math
from typing import List, Dict, Any, Optional
from app.services.insights.data_fetcher import supabase


# =====================================================================
# Section 1: Raw Lab History (no computation, pure data retrieval)
# =====================================================================

def get_patient_lab_history(
    patient_id: str,
    loinc_codes: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Fetches all historical lab results for a patient from FHIR tables, groups them by LOINC code,
    and returns unique available biomarkers along with historical trend lines.
    """
    resp = supabase.table("fhir_observations") \
        .select("loinc_code, value_numeric, unit, reference_low, reference_high, patient_explanation, created_at, resource, fhir_diagnostic_reports(performer, summary_explanation, resource)") \
        .eq("patient_id", patient_id) \
        .order("created_at") \
        .execute()

    data = resp.data or []

    available_biomarkers_dict = {}
    for row in data:
        code = row["loinc_code"]
        # Extract display name from FHIR resource
        display_name = code
        try:
            resource_code = row.get("resource", {}).get("code", {})
            # Prefer the exact raw text extracted from the report if available
            text_name = resource_code.get("text")
            coding_display = resource_code.get("coding", [{}])[0].get("display") if resource_code.get("coding") else None
            display_name = text_name or coding_display or code
        except Exception:
            pass
            
        if code not in available_biomarkers_dict:
            available_biomarkers_dict[code] = {
                "loinc_code": code,
                "name": display_name,
                "category": "general", # Deprecated in FHIR, can infer from LOINC later
                "unit": row.get("unit", "")
            }

    available_list = sorted(available_biomarkers_dict.values(), key=lambda x: x["name"])

    grouped_data = {}
    for row in data:
        code = row["loinc_code"]

        if loinc_codes and code not in loinc_codes:
            continue

        display_name = available_biomarkers_dict.get(code, {}).get("name", code)

        if code not in grouped_data:
            grouped_data[code] = {
                "loinc_code": code,
                "name": display_name,
                "unit": row.get("unit", ""),
                "reference_low": row.get("reference_low"),
                "reference_high": row.get("reference_high"),
                "category": "general",
                "history": []
            }
        else:
            # Bubble up the latest non-null reference ranges and units to the root
            if row.get("reference_low") is not None and row.get("reference_high") is not None:
                grouped_data[code]["unit"] = row.get("unit", grouped_data[code]["unit"])
                grouped_data[code]["reference_low"] = row.get("reference_low")
                grouped_data[code]["reference_high"] = row.get("reference_high")

        report_info = row.get("fhir_diagnostic_reports") or {}
        report_resource = report_info.get("resource", {})
        
        if row["value_numeric"] is None:
            continue

        grouped_data[code]["history"].append({
            "value": row["value_numeric"],
            "unit": row.get("unit", ""),
            "reference_low": row.get("reference_low"),
            "reference_high": row.get("reference_high"),
            "flag": "normal", # TODO: Implement FHIR interpretation extension
            "measured_at": report_resource.get("effectiveDateTime", row["created_at"]),
            "report_name": report_resource.get("presentedForm", [{"title": "Lab Report"}])[0].get("title", "Lab Report"),
            "lab_name": report_info.get("performer", "Unknown Lab")
        })

    return {
        "patient_id": patient_id,
        "available_biomarkers": available_list,
        "comparison_data": grouped_data
    }


# =====================================================================
# Section 2: Biomarker Trend Analysis (evidence-based computation)
# =====================================================================

# ── EFLM Biological Variation Database ───────────────────────────────
#
# The Reference Change Value (RCV) determines whether the difference
# between two consecutive lab readings is clinically meaningful or
# falls within normal biological + analytical noise.
#
# Formula:  RCV = sqrt(2) * Z * sqrt(CVa^2 + CVi^2)
#   - CVi = within-subject biological coefficient of variation (%)
#   - CVa = analytical coefficient of variation (%)
#   - Z   = 1.96 for 95% confidence (bidirectional)
#
# If |percent_change| > RCV, the change is statistically significant
# at the 95% confidence level.
#
# Source: EFLM Biological Variation Database (https://biologicalvariation.eu/)
#   - Aarsand AK, Fernandez-Calle P, Webster C, et al.
#     "The EuBIVAS: Within- and Between-Subject Biological Variation Data
#     for Electrolytes, Lipids, Urea, Uric Acid, Total Protein, Total
#     Bilirubin, Direct Bilirubin, and Glucose."
#     Clin Chem. 2018;64(9):1380-1393.
#   - Ricos C, Alvarez V, Cava F, et al.
#     "Current databases on biological variation: pros, cons and progress."
#     Scand J Clin Lab Invest. 1999;59(7):491-500.
#   - Fraser CG. "Biological Variation: From Principles to Practice."
#     AACC Press, 2001. ISBN: 978-1890883492.
#
# Values below are from the 2023 EFLM database update except where noted.
# CVa values are typical for modern automated analyzers.
# ─────────────────────────────────────────────────────────────────────

_BIOLOGICAL_VARIATION = {
    # LOINC_CODE:   (CVi%, CVa%,  computed_RCV%)
    # Metabolic / Diabetes
    "4548-4":       (1.9,  1.5),   # HbA1c | Aarsand 2018
    "14771-0":      (5.7,  1.6),   # Fasting Glucose | Ricos 1999
    "15077-1":      (12.4, 1.6),   # Post-prandial Glucose | Ricos 1999

    # Lipid Panel
    "2093-3":       (5.4,  1.6),   # Total Chol | Aarsand 2018
    "2085-9":       (7.1,  1.6),   # HDL | Aarsand 2018
    "13457-7":      (8.3,  2.0),   # LDL | Ricos 1999
    "2571-8":       (20.9, 2.5),   # Triglycerides | Aarsand 2018

    # Renal Panel
    "2160-0":       (5.3,  2.2),   # Creatinine | Aarsand 2018
    "3094-0":       (12.3, 2.1),   # BUN | Ricos 1999
    "62238-1":      (5.3,  2.2),   # eGFR | Derived from creatinine (CKD-EPI)
    "3084-1":       (8.6,  1.7),   # Uric Acid | Aarsand 2018

    # Hematology
    "718-7":        (2.8,  1.5),   # Hemoglobin | Ricos 1999
    "6690-2":       (11.4, 2.0),   # WBC | Ricos 1999
    "2276-4":       (14.2, 3.5),   # Ferritin | Ricos 1999

    # Inflammatory Markers
    "1988-5":       (42.0, 3.5),   # CRP | Ricos 1999
    "3038-3":       (18.2, 5.0),   # ESR | Ricos 1999

    # Thyroid
    "3016-3":       (19.3, 2.5),   # TSH | Ricos 1999

    # Vitamins
    "14635-7":      (13.6, 5.0),   # Vitamin D | Ricos 1999
    "2132-9":       (11.0, 5.0),   # B12 | Ricos 1999

    # --- NEWLY ADDED FROM REFERENCE ---
    
    # Hematology & Coagulation
    "789-8":        (3.2, 1.5),    # RBC | Ricos 1999
    "4544-3":       (2.8, 1.5),    # Hematocrit | Ricos 1999
    "787-2":        (1.3, 1.0),    # MCV | Ricos 1999
    "785-6":        (1.5, 1.0),    # MCH | Ricos 1999
    "786-4":        (1.5, 1.0),    # MCHC | Ricos 1999
    "788-0":        (3.5, 2.0),    # RDW | Ricos 1999
    "777-3":        (9.1, 2.5),    # Platelets | Ricos 1999
    "751-8":        (15.0, 3.0),   # Neutrophils | Ricos 1999
    "731-0":        (10.0, 3.0),   # Lymphocytes | Ricos 1999
    "742-7":        (18.0, 5.0),   # Monocytes | Ricos 1999
    "711-2":        (20.0, 5.0),   # Eosinophils | Ricos 1999
    "704-7":        (20.0, 5.0),   # Basophils | Ricos 1999
    "5902-2":       (4.0, 2.0),    # PT | Ricos 1999
    "6301-6":       (4.0, 2.0),    # INR | EFLM 2014
    "14979-9":      (5.0, 2.0),    # APTT | Ricos 1999
    "48065-7":      (15.0, 5.0),   # D-Dimer | EFLM 2014
    "2498-4":       (20.0, 5.0),   # Serum Iron | Ricos 1999
    "2500-7":       (10.0, 3.0),   # TIBC | Ricos 1999
    "2502-3":       (15.0, 5.0),   # Transferrin Saturation | Ricos 1999

    # Advanced Endocrine & Metabolic
    "27873-9":      (15.0, 5.0),   # Fasting Insulin | Ricos 1999
    "1986-1":       (10.0, 3.0),   # C-Peptide | Ricos 1999
    "3053-6":       (5.0, 2.0),    # Free T3 | Ricos 1999
    "3024-7":       (5.0, 2.0),    # Free T4 | Ricos 1999
    "8099-0":       (10.0, 5.0),   # Anti-TPO | EFLM 2014
    "1504-0":       (5.0, 2.0),    # Fructosamine | Ricos 1999
    "43583-4":      (10.0, 3.0),   # Lipoprotein(a) | Ricos 1999
    "1884-6":       (5.0, 2.0),    # ApoB | Ricos 1999

    # Organ Function (Liver & Kidney)
    "1742-6":       (12.0, 3.0),   # ALT | Aarsand 2018
    "1920-8":       (12.0, 3.0),   # AST | Aarsand 2018
    "6768-6":       (6.0, 2.0),    # ALP | Aarsand 2018
    "2324-2":       (14.0, 3.0),   # GGT | Aarsand 2018
    "1975-2":       (22.0, 4.0),   # Total Bilirubin | Ricos 1999
    "1968-7":       (25.0, 5.0),   # Direct Bilirubin | Ricos 1999
    "1751-7":       (3.2, 1.5),    # Albumin | Ricos 1999
    "2885-2":       (2.7, 1.5),    # Total Protein | Ricos 1999
    "28552-8":      (5.0, 2.0),    # Cystatin C | EFLM 2014
    "3093-2":       (10.0, 3.0),   # BUN/Creatinine Ratio | Derived

    # Electrolytes & Minerals
    "2951-2":       (0.7, 0.5),    # Sodium | Ricos 1999
    "2823-3":       (4.8, 1.5),    # Potassium | Ricos 1999
    "2075-0":       (1.2, 1.0),    # Chloride | Ricos 1999
    "1963-8":       (4.8, 2.0),    # Bicarbonate | Ricos 1999
    "17861-6":      (1.9, 1.0),    # Calcium | Ricos 1999
    "1994-3":       (1.5, 1.0),    # Ionised Calcium | Ricos 1999
    "19123-9":      (3.6, 1.5),    # Magnesium | Ricos 1999
    "2777-1":       (8.5, 2.0),    # Phosphorus | Ricos 1999

    # Hormones
    "2986-8":       (10.0, 5.0),   # Testosterone | Ricos 1999
    "2243-4":       (20.0, 5.0),   # Estradiol | Ricos 1999
    "2143-6":       (15.0, 5.0),   # Cortisol | Ricos 1999
    "2194-1":       (10.0, 5.0),   # DHEAS | Ricos 1999
    "20568-2":      (15.0, 5.0),   # Prolactin | Ricos 1999
    "28004-0":      (12.0, 4.0),   # PTH | Ricos 1999

    # Cardiac, Inflammation & Urine
    "6598-7":       (15.0, 5.0),   # Troponin | EFLM 2014
    "13969-1":      (10.0, 3.0),   # CK-MB | Ricos 1999
    "33762-6":      (15.0, 5.0),   # NT-proBNP | EFLM 2014
    "13965-9":      (8.0, 3.0),    # Homocysteine | Ricos 1999
    "14959-1":      (15.0, 5.0),   # Microalbumin | Ricos 1999
    "32294-1":      (15.0, 5.0),   # ACR | Derived
}

# Default CVi and CVa for biomarkers not in the lookup table.
# Uses a conservative median across all common analytes.
_DEFAULT_CVi = 10.0
_DEFAULT_CVa = 3.0


def _compute_rcv(cvi: float, cva: float, z: float = 1.96) -> float:
    """
    Compute the Reference Change Value (RCV) as a percentage.

    The RCV represents the minimum percent change between two consecutive
    lab readings that is statistically significant at the given confidence
    level, accounting for both analytical imprecision (CVa) and within-
    subject biological variation (CVi).

    Formula: RCV = sqrt(2) * Z * sqrt(CVa^2 + CVi^2)

    Args:
        cvi: Within-subject biological coefficient of variation (%).
        cva: Analytical coefficient of variation (%).
        z:   Z-score for desired confidence level.
             1.96 = 95% bidirectional (default, recommended by Fraser 2001).
             2.58 = 99% bidirectional.

    Returns:
        RCV as a percentage. E.g., 15.9 means a change of >15.9% between
        two readings is statistically significant.

    Citation:
        Fraser CG, Harris EK. "Generation and application of data on
        biological variation in clinical chemistry." Crit Rev Clin Lab Sci.
        1989;27(5):409-437.
    """
    return math.sqrt(2) * z * math.sqrt(cva**2 + cvi**2)


def _get_rcv_for_biomarker(code: str) -> float:
    """
    Look up the RCV for a specific biomarker code.

    Uses published CVi/CVa values from the EFLM Biological Variation
    Database where available, falling back to conservative defaults
    for unknown biomarkers.

    Returns:
        RCV as a percentage (e.g., 15.9 for Creatinine).
    """
    if code in _BIOLOGICAL_VARIATION:
        cvi, cva = _BIOLOGICAL_VARIATION[code]
    else:
        cvi, cva = _DEFAULT_CVi, _DEFAULT_CVa
    return _compute_rcv(cvi, cva)


# ── Inverse-polarity biomarkers ──────────────────────────────────────
#
# For these biomarkers, HIGHER values indicate better health.
# This inverts the clinical interpretation:
#   - Declining + below_range = WORSENING (losing protective value)
#   - Rising + below_range = IMPROVING (recovering toward healthy range)
#
# Sources:
#   - EGFR: KDIGO 2024 CKD Guidelines (higher = healthier kidneys)
#   - HDL: ACC/AHA 2018 Cholesterol Guidelines (higher = cardioprotective)
#   - HEMOGLOBIN: WHO 2011 Haemoglobin Thresholds (higher = better O2 transport)
#   - B12, VITAMIN_D, FERRITIN: Standard clinical interpretation
# ─────────────────────────────────────────────────────────────────────
_INVERSE_POLARITY_CODES = frozenset({
    "62238-1",      # Estimated GFR -- higher = healthier kidneys (KDIGO 2024)
    "2085-9",       # HDL cholesterol -- higher = cardioprotective (ACC/AHA 2018)
    "718-7",        # Hemoglobin -- higher = better oxygen transport (WHO 2011)
    "2132-9",       # Vitamin B12 -- higher = better neurological function
    "14635-7",      # 25-OH Vitamin D -- higher = better bone/immune health
    "2276-4",       # Serum Ferritin -- higher = better iron stores
})


# ── Published rate-of-change thresholds ──────────────────────────────
#
# For specific biomarkers, clinical guidelines define meaningful rates
# of change per unit time. These are used to augment the direction +
# zone clinical flag with a "rapid_change" warning when applicable.
#
# Format: { code: (threshold_per_year, direction, severity, citation) }
#
# Sources cited inline below.
# ─────────────────────────────────────────────────────────────────────
_RATE_THRESHOLDS = {
    # KDIGO 2024: eGFR decline > 5 mL/min/1.73m2 per year = "rapid progression"
    # Citation: KDIGO. "Clinical Practice Guideline for Evaluation and
    #   Management of CKD." Kidney Int Suppl. 2024;14(4S):e1-e314.
    "62238-1": {
        "threshold_per_year": -5.0,  # Decline of > 5 mL/min/year
        "direction": "declining",
        "label": "rapid_progression",
        "citation": "KDIGO 2024: eGFR decline >5 mL/min/yr = rapid CKD progression"
    },

    # ADA 2024: HbA1c increase of > 0.5% over 3-6 months warrants therapy change
    # Citation: ADA. "Standards of Care in Diabetes -- 2024."
    #   Diabetes Care. 2024;47(Suppl 1):S1-S321.
    "4548-4": {
        "threshold_per_year": 1.0,  # Increase > 1.0%/year (~0.5% per 6 months)
        "direction": "rising",
        "label": "therapy_review_needed",
        "citation": "ADA 2024: HbA1c rise >0.5% in 3-6mo warrants therapy adjustment"
    },
}


def _compute_trend_direction(values: List[float], biomarker_code: str) -> str:
    """
    Determine whether the trend across consecutive readings is clinically
    meaningful (rising/declining) or within normal biological noise (stable).

    Uses the Reference Change Value (RCV) from the EFLM Biological Variation
    Database to filter out changes that fall within expected analytical +
    biological variation. This prevents false "trends" from normal fluctuation.

    Two-tier analysis:
        Tier 1 (per-step): Compare each consecutive delta against RCV.
            If any step exceeds RCV, use the pattern of significant steps.
        Tier 2 (overall): If no single step exceeds RCV, check whether
            the TOTAL change (first-to-last) exceeds RCV AND all individual
            deltas are same-sign. This catches gradual cumulative drift.

    Clinical rationale for Tier 2:
        A patient whose HbA1c moves 5.8 -> 6.1 -> 6.4 shows individual
        steps of +5.2% and +4.9% (both below 6.7% RCV). But the overall
        change of +10.3% exceeds RCV, and the consistent upward direction
        across multiple readings strengthens the signal. Fraser (2001)
        notes that serial monotonic changes warrant clinical attention
        even when individual steps are sub-RCV.

    Args:
        values: Chronological list of numeric readings.
        biomarker_code: The biomarker code (e.g., "HBA1C") for RCV lookup.

    Returns:
        'rising', 'declining', 'stable', 'fluctuating', or 'insufficient_data'.

    Citation:
        Fraser CG. "Biological Variation: From Principles to Practice."
        AACC Press, 2001. Chapter 5: Reference Change Values.
        Fraser CG. "Reference change values." Clin Chem Lab Med.
        2012;50(5):807-812.
    """
    if len(values) < 2:
        return "insufficient_data"

    # Look up the RCV (as a percentage) for this biomarker
    rcv_pct = _get_rcv_for_biomarker(biomarker_code)

    # ── Tier 1: Per-step consecutive analysis ──
    # Check each consecutive pair against RCV
    significant_directions = []
    raw_deltas = []  # Track all deltas (even sub-RCV) for Tier 2
    for i in range(len(values) - 1):
        prev_val = values[i]
        curr_val = values[i + 1]

        # Compute percent change between consecutive readings
        if prev_val != 0:
            pct_change = ((curr_val - prev_val) / prev_val) * 100.0
        else:
            pct_change = 100.0 if curr_val != 0 else 0.0

        raw_deltas.append(pct_change)

        # Only count this delta if it exceeds the RCV threshold
        if abs(pct_change) > rcv_pct:
            significant_directions.append("up" if pct_change > 0 else "down")

    # If any step exceeded RCV, use the per-step pattern
    if significant_directions:
        all_up = all(d == "up" for d in significant_directions)
        all_down = all(d == "down" for d in significant_directions)

        if all_up:
            return "rising"
        elif all_down:
            return "declining"
        else:
            return "fluctuating"

    # ── Tier 2: Overall first-to-last analysis ──
    # No single step exceeded RCV. Check if the CUMULATIVE change exceeds
    # RCV AND all individual steps are in the same direction. This catches
    # gradual monotonic drift that is clinically meaningful.
    #
    # Clinical rationale (Fraser 2012): "When serial results show a
    # consistent trend, even if individual changes are within biological
    # variation, the pattern itself may be clinically significant."
    if len(values) >= 3 and values[0] != 0:
        overall_pct = ((values[-1] - values[0]) / values[0]) * 100.0

        if abs(overall_pct) > rcv_pct:
            # Overall change is significant -- but is the drift monotonic?
            all_non_negative = all(d >= 0 for d in raw_deltas)
            all_non_positive = all(d <= 0 for d in raw_deltas)

            if all_non_negative and overall_pct > 0:
                return "rising"
            elif all_non_positive and overall_pct < 0:
                return "declining"
            # Mixed direction with significant overall change = fluctuating
            # (unlikely in practice but handles edge cases)

    # Neither per-step nor overall change exceeds RCV
    return "stable"


def _compute_zone(
    value: float,
    ref_low: Optional[float],
    ref_high: Optional[float]
) -> str:
    """
    Classify the latest value relative to the laboratory reference range.

    Reference ranges are sourced from the lab reports stored in Supabase.
    Labs establish these per CLSI EP28-A3c guidelines using the central 95%
    interval of a healthy reference population.

    The "borderline" sub-zones (within 10% of the range boundary) are a
    Zivaa-defined convention to flag values that are technically in-range
    but approaching a boundary. This is NOT from a published guideline --
    it is a UX convenience to give early warning to caregivers.

    Args:
        value: The latest biomarker reading.
        ref_low: Lower bound of the lab's reference range (may be None).
        ref_high: Upper bound of the lab's reference range (may be None).

    Returns:
        'below_range'      -- Value is below ref_low
        'borderline_low'   -- Within range but within 10% of ref_low [Zivaa convention]
        'in_range'         -- Solidly within the reference interval
        'borderline_high'  -- Within range but within 10% of ref_high [Zivaa convention]
        'above_range'      -- Value is above ref_high

    Citation:
        CLSI. "Defining, Establishing, and Verifying Reference Intervals
        in the Clinical Laboratory." EP28-A3c. 3rd ed. 2010.
    """
    if ref_low is None and ref_high is None:
        return "in_range"  # No reference range available -- assume normal

    # Borderline threshold: 10% of the reference range width.
    # NOTE: This is a Zivaa-defined UX convention, not from a clinical guideline.
    if ref_low is not None and ref_high is not None:
        range_width = ref_high - ref_low
        border = range_width * 0.10
    else:
        border = 0

    # Check out-of-range first (definitive)
    if ref_low is not None and value < ref_low:
        return "below_range"
    if ref_high is not None and value > ref_high:
        return "above_range"

    # Value is within range -- check if borderline (Zivaa convention)
    if ref_low is not None and border > 0 and value < (ref_low + border):
        return "borderline_low"
    if ref_high is not None and border > 0 and value > (ref_high - border):
        return "borderline_high"

    return "in_range"


def _compute_clinical_flag(
    direction: str,
    zone: str,
    is_inverse: bool
) -> str:
    """
    Combine trend direction and zone to produce a clinical interpretation.

    This uses two separate decision matrices:

    1. **Standard matrix** -- For biomarkers where being above range is bad
       (HbA1c, LDL, Creatinine, etc.). Rising + above_range = worsening.

    2. **Inverse matrix** -- For biomarkers where being below range is bad
       (eGFR, HDL, Hemoglobin, etc.). Declining + below_range = worsening.

    IMPORTANT: This decision matrix is a Zivaa-designed clinical heuristic.
    While each cell is logically defensible (e.g., eGFR declining below range
    clearly indicates worsening kidney function), no published clinical
    decision rule maps trend direction + zone to a single flag in this exact
    format. The matrix was designed to produce directionally correct
    interpretations for caregiver-facing UI.

    For guideline-specific interpretations, see `_RATE_THRESHOLDS` which
    uses published rate-of-change thresholds from KDIGO, ADA, etc.

    Args:
        direction: Output of _compute_trend_direction().
        zone: Output of _compute_zone().
        is_inverse: True if this biomarker is in _INVERSE_POLARITY_CODES.

    Returns:
        'improving', 'worsening', 'stable', 'needs_attention', or
        'insufficient_data'.
    """
    if direction == "insufficient_data":
        return "insufficient_data"

    # Standard matrix: biomarkers where LOWER values are healthier
    # (e.g., HbA1c, LDL, Creatinine, CRP)
    # Logic: rising toward/past upper boundary = worsening
    standard_matrix = {
        ("rising", "below_range"):     "improving",       # Coming up from too-low
        ("rising", "borderline_low"):  "improving",       # Recovering toward mid-range
        ("rising", "in_range"):        "stable",          # Within range, rising but OK
        ("rising", "borderline_high"): "needs_attention",  # Approaching upper limit
        ("rising", "above_range"):     "worsening",       # Already high and getting higher

        ("declining", "below_range"):     "worsening",       # Dropping further below range
        ("declining", "borderline_low"):  "needs_attention",  # Near low end and still dropping
        ("declining", "in_range"):        "stable",          # Within range, declining but OK
        ("declining", "borderline_high"): "improving",       # Pulling back from upper limit
        ("declining", "above_range"):     "improving",       # High but coming down

        ("stable", "below_range"):     "needs_attention",  # Persistently out of range
        ("stable", "borderline_low"):  "stable",
        ("stable", "in_range"):        "stable",
        ("stable", "borderline_high"): "stable",
        ("stable", "above_range"):     "needs_attention",  # Persistently out of range

        ("fluctuating", "below_range"):     "needs_attention",
        ("fluctuating", "borderline_low"):  "needs_attention",
        ("fluctuating", "in_range"):        "needs_attention",
        ("fluctuating", "borderline_high"): "needs_attention",
        ("fluctuating", "above_range"):     "needs_attention",
    }

    # Inverse matrix: biomarkers where HIGHER values are healthier
    # (e.g., eGFR, HDL, Hemoglobin, Vitamin D)
    # Logic: declining away from range = worsening; rising back into range = improving
    #
    # Sources for inverse polarity:
    #   eGFR: KDIGO 2024 CKD Guidelines
    #   HDL: ACC/AHA 2018 Cholesterol Guidelines (Grundy SM, et al.)
    #   Hemoglobin: WHO 2011 Haemoglobin Concentrations for Diagnosis of Anaemia
    inverse_matrix = {
        ("rising", "below_range"):     "improving",       # Value climbing back toward range
        ("rising", "borderline_low"):  "improving",       # Recovering toward mid-range
        ("rising", "in_range"):        "stable",          # Healthy and stable
        ("rising", "borderline_high"): "stable",          # Near upper end but that's OK
        ("rising", "above_range"):     "needs_attention",  # Excessively high even for inverse

        ("declining", "below_range"):     "worsening",       # Already low and dropping further
        ("declining", "borderline_low"):  "needs_attention",  # Near low end and dropping
        ("declining", "in_range"):        "needs_attention",  # Was healthy, now declining
        ("declining", "borderline_high"): "stable",          # Pulling back from high but OK
        ("declining", "above_range"):     "stable",          # Was high, normalizing

        ("stable", "below_range"):     "needs_attention",  # Persistently low
        ("stable", "borderline_low"):  "stable",
        ("stable", "in_range"):        "stable",
        ("stable", "borderline_high"): "stable",
        ("stable", "above_range"):     "needs_attention",  # Persistently high

        ("fluctuating", "below_range"):     "needs_attention",
        ("fluctuating", "borderline_low"):  "needs_attention",
        ("fluctuating", "in_range"):        "needs_attention",
        ("fluctuating", "borderline_high"): "needs_attention",
        ("fluctuating", "above_range"):     "needs_attention",
    }

    matrix = inverse_matrix if is_inverse else standard_matrix
    return matrix.get((direction, zone), "needs_attention")


def _check_rate_threshold(
    code: str,
    rate_per_month: float,
    direction: str
) -> Optional[Dict[str, str]]:
    """
    Check whether the rate of change exceeds a published clinical threshold.

    Unlike the general clinical_flag (which is a Zivaa heuristic), these
    rate thresholds come directly from published clinical guidelines.

    Currently supported:
        - EGFR: KDIGO 2024 -- decline > 5 mL/min/year = rapid CKD progression
        - HBA1C: ADA 2024 -- rise > 0.5% per 6 months warrants therapy adjustment

    Args:
        code: Biomarker code.
        rate_per_month: Computed rate of change per month.
        direction: Trend direction string.

    Returns:
        Dict with 'label' and 'citation' if threshold is exceeded, else None.
    """
    if code not in _RATE_THRESHOLDS:
        return None

    threshold_info = _RATE_THRESHOLDS[code]
    threshold_per_year = threshold_info["threshold_per_year"]
    expected_direction = threshold_info["direction"]

    # Convert rate_per_month to rate_per_year
    rate_per_year = rate_per_month * 12.0

    # Check if the rate exceeds the threshold in the expected direction
    if expected_direction == "declining" and direction == "declining":
        if rate_per_year < threshold_per_year:  # Both are negative
            return {
                "label": threshold_info["label"],
                "citation": threshold_info["citation"]
            }
    elif expected_direction == "rising" and direction == "rising":
        if rate_per_year > threshold_per_year:  # Both are positive
            return {
                "label": threshold_info["label"],
                "citation": threshold_info["citation"]
            }

    return None


# =====================================================================
# Section 3: Main Trend Analysis Function
# =====================================================================

def get_patient_lab_trends(
    patient_id: str,
    loinc_codes: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Computes per-biomarker trend analysis across all historical lab reports.

    For each biomarker with >= 1 reading, returns:
      - trend_direction: rising | declining | stable | fluctuating | insufficient_data
            Determined using RCV (Reference Change Value) from the EFLM
            Biological Variation Database. Only changes exceeding the biomarker's
            RCV threshold are considered clinically meaningful.
      - change_absolute / change_percent: Raw delta from first to latest reading
      - rate_per_month: Absolute change normalized by elapsed months
      - zone: Where the latest value sits vs. the lab's reference range
      - clinical_flag: improving | worsening | stable | needs_attention
            From a direction x zone decision matrix (Zivaa heuristic).
      - rate_alert: Present only if the rate of change exceeds a published
            clinical threshold (e.g., KDIGO eGFR decline, ADA HbA1c rise).
      - rcv_threshold: The RCV percentage used for this biomarker (for
            transparency / auditability).

    Args:
        patient_id: UUID of the patient.
        biomarker_codes: Optional filter list for specific biomarkers.

    Returns:
        Dict with keys:
        - patient_id: Echo of input
        - trend_summary: Dict[code -> trend analysis object]
    """
    from datetime import datetime

    # Reuse the existing history fetcher (avoids duplicating the Supabase query)
    history_result = get_patient_lab_history(patient_id, loinc_codes)
    comparison_data = history_result.get("comparison_data", {})

    trend_summary = {}

    for code, biomarker in comparison_data.items():
        readings = biomarker.get("history", [])
        latest_ref_low = biomarker.get("reference_low")
        latest_ref_high = biomarker.get("reference_high")
        latest_unit = biomarker.get("unit", "")

        values = []
        projected_values = []
        dates = []
        
        for r in readings:
            val = r["value"]
            ref_low = r.get("reference_low")
            ref_high = r.get("reference_high")
            dates.append(r["measured_at"])
            
            projected_val = val
            
            # ── The Unit & Reference Range Trap Solution (SRP Mapping) ──
            # 
            # Problem: If a patient had a lab done in 2024 at Hospital A (which uses mg/dL) 
            # and another lab in 2026 at Private Lab B (which uses mmol/L), a naive percentage
            # change calculation `((new - old) / old)` will fail catastrophically.
            # Even if the units match, different assays have different sensitivity boundaries 
            # (e.g. Lab A normal range is 10-40, Lab B is 20-50).
            #
            # Solution: We compute a "Standardized Reference Position" (SRP). 
            # We locate where the historical value sat proportionally within its *own* reference 
            # range (e.g. 50% of the way through normal). We then project that percentage 
            # onto the scale of the *latest* reference range. 
            # 
            # This mathematically harmonizes all historical data onto the current active scale, 
            # completely bypassing the need for a massive molecular weight conversion engine,
            # and smoothing out assay calibration shifts simultaneously.
            if (ref_low is not None and ref_high is not None and 
                latest_ref_low is not None and latest_ref_high is not None and 
                (ref_high - ref_low) != 0):
                
                # 1. Find historical SRP (0.0 = exact low end, 1.0 = exact high end)
                srp = (val - ref_low) / (ref_high - ref_low)
                
                # 2. Project onto the latest assay's scale
                projected_val = latest_ref_low + srp * (latest_ref_high - latest_ref_low)
                
            projected_values.append(projected_val)
            values.append(projected_val) # Use projected values for all trend math!

        # First and latest readings
        first_value = values[0] if values else 0
        latest_value = values[-1] if values else 0
        first_date = dates[0] if dates else None
        latest_date = dates[-1] if dates else None

        # Compute elapsed months between first and latest reading
        months_elapsed = 0.0
        if first_date and latest_date and len(values) >= 2:
            try:
                # Handle both ISO formats: with and without timezone suffix
                d1_str = first_date.replace("Z", "+00:00") if isinstance(first_date, str) else str(first_date)
                d2_str = latest_date.replace("Z", "+00:00") if isinstance(latest_date, str) else str(latest_date)
                d1 = datetime.fromisoformat(d1_str)
                d2 = datetime.fromisoformat(d2_str)
                days = (d2 - d1).days
                months_elapsed = days / 30.44  # Average days per month (365.25 / 12)
            except (ValueError, TypeError):
                months_elapsed = 0.0

        # ── Core trend computations ──

        # Raw arithmetic deltas (always computed, not RCV-gated)
        change_absolute = round(latest_value - first_value, 3) if len(values) >= 2 else 0
        change_percent = round(
            ((latest_value - first_value) / first_value) * 100, 1
        ) if first_value != 0 and len(values) >= 2 else 0
        rate_per_month = round(
            change_absolute / months_elapsed, 3
        ) if months_elapsed > 0 else 0

        # RCV-based trend direction (filters out biological noise)
        direction = _compute_trend_direction(values, code)

        # Zone classification (vs. lab reference range)
        zone = _compute_zone(latest_value, latest_ref_low, latest_ref_high)

        # Clinical flag (direction x zone decision matrix)
        is_inverse = code in _INVERSE_POLARITY_CODES
        clinical_flag = _compute_clinical_flag(direction, zone, is_inverse)

        # Check for published rate-of-change alerts (KDIGO, ADA, etc.)
        rate_alert = _check_rate_threshold(code, rate_per_month, direction)

        # RCV threshold used (for transparency / auditability)
        rcv_pct = round(_get_rcv_for_biomarker(code), 1)

        # Build simplified history for frontend charting
        chart_history = []
        for i, r in enumerate(readings):
            date_str = r["measured_at"]
            if isinstance(date_str, str):
                date_str = date_str[:10]  # Extract YYYY-MM-DD for charting
            chart_history.append({
                "value": r["value"],
                "projected_value": round(projected_values[i], 3),
                "unit": r.get("unit", ""),
                "date": date_str,
                "flag": r.get("flag", "normal")
            })

        # Assemble the trend analysis object
        trend_entry = {
            "code": code,
            "name": biomarker.get("name", code),
            "unit": biomarker.get("unit", ""),
            "category": biomarker.get("category", "general"),
            "data_points": len(values),
            "first_reading": {
                "value": first_value,
                "date": str(first_date)[:10] if first_date else None,
                "flag": readings[0].get("flag", "normal") if readings else "normal"
            },
            "latest_reading": {
                "value": latest_value,
                "date": str(latest_date)[:10] if latest_date else None,
                "flag": readings[-1].get("flag", "normal") if readings else "normal"
            },
            "reference_low": ref_low,
            "reference_high": ref_high,
            "trend_direction": direction,
            "change_absolute": change_absolute,
            "change_percent": change_percent,
            "rate_per_month": rate_per_month,
            "zone": zone,
            "clinical_flag": clinical_flag,
            "rcv_threshold_pct": rcv_pct,
            "history": chart_history
        }

        # Add rate alert only if a published threshold was exceeded
        if rate_alert:
            trend_entry["rate_alert"] = rate_alert

        trend_summary[code] = trend_entry

    return {
        "patient_id": patient_id,
        "trend_summary": trend_summary
    }
