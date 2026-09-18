"""
CLI runner for the Senior Geriatric Clinical Advisor Agent.
Audits nudge_alerts in Supabase and prints the 7-point clinical analysis.

Usage:
  python run_clinical_advisor.py --nudge-id <UUID>
  python run_clinical_advisor.py --recent <N>
  python run_clinical_advisor.py --patient <PATIENT_UUID>
"""

import sys
import os
import argparse
import json

# Ensure UTF-8 output on Windows console
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from app.services.clinical_advisor import (
    audit_nudge_alert,
    format_clinical_audit_markdown,
    get_supabase_client
)


def main():
    parser = argparse.ArgumentParser(description="Run Clinical Audit on Zivaa Nudge Alerts")
    parser.add_argument("--nudge-id", type=str, help="Specific Nudge ID (UUID) to audit")
    parser.add_argument("--recent", type=int, default=0, help="Number of recent nudges to audit")
    parser.add_argument("--patient", type=str, help="Audit recent nudges for a specific patient ID")
    parser.add_argument("--json", action="store_true", help="Output raw JSON instead of markdown")
    args = parser.parse_args()

    client = get_supabase_client()

    if args.nudge_id:
        print(f"\nAuditing Nudge ID: {args.nudge_id}...")
        audit = audit_nudge_alert(args.nudge_id, client)
        if args.json:
            print(json.dumps(audit, indent=2, default=str))
        else:
            print(format_clinical_audit_markdown(audit))
        return

    # If recent count specified
    count = args.recent if args.recent > 0 else 1
    query = client.table("nudge_alerts").select("id, patient_id, nudge_title, risk_level, created_at").order("created_at", desc=True)
    if args.patient:
        query = query.eq("patient_id", args.patient)
    res = query.limit(count).execute()

    if not res.data:
        print("No nudge alerts found to audit.")
        return

    for idx, row in enumerate(res.data, 1):
        nudge_id = row["id"]
        print(f"\n{'=' * 75}")
        print(f"CLINICAL AUDIT #{idx} OF {len(res.data)}: Nudge ID {nudge_id}")
        print(f"{'=' * 75}")
        try:
            audit = audit_nudge_alert(nudge_id, client)
            if args.json:
                print(json.dumps(audit, indent=2, default=str))
            else:
                print(format_clinical_audit_markdown(audit))
        except Exception as e:
            print(f"Error auditing nudge {nudge_id}: {e}")


if __name__ == "__main__":
    main()
