import sys
import os
# Add user-site packages to sys.path so IDE linter resolves imports
user_site = os.path.expanduser("~\\AppData\\Roaming\\Python\\Python314\\site-packages")
if user_site not in sys.path and os.path.exists(user_site):
    sys.path.insert(0, user_site)

import numpy as np
from sklearn.ensemble import IsolationForest
from typing import List, Dict, Any

def run_univariate_anomaly_detector(new_values: List[float], historical_values: List[float], sensitivity: float = -0.03) -> Dict[str, Any]:
    """
    Option B: Parallel 1D Outlier Detector.
    Fits an Isolation Forest model on a single vital metric's history to identify
    if new readings deviate from their independent historical distribution.
    """
    result = {
        "anomaly_detected": False,
        "anomaly_count": 0,
        "avg_value": sum(new_values) / len(new_values) if new_values else 0.0
    }
    
    all_values = []
    if historical_values:
        all_values.extend(historical_values)
    all_values.extend(new_values)
    
    if len(all_values) >= 10:
        X = np.array(all_values).reshape(-1, 1)
        
        # Train 1D Outlier Detector
        model = IsolationForest(contamination='auto', random_state=42)
        model.fit(X)
        
        # Check scores of new records
        scores = model.decision_function(X)
        new_scores = scores[-len(new_values):]
        
        anomalies = [score for score in new_scores if score < sensitivity]
        result["anomaly_detected"] = len(anomalies) > 0
        result["anomaly_count"] = len(anomalies)
        result["anomalous_indices"] = [i for i, score in enumerate(new_scores) if score < sensitivity]
        
    return result

def run_multivariate_anomaly_detector(
    new_daily_records: List[Dict[str, float]], 
    historical_daily_records: List[Dict[str, float]], 
    features_to_use: List[str], 
    sensitivity: float = -0.03
) -> Dict[str, Any]:
    """
    Option A: Multivariate Outlier Detector.
    Combines multiple variables (e.g. Heart Rate, Blood Pressure, Steps, Sleep) into a 
    multi-dimensional feature space. Fits a single Isolation Forest model to detect if the 
    correlation profile of the active day represents a cross-metric anomaly.
    """
    result = {
        "anomaly_detected": False,
        "anomalous_indices": []
    }
    
    # 1. Transform dictionaries to feature matrices
    all_records = []
    all_records.extend(historical_daily_records)
    all_records.extend(new_daily_records)
    
    if len(all_records) < 10:
        return result # Not enough historical data points
        
    feature_matrix = []
    for r in all_records:
        row = []
        for feat in features_to_use:
            row.append(r.get(feat, 0.0))
        feature_matrix.append(row)
        
    X = np.array(feature_matrix)
    
    # 2. Fit Multivariate Outlier Forest
    model = IsolationForest(contamination='auto', random_state=42)
    model.fit(X)
    
    # 3. Predict anomaly scores
    scores = model.decision_function(X)
    
    # Evaluate only the new daily records (at the end of the matrix)
    new_records_count = len(new_daily_records)
    new_scores = scores[-new_records_count:]
    
    flagged_indices = []
    for idx, score in enumerate(new_scores):
        if score < sensitivity:
            flagged_indices.append(idx)
            
    result["anomaly_detected"] = len(flagged_indices) > 0
    result["anomalous_indices"] = flagged_indices
    
    return result

def extract_features(new_records: List[Any], historical_heart_rates: List[float] = None) -> Dict[str, Any]:
    """
    Time-series ML Pipeline interface.
    Extracts core averages from incoming records, and triggers the Univariate (1D)
    model to maintain backward-compatibility with the default ingestion pipeline.
    """
    features = {
        "avg_heart_rate": 72.0,
        "hr_spikes": 0,
        "sleep_hours": 7.0,
        "bp_systolic": 120.0,
        "bp_diastolic": 80.0,
        "total_steps": 0.0,
        "ml_anomaly_detected": False,
        "ml_anomaly_count": 0
    }
    
    hr_values = []
    bp_sys_values = []
    bp_dia_values = []
    total_steps = 0
    sleep_minutes = 0

    for record in new_records:
        r_type = record.type.lower()
        if r_type == "heart_rate" and "bpm" in record.values:
            hr_values.append(record.values["bpm"])
        elif r_type == "blood_pressure":
            if "systolic" in record.values:
                bp_sys_values.append(record.values["systolic"])
            if "diastolic" in record.values:
                bp_dia_values.append(record.values["diastolic"])
        elif r_type == "steps" and "count" in record.values:
            total_steps += record.values["count"]
        elif r_type == "sleep" and "duration_minutes" in record.values:
            sleep_minutes += record.values["duration_minutes"]

    if hr_values:
        features["avg_heart_rate"] = sum(hr_values) / len(hr_values)
    if bp_sys_values:
        features["bp_systolic"] = sum(bp_sys_values) / len(bp_sys_values)
    if bp_dia_values:
        features["bp_diastolic"] = sum(bp_dia_values) / len(bp_dia_values)
    if total_steps > 0:
        features["total_steps"] = total_steps
    if sleep_minutes > 0:
        features["sleep_hours"] = sleep_minutes / 60.0

    # Trigger Univariate Anomaly detection on heart rate for backward compatibility
    if hr_values:
        hr_result = run_univariate_anomaly_detector(hr_values, historical_heart_rates)
        features["ml_anomaly_detected"] = hr_result["anomaly_detected"]
        features["ml_anomaly_count"] = hr_result["anomaly_count"]
        features["hr_spikes"] = hr_result["anomaly_count"]

    return features
