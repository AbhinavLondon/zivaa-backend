"""Script to insert Neha into Supabase with 30 days of specific vitals and no lab reports."""
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

patient_id = "22222222-2222-2222-2222-222222222222"

print(f"1. Upserting patient Neha (ID: {patient_id})...")
patient_data = {
    "id": patient_id,
    "full_name": "Neha",
    "gender": "female",
    "date_of_birth": "24-06-1971",  # 55 years old
}

# Upsert patient
patient_resp = sb.table("patients").upsert(patient_data).execute()
print("Patient Neha upserted successfully.")

print("2. Deleting any existing vitals, logs, or labs for Neha...")
sb.table("vitals_daily").delete().eq("patient_id", patient_id).execute()
sb.table("lab_results").delete().eq("patient_id", patient_id).execute()
sb.table("medication_logs").delete().eq("patient_id", patient_id).execute()
sb.table("patient_baselines").delete().eq("patient_id", patient_id).execute()

print("3. Generating and inserting 30 days of vitals (steps, heart rate, sleep, mood) for Neha...")
vitals_rows = []
base_date = datetime.now().date()

# Seed random for repeatability
random.seed(42)

for i in range(30, 0, -1):
    record_date = base_date - timedelta(days=i)
    
    # Generate realistic metrics
    # steps: baseline ~6000, standard deviation ~500
    steps = int(random.gauss(6000, 500))
    # heart rate: resting ~68, standard deviation ~3
    hr = int(random.gauss(68, 3))
    # sleep hours: baseline ~7.5, standard deviation ~0.5
    sleep_hrs = round(random.gauss(7.5, 0.5), 1)
    # sleep quality score: baseline ~82, standard deviation ~4
    sleep_quality = int(random.gauss(82, 4))
    # sleep efficiency: baseline ~90%, standard deviation ~3%
    sleep_eff = round(random.gauss(90, 3), 1)
    # mood score: 1-5, average ~4
    mood = int(random.choice([4, 5]))
    
    # Yesterday (last logged day) has a slightly lower steps / sleep to test summary variation
    if i == 1:
        steps = 4200
        hr = 70
        sleep_hrs = 6.8
        sleep_quality = 75
        sleep_eff = 85.0
        mood = 3

    row = {
        "patient_id": patient_id,
        "date": record_date.isoformat(),
        "total_steps": steps,
        "avg_heart_rate": hr,
        "sleep_hours": sleep_hrs,
        "sleep_quality_score": sleep_quality,
        "mood_score": mood,
    }
    vitals_rows.append(row)

# Insert in chunks of 10
for j in range(0, len(vitals_rows), 10):
    chunk = vitals_rows[j:j+10]
    sb.table("vitals_daily").insert(chunk).execute()

print(f"Successfully inserted {len(vitals_rows)} days of vitals daily data.")
print("Database seed complete.")
