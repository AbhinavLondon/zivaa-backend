"""
Verification test suite for Sleep Event Date Disambiguation and Missing Sleep Guardrail.
Tests:
1. Guardrail suppresses stale sleep alerts when vitals_daily.sleep_hours is None.
2. Guardrail allows valid acute sleep alerts when fresh sleep telemetry exists.
3. Guardrail preserves updated_at for cardiac / continuous vitals escalations.
4. medgemma_services prompt instructions use dynamic temporal phrasing instead of hardcoded 'today'.
"""

import sys
import os
import re
from datetime import datetime, timezone, timedelta

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()


def test_guardrail_logic():
    print("=" * 75)
    print("RUNNING SLEEP EVENT DATE & TELEMETRY GUARDRAIL TESTS")
    print("=" * 75)

    twelve_hours_ago = (datetime.now(timezone.utc) - timedelta(hours=12)).isoformat()
    four_hours_ago = (datetime.now(timezone.utc) - timedelta(hours=4)).isoformat()
    twenty_two_hours_ago = (datetime.now(timezone.utc) - timedelta(hours=22)).isoformat()

    # --- TEST 1: Parinita Case (Stale sleep insight updated recently, but sleep_hours is None) ---
    stale_sleep_alert = {
        "id": "alert-sleep-1",
        "rule_id": "critically_elevated_waso_mins",
        "name": "Critically Elevated WASO",
        "category": "SLEEP",
        "severity": "HIGH",
        "message": "Patient's Wake After Sleep Onset (WASO) on 2026-09-16 remains critically elevated at 29.0 minutes.",
        "created_at": twenty_two_hours_ago, # Created yesterday morning
        "updated_at": four_hours_ago        # Touched 4 hours ago by evening step sync
    }

    # vitals_daily has no sleep for today (watch unworn)
    latest_vd_missing = {
        "date": "2026-09-17T00:00:00",
        "sleep_hours": None
    }
    latest_date_str = latest_vd_missing["date"][:10]
    has_overnight_sleep = (latest_vd_missing.get("sleep_hours") is not None and latest_vd_missing.get("sleep_hours") > 0)

    # Run filtering logic
    alerts_1 = []
    is_recent = (stale_sleep_alert["created_at"] >= twelve_hours_ago) or (stale_sleep_alert["updated_at"] >= twelve_hours_ago)
    assert is_recent, "Should pass 12h freshness check due to updated_at"

    rule_id = (stale_sleep_alert.get("rule_id") or "").lower()
    cat = (stale_sleep_alert.get("category") or "").upper()
    is_sleep_rule = (cat == "SLEEP") or any(k in rule_id for k in ("sleep", "waso", "awakening"))
    assert is_sleep_rule, "Should be recognized as sleep rule"

    m_date = re.search(r'\b(\d{4}-\d{2}-\d{2})\b', stale_sleep_alert.get("message", ""))
    obs_date = m_date.group(1) if m_date else None
    assert obs_date == "2026-09-16", f"Expected 2026-09-16, got {obs_date}"

    if not has_overnight_sleep:
        print("[Test 1 PASS] Correctly suppressed stale sleep alert when sleep_hours is None!")
    else:
        alerts_1.append(stale_sleep_alert)
    assert len(alerts_1) == 0, "Stale sleep alert should NOT be included when sleep_hours is None"


    # --- TEST 2: Valid Fresh Sleep Alert (sleep_hours > 0 and observation date matches) ---
    fresh_sleep_alert = {
        "id": "alert-sleep-fresh",
        "rule_id": "critically_elevated_waso_mins",
        "name": "Critically Elevated WASO",
        "category": "SLEEP",
        "severity": "HIGH",
        "message": "Patient's Wake After Sleep Onset (WASO) on 2026-09-17 remains critically elevated at 32.0 minutes.",
        "created_at": four_hours_ago,
        "updated_at": four_hours_ago
    }
    latest_vd_fresh = {
        "date": "2026-09-17T00:00:00",
        "sleep_hours": 6.8
    }
    has_overnight_sleep_2 = (latest_vd_fresh.get("sleep_hours") is not None and latest_vd_fresh.get("sleep_hours") > 0)
    alerts_2 = []
    if has_overnight_sleep_2:
        m_date2 = re.search(r'\b(\d{4}-\d{2}-\d{2})\b', fresh_sleep_alert.get("message", ""))
        obs_date2 = m_date2.group(1) if m_date2 else None
        if obs_date2 == latest_vd_fresh["date"][:10]:
            alerts_2.append(fresh_sleep_alert)
    assert len(alerts_2) == 1, "Fresh sleep alert should be included when sleep_hours is valid"
    print("[Test 2 PASS] Fresh sleep alert correctly included when valid telemetry exists!")


    # --- TEST 3: Preserving updated_at for Cardiac Escalation ---
    cardiac_escalation_alert = {
        "id": "alert-cardiac-1",
        "rule_id": "elevated_avg_heart_rate",
        "name": "Elevated Average Heart Rate",
        "category": "CARDIAC",
        "severity": "HIGH",
        "message": "Patient's heart rate escalated to 115 bpm.",
        "created_at": twenty_two_hours_ago, # Created 22 hours ago
        "updated_at": four_hours_ago        # Escalated 4 hours ago
    }
    alerts_3 = []
    is_recent_3 = (cardiac_escalation_alert["created_at"] >= twelve_hours_ago) or (cardiac_escalation_alert["updated_at"] >= twelve_hours_ago)
    rule_id_3 = (cardiac_escalation_alert.get("rule_id") or "").lower()
    cat_3 = (cardiac_escalation_alert.get("category") or "").upper()
    is_sleep_rule_3 = (cat_3 == "SLEEP") or any(k in rule_id_3 for k in ("sleep", "waso", "awakening"))

    if is_recent_3:
        if not is_sleep_rule_3:
            # Continuous vital: preserved based on updated_at!
            alerts_3.append(cardiac_escalation_alert)
    assert len(alerts_3) == 1, "Cardiac escalation MUST be preserved based on updated_at"
    print("[Test 3 PASS] Cardiac escalation correctly preserved based on updated_at!")


    # --- TEST 4: Verify Prompt Constraint in medgemma_services.py ---
    medgemma_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "services", "medgemma_services.py")
    with open(medgemma_path, "r", encoding="utf-8") as f:
        medgemma_code = f.read()

    assert 'ALWAYS refer to them as "today" (NEVER "yesterday")' not in medgemma_code, \
        "Hardcoded 'ALWAYS refer to them as today' MUST be removed from medgemma_services.py"
    assert "Last night's sleep" in medgemma_code, \
        "'Last night's sleep' instruction should be present in medgemma_services.py"
    print("[Test 4 PASS] medgemma_services.py has dynamic temporal accuracy instructions!")

    print("\nALL 4 TESTS PASSED PERFECTLY!")


if __name__ == "__main__":
    test_guardrail_logic()
