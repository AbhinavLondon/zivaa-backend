import os
from dotenv import load_dotenv
import psycopg2

load_dotenv()

DB_URL = os.getenv("DATABASE_URL")
if not DB_URL:
    print("No DATABASE_URL found.")
    exit(1)

sql = """
ALTER TABLE nudge_alerts 
ALTER COLUMN action_steps TYPE jsonb 
USING CASE 
    WHEN action_steps IS NULL THEN NULL 
    WHEN action_steps LIKE '{%' OR action_steps LIKE '[%' THEN action_steps::jsonb 
    ELSE to_jsonb(action_steps) 
END;
"""

try:
    conn = psycopg2.connect(DB_URL)
    conn.autocommit = True
    cursor = conn.cursor()
    cursor.execute(sql)
    print("Migration applied successfully.")
    conn.close()
except Exception as e:
    print(f"Error applying migration: {e}")
