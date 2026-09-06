import os
from dotenv import load_dotenv
import psycopg2

load_dotenv()

DB_URL = os.getenv("DATABASE_URL")
if not DB_URL:
    print("No DATABASE_URL found.")
    exit(1)

sql = """
CREATE TABLE IF NOT EXISTS fhir_diagnostic_reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id UUID NOT NULL,
    status TEXT NOT NULL DEFAULT 'final',
    effective_datetime TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    performer TEXT,
    resource JSONB NOT NULL,
    summary_explanation TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS fhir_observations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id UUID NOT NULL,
    report_id UUID REFERENCES fhir_diagnostic_reports(id) ON DELETE CASCADE,
    loinc_code TEXT NOT NULL,
    value_numeric NUMERIC,
    unit TEXT,
    reference_low NUMERIC,
    reference_high NUMERIC,
    resource JSONB NOT NULL,
    patient_explanation TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS condition_targets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id UUID NOT NULL,
    condition TEXT NOT NULL,
    loinc_code TEXT NOT NULL,
    target_low NUMERIC,
    target_high NUMERIC,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS critical_values (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    loinc_code TEXT NOT NULL UNIQUE,
    critical_low NUMERIC,
    critical_high NUMERIC,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
"""

try:
    conn = psycopg2.connect(DB_URL)
    conn.autocommit = True
    cursor = conn.cursor()
    cursor.execute(sql)
    print("Migration 16 applied successfully.")
    conn.close()
except Exception as e:
    print(f"Error applying migration: {e}")
