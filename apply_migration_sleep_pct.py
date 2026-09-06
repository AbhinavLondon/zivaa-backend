import os
from dotenv import load_dotenv
import psycopg2

load_dotenv()

DB_URL = os.getenv("DATABASE_URL")
if not DB_URL:
    print("No DATABASE_URL found.")
    exit(1)

with open("migrations/014_sleep_stage_percentages.sql", "r") as f:
    sql = f.read()

try:
    conn = psycopg2.connect(DB_URL)
    conn.autocommit = True
    cursor = conn.cursor()
    cursor.execute(sql)
    print("Migration applied successfully.")
    conn.close()
except Exception as e:
    print(f"Error applying migration: {e}")
