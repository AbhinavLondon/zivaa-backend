"""
Create patient: Mukesh Patel
=================================
Purpose: Test the system's robustness with noisy, inconsistent wearable data.

Mukesh is a 68-year-old male from Ahmedabad (West India) with Type 2 Diabetes
and Essential Hypertension. He doesn't wear his wearable consistently, resulting in:

  - 60-day window but only ~35 days of data (many gaps)
  - On days he wears it, some metrics are missing (e.g., has HR but no steps)
  - Occasional junk/outlier readings (impossible values from bad sensor contact)
  - Some stretches of 3-5 consecutive missing days (forgot the watch on a trip)
  - Sleep data is especially sparse (takes watch off at night)
  - BP data only on ~40% of days (manual cuff, forgets)
  - Glucose data only on ~30% of days (doesn't always prick)
  - SpO2 occasionally missing due to poor wrist fit
  - Some days with partial data (only steps, nothing else)

This exercises the system's:
  - Baseline calibration with sparse data
  - Graceful degradation when metrics are missing
  - Outlier robustness
  - RCV trend computation with few lab readings
  - Daily plan generation with incomplete context
"""
import os
import random
import math
from datetime import datetime, timedelta
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("ERROR: Supabase URL or Service Role Key missing.")
    exit(1)

sb = create_client(SUPABASE_URL, SUPABASE_KEY)

patient_id = "44444444-4444-4444-4444-444444444444"

# ═══════════════════════════════════════════════════════════════
# 1. UPSERT PATIENT
# ═══════════════════════════════════════════════════════════════
print(f"1. Upserting patient Mukesh Patel (ID: {patient_id})...")
patient_data = {
    "id": patient_id,
    "full_name": "Mukesh Patel",
    "gender": "male",
    "date_of_birth": "15-03-1957",   # 68 years old
    "location_city": "Ahmedabad",    # West India
}
sb.table("patients").upsert(patient_data).execute()
print("   Patient upserted.")

# ═══════════════════════════════════════════════════════════════
# 2. CLEAN EXISTING DATA
# ═══════════════════════════════════════════════════════════════
print("2. Cleaning existing data...")
for table in ["lab_results", "lab_reports", "vitals_daily", "medication_logs",
              "patient_baselines", "conditions"]:
    try:
        sb.table(table).delete().eq("patient_id", patient_id).execute()
    except Exception:
        pass  # Table may not exist
print("   Cleaned.")

# ═══════════════════════════════════════════════════════════════
# 3. INSERT CONDITIONS
# ═══════════════════════════════════════════════════════════════
print("3. Inserting conditions...")
conditions = [
    {"patient_id": patient_id, "condition_name": "Type 2 Diabetes Mellitus"},
    {"patient_id": patient_id, "condition_name": "Essential Hypertension"},
]
try:
    sb.table("conditions").insert(conditions).execute()
    print("   Conditions inserted.")
except Exception as e:
    print(f"   Conditions table may not exist: {e}")

# ═══════════════════════════════════════════════════════════════
# 4. GENERATE NOISY, SPARSE VITALS (60 days)
# ═══════════════════════════════════════════════════════════════
print("4. Generating noisy, sparse vitals data...")
random.seed(2026)  # Reproducible
base_date = datetime.now().date()

# Define which days Mukesh SKIPS entirely
# Pattern: regular gaps + a 5-day trip + random skip days
skip_days = set()

# 5-day trip (days 40-44 ago) — left watch at home
for d in range(40, 45):
    skip_days.add(d)

# 3-day illness (days 20-22) — too sick to bother
for d in range(20, 23):
    skip_days.add(d)

# Random skip days (~30% of remaining days)
for d in range(60, 0, -1):
    if d not in skip_days and random.random() < 0.30:
        skip_days.add(d)

# Mukesh's "true" baselines (what his healthy values would be)
TRUE_HR = 78        # Slightly elevated resting HR (age, HTN)
TRUE_BP_SYS = 145   # Uncontrolled hypertension
TRUE_BP_DIA = 88
TRUE_STEPS = 3200   # Low activity elderly
TRUE_SLEEP = 6.0    # Poor sleeper
TRUE_GLUCOSE = 148  # Poorly controlled diabetes
TRUE_SPO2 = 95.5
TRUE_TEMP = 36.6
TRUE_WEIGHT = 82.0

vitals_rows = []

for days_ago in range(60, 0, -1):
    if days_ago in skip_days:
        continue  # No data this day

    record_date = (base_date - timedelta(days=days_ago)).isoformat()
    row = {
        "patient_id": patient_id,
        "date": record_date,
    }

    # ── Heart Rate: available ~80% of wearing days ──
    if random.random() < 0.80:
        hr = random.gauss(TRUE_HR, 6)
        # 5% chance of junk reading (bad sensor contact → impossible value)
        if random.random() < 0.05:
            hr = random.choice([32, 180, 210, 15, 250])  # Garbage values
        row["avg_heart_rate"] = round(hr, 1)

    # ── Blood Pressure: only ~40% of days (manual cuff) ──
    if random.random() < 0.40:
        sys = random.gauss(TRUE_BP_SYS, 10)
        dia = random.gauss(TRUE_BP_DIA, 6)
        # 3% chance of impossible BP (cuff error)
        if random.random() < 0.03:
            sys = random.choice([250, 60, 300])
            dia = random.choice([140, 30, 180])
        row["bp_systolic"] = round(sys, 1)
        row["bp_diastolic"] = round(dia, 1)

    # ── Steps: available ~70% (sometimes forgets to put watch on) ──
    if random.random() < 0.70:
        steps = int(random.gauss(TRUE_STEPS, 1200))
        if steps < 0:
            steps = 0
        # Some days barely moves (TV day)
        if random.random() < 0.10:
            steps = random.randint(50, 300)
        row["total_steps"] = steps

    # ── Sleep: very sparse ~35% (takes watch off at night) ──
    if random.random() < 0.35:
        sleep = random.gauss(TRUE_SLEEP, 1.2)
        if sleep < 2.0:
            sleep = 2.0
        if sleep > 12.0:
            sleep = 12.0
        row["sleep_hours"] = round(sleep, 1)
        # Sleep quality only if sleep hours is recorded
        row["sleep_quality_score"] = max(30, min(100, int(random.gauss(60, 15))))

    # ── Blood Glucose: only ~30% (doesn't prick daily) ──
    if random.random() < 0.30:
        bg = random.gauss(TRUE_GLUCOSE, 25)
        if bg < 50:
            bg = 50
        # Post-meal spike days
        if random.random() < 0.15:
            bg = random.gauss(220, 30)
        row["blood_glucose_avg"] = round(bg, 1)

    # ── SpO2: available ~60% (poor wrist fit) ──
    if random.random() < 0.60:
        spo2 = random.gauss(TRUE_SPO2, 1.5)
        # 5% chance of bad reading
        if random.random() < 0.05:
            spo2 = random.choice([80, 75, 100, 65])
        spo2 = max(70, min(100, spo2))
        row["oxygen_sat_avg"] = round(spo2, 1)

    # ── Body Temp: available ~50% ──
    if random.random() < 0.50:
        temp = random.gauss(TRUE_TEMP, 0.3)
        row["body_temp_avg"] = round(temp, 1)

    # ── Weight: measured only ~15% of days (bathroom scale) ──
    if random.random() < 0.15:
        weight = random.gauss(TRUE_WEIGHT, 0.5)
        row["weight_kg"] = round(weight, 1)

    # ── Mood: only records ~20% of days ──
    if random.random() < 0.20:
        row["mood_score"] = random.choice([2, 3, 3, 3, 4])

    # Some days are "ghost days" — watch was on but
    # only recorded steps and nothing else
    non_date_fields = [k for k in row if k not in ("patient_id", "date")]
    if len(non_date_fields) == 0:
        # If nothing was recorded, add at least steps (watch was technically on)
        row["total_steps"] = random.randint(100, 800)

    vitals_rows.append(row)

# Count data completeness stats
total_days = 60
recorded_days = len(vitals_rows)
days_with_hr = sum(1 for r in vitals_rows if "avg_heart_rate" in r)
days_with_bp = sum(1 for r in vitals_rows if "bp_systolic" in r)
days_with_steps = sum(1 for r in vitals_rows if "total_steps" in r)
days_with_sleep = sum(1 for r in vitals_rows if "sleep_hours" in r)
days_with_glucose = sum(1 for r in vitals_rows if "blood_glucose_avg" in r)
days_with_spo2 = sum(1 for r in vitals_rows if "oxygen_sat_avg" in r)

print(f"   Data completeness over {total_days} days:")
print(f"     Days with ANY data:   {recorded_days}/{total_days} ({100*recorded_days/total_days:.0f}%)")
print(f"     Heart Rate:           {days_with_hr}/{total_days} ({100*days_with_hr/total_days:.0f}%)")
print(f"     Blood Pressure:       {days_with_bp}/{total_days} ({100*days_with_bp/total_days:.0f}%)")
print(f"     Steps:                {days_with_steps}/{total_days} ({100*days_with_steps/total_days:.0f}%)")
print(f"     Sleep:                {days_with_sleep}/{total_days} ({100*days_with_sleep/total_days:.0f}%)")
print(f"     Blood Glucose:        {days_with_glucose}/{total_days} ({100*days_with_glucose/total_days:.0f}%)")
print(f"     SpO2:                 {days_with_spo2}/{total_days} ({100*days_with_spo2/total_days:.0f}%)")

# Insert in chunks
for j in range(0, len(vitals_rows), 10):
    chunk = vitals_rows[j:j+10]
    sb.table("vitals_daily").insert(chunk).execute()
print(f"   Inserted {len(vitals_rows)} vitals rows.")

# ═══════════════════════════════════════════════════════════════
# 5. INSERT SPARSE LAB REPORTS (only 2, months apart)
#    Mukesh only goes to the lab when his doctor insists
# ═══════════════════════════════════════════════════════════════
print("5. Inserting sparse lab reports...")

lab_results = []

# Insert parent lab_reports first (FK constraint)
report_1_id = "44444444-4444-4444-4444-888888888801"
report_2_id = "44444444-4444-4444-4444-888888888802"
report_1_date = (base_date - timedelta(days=120)).isoformat()
report_2_date = (base_date - timedelta(days=21)).isoformat()

lab_reports = [
    {
        "id": report_1_id,
        "patient_id": patient_id,
        "report_name": "Basic Health Panel",
        "lab_name": "SRL Diagnostics",
        "ordered_date": report_1_date,
        "status": "completed",
    },
    {
        "id": report_2_id,
        "patient_id": patient_id,
        "report_name": "Comprehensive Blood Work",
        "lab_name": "Thyrocare",
        "ordered_date": report_2_date,
        "status": "completed",
    },
]
sb.table("lab_reports").upsert(lab_reports).execute()
print("   Lab reports (parent) inserted.")
report_1_labs = [
    ("HBA1C", "HbA1c", 7.2, "%", 4.0, 5.6, "high"),
    ("FBS", "Fasting Blood Sugar", 152, "mg/dL", 70, 100, "high"),
    ("CREATININE", "Creatinine", 1.1, "mg/dL", 0.7, 1.3, "normal"),
    # eGFR was NOT ordered — doctor forgot
    ("HEMOGLOBIN", "Hemoglobin", 13.5, "g/dL", 13.0, 17.0, "normal"),
    ("LDL", "LDL Cholesterol", 145, "mg/dL", 0, 100, "high"),
    # TSH was NOT ordered
    # HDL was NOT ordered
]

for code, name, value, unit, ref_low, ref_high, flag in report_1_labs:
    lab_results.append({
        "patient_id": patient_id,
        "report_id": report_1_id,
        "biomarker_code": code,
        "biomarker_name": name,
        "value": value,
        "unit": unit,
        "reference_low": ref_low,
        "reference_high": ref_high,
        "flag": flag,
        "measured_at": report_1_date,
    })

# Report 2: 3 weeks ago — more complete, some new tests
report_2_labs = [
    ("HBA1C", "HbA1c", 7.8, "%", 4.0, 5.6, "high"),         # Worsened
    ("FBS", "Fasting Blood Sugar", 168, "mg/dL", 70, 100, "high"),  # Worsened
    ("CREATININE", "Creatinine", 1.3, "mg/dL", 0.7, 1.3, "normal"),  # Borderline
    ("EGFR", "eGFR", 58, "mL/min", 90, 120, "low"),          # New — CKD Stage 3a!
    ("HEMOGLOBIN", "Hemoglobin", 12.1, "g/dL", 13.0, 17.0, "low"),  # Dropped
    ("LDL", "LDL Cholesterol", 158, "mg/dL", 0, 100, "high"),  # Worsened
    ("TSH", "TSH", 3.8, "mIU/L", 0.4, 4.5, "normal"),          # Normal
    ("CRP", "C-Reactive Protein", 4.2, "mg/L", 0, 3.0, "high"),  # New — inflamed
    # HDL still not ordered
    # Vitamin D not ordered
]

for code, name, value, unit, ref_low, ref_high, flag in report_2_labs:
    lab_results.append({
        "patient_id": patient_id,
        "report_id": report_2_id,
        "biomarker_code": code,
        "biomarker_name": name,
        "value": value,
        "unit": unit,
        "reference_low": ref_low,
        "reference_high": ref_high,
        "flag": flag,
        "measured_at": report_2_date,
    })

sb.table("lab_results").insert(lab_results).execute()
print(f"   Inserted {len(lab_results)} lab results (2 reports).")

# ═══════════════════════════════════════════════════════════════
# 6. INSERT MEDICATIONS + LOGS (very inconsistent adherence)
# ═══════════════════════════════════════════════════════════════
print("6. Inserting medications and logs (poor adherence)...")

# First, clean existing medications for this patient
try:
    sb.table("medications").delete().eq("patient_id", patient_id).execute()
except Exception:
    pass

# Insert medications (parent table)
metformin_id = "44444444-4444-4444-4444-aaaaaaaaaaaa"
amlodipine_id = "44444444-4444-4444-4444-bbbbbbbbbbbb"

medications = [
    {
        "id": metformin_id,
        "patient_id": patient_id,
        "medication_name": "Metformin 500mg",
        "dosage": "500mg",
        "form": "tablet",
        "frequency": "twice_daily",
        "time_slots": [{"time": "08:00"}, {"time": "20:00"}],
        "timing_instruction": "after_food",
        "start_date": (base_date - timedelta(days=180)).isoformat(),
        "is_active": True,
    },
    {
        "id": amlodipine_id,
        "patient_id": patient_id,
        "medication_name": "Amlodipine 5mg",
        "dosage": "5mg",
        "form": "tablet",
        "frequency": "once_daily",
        "time_slots": [{"time": "08:00"}],
        "timing_instruction": "before_food",
        "start_date": (base_date - timedelta(days=180)).isoformat(),
        "is_active": True,
    },
]
sb.table("medications").upsert(medications).execute()
print("   Medications inserted.")

# Insert medication logs with FK reference
med_logs = []
for days_ago in range(14, 0, -1):
    med_date = base_date - timedelta(days=days_ago)
    # Metformin — twice daily, forgets ~40%
    for hour in [8, 20]:
        scheduled = datetime(med_date.year, med_date.month, med_date.day, hour, 0)
        if random.random() < 0.60:
            status = "taken"
        else:
            status = random.choice(["missed", "missed", "skipped"])
        log = {
            "patient_id": patient_id,
            "medication_id": metformin_id,
            "scheduled_at": scheduled.isoformat(),
            "status": status,
        }
        if status == "taken":
            # Taken 5-30 min late
            taken_time = scheduled + timedelta(minutes=random.randint(5, 30))
            log["taken_at"] = taken_time.isoformat()
        med_logs.append(log)

    # Amlodipine — once daily morning, forgets ~45%
    scheduled = datetime(med_date.year, med_date.month, med_date.day, 8, 0)
    if random.random() < 0.55:
        status = "taken"
    else:
        status = random.choice(["missed", "skipped"])
    log = {
        "patient_id": patient_id,
        "medication_id": amlodipine_id,
        "scheduled_at": scheduled.isoformat(),
        "status": status,
    }
    if status == "taken":
        taken_time = scheduled + timedelta(minutes=random.randint(5, 45))
        log["taken_at"] = taken_time.isoformat()
    med_logs.append(log)

# Insert in chunks (avoid large payloads)
for j in range(0, len(med_logs), 10):
    sb.table("medication_logs").insert(med_logs[j:j+10]).execute()

taken = sum(1 for m in med_logs if m["status"] == "taken")
total = len(med_logs)
print(f"   Inserted {total} med logs. Adherence: {100*taken/total:.0f}%")

# ═══════════════════════════════════════════════════════════════
# 7. SUMMARY
# ═══════════════════════════════════════════════════════════════
print()
print("=" * 60)
print("  MUKESH PATEL — NOISY DATA PATIENT CREATED")
print("=" * 60)
print(f"  ID:         {patient_id}")
print(f"  Age:        68 | Sex: Male | Location: Ahmedabad (West)")
print(f"  Conditions: Type 2 Diabetes, Essential Hypertension")
print(f"  Vitals:     {recorded_days}/{total_days} days with data ({len(skip_days)} days missing)")
print(f"  Lab reports: 2 (4 months ago + 3 weeks ago)")
print(f"  Med logs:   {total} entries, {100*taken/total:.0f}% adherence")
print()
print("  NOISE CHARACTERISTICS:")
print(f"    - {total_days - recorded_days} completely missing days")
print(f"    - BP recorded only {days_with_bp} days (manual cuff)")
print(f"    - Sleep only {days_with_sleep} days (watch off at night)")
print(f"    - Glucose only {days_with_glucose} days (lazy pricker)")
print(f"    - ~5% of HR/BP readings are garbage (sensor errors)")
print(f"    - 5-day gap (trip, days 40-44 ago)")
print(f"    - 3-day gap (illness, days 20-22 ago)")
print("=" * 60)
