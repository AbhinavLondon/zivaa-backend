import os
from dotenv import load_dotenv
import psycopg2

load_dotenv()

DB_URL = os.getenv("DATABASE_URL")
if not DB_URL:
    print("No DATABASE_URL found in environment or .env.")
    print("You can run this migration directly in the Supabase Dashboard SQL Editor:")
    print("https://supabase.com/dashboard/project/ecwueqoxfjcepktubqrs/sql/new")
    exit(1)

with open("migrations/033_auto_create_patient_trigger_and_rls.sql", "r", encoding="utf-8") as f:
    sql = f.read()

try:
    conn = psycopg2.connect(DB_URL)
    conn.autocommit = True
    cursor = conn.cursor()
    cursor.execute(sql)
    print("Migration 033 applied successfully!")
    conn.close()
except Exception as e:
    print(f"Error applying migration 033: {e}")
