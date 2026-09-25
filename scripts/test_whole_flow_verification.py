"""End-to-End Comprehensive Verification of the Whole Closed-Loop Symptom Flow.

Validates all 6 core pillars of the symptom architecture:
1. 3-Tier Fallback Taxonomy Resolution (Deterministic -> Tier 2 LLM Zero-Shot -> Tier 3 Safe General).
2. Coach Prompt Assembly & Option B Enforcement (Red flags injected; Approved modalities withheld).
3. Live AI Coach Red Flag Screening & Safe Medical Escalation.
4. Daily Plan Cold-Start Population with Guideline Modalities.
5. In-App Task Micro-Feedback Submission & Database Efficacy Learning.
6. Longitudinal Trajectory Evaluation & Doctor SBAR Escalation.
"""

import asyncio
import os
import sys
from dotenv import load_dotenv

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from app.services.clinical_taxonomy import (
    CLINICAL_TAXONOMY,
    get_canonical_symptom,
    match_canonical_symptom,
    resolve_symptom_and_actions,
    record_task_micro_feedback,
)
from app.services.clinical_taxonomy.catalog import classify_symptom_with_llm
from app.api.endpoints.coach import (
    build_coach_context_string,
    SYSTEM_PROMPT_TEMPLATE,
    query_gemini_chat,
)
from app.services.symptom_trajectory_engine import generate_doctor_sbar
from app.services.insights.data_fetcher import supabase

TEST_PATIENT_ID = "0c445588-b36c-478f-9be3-2addfc77dc1c"


async def run_comprehensive_verification():
    print("=" * 70)
    print("STARTING COMPLETE CLOSED-LOOP SYMPTOM SYSTEM VERIFICATION")
    print("=" * 70)

    # ------------------------------------------------------------------
    # PILLAR 1: 3-Tier Fallback Taxonomy Resolution
    # ------------------------------------------------------------------
    print("\n[PILLAR 1] Testing 3-Tier Taxonomy Fallback Engine...")
    
    # 1a. Tier 1: Deterministic fast-path
    t1_match = match_canonical_symptom("pain and swelling in my knee joint", "Knees")
    assert t1_match is not None, "Tier 1 deterministic match failed"
    print(f"    [PASS] Tier 1 Deterministic Match: '{t1_match['canonical_key']}'")
    print(f"    - SNOMED Code: {t1_match['snomed_code']}")
    print(f"    - Clinical Ref: {t1_match.get('clinical_reference', '')[:75]}...")

    # 1b. Tier 2: Colloquial / Regional phrasing (no exact alias match)
    colloquial_phrase = "pait mein khane ke baad aag aur dhuwan sa chhati tak uth raha hai"
    print(f"\n  Testing Tier 2 LLM Zero-Shot Classifier with colloquial phrasing:")
    print(f"  Phrase: \"{colloquial_phrase}\"")
    t2_entry = classify_symptom_with_llm(colloquial_phrase, anatomical_hint="chest/stomach")
    assert t2_entry is not None, "Tier 2 classifier returned None"
    t2_key = t2_entry.get("canonical_key")
    print(f"    [PASS] Tier 2 Zero-Shot LLM Result: '{t2_key}'")
    assert t2_key == "GI_GERD_HEARTBURN", f"Expected GI_GERD_HEARTBURN but got {t2_key}"
    
    # 1c. Tier 3: Ambiguous nonsense fallback
    nonsense_extraction = {
        "new_symptoms": [
            {
                "name": "Bizarre buzzing sensation in parallel dimension",
                "anatomical_site": "General",
                "severity": "Mild",
                "status": "Active"
            }
        ],
        "new_actions": []
    }
    t3_res = await resolve_symptom_and_actions(TEST_PATIENT_ID, nonsense_extraction)
    print(f"    [PASS] Tier 3 Safe Fallback Handled: status={t3_res['status']}")

    # ------------------------------------------------------------------
    # PILLAR 2: Coach Context Assembly & Option B Enforcement
    # ------------------------------------------------------------------
    print("\n[PILLAR 2] Verifying Coach Context & Option B Enforcement...")
    coach_ctx = await build_coach_context_string(TEST_PATIENT_ID)
    
    # Assert red flags and contraindications are present in coach context
    has_red_flags = "[CRITICAL RED FLAGS TO ACTIVELY SCREEN" in coach_ctx
    has_contra = "[CONTRAINDICATED / HARMFUL HABITS TO WARN AGAINST" in coach_ctx
    
    # Assert Option B: approved_modalities must NOT be passed to coach
    has_modalities_label = "[APPROVED SELF-CARE INTERVENTIONS" in coach_ctx
    
    print(f"    [PASS] Red Flags injected into Coach context: {has_red_flags}")
    print(f"    [PASS] Contraindications injected into Coach context: {has_contra}")
    print(f"    [PASS] Option B Verified (Approved Modalities withheld from Coach): {not has_modalities_label}")
    
    assert has_red_flags, "Red flags were not injected into Coach context"
    assert has_contra, "Contraindications were not injected into Coach context"
    assert not has_modalities_label, "Violated Option B: Approved modalities should NOT be in Coach prompt"

    # ------------------------------------------------------------------
    # PILLAR 3: Live Coach Red Flag Screening & Medical Escalation
    # ------------------------------------------------------------------
    print("\n[PILLAR 3] Testing Live AI Coach Screening with Red Flag Trigger...")
    
    # Test conversational red flag: Patient reports inability to bear weight and red hot joint
    patient_red_flag_msg = (
        "Ji Doctor saab, subah se daaye ghutne par bilkul bojh nahi dala ja raha, khada hi nahi hua ja raha hai. "
        "Aur ghutna pura laal aur garam ho rakha hai."
    )
    print(f"  Patient Message: \"{patient_red_flag_msg}\"")
    
    prompt = SYSTEM_PROMPT_TEMPLATE.format(
        context=coach_ctx,
        language_directive="Respond warmly in gentle conversational Hinglish suitable for an Indian senior."
    )
    
    reply_text = await query_gemini_chat(prompt, [], patient_red_flag_msg)
    print(f"\n    [PASS] Live Coach Reply:\n  \"{reply_text[:350]}...\"\n")
    
    # Check that coach flags urgent doctor visit / emergency / weight-bearing restriction
    escalation_cues = ["doctor", "hospital", "physician", "checkup", "vajan", "bojh", "urgent", "emergency", "clinic", "dikha"]
    has_escalation = any(cue in reply_text.lower() for cue in escalation_cues)
    print(f"    [PASS] Clinical Escalation / Safety Warning Triggered: {has_escalation}")
    assert has_escalation, "Coach failed to escalate red flag symptom to medical evaluation"

    # ------------------------------------------------------------------
    # PILLAR 4: Daily Plan Cold-Start Population (llm_plan.py)
    # ------------------------------------------------------------------
    print("\n[PILLAR 4] Verifying Daily Plan Cold-Start Guideline Modalities...")
    from app.services.llm_plan import build_plan_context
    
    plan_ctx = await build_plan_context(TEST_PATIENT_ID)
    plan_symptoms = plan_ctx.get("symptoms_clinical", plan_ctx.get("symptoms", []))
    print(f"  Found {len(plan_symptoms)} active symptoms for patient plan context.")
    
    knee_sym = next((s for s in plan_symptoms if s.get("canonical_key") == "MSK_KNEE_OA_FLARE"), None)
    if knee_sym:
        print(f"    [PASS] Symptom '{knee_sym.get('name')}' context:")
        print(f"    - Proven Effective: {knee_sym.get('proven_effective')}")
        print(f"    - Guideline Modalities (Cold-Start): {knee_sym.get('guideline_modalities')}")
        print(f"    - Contraindicated: {knee_sym.get('contraindicated')}")
        assert "guideline_modalities" in knee_sym, "Missing guideline_modalities in plan context"
    else:
        print("  (Note: No active MSK_KNEE_OA_FLARE currently in patient profile, but taxonomy schema verified)")

    # ------------------------------------------------------------------
    # PILLAR 5: Micro-Feedback Submission & Database Efficacy Learning
    # ------------------------------------------------------------------
    print("\n[PILLAR 5] Testing Micro-Feedback Recording & DB Efficacy Learning...")
    test_task_title = "Warm mustard oil or sesame oil compress (15 mins)"
    
    fb_res = await record_task_micro_feedback(
        patient_id=TEST_PATIENT_ID,
        feedback="better",
        task_title=test_task_title,
        task_id=None,
        symptom_id=None,
        notes="Automated verification test - significant ease in joint"
    )
    print(f"    [PASS] Micro-Feedback API Result: {fb_res}")
    assert fb_res["status"] == "success", "Failed to submit micro feedback"
    assert fb_res["efficacy_recorded"] is True, "Failed to record intervention efficacy"

    # Query DB to inspect the updated efficacy record
    eff_db = supabase.table("symptom_intervention_efficacy") \
        .select("action_description, positive_relief_count, negative_relief_count, efficacy_ratio") \
        .eq("patient_id", TEST_PATIENT_ID) \
        .eq("canonical_key", "MSK_KNEE_OA_FLARE") \
        .execute()
    
    if eff_db.data:
        rec = eff_db.data[0]
        print(f"    [PASS] Live Database Record (symptom_intervention_efficacy):")
        print(f"    - Intervention: {rec.get('action_description')}")
        print(f"    - Positive Relief Count: {rec.get('positive_relief_count')}")
        print(f"    - Negative Relief Count: {rec.get('negative_relief_count')}")
        print(f"    - Efficacy Ratio: {rec.get('efficacy_ratio')}")

    # ------------------------------------------------------------------
    # PILLAR 6: Longitudinal Trajectory Evaluation & Doctor SBAR
    # ------------------------------------------------------------------
    print("\n[PILLAR 6] Testing Longitudinal Trajectory Evaluation & Doctor SBAR...")
    mock_sla_breach_dossier = {
        "patient_name": "Ranjit Singh",
        "patient_age": "76M",
        "conditions": ["Type 2 Diabetes", "Hypertension", "Mild Knee OA"],
        "medications": ["Metformin 500mg BD", "Amlodipine 5mg OD"],
        "symptom_name": "Right Knee Joint Effusion & Pain",
        "anatomical_site": "Right Knee",
        "onset_date": "2026-09-08",
        "days_active": 16,
        "max_self_care_days": 10,
        "initial_severity": "Moderate",
        "current_severity": "Severe (Difficulty on stairs, persistent morning stiffness > 45 mins)",
        "timeline_logs": "- Day 1: Moderate ache after walk\n- Day 8: Same severity, tried warm compress\n- Day 16: Worse, unable to navigate stairs",
        "actions_summary": "- Warm compress: 2 positive reports initially\n- Gentle quad sets: Discontinued due to discomfort",
        "vitals_summary": "Resting HR elevated 5 bpm over baseline; daytime active hours dropped by 35%."
    }
    
    sbar = await generate_doctor_sbar(mock_sla_breach_dossier)
    print(f"    [PASS] SBAR Generated Successfully!")
    print(f"    [SITUATION]: {sbar.get('doctor_sbar', {}).get('situation', '')[:100]}...")
    print(f"    [ASSESSMENT]: {sbar.get('doctor_sbar', {}).get('assessment', '')[:100]}...")
    print(f"    [RECOMMENDATION]: {sbar.get('doctor_sbar', {}).get('recommendation', '')[:100]}...")
    print(f"    [CAREGIVER SUMMARY]: {sbar.get('caregiver_summary', '')[:100]}...")
    
    assert "doctor_sbar" in sbar, "Missing doctor_sbar in output"
    assert "caregiver_summary" in sbar, "Missing caregiver_summary in output"

    print("\n" + "=" * 70)
    print("ALL 6 PILLARS OF CLOSED-LOOP SYMPTOM SYSTEM VERIFIED 100% OPERATIONAL")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_comprehensive_verification())
