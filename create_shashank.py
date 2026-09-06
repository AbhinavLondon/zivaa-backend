"""Script to insert Shashank into Supabase with 15 days of specific vitals and no lab reports."""
import os
import random
from datetime import datetime, timedelta
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

# Initialize Supabase client
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("ERROR: Supabase URL or Service Role Key missing.")
    exit(1)

sb = create_client(SUPABASE_URL, SUPABASE_KEY)

patient_id = "33333333-3333-3333-3333-333333333333"

print(f"1. Upserting patient Shashank (ID: {patient_id})...")
patient_data = {
    "id": patient_id,
    "full_name": "Shashank",
    "gender": "male",
    "date_of_birth": "24-06-2001",  # 25 years old
}

# Upsert patient
patient_resp = sb.table("patients").upsert(patient_data).execute()
print("Patient Shashank upserted successfully.")

print("2. Deleting any existing vitals, logs, or labs for Shashank...")
sb.table("vitals_daily").delete().eq("patient_id", patient_id).execute()
sb.table("lab_results").delete().eq("patient_id", patient_id).execute()
sb.table("medication_logs").delete().eq("patient_id", patient_id).execute()
sb.table("patient_baselines").delete().eq("patient_id", patient_id).execute()

print("3. Generating and inserting 15 days of vitals (steps, heart rate, sleep) for Shashank...")
vitals_rows = []
base_date = datetime.now().date()

# Seed random for repeatability
random.seed(100)

for i in range(15, 0, -1):
    record_date = base_date - timedelta(days=i)
    
    # Generate healthy, active metrics
    # steps: baseline ~12000, standard deviation ~800
    steps = int(random.gauss(12000, 800))
    # heart rate: resting ~55 (athletic/healthy), standard deviation ~2
    hr = int(random.gauss(55, 2))
    # sleep hours: baseline ~8.0, standard deviation ~0.4
    sleep_hrs = round(random.gauss(8.0, 0.4), 1)
    # sleep quality score: baseline ~90, standard deviation ~3
    sleep_quality = int(random.gauss(90, 3))
    
    # Yesterday is also active and healthy
    if i == 1:
        steps = 11800
        hr = 54
        sleep_hrs = 8.2
        sleep_quality = 92

    row = {
        "patient_id": patient_id,
        "date": record_date.isoformat(),
        "total_steps": steps,
        "avg_heart_rate": hr,
        "sleep_hours": sleep_hrs,
        "sleep_quality_score": sleep_quality,
        # Mood is not requested, but let's keep it null/empty as requested (only steps, sleep, heart rate)
        "mood_score": None,
    }
    vitals_rows.append(row)

# Insert in chunks of 10
for j in range(0, len(vitals_rows), 10):
    chunk = vitals_rows[j:j+10]
    sb.table("vitals_daily").insert(chunk).execute()

print(f"Successfully inserted {len(vitals_rows)} days of vitals daily data.")
print("Database seed complete.")
