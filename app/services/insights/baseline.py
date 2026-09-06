"""
Baseline Establishment Service

Manages per-patient, per-metric baselines with a lifecycle:
  CALIBRATING → ESTABLISHED → (RECALIBRATING if data gap detected)

Design decisions:
- First-time patients need 5 days minimum of data (per user requirement)
- After initial establishment, per-metric clinical thresholds apply
- Today's readings are excluded from baseline computation to prevent contamination
- Baselines are lazily refreshed if >24 hours stale
- A data gap of >14 days resets the baseline to CALIBRATING
"""

import statistics
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

from app.config import settings


# ---------------------------------------------------------------------------
# Per-metric calibration thresholds (clinically informed)
# ---------------------------------------------------------------------------
# "min_days" = minimum distinct data-points (days) required to establish.
# Initial onboarding uses 5 for all; after first establishment these
# clinical thresholds take over on subsequent recalibrations.

METRIC_THRESHOLDS: Dict[str, Dict[str, Any]] = {
    # Core vitals — relatively stable day-to-day
    "avg_heart_rate":   {"min_days": 5, "window_days": 30, "label": "Average Heart Rate"},
    "hr_avg_morning":   {"min_days": 5, "window_days": 30, "label": "Morning Heart Rate"},
    "hr_avg_afternoon": {"min_days": 5, "window_days": 30, "label": "Afternoon Heart Rate"},
    "hr_avg_evening":   {"min_days": 5, "window_days": 30, "label": "Evening Heart Rate"},
    "hr_avg_night":     {"min_days": 5, "window_days": 30, "label": "Night Heart Rate"},
    "bp_systolic":  {"min_days": 5, "window_days": 30, "label": "Systolic Blood Pressure"},
    "bp_diastolic": {"min_days": 5, "window_days": 30, "label": "Diastolic Blood Pressure"},
    
    # Activity/behavioural — higher variability (weekend vs weekday)
    "steps":        {"min_days": 7, "window_days": 30, "label": "Daily Step Count"},
    "sleep_hours":  {"min_days": 7, "window_days": 30, "label": "Sleep Duration"},
    
    # Sensor-dependent — physiologically stable
    "oxygen_sat":   {"min_days": 3, "window_days": 30, "label": "Oxygen Saturation"},
    "body_temp":    {"min_days": 3, "window_days": 30, "label": "Body Temperature"},
    "skin_temp_delta": {"min_days": 3, "window_days": 30, "label": "Skin Temperature Delta"},
    
    # Metabolic — needs enough readings to see variance
    "blood_glucose": {"min_days": 5, "window_days": 30, "label": "Blood Glucose"},
    
    # Weight — changes slowly
    "weight":       {"min_days": 5, "window_days": 30, "label": "Body Weight"},
    
    # Mental health / self-reported — need a full week for pattern
    "mood_score":     {"min_days": 7, "window_days": 30, "label": "Mood Score"},
    "sleep_quality":  {"min_days": 7, "window_days": 30, "label": "Sleep Quality"},
    
    # New metrics from Health Connect (Build Now — Jun 2026)
    "respiratory_rate":   {"min_days": 3, "window_days": 30, "label": "Respiratory Rate"},
    "resting_heart_rate": {"min_days": 5, "window_days": 30, "label": "Resting Heart Rate"},
    "exercise_minutes":   {"min_days": 7, "window_days": 30, "label": "Exercise Minutes"},
    "heart_rate_recovery": {"min_days": 5, "window_days": 30, "label": "Heart Rate Recovery"},

    # Validated screening instruments — less frequent, longer windows
    # PHQ-2 is administered biweekly: need ≥3 readings (6+ weeks) for baseline
    "phq2_score":     {"min_days": 3, "window_days": 90, "label": "PHQ-2 Depression Screen"},
    # PSQI Item 6 is administered weekly: need ≥3 readings (3+ weeks)
    "psqi_item6":     {"min_days": 3, "window_days": 60, "label": "PSQI Sleep Quality"},
    # Wearable-derived sleep efficiency — daily, like other sleep metrics
    "sleep_efficiency": {"min_days": 7, "window_days": 30, "label": "Sleep Efficiency"},
}

# Default for any metric not listed above
DEFAULT_THRESHOLD = {"min_days": 5, "window_days": 30, "label": "Unknown Metric"}

# How many days of no data before we reset to CALIBRATING
DATA_GAP_RESET_DAYS = 14

# Baselines are considered stale after this many hours
STALE_AFTER_HOURS = 24


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class BaselineInfo:
    """Holds computed baseline statistics for a single metric."""
    metric_name: str
    status: str  # "calibrating" | "established"
    mean: float
    std: float
    median: float
    data_points: int
    min_required: int
    last_refreshed: Optional[datetime] = None
    established_at: Optional[datetime] = None
    
    @property
    def is_established(self) -> bool:
        return self.status == "established"
    
    @property
    def days_until_ready(self) -> int:
        """How many more days of data are needed."""
        if self.is_established:
            return 0
        return max(0, self.min_required - self.data_points)
    
    def to_dict(self) -> Dict[str, Any]:
        result = {
            "status": self.status,
            "data_points": self.data_points,
            "min_required": self.min_required,
        }
        if self.is_established:
            result["baseline_mean"] = round(self.mean, 2)
            result["baseline_std"] = round(self.std, 2)
            result["baseline_median"] = round(self.median, 2)
        else:
            result["days_until_ready"] = self.days_until_ready
        return result


@dataclass
class PatientBaselineStatus:
    """Overall baseline status for a patient across all metrics."""
    patient_id: str
    baselines: Dict[str, BaselineInfo]
    
    @property
    def overall_status(self) -> str:
        """Returns 'established' only if at least one metric is established."""
        if not self.baselines:
            return "calibrating"
        if any(b.is_established for b in self.baselines.values()):
            return "partial" if any(not b.is_established for b in self.baselines.values()) else "established"
        return "calibrating"
    
    @property
    def max_days_until_ready(self) -> int:
        """Maximum days across all calibrating metrics."""
        if not self.baselines:
            return 5  # Default first-time
        return max((b.days_until_ready for b in self.baselines.values()), default=0)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "patient_id": self.patient_id,
            "overall_status": self.overall_status,
            "days_until_ready": self.max_days_until_ready,
            "metrics": {
                name: info.to_dict() for name, info in self.baselines.items()
            }
        }


# ---------------------------------------------------------------------------
# Core computation logic (pure functions — no DB dependency)
# ---------------------------------------------------------------------------

def compute_baseline_stats(
    values: List[float],
    metric_name: str,
    is_first_establishment: bool = True
) -> BaselineInfo:
    """
    Compute baseline statistics from a list of daily values.
    
    Args:
        values: List of metric values (one per day), excluding today.
        metric_name: The metric identifier (e.g. "heart_rate").
        is_first_establishment: If True, uses 5-day minimum for all metrics
                                (first-time onboarding). If False, uses 
                                per-metric clinical thresholds.
    
    Returns:
        BaselineInfo with status set to "calibrating" or "established".
    """
    threshold = METRIC_THRESHOLDS.get(metric_name, DEFAULT_THRESHOLD)
    
    # First-time onboarding: 5 days for everything
    # After that: use clinical per-metric thresholds
    min_required = 5 if is_first_establishment else threshold["min_days"]
    
    data_points = len(values)
    
    if data_points < min_required:
        return BaselineInfo(
            metric_name=metric_name,
            status="calibrating",
            mean=0.0,
            std=0.0,
            median=0.0,
            data_points=data_points,
            min_required=min_required,
        )
    
    mean_val = statistics.mean(values)
    std_val = statistics.stdev(values) if len(values) >= 2 else 0.0
    median_val = statistics.median(values)
    
    return BaselineInfo(
        metric_name=metric_name,
        status="established",
        mean=mean_val,
        std=std_val,
        median=median_val,
        data_points=data_points,
        min_required=min_required,
        established_at=datetime.utcnow(),
        last_refreshed=datetime.utcnow(),
    )


def should_recalibrate(last_data_date: Optional[date]) -> bool:
    """Check if the patient has a data gap that requires recalibration."""
    if last_data_date is None:
        return True
    days_since = (datetime.now().date() - last_data_date).days
    return days_since > DATA_GAP_RESET_DAYS


def is_stale(last_refreshed: Optional[datetime]) -> bool:
    """Check if the baseline needs a refresh (>24 hours old)."""
    if last_refreshed is None:
        return True
    hours_since = (datetime.utcnow() - last_refreshed).total_seconds() / 3600
    return hours_since > STALE_AFTER_HOURS


# ---------------------------------------------------------------------------
# Database operations (Supabase)
# ---------------------------------------------------------------------------

def _get_supabase_client():
    """Lazy import to avoid circular dependencies."""
    from supabase import create_client
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)


def fetch_stored_baselines(patient_id: str) -> Dict[str, Dict[str, Any]]:
    """
    Fetch all stored baselines for a patient from the patient_baselines table.
    Returns a dict keyed by metric_name.
    """
    supabase = _get_supabase_client()
    resp = supabase.table("patient_baselines") \
        .select("*") \
        .eq("patient_id", patient_id) \
        .execute()
    
    return {row["metric_name"]: row for row in resp.data}


def upsert_baseline(patient_id: str, info: BaselineInfo, last_data_date: Optional[date] = None) -> None:
    """
    Insert or update a baseline record in Supabase.
    Uses the UNIQUE (patient_id, metric_name) constraint for upsert.
    """
    supabase = _get_supabase_client()
    
    row = {
        "patient_id": patient_id,
        "metric_name": info.metric_name,
        "status": info.status,
        "baseline_mean": round(info.mean, 4) if info.is_established else None,
        "baseline_std": round(info.std, 4) if info.is_established else None,
        "baseline_median": round(info.median, 4) if info.is_established else None,
        "data_points_used": info.data_points,
        "last_refreshed_at": datetime.utcnow().isoformat(),
        "last_data_date": last_data_date.isoformat() if last_data_date else None,
        "updated_at": datetime.utcnow().isoformat(),
    }
    
    if info.is_established and info.established_at:
        row["established_at"] = info.established_at.isoformat()
    
    supabase.table("patient_baselines") \
        .upsert(row, on_conflict="patient_id,metric_name") \
        .execute()


# ---------------------------------------------------------------------------
# High-level orchestration
# ---------------------------------------------------------------------------

def get_or_refresh_baselines(
    patient_id: str,
    vitals_data: Dict[str, list],
    today: Optional[date] = None,
) -> PatientBaselineStatus:
    """
    Main entry point. For each metric the patient has data for:
    1. Check if a stored baseline exists and is fresh
    2. If stale or missing, recompute from vitals_data (excluding today)
    3. Check for data gaps that require recalibration
    4. Persist updated baselines to Supabase
    
    Args:
        patient_id: The patient's UUID.
        vitals_data: Dict of metric_name → List[MetricValue] from the data fetcher.
                     Each MetricValue has .value and .date attributes.
        today: Override for testing. Defaults to datetime.now().date().
    
    Returns:
        PatientBaselineStatus with all metric baselines.
    """
    if today is None:
        today = datetime.now().date()
    
    # 1. Fetch stored baselines
    stored = fetch_stored_baselines(patient_id)
    
    baselines: Dict[str, BaselineInfo] = {}
    
    for metric_name, metric_values in vitals_data.items():
        stored_row = stored.get(metric_name)
        
        # Check if we need to recompute
        needs_recompute = False
        is_first = True
        
        if stored_row is None:
            needs_recompute = True
        else:
            is_first = stored_row.get("established_at") is None
            
            # Check for data gap → recalibrate
            last_data = stored_row.get("last_data_date")
            if last_data:
                last_data_parsed = datetime.strptime(last_data, "%Y-%m-%d").date() if isinstance(last_data, str) else last_data
                if should_recalibrate(last_data_parsed):
                    needs_recompute = True
                    is_first = True  # Reset to first-time thresholds
            
            # Check staleness
            last_refreshed = stored_row.get("last_refreshed_at")
            if last_refreshed:
                if isinstance(last_refreshed, str):
                    last_refreshed = datetime.fromisoformat(last_refreshed.replace("Z", "+00:00")).replace(tzinfo=None)
                if is_stale(last_refreshed):
                    needs_recompute = True
        
        if needs_recompute:
            # Get the threshold config for the window
            threshold = METRIC_THRESHOLDS.get(metric_name, DEFAULT_THRESHOLD)
            window_days = threshold["window_days"]
            cutoff = today - timedelta(days=window_days)
            
            # Filter to window and EXCLUDE today
            window_values = [
                mv.value for mv in metric_values
                if cutoff <= mv.date < today  # Strictly before today
            ]
            
            # Compute
            info = compute_baseline_stats(window_values, metric_name, is_first_establishment=is_first)
            
            # Determine last data date
            all_dates = [mv.date for mv in metric_values]
            last_data_date = max(all_dates) if all_dates else None
            
            # Set calibration start
            if stored_row and stored_row.get("calibration_start"):
                cal_start = stored_row["calibration_start"]
            else:
                cal_start = min(all_dates).isoformat() if all_dates else today.isoformat()
            
            # If transitioning from calibrating → established, preserve established_at
            if info.is_established and stored_row and stored_row.get("established_at"):
                info.established_at = datetime.fromisoformat(
                    stored_row["established_at"].replace("Z", "+00:00")
                ).replace(tzinfo=None)
            
            # Persist
            try:
                upsert_baseline(patient_id, info, last_data_date)
            except Exception as e:
                print(f"Warning: Failed to persist baseline for {metric_name}: {e}")
            
            baselines[metric_name] = info
        else:
            # Use stored values
            baselines[metric_name] = BaselineInfo(
                metric_name=metric_name,
                status=stored_row["status"],
                mean=stored_row.get("baseline_mean", 0.0) or 0.0,
                std=stored_row.get("baseline_std", 0.0) or 0.0,
                median=stored_row.get("baseline_median", 0.0) or 0.0,
                data_points=stored_row.get("data_points_used", 0),
                min_required=METRIC_THRESHOLDS.get(metric_name, DEFAULT_THRESHOLD)["min_days"],
                established_at=stored_row.get("established_at"),
                last_refreshed=stored_row.get("last_refreshed_at"),
            )
    
    return PatientBaselineStatus(patient_id=patient_id, baselines=baselines)
