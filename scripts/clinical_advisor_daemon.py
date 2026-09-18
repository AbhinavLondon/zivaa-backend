"""
Clinical Advisor Background Daemon.
Monitors Supabase `nudge_alerts` table in real time for any newly created alerts across any patient.
Whenever a new nudge is detected, it automatically conducts a 7-point clinical audit.

Usage:
  python clinical_advisor_daemon.py               # Runs continuously (poll interval 5s)
  python clinical_advisor_daemon.py --once        # Checks for un-audited nudges once and exits
  python clinical_advisor_daemon.py --interval 10 # Custom poll interval in seconds
"""

import sys
import os
import time
import argparse
import json
from datetime import datetime, timezone

# Ensure UTF-8 output on Windows console
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(backend_dir, ".env"))

from app.services.clinical_advisor import (
    audit_nudge_alert,
    format_clinical_audit_markdown,
    get_supabase_client
)

LOG_DIR = os.path.join(backend_dir, "logs")
AUDITED_IDS_FILE = os.path.join(LOG_DIR, "audited_nudge_ids.txt")


def load_audited_ids() -> set:
    """Loads set of already audited nudge IDs."""
    os.makedirs(LOG_DIR, exist_ok=True)
    if not os.path.exists(AUDITED_IDS_FILE):
        return set()
    try:
        with open(AUDITED_IDS_FILE, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    except Exception:
        return set()


def record_audited_id(nudge_id: str):
    """Records an audited nudge ID to disk."""
    os.makedirs(LOG_DIR, exist_ok=True)
    try:
        with open(AUDITED_IDS_FILE, "a", encoding="utf-8") as f:
            f.write(f"{nudge_id}\n")
    except Exception as e:
        print(f"[Daemon] Error recording audited ID: {e}")


def check_and_audit_new_nudges(client, audited_ids: set, limit: int = 15) -> int:
    """
    Checks for any nudges in Supabase not yet present in audited_ids,
    and runs the clinical audit on each.
    """
    try:
        res = client.table("nudge_alerts") \
            .select("id, patient_id, nudge_title, risk_level, created_at") \
            .order("created_at", desc=True) \
            .limit(limit) \
            .execute()

        if not res.data:
            return 0

        # Process in chronological order (oldest un-audited first)
        un_audited = [r for r in reversed(res.data) if r["id"] not in audited_ids]
        
        for row in un_audited:
            nudge_id = row["id"]
            title = row.get("nudge_title", "Untitled Alert")
            risk = row.get("risk_level", "UNKNOWN")
            created_at = row.get("created_at", "")

            print(f"\n{'=' * 80}")
            print(f"[ClinicalAdvisor Daemon] 🔔 NEW NUDGE DETECTED")
            print(f"  Nudge ID  : {nudge_id}")
            print(f"  Title     : {title}")
            print(f"  Risk Level: {risk}")
            print(f"  Created At: {created_at}")
            print(f"{'=' * 80}\n")
            print("Conducting 7-Point Clinical Audit as Senior Geriatrician (MBBS, MD)...\n")

            try:
                audit = audit_nudge_alert(nudge_id, client)
                print(format_clinical_audit_markdown(audit))
                print(f"{'=' * 80}\n")
            except Exception as audit_err:
                print(f"[Daemon] Error auditing nudge {nudge_id}: {audit_err}")

            # Mark as audited
            audited_ids.add(nudge_id)
            record_audited_id(nudge_id)

        return len(un_audited)
    except Exception as e:
        print(f"[Daemon] Polling error: {e}")
        return 0


def run_daemon(poll_interval: int = 5, once: bool = False):
    print("=" * 80)
    print("  🩺 SENIOR GERIATRIC CLINICAL ADVISOR DAEMON (MBBS, MD — 25 Years Exp)")
    print(f"  Monitoring Supabase `nudge_alerts` table in real time...")
    print(f"  Poll interval: {poll_interval}s | Single-run mode: {once}")
    print("=" * 80)

    client = get_supabase_client()
    audited_ids = load_audited_ids()
    print(f"[Daemon] Initialized with {len(audited_ids)} previously audited alerts.")

    if once:
        count = check_and_audit_new_nudges(client, audited_ids, limit=20)
        print(f"[Daemon] Single run complete. Audited {count} new nudges.")
        return

    print("[Daemon] Listening for newly created nudge_alerts... (Press Ctrl+C to stop)\n")
    try:
        while True:
            check_and_audit_new_nudges(client, audited_ids)
            time.sleep(poll_interval)
    except KeyboardInterrupt:
        print("\n[Daemon] Shutting down Senior Clinical Advisor Daemon gracefully.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Clinical Advisor Real-Time Daemon")
    parser.add_argument("--interval", type=int, default=5, help="Poll interval in seconds (default: 5)")
    parser.add_argument("--once", action="store_true", help="Run once for un-audited alerts and exit")
    args = parser.parse_args()

    run_daemon(poll_interval=args.interval, once=args.once)
