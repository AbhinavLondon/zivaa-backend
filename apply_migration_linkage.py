import os
from dotenv import load_dotenv
import psycopg2

load_dotenv()

DB_URL = os.getenv("DATABASE_URL")
if not DB_URL:
    print("No DATABASE_URL found.")
    exit(1)

sql = """
-- 1. Add linked_symptom_id to patient_memory
ALTER TABLE patient_memory 
ADD COLUMN IF NOT EXISTS linked_symptom_id UUID REFERENCES patient_memory(id) ON DELETE CASCADE;

-- 2. Create the trigger function to cascade status updates
CREATE OR REPLACE FUNCTION cascade_symptom_status_update()
RETURNS TRIGGER AS $$
BEGIN
    -- Only act if this row is a symptom and its status has changed
    IF NEW.category = 'symptom' AND NEW.status IS DISTINCT FROM OLD.status THEN
        -- Update the status of all actions linked to this symptom
        UPDATE patient_memory
        SET status = NEW.status
        WHERE linked_symptom_id = NEW.id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 3. Attach the trigger to the table (Drop first to avoid duplicates)
DROP TRIGGER IF EXISTS trigger_cascade_symptom_status ON patient_memory;

CREATE TRIGGER trigger_cascade_symptom_status
AFTER UPDATE ON patient_memory
FOR EACH ROW
EXECUTE FUNCTION cascade_symptom_status_update();
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
