import os
from dotenv import load_dotenv
import psycopg2

load_dotenv("C:/Users/abhin/Downloads/Zivaa Apps/zivaa-backend/.env")

DB_URL = os.getenv("DATABASE_URL")
if not DB_URL:
    print("No DATABASE_URL found.")
    exit(1)

sql = """
ALTER TABLE fhir_observations ADD COLUMN IF NOT EXISTS value_string TEXT;
"""

try:
    conn = psycopg2.connect(DB_URL)
    conn.autocommit = True
    cursor = conn.cursor()
    cursor.execute(sql)
    print("Column value_string added successfully.")
    conn.close()
except Exception as e:
    print(f"Error: {e}")
