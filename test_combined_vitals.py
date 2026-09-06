import asyncio
import json
from app.services.ml_pipeline import run_univariate_anomaly_detector, run_multivariate_anomaly_detector

# 1. Generate 60 days of combined daily telemetry records
# Baseline (Days 1-55): healthy metrics
# Anomaly (Day 60): RHR = 88 bpm (high), Systolic BP = 154 (high), Steps = 200 (low), Sleep = 320 mins (low)
def generate_combined_vitals_dataset():
    historical_daily = []
    
    # Days 1 to 55: Normal Baseline Profiles
    for day in range(1, 56):
        record = {
            "avg_heart_rate": 68.0 + (day % 3),
            "bp_systolic": 122.0 + (day % 4),
            "bp_diastolic": 78.0 + (day % 2),
            "total_steps": 1600.0 + (day * 10 % 300),
            "sleep_hours": 7.2
        }
        historical_daily.append(record)
        
    # Day 60: Single daily ingestion payload containing a correlation outlier
    new_daily = [{
        "avg_heart_rate": 88.0,
        "bp_systolic": 154.0,
        "bp_diastolic": 98.0,
        "total_steps": 200.0,
        "sleep_hours": 5.3
    }]
    
    return historical_daily, new_daily

async def main():
    print("Generating 60-day combined vitals datasets...")
    history, active_day = generate_combined_vitals_dataset()
    
    print(f"-> Historical database size: {len(history)} daily profiles")
    print(f"-> Active day payload: {active_day[0]}")
    
    print("\n--- [TEST 1] Parallel Univariate (1D) Outlier Test ---")
    # Test Heart Rate independently
    history_hr = [r["avg_heart_rate"] for r in history]
    active_hr = [r["avg_heart_rate"] for r in active_day]
    hr_result = run_univariate_anomaly_detector(active_hr, history_hr)
    print(f"Heart Rate Outlier Check: {json.dumps(hr_result, indent=2)}")
    
    # Test Blood Pressure independently
    history_bp = [r["bp_systolic"] for r in history]
    active_bp = [r["bp_systolic"] for r in active_day]
    bp_result = run_univariate_anomaly_detector(active_bp, history_bp)
    print(f"Blood Pressure (Systolic) Outlier Check: {json.dumps(bp_result, indent=2)}")

    print("\n--- [TEST 2] Combined Multivariate (5D) Outlier Test ---")
    # Feed multiple variables to evaluate complex correlation anomalies
    features = ["avg_heart_rate", "bp_systolic", "bp_diastolic", "total_steps", "sleep_hours"]
    multivariate_result = run_multivariate_anomaly_detector(
        new_daily_records=active_day,
        historical_daily_records=history,
        features_to_use=features
    )
    print(f"Combined Vitals Correlation Outlier Check: {json.dumps(multivariate_result, indent=2)}")

if __name__ == "__main__":
    asyncio.run(main())
