"""Backfill Migration Script for Legacy patient_symptoms records.

Iterates over all existing patient_symptoms:
1. Decrypts encrypted symptom names using Fernet.
2. Resolves against the 12-domain CLINICAL_TAXONOMY catalog.
3. Applies comorbidity and geriatric modifiers for accurate clinical SLAs.
4. Updates patient_symptoms: canonical_key, snomed_code, anatomical_site, symptom_category, max_self_care_days.
"""

import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from dotenv import load_dotenv

load_dotenv()

from app.services.insights.data_fetcher import supabase, fetch_patient_context
from app.utils.crypto import decrypt_text
from app.services.clinical_taxonomy.catalog import match_canonical_symptom
from app.services.clinical_taxonomy.modifiers import apply_geriatric_modifiers


def run_backfill():
    print("=" * 70)
    print("STARTING CLINICAL TAXONOMY BACKFILL FOR PATIENT SYMPTOMS")
    print("=" * 70)

    # 1. Fetch all symptoms
    res = supabase.table("patient_symptoms").select("id, patient_id, name, anatomical_site, symptom_category, canonical_key").execute()
    symptoms = res.data or []
    print(f"Total symptoms found in database: {len(symptoms)}\n")

    updated_count = 0
    skipped_count = 0

    # Cache patient profiles to avoid repeated fetches
    patient_cache = {}

    for symp in symptoms:
        symp_id = symp["id"]
        pid = symp.get("patient_id")
        raw_name = symp.get("name")
        decrypted_name = decrypt_text(raw_name) if raw_name else "Unknown"

        # Fetch patient profile
        if pid not in patient_cache:
            profile = {"age": 70, "conditions": [], "medications": []}
            try:
                p_res = supabase.table("patients").select("age").eq("id", pid).execute()
                if p_res.data and p_res.data[0].get("age"):
                    profile["age"] = p_res.data[0]["age"]
                ctx = fetch_patient_context(pid)
                profile["conditions"] = ctx.patient_conditions or []
                profile["medications"] = getattr(ctx, "medications", [])
            except Exception:
                pass
            patient_cache[pid] = profile

        pt_profile = patient_cache[pid]

        # Match against taxonomy
        matched = match_canonical_symptom(decrypted_name, symp.get("anatomical_site"))

        if not matched:
            print(f"[SKIP] ID: {symp_id[:8]} | Decrypted: '{decrypted_name}' -> No match found in catalog")
            skipped_count += 1
            continue

        # Apply geriatric modifiers
        mod_entry = apply_geriatric_modifiers(matched, pt_profile)

        update_payload = {
            "canonical_key": mod_entry["canonical_key"],
            "snomed_code": mod_entry["snomed_code"],
            "anatomical_site": mod_entry["anatomical_site"],
            "symptom_category": mod_entry["domain"].upper(),
            "expected_resolution_days": mod_entry.get("expected_resolution_days", 7),
            "max_self_care_days": mod_entry.get("max_self_care_days", 14),
            "checkin_cadence_days": mod_entry.get("checkin_cadence_days", 3)
        }

        try:
            supabase.table("patient_symptoms").update(update_payload).eq("id", symp_id).execute()
            updated_count += 1
            print(f"[UPDATED] ID: {symp_id[:8]} | '{decrypted_name}'")
            print(f"          Category: {mod_entry['domain'].upper()} | Key: {mod_entry['canonical_key']}")
            print(f"          Site: {mod_entry['anatomical_site']} | SLA: {mod_entry['max_self_care_days']}d")
        except Exception as e:
            print(f"[ERROR] Failed to update {symp_id}: {e}")

    print("\n" + "=" * 70)
    print(f"BACKFILL COMPLETE: {updated_count} updated, {skipped_count} skipped.")
    print("=" * 70)


if __name__ == "__main__":
    run_backfill()
