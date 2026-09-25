"""Geriatric Comorbidity & Vulnerability SLA Modifiers.

Applies clinical safety rules to modulate conservative self-care limits
based on patient age, chronic diagnoses, and active medications.
"""

from typing import Dict, Any, List

def apply_geriatric_modifiers(canonical_entry: Dict[str, Any], patient_profile: Dict[str, Any]) -> Dict[str, Any]:
    """
    Modulates conservative self-care limits and red flags based on geriatric profile.
    Returns a copy of the canonical entry with adjusted max_self_care_days and checkin_cadence_days.
    """
    modified = dict(canonical_entry)
    
    age = patient_profile.get("age", 70)
    conditions = [c.lower() for c in patient_profile.get("conditions", [])]
    medications = [m.lower() for m in patient_profile.get("medications", [])]
    anatomical_site = canonical_entry.get("anatomical_site", "").lower()
    canonical_key = canonical_entry.get("canonical_key", "")

    adjusted_sla = modified.get("max_self_care_days", 7)
    adjusted_cadence = modified.get("checkin_cadence_days", 3)

    # 1. Diabetic Foot & Extremity Vulnerability Rule
    # Diabetics have peripheral neuropathy; foot pain or swelling can rapidly progress to ulcers.
    has_diabetes = any("diabetes" in c or "t2d" in c or "type 2" in c for c in conditions)
    if has_diabetes and any(part in anatomical_site for part in ["feet", "ankles", "toes", "foot"]):
        adjusted_sla = min(adjusted_sla, 3)  # Maximum 3 days self-care
        adjusted_cadence = 1                  # Daily check-in

    # 2. Anticoagulant / Antiplatelet Cranial Trauma Rule
    # Seniors on blood thinners are at elevated risk for chronic subdural hematomas after minor head trauma.
    blood_thinners = ["warfarin", "aspirin", "ecosprin", "clopidogrel", "apixaban", "rivaroxaban", "eliquis", "xarelto"]
    is_on_anticoagulants = any(bt in m for bt in blood_thinners for m in medications)
    if is_on_anticoagulants and "head" in anatomical_site:
        adjusted_sla = min(adjusted_sla, 2)   # Maximum 48h observation
        adjusted_cadence = 1

    # 3. Congestive Heart Failure / Renal Fluid Balance Rule
    # Pedal edema in patients with heart failure or CKD requires rapid medical review.
    has_cardiorenal = any("heart failure" in c or "ckd" in c or "kidney" in c or "hypertension" in c for c in conditions)
    if has_cardiorenal and "edema" in canonical_key.lower():
        adjusted_sla = min(adjusted_sla, 3)
        adjusted_cadence = 1

    # 4. Advanced Age & Frailty Modifier (Age >= 80)
    # Reduced physiological reserve: compress self-care window by 25%.
    if age >= 80:
        adjusted_sla = max(2, int(adjusted_sla * 0.75))
        adjusted_cadence = max(1, min(adjusted_cadence, 2))

    modified["max_self_care_days"] = adjusted_sla
    modified["checkin_cadence_days"] = adjusted_cadence
    return modified
