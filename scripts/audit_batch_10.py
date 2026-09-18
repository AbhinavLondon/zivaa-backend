"""
Audit the last 10 nudges created in Supabase.
Generates comprehensive 7-point clinical audits as Senior Geriatric Advisor.
"""

import sys
import os
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
    client = get_supabase_client()
    print("Fetching last 10 nudge_alerts from Supabase...")
    res = client.table("nudge_alerts") \
        .select("id, patient_id, nudge_title, risk_level, created_at, source") \
        .order("created_at", desc=True) \
        .limit(10) \
        .execute()

    if not res.data:
        print("No nudges found.")
        return

    print(f"Found {len(res.data)} nudges. Beginning clinical audit:\n")
    all_audits = []

    for i, r in enumerate(res.data, 1):
        nudge_id = r["id"]
        print("=" * 80)
        print(f"AUDITING NUDGE {i}/10: {nudge_id}")
        print(f"Title: {r.get('nudge_title')}")
        print(f"Created At: {r.get('created_at')}")
        print("=" * 80)
        try:
            audit = audit_nudge_alert(nudge_id, client)
            all_audits.append(audit)
            print(format_clinical_audit_markdown(audit))
            print("\n" + "#" * 80 + "\n")
        except Exception as e:
            print(f"Error auditing {nudge_id}: {e}")

    # Save all 10 audits to a consolidated JSON file
    out_path = os.path.join(os.path.dirname(__file__), "last_10_clinical_audits.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_audits, f, indent=2, default=str)
    print(f"\nSaved all 10 clinical audits to: {out_path}")

if __name__ == "__main__":
    main()
