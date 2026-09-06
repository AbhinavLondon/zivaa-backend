import os
import uuid
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# Step 1: Attempt direct PostgreSQL DDL if DATABASE_URL is available
db_url = os.getenv("DATABASE_URL")
if db_url:
    try:
        import psycopg2
        conn = psycopg2.connect(db_url)
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(open("migrations/032_add_coach_chat_session_id.sql").read())
        conn.close()
        print("SQL migration 032 applied to Postgres successfully.")
    except Exception as e:
        print(f"Direct Postgres execution note: {e}")
else:
    print("No DATABASE_URL found. Will backfill session_id via Supabase client metadata.")

# Step 2: Backfill existing rows via Supabase client
from app.services.insights.data_fetcher import supabase

try:
    # Fetch all logs ordered by patient_id and created_at
    res = supabase.table("coach_chat_logs").select("*").order("created_at", desc=False).execute()
    logs = res.data or []
    print(f"Total coach_chat_logs found: {len(logs)}")

    # Group by patient_id
    patient_logs = {}
    for log in logs:
        pid = log["patient_id"]
        patient_logs.setdefault(pid, []).append(log)

    total_updated = 0
    for pid, p_logs in patient_logs.items():
        current_session_id = None
        last_dt = None

        for log in p_logs:
            meta = log.get("metadata") or {}
            existing_session = log.get("session_id") or meta.get("session_id")
            
            created_str = log.get("created_at")
            log_dt = None
            if created_str:
                try:
                    log_dt = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
                except Exception:
                    pass

            # If message doesn't have a session_id, assign one based on 2-hour inactivity gap
            if not existing_session:
                if current_session_id is None or last_dt is None or (log_dt and (log_dt - last_dt).total_seconds() > 7200):
                    current_session_id = str(uuid.uuid4())

                # Update row
                new_meta = {**meta, "session_id": current_session_id}
                update_payload = {"metadata": new_meta}
                try:
                    # Try including session_id column
                    supabase.table("coach_chat_logs").update({**update_payload, "session_id": current_session_id}).eq("id", log["id"]).execute()
                except Exception:
                    supabase.table("coach_chat_logs").update(update_payload).eq("id", log["id"]).execute()

                total_updated += 1
            else:
                current_session_id = existing_session

            if log_dt:
                last_dt = log_dt

    print(f"Session backfill complete. Successfully assigned sessions to {total_updated} historical messages.")
except Exception as e:
    print(f"Error during session backfill: {e}")
