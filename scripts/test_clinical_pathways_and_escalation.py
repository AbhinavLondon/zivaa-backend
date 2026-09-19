import sys
import os
import unittest
from unittest.mock import MagicMock
from datetime import datetime, timezone, timedelta

# Add backend directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.insights.cta_resolver import resolve_ctas, get_care_pathways


class TestClinicalPathwaysAndEscalation(unittest.TestCase):

    def setUp(self):
        self.catalog = get_care_pathways()
        self.pathways = self.catalog.get("pathways", {})
        self.legacy_aliases = self.catalog.get("legacy_aliases", {})

    # =========================================================================
    # SUITE 1: Instantaneous Risk Safety Clamping (Deterministic Coupling)
    # =========================================================================

    def test_1_1_high_risk_sepsis_emergency_coupling(self):
        """Test that HIGH risk infection alert resolves to Level 3 ambulance transfer."""
        input_steps = {
            "title": "Possible Sepsis",
            "title_emphasis": "URGENT",
            "description": "Temperature and heart rate spike.",
            "selected_domain": "occult_infection_sepsis"
        }
        res = resolve_ctas(input_steps, risk_level="HIGH")
        self.assertEqual(res["escalation_tier"], "level_3_acute_emergency")
        self.assertEqual(res["clinical_domain"], "occult_infection_sepsis")
        self.assertEqual(res["primary_cta"]["action"], "CALL_AMBULANCE")
        self.assertEqual(res["secondary_cta"]["action"], "CALL_CAREGIVER")
        self.assertTrue(len(res["caregiver_checklist"]) >= 3)

    def test_1_2_safety_clamp_prevents_llm_downgrade(self):
        """Test that when LLM erroneously outputs level_1 for a HIGH risk alert, resolver forces level_3."""
        input_steps = {
            "title": "Chest Tightness & Dyspnea",
            "description": "Severe cardiac strain detected.",
            "selected_domain": "cardio_autonomic_strain",
            "escalation_level": "level_1_bedside_triage"  # LLM attempt to downgrade
        }
        res = resolve_ctas(input_steps, risk_level="HIGH")
        # Must be clamped to Level 3 emergency
        self.assertEqual(res["escalation_tier"], "level_3_acute_emergency")
        self.assertEqual(res["primary_cta"]["action"], "CALL_AMBULANCE")

    def test_1_3_medium_risk_hypoxemia_diagnostic_coupling(self):
        """Test that MEDIUM risk OSA alert resolves to Level 2 home sleep study."""
        input_steps = {
            "title": "Sleep Disruption & Snoring",
            "description": "SpO2 dipped below 92% with snoring events.",
            "selected_domain": "respiratory_hypoxemia_osa"
        }
        res = resolve_ctas(input_steps, risk_level="MEDIUM")
        self.assertEqual(res["escalation_tier"], "level_2_diagnostic_investigation")
        self.assertEqual(res["primary_cta"]["action"], "BOOK_HOME_SLEEP_STUDY")
        self.assertEqual(res["secondary_cta"]["action"], "BOOK_SPECIALIST_TELEHEALTH")

    def test_1_4_low_risk_sarcopenia_bedside_checklist(self):
        """Test that LOW risk sarcopenia alert resolves to Level 1 fall audit with checklist."""
        input_steps = {
            "title": "Cautious Walking Pace",
            "description": "Cadence slowed slightly after tired night.",
            "selected_domain": "sarcopenia_fall_prevention"
        }
        res = resolve_ctas(input_steps, risk_level="LOW")
        self.assertEqual(res["escalation_tier"], "level_1_bedside_triage")
        self.assertEqual(res["primary_cta"]["action"], "START_GUIDED_TRIAGE")
        self.assertTrue(any("loose carpets" in item.lower() or "rugs" in item.lower() or "walking paths" in item.lower() for item in res["caregiver_checklist"]))

    # =========================================================================
    # SUITE 2: Longitudinal / Temporal Escalation (Failure-to-Resolve)
    # =========================================================================

    def test_2_1_temporal_escalation_after_48_hours(self):
        """Test that an unaddressed Level 1 alert active >48h is automatically promoted to Level 2 diagnostics."""
        mock_supabase = MagicMock()
        old_time = (datetime.now(timezone.utc) - timedelta(hours=50)).isoformat()
        
        # Mock active insight that was created 50 hours ago
        mock_supabase.table().select().eq().eq().lte().limit().execute.return_value.data = [
            {"id": "alert_123", "created_at": old_time, "category": "GENERAL", "rule_id": "early_infection_prediction"}
        ]
        
        input_steps = {
            "title": "Persistent Low-Grade Temperature",
            "description": "Skin temperature still slightly elevated.",
            "selected_domain": "occult_infection_sepsis",
            "escalation_level": "level_1_bedside_triage"
        }
        
        res = resolve_ctas(input_steps, risk_level="LOW", patient_id="mock_patient_1", supabase_client=mock_supabase)
        self.assertEqual(res["escalation_tier"], "level_2_diagnostic_investigation")
        self.assertEqual(res["primary_cta"]["action"], "ORDER_HOME_LABS")
        self.assertIn("escalation_reason", res)
        self.assertIn("48 hours", res["escalation_reason"])

    def test_2_2_recent_anomaly_not_temporally_escalated(self):
        """Test that a fresh Level 1 alert (< 48 hours) stays at Level 1."""
        mock_supabase = MagicMock()
        # Mock returning no alerts older than 48 hours
        mock_supabase.table().select().eq().eq().lte().limit().execute.return_value.data = []
        mock_supabase.table().select().eq().lte().order().limit().execute.return_value.data = []

        input_steps = {
            "title": "Mild Evening Fluid Drift",
            "description": "Mild swelling noted.",
            "selected_domain": "cardiorenal_fluid_balance",
            "escalation_level": "level_1_bedside_triage"
        }
        res = resolve_ctas(input_steps, risk_level="LOW", patient_id="mock_patient_2", supabase_client=mock_supabase)
        self.assertEqual(res["escalation_tier"], "level_1_bedside_triage")
        self.assertEqual(res["primary_cta"]["action"], "START_GUIDED_TRIAGE")
        self.assertNotIn("escalation_reason", res)

    # =========================================================================
    # SUITE 3: Backwards Compatibility & Resilience
    # =========================================================================

    def test_3_1_legacy_level_1_alias_resolves_to_emergency(self):
        """Test that legacy key 'level_1_emergency_dispatch' maps to Level 3 emergency."""
        input_steps = {
            "title": "Emergency Situation",
            "description": "Vitals critical.",
            "selected_pathway": "level_1_emergency_dispatch"
        }
        res = resolve_ctas(input_steps, risk_level="HIGH")
        self.assertEqual(res["escalation_tier"], "level_3_acute_emergency")
        self.assertEqual(res["primary_cta"]["action"], "CALL_AMBULANCE")

    def test_3_2_legacy_level_4_alias_resolves_to_sarcopenia_physio(self):
        """Test that legacy key 'level_4_proactive_intervention' maps to Physio Level 2."""
        input_steps = {
            "title": "Declining Step Count",
            "description": "Mobility is dropping.",
            "selected_pathway": "level_4_proactive_intervention"
        }
        res = resolve_ctas(input_steps, risk_level="MEDIUM")
        self.assertEqual(res["clinical_domain"], "sarcopenia_fall_prevention")
        self.assertEqual(res["escalation_tier"], "level_2_diagnostic_investigation")
        self.assertEqual(res["primary_cta"]["action"], "BOOK_HOME_PHYSIO")

    def test_3_3_corrupted_key_graceful_fallback(self):
        """Test that completely unknown or corrupted pathway keys fallback safely."""
        input_steps = {
            "title": "Unknown Alert",
            "description": "Data parsed.",
            "selected_pathway": "some_gibberish_nonexistent_key_123"
        }
        res = resolve_ctas(input_steps, risk_level="LOW")
        self.assertEqual(res["clinical_domain"], "wellness_vitality_reinforcement")
        self.assertEqual(res["escalation_tier"], "level_1_bedside_triage")
        self.assertIn("primary_cta", res)
        self.assertIn("caregiver_checklist", res)

    def test_3_4_non_dict_action_steps_fallback(self):
        """Test that if action_steps is passed as a string or None, it returns a valid dict."""
        res = resolve_ctas("Drink water and rest.", risk_level="LOW")
        self.assertIsInstance(res, dict)
        self.assertEqual(res["primary_cta"]["action"], "VIEW_METRICS")
        self.assertEqual(res["escalation_tier"], "level_1_bedside_triage")

    # =========================================================================
    # SUITE 4: Pathway Schema & Integrity Validation
    # =========================================================================

    def test_4_1_all_eight_domains_have_three_escalation_levels(self):
        """Validate that all 8 domains exist and each defines all 3 escalation levels."""
        expected_domains = [
            "occult_infection_sepsis",
            "respiratory_hypoxemia_osa",
            "cardiorenal_fluid_balance",
            "sarcopenia_fall_prevention",
            "cardio_autonomic_strain",
            "sleep_metabolic_dysregulation",
            "geriatric_polypharmacy",
            "wellness_vitality_reinforcement"
        ]
        expected_levels = [
            "level_1_bedside_triage",
            "level_2_diagnostic_investigation",
            "level_3_acute_emergency"
        ]
        for dom in expected_domains:
            self.assertIn(dom, self.pathways, f"Missing domain: {dom}")
            levels = self.pathways[dom].get("escalation_levels", {})
            for lvl in expected_levels:
                self.assertIn(lvl, levels, f"Domain '{dom}' is missing level '{lvl}'")

    def test_4_2_all_levels_have_valid_buttons_and_checklists(self):
        """Validate that no pathway level has empty CTAs or checklists."""
        for dom_name, dom_data in self.pathways.items():
            for lvl_name, lvl_data in dom_data.get("escalation_levels", {}).items():
                p_cta = lvl_data.get("primary_cta")
                s_cta = lvl_data.get("secondary_cta")
                checklist = lvl_data.get("caregiver_checklist")

                self.assertIsNotNone(p_cta, f"{dom_name}.{lvl_name} missing primary_cta")
                self.assertTrue(len(p_cta.get("label", "")) > 0, f"{dom_name}.{lvl_name} empty primary label")
                self.assertTrue(len(p_cta.get("action", "")) > 0, f"{dom_name}.{lvl_name} empty primary action")

                self.assertIsNotNone(s_cta, f"{dom_name}.{lvl_name} missing secondary_cta")
                self.assertTrue(len(s_cta.get("label", "")) > 0, f"{dom_name}.{lvl_name} empty secondary label")
                self.assertTrue(len(s_cta.get("action", "")) > 0, f"{dom_name}.{lvl_name} empty secondary action")

                self.assertIsNotNone(checklist, f"{dom_name}.{lvl_name} missing caregiver_checklist")
                self.assertTrue(len(checklist) >= 2, f"{dom_name}.{lvl_name} checklist has < 2 items")


if __name__ == "__main__":
    unittest.main()
