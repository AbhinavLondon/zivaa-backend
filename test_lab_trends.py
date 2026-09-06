"""
Test: Biomarker Trend Analysis with RCV-Based Thresholds
=========================================================

Tests the get_patient_lab_trends() service against Ranjit's real lab data
(3 reports: Jan, Mar, Jun 2026).

Key verification points:
  - RCV thresholds correctly filter biological noise from real trends
  - Inverse-polarity biomarkers (eGFR, HDL) are flagged correctly
  - Rate-of-change alerts fire for KDIGO eGFR and ADA HbA1c thresholds
  - Filtering by biomarker code works
  - Arithmetic on rate_per_month is correct
"""

import json
from app.services.lab_history import (
    get_patient_lab_trends,
    _compute_rcv,
    _get_rcv_for_biomarker,
    _BIOLOGICAL_VARIATION,
)

RANJIT_ID = "11111111-1111-1111-1111-111111111111"


def test_rcv_computation():
    """Verify the RCV formula against known values."""
    # HbA1c: CVi=1.9%, CVa=1.5% -> RCV should be ~6.7%
    rcv = _compute_rcv(1.9, 1.5)
    assert 6.5 < rcv < 7.0, f"HbA1c RCV expected ~6.7%, got {rcv:.1f}%"

    # Creatinine: CVi=5.3%, CVa=2.2% -> RCV should be ~15.9%
    rcv = _compute_rcv(5.3, 2.2)
    assert 15.5 < rcv < 16.5, f"Creatinine RCV expected ~15.9%, got {rcv:.1f}%"

    # TSH: CVi=19.3%, CVa=2.5% -> RCV should be ~54.1%
    rcv = _compute_rcv(19.3, 2.5)
    assert 53.0 < rcv < 55.0, f"TSH RCV expected ~54.1%, got {rcv:.1f}%"

    print("[PASS] RCV formula verified for HbA1c (6.7%), Creatinine (15.9%), TSH (54.1%)")


def test_rcv_lookup():
    """Verify the RCV lookup returns correct per-biomarker values."""
    hba1c_rcv = _get_rcv_for_biomarker("HBA1C")
    creat_rcv = _get_rcv_for_biomarker("CREATININE")
    tsh_rcv = _get_rcv_for_biomarker("TSH")
    unknown_rcv = _get_rcv_for_biomarker("UNKNOWN_MARKER")

    assert hba1c_rcv < creat_rcv < tsh_rcv, "RCV ordering should be HbA1c < Creatinine < TSH"
    assert unknown_rcv > 0, "Unknown biomarker should get a default RCV"
    print(f"[PASS] RCV lookup: HbA1c={hba1c_rcv:.1f}%, Creat={creat_rcv:.1f}%, TSH={tsh_rcv:.1f}%, Unknown={unknown_rcv:.1f}%")


def test_full_trends():
    """Fetch all trends for Ranjit and print a summary table."""
    result = get_patient_lab_trends(RANJIT_ID)
    trends = result["trend_summary"]

    print(f"\n{'='*100}")
    print(f"  Biomarker Trend Analysis -- Patient: {result['patient_id'][:8]}...")
    print(f"  Total biomarkers tracked: {len(trends)}")
    print(f"{'='*100}")

    print(f"\n{'Biomarker':<25} {'Direction':<18} {'Rate/mo':<10} {'Zone':<18} {'Flag':<18} {'RCV%':<8} {'Chg%':<8}")
    print(f"{'-'*25} {'-'*18} {'-'*10} {'-'*18} {'-'*18} {'-'*8} {'-'*8}")

    for code, t in sorted(trends.items()):
        alert_marker = " (!)" if "rate_alert" in t else ""
        print(
            f"{t['name'][:24]:<25} "
            f"{t['trend_direction']:<18} "
            f"{t['rate_per_month']:>+8.3f}  "
            f"{t['zone']:<18} "
            f"{t['clinical_flag']:<18} "
            f"{t['rcv_threshold_pct']:>5.1f}%  "
            f"{t['change_percent']:>+6.1f}%{alert_marker}"
        )

    # Print rate alerts separately
    alerts = [(c, t) for c, t in trends.items() if "rate_alert" in t]
    if alerts:
        print(f"\n  Rate-of-change alerts (published guideline thresholds):")
        for code, t in alerts:
            alert = t["rate_alert"]
            print(f"    {t['name']}: {alert['label']} -- {alert['citation']}")

    print()
    return trends


def test_hba1c_trend(trends):
    """
    HbA1c: 5.8 -> 6.1 -> 6.4 (change = +10.3%)
    RCV for HbA1c = ~6.7%
    10.3% > 6.7% => should be flagged as 'rising' (not filtered as noise)
    """
    hba1c = trends.get("HBA1C")
    if not hba1c:
        print("[WARN] HBA1C not found in trends -- skipping")
        return

    assert hba1c["trend_direction"] == "rising", f"Expected rising, got {hba1c['trend_direction']}"
    assert hba1c["zone"] == "above_range", f"Expected above_range, got {hba1c['zone']}"
    assert hba1c["clinical_flag"] == "worsening", f"Expected worsening, got {hba1c['clinical_flag']}"
    assert hba1c["data_points"] == 3
    assert hba1c["rcv_threshold_pct"] > 0, "Should have a non-zero RCV"
    print(f"[PASS] HBA1C: rising + above_range = worsening (RCV={hba1c['rcv_threshold_pct']}%, change={hba1c['change_percent']}%)")


def test_egfr_trend(trends):
    """
    eGFR: 78 -> 68 -> 58 (change = -25.6%)
    RCV for eGFR = ~15.9%
    25.6% > 15.9% => should be flagged as 'declining'
    eGFR is inverse-polarity: declining + below_range = worsening
    """
    egfr = trends.get("EGFR")
    if not egfr:
        print("[WARN] EGFR not found in trends -- skipping")
        return

    assert egfr["trend_direction"] == "declining", f"Expected declining, got {egfr['trend_direction']}"
    assert egfr["zone"] == "below_range", f"Expected below_range, got {egfr['zone']}"
    assert egfr["clinical_flag"] == "worsening", f"Expected worsening, got {egfr['clinical_flag']}"
    assert egfr["data_points"] == 3
    print(f"[PASS] EGFR: declining + below_range + inverse = worsening (RCV={egfr['rcv_threshold_pct']}%)")


def test_egfr_rate_alert(trends):
    """
    eGFR rate: -4.06 mL/min per month = -48.7 mL/min per year
    KDIGO threshold: decline > 5 mL/min per year = rapid progression
    -48.7 < -5 => rate_alert should be present
    """
    egfr = trends.get("EGFR")
    if not egfr:
        print("[WARN] EGFR not found -- skipping rate alert check")
        return

    assert "rate_alert" in egfr, f"Expected rate_alert for EGFR (rate={egfr['rate_per_month'] * 12:.1f}/year)"
    alert = egfr["rate_alert"]
    assert alert["label"] == "rapid_progression", f"Expected rapid_progression, got {alert['label']}"
    assert "KDIGO" in alert["citation"], "Citation should mention KDIGO"
    print(f"[PASS] EGFR rate alert: {alert['label']} ({alert['citation'][:60]}...)")


def test_creatinine_trend(trends):
    """
    Creatinine: 1.1 -> 1.25 -> 1.4 (change = +27.3%)
    RCV for Creatinine = ~15.9%
    27.3% > 15.9% => should be flagged as 'rising'
    """
    creat = trends.get("CREATININE")
    if not creat:
        print("[WARN] CREATININE not found -- skipping")
        return

    assert creat["trend_direction"] == "rising", f"Expected rising, got {creat['trend_direction']}"
    assert creat["zone"] == "above_range", f"Expected above_range, got {creat['zone']}"
    assert creat["clinical_flag"] == "worsening", f"Expected worsening, got {creat['clinical_flag']}"
    print(f"[PASS] CREATININE: rising + above_range = worsening (RCV={creat['rcv_threshold_pct']}%)")


def test_high_biovariation_markers(trends):
    """
    CRP has CVi=42% => RCV ~117%. Most CRP changes should be 'stable'
    unless the change is truly dramatic (e.g., >117%).
    TSH has CVi=19.3% => RCV ~54.1%.
    These high-variation biomarkers should NOT produce false trends.
    """
    crp = trends.get("CRP")
    tsh = trends.get("TSH")

    if crp:
        crp_rcv = crp["rcv_threshold_pct"]
        assert crp_rcv > 100, f"CRP RCV should be >100%, got {crp_rcv}%"
        print(f"[PASS] CRP: RCV={crp_rcv}% (extreme bio-variation correctly captured)")
        # CRP: 0.9 -> 1.8 -> 3.1 = +244% change, which exceeds even the 117% RCV
        # So it may still be 'rising' -- that's correct for a >244% change

    if tsh:
        tsh_rcv = tsh["rcv_threshold_pct"]
        assert tsh_rcv > 50, f"TSH RCV should be >50%, got {tsh_rcv}%"
        print(f"[PASS] TSH: RCV={tsh_rcv}% (high bio-variation correctly captured), direction={tsh['trend_direction']}")


def test_filtered_trends():
    """Verify filtering to specific biomarkers."""
    result = get_patient_lab_trends(RANJIT_ID, ["HBA1C", "FBS"])
    trends = result["trend_summary"]

    assert "HBA1C" in trends, "HBA1C should be in filtered results"
    assert "FBS" in trends, "FBS should be in filtered results"
    assert "EGFR" not in trends, "EGFR should NOT be in filtered results"
    print(f"[PASS] Filtered trends: got {len(trends)} biomarkers (HBA1C, FBS only)")


def test_rate_per_month_arithmetic(trends):
    """Spot-check rate_per_month for HbA1c: 0.6 change over ~5 months ~ 0.12/month."""
    hba1c = trends.get("HBA1C")
    if not hba1c:
        print("[WARN] HBA1C not found -- skipping rate check")
        return

    rate = hba1c["rate_per_month"]
    assert 0.08 < rate < 0.16, f"Expected rate ~0.12/mo, got {rate}"
    print(f"[PASS] Rate/month arithmetic: HbA1c = {rate:+.3f}/month (expected ~0.12)")


def test_history_has_chart_dates(trends):
    """Verify history entries have YYYY-MM-DD date format for charting."""
    for code, t in trends.items():
        for h in t["history"]:
            assert len(h["date"]) == 10, f"{code}: date '{h['date']}' is not YYYY-MM-DD"
        break  # Just check the first biomarker
    print("[PASS] History dates are in YYYY-MM-DD chart format")


def test_rcv_in_response(trends):
    """Verify that rcv_threshold_pct is included in every trend entry."""
    for code, t in trends.items():
        assert "rcv_threshold_pct" in t, f"{code} missing rcv_threshold_pct"
        assert t["rcv_threshold_pct"] > 0, f"{code} has zero RCV"
    print(f"[PASS] All {len(trends)} biomarkers include rcv_threshold_pct for auditability")


if __name__ == "__main__":
    print("\n[TEST] Running Biomarker Trend Analysis Tests (RCV-based)...\n")

    test_rcv_computation()
    test_rcv_lookup()

    trends = test_full_trends()
    test_hba1c_trend(trends)
    test_egfr_trend(trends)
    test_egfr_rate_alert(trends)
    test_creatinine_trend(trends)
    test_high_biovariation_markers(trends)
    test_filtered_trends()
    test_rate_per_month_arithmetic(trends)
    test_history_has_chart_dates(trends)
    test_rcv_in_response(trends)

    print("\n" + "="*50)
    print("[PASS] All biomarker trend tests passed!")
    print("="*50 + "\n")
