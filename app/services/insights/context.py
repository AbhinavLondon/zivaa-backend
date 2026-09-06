import statistics
from typing import List, Dict, Any, Optional, TYPE_CHECKING, Union
from datetime import datetime, date, timedelta

if TYPE_CHECKING:
    from app.services.insights.baseline import BaselineInfo, PatientBaselineStatus

class MetricValue:
    def __init__(self, value: float, date_recorded: date):
        self.value = value
        self.date = date_recorded

class TrendResult:
    def __init__(self, start_val: float, end_val: float, days: int):
        self.start_value = start_val
        self.end_value = end_val
        self.days = days
        
    def is_increasing(self) -> bool:
        return self.end_value > self.start_value
        
    def is_decreasing(self) -> bool:
        return self.end_value < self.start_value
        
    @property
    def percent_change(self) -> float:
        if self.start_value == 0:
            return 0.0
        return ((self.end_value - self.start_value) / self.start_value) * 100

class VitalsMetric:
    def __init__(self, name: str, data: List[MetricValue], baseline_info: Optional['BaselineInfo'] = None, validity_window_days: int = 7):
        self.name = name
        # Sort data by date ascending
        self.data = sorted(data, key=lambda x: x.date)
        # Persisted baseline (from patient_baselines table)
        self._baseline_info = baseline_info
        self.validity_window_days = validity_window_days

    @property
    def has_data(self) -> bool:
        """Returns True if at least one reading exists for this metric."""
        return len(self.data) > 0

    def has_sufficient_history(self, days: int = 7) -> bool:
        """Returns True if we have at least 2 readings within the given window."""
        if len(self.data) < 2:
            return False
        cutoff = datetime.now().date() - timedelta(days=days)
        recent = [d for d in self.data if d.date >= cutoff]
        return len(recent) >= 2

    @property
    def latest(self) -> float:
        if not self.data:
            return 0.0
        return self.data[-1].value
        
    @property
    def latest_date(self) -> str:
        if not self.data:
            return ""
        return self.data[-1].date.isoformat()
        
    @property
    def is_stale(self) -> bool:
        """Returns True if the most recent reading is older than its validity window."""
        if not self.data:
            return False
        age_days = (datetime.now().date() - self.data[-1].date).days
        return age_days > self.validity_window_days

    @property
    def is_baseline_established(self) -> bool:
        """Returns True if this metric has a persisted, established baseline."""
        return self._baseline_info is not None and self._baseline_info.is_established

    @property
    def established_baseline(self) -> Optional['BaselineInfo']:
        """Returns the persisted BaselineInfo, or None if not established."""
        if self._baseline_info is not None and self._baseline_info.is_established:
            return self._baseline_info
        return None

    def baseline(self, days: int = 30) -> float:
        """Legacy rolling-mean baseline. Prefer established_baseline for rules."""
        # If we have a persisted established baseline, use it
        if self.is_baseline_established:
            return self._baseline_info.mean
        # Fallback: compute on the fly (backward compatibility)
        if not self.data:
            return 0.0
        cutoff = datetime.now().date() - timedelta(days=days)
        recent = [d.value for d in self.data if d.date >= cutoff]
        if not recent:
            recent = [d.value for d in self.data]
        return statistics.mean(recent) if recent else 0.0

    def rolling_average(self, days: int = 3) -> Optional[float]:
        """Computes a short-term moving average over the specified recent window."""
        if not self.data:
            return None
        cutoff = datetime.now().date() - timedelta(days=days)
        recent = [d.value for d in self.data if d.date > cutoff]
        if not recent:
            return None
        return statistics.mean(recent)
        
    def trend(self, days: int = 7) -> TrendResult:
        if len(self.data) < 2:
            return TrendResult(0.0, 0.0, days)
        cutoff = datetime.now().date() - timedelta(days=days)
        recent = [d for d in self.data if d.date >= cutoff]
        if len(recent) < 2:
            # Fall back to first and last available if not enough recent data
            return TrendResult(self.data[0].value, self.data[-1].value, days)
        return TrendResult(recent[0].value, recent[-1].value, days)

class VitalsContext:
    def __init__(self, vitals_dict: Dict[str, List[MetricValue]], baselines: Optional[Dict[str, 'BaselineInfo']] = None):
        self._vitals = vitals_dict
        self._baselines = baselines or {}
        
    def metric(self, name: str) -> VitalsMetric:
        baseline_info = self._baselines.get(name)
        return VitalsMetric(name, self._vitals.get(name, []), baseline_info=baseline_info)

class LabMetric:
    """
    Wraps raw lab readings for a single biomarker, optionally enriched
    with RCV-based trend data from lab_history.get_patient_lab_trends().

    Raw properties (.latest, .flag, .is_out_of_range) always work from
    the raw lab_results rows. Trend properties (.trend_direction,
    .clinical_flag, .is_worsening, etc.) come from the pre-computed
    trend analysis and gracefully return defaults when unavailable.
    """
    def __init__(
        self,
        name: str,
        data: List[Dict[str, Any]],
        trend_info: Optional[Dict[str, Any]] = None
    ):
        self.name = name
        # data contains dicts with 'value', 'measured_at', 'reference_low', 'reference_high', 'flag'
        self.data = sorted(data, key=lambda x: x.get('measured_at', ''))
        # Pre-computed trend analysis from lab_history.get_patient_lab_trends()
        self._trend = trend_info or {}
        # Validity days for this specific biomarker (fallback to 180 if unknown)
        self.validity_days = 180
        
    @property
    def is_historical(self) -> bool:
        """Returns True if the most recent lab result is older than its validity window."""
        if not self.data:
            return False
            
        latest_date_str = self.data[-1].get('measured_at')
        if not latest_date_str:
            return False
            
        try:
            # Handle ISO strings like 2021-05-29T00:00:00+00:00 or 2021-05-29
            date_part = latest_date_str[:10]
            measured_dt = datetime.strptime(date_part, "%Y-%m-%d").date()
            age_days = (datetime.now().date() - measured_dt).days
            return age_days > self.validity_days
        except Exception:
            return False

    @property
    def has_data(self) -> bool:
        """Returns True if at least one lab result exists for this biomarker."""
        return len(self.data) > 0

    def has_multiple_readings(self) -> bool:
        """Returns True if we have at least 2 readings to establish a trend."""
        return len(self.data) >= 2

    @property
    def latest(self) -> float:
        if not self.data:
            return 0.0
        return float(self.data[-1].get('value', 0.0))
        
    @property
    def latest_date(self) -> str:
        if not self.data:
            return ""
        return self.data[-1].get('measured_at', '')[:10]
        
    @property
    def flag(self) -> str:
        if not self.data:
            return "normal"
        return self.data[-1].get('flag', 'normal')
        
    def is_out_of_range(self) -> bool:
        return self.flag in ('high', 'low', 'critical')

    # ── RCV-based trend properties ───────────────────────────────────
    # These come from lab_history.get_patient_lab_trends() which uses
    # per-biomarker Reference Change Values (RCV) from the EFLM
    # Biological Variation Database to distinguish real trends from
    # biological noise.
    #
    # All properties gracefully degrade: if no trend data is available,
    # they return safe defaults that won't trigger rules.
    # ─────────────────────────────────────────────────────────────────

    @property
    def has_trend_data(self) -> bool:
        """Returns True if RCV-based trend analysis is available."""
        return bool(self._trend)

    @property
    def trend_direction(self) -> str:
        """
        RCV-filtered trend direction.

        Returns: 'rising', 'declining', 'stable', 'fluctuating',
                 or 'insufficient_data'.

        Uses EFLM Biological Variation Database RCV thresholds
        (Aarsand 2018, Ricos 1999) via a two-tier analysis:
          Tier 1: per-step consecutive comparison
          Tier 2: cumulative monotonic drift detection
        See lab_history._compute_trend_direction() for details.
        """
        return self._trend.get("trend_direction", "insufficient_data")

    @property
    def clinical_flag(self) -> str:
        """
        Combined direction + zone clinical interpretation.

        Returns: 'improving', 'worsening', 'stable', 'needs_attention',
                 or 'insufficient_data'.

        Uses a direction x zone decision matrix with separate matrices
        for standard and inverse-polarity biomarkers.
        NOTE: This is a Zivaa-designed heuristic, not from a published
        clinical decision rule.
        """
        return self._trend.get("clinical_flag", "insufficient_data")

    @property
    def is_worsening(self) -> bool:
        """Convenience: True if clinical_flag is 'worsening'."""
        return self.clinical_flag == "worsening"

    @property
    def is_improving(self) -> bool:
        """Convenience: True if clinical_flag is 'improving'."""
        return self.clinical_flag == "improving"

    @property
    def rate_alert(self) -> Optional[Dict[str, str]]:
        """
        Published guideline rate-of-change alert, if triggered.

        Returns a dict with 'label' and 'citation' when the rate of
        change exceeds a published threshold:
          - eGFR: KDIGO 2024 (decline >5 mL/min/year = rapid_progression)
          - HbA1c: ADA 2024 (rise >0.5%/6mo = therapy_review_needed)

        Returns None if no threshold is exceeded.
        """
        return self._trend.get("rate_alert")

    @property
    def has_rate_alert(self) -> bool:
        """Convenience: True if a published rate threshold was exceeded."""
        return self.rate_alert is not None

    @property
    def change_percent(self) -> float:
        """Total percentage change from first to latest reading."""
        return self._trend.get("change_percent", 0.0)

    @property
    def rate_per_month(self) -> float:
        """Absolute change per month (for rate-based clinical reasoning)."""
        return self._trend.get("rate_per_month", 0.0)

    @property
    def rcv_threshold_pct(self) -> Optional[float]:
        """
        The RCV percentage used for this biomarker (for auditability).

        Source: EFLM Biological Variation Database
        (https://biologicalvariation.eu/)
        """
        return self._trend.get("rcv_threshold_pct")

    @property
    def zone(self) -> str:
        """
        Where the latest value sits relative to the reference range.

        Returns: 'below_range', 'borderline_low', 'in_range',
                 'borderline_high', or 'above_range'.
        """
        return self._trend.get("zone", "in_range")


class LabContext:
    """
    Provides access to lab biomarker data, optionally enriched with
    RCV-based trend analysis from lab_history.get_patient_lab_trends().

    Args:
        labs_dict: Raw lab results keyed by biomarker code.
        trend_data: Optional pre-computed trend summary from
                    get_patient_lab_trends()["trend_summary"].
    """
    def __init__(
        self,
        labs_dict: Dict[str, List[Dict[str, Any]]],
        trend_data: Optional[Dict[str, Dict[str, Any]]] = None,
        validity_windows: Optional[Dict[str, int]] = None
    ):
        self._labs = labs_dict
        self._trends = trend_data or {}
        self._validity_windows = validity_windows or {}
        
    def biomarker(self, code_or_codes: Union[str, List[str]]) -> LabMetric:
        codes = [code_or_codes] if isinstance(code_or_codes, str) else code_or_codes
        
        # Try to find the first code that actually has data
        for c in codes:
            if c in self._labs and len(self._labs[c]) > 0:
                m = LabMetric(c, self._labs[c], trend_info=self._trends.get(c))
                m.validity_days = self._validity_windows.get(c, 180)
                return m
                
        # If none have data, return an empty LabMetric using the first code as the primary identifier
        primary_code = codes[0] if codes else ""
        trend_info = self._trends.get(primary_code, {})
        m = LabMetric(primary_code, [], trend_info=trend_info)
        m.validity_days = self._validity_windows.get(primary_code, 180)
        return m

    def get_synchronous_readings(self, codes: List[str], max_gap_days: int = 0) -> Optional[Dict[str, float]]:
        """
        Finds the most recent set of readings for the given biomarker codes
        where all readings were drawn within the specified timeframe.
        
        Args:
            codes: List of LOINC codes required for the clinical ratio/formula.
            max_gap_days: Maximum allowable time drift between the oldest and newest
                reading in the returned set. 0 = exact calendar day.
                
        Returns:
            A dictionary mapping code -> value if a synchronous set is found,
            or None if the patient has never had all required tests done simultaneously.
        """
        # Ensure we have data for all requested codes
        for code in codes:
            if not self.biomarker(code).has_data:
                return None
                
        # Gather all unique reading dates across all requested codes to act as potential "anchors"
        # We sort descending so we always evaluate the most recent possible synchronous set first.
        all_dates = set()
        for code in codes:
            metric = self.biomarker(code)
            for reading in metric.data:
                date_str = reading.get('measured_at')
                if date_str:
                    # Parse flexibly, taking just the YYYY-MM-DD part if it's an ISO datetime
                    try:
                        dt = date.fromisoformat(date_str[:10])
                        all_dates.add(dt)
                    except (ValueError, TypeError):
                        continue
                        
        anchor_dates = sorted(list(all_dates), reverse=True)
        
        # Test each anchor date to see if it provides a complete synchronous panel
        for anchor_date in anchor_dates:
            min_date = anchor_date - timedelta(days=max_gap_days)
            
            valid_set = {}
            for code in codes:
                metric = self.biomarker(code)
                
                # Find the most recent reading for this specific code that falls within the acceptable window
                best_reading = None
                for reading in reversed(metric.data): # reversed to evaluate newest first
                    date_str = reading.get('measured_at')
                    if date_str:
                        try:
                            rdt = date.fromisoformat(date_str[:10])
                            # It must be ON or BEFORE the anchor date, and ON or AFTER the minimum date
                            if min_date <= rdt <= anchor_date:
                                best_reading = float(reading.get('value', 0.0))
                                break # Found the most recent valid one for this code
                        except (ValueError, TypeError):
                            continue
                            
                if best_reading is not None:
                    valid_set[code] = best_reading
                else:
                    break # This code didn't have a reading in the window; skip to next anchor
                    
            if len(valid_set) == len(codes):
                # We found a complete synchronous set!
                return valid_set
                
        # If we exhausted all anchors and found no complete sets
        return None

class MedContext:
    def __init__(self, adherence_rate: Optional[float], recent_misses: int):
        self._adherence_rate = adherence_rate
        self._recent_misses = recent_misses
        
    def adherence_rate(self, days: int = 7) -> Optional[float]:
        return self._adherence_rate
        
    def missed_doses(self, days: int = 3) -> int:
        return self._recent_misses
        
    def has_recent_miss(self) -> bool:
        return self._recent_misses > 0

class EvalContext:
    def __init__(
        self, 
        patient_id: str, 
        vitals: VitalsContext, 
        labs: LabContext, 
        meds: MedContext,
        baseline_status: Optional['PatientBaselineStatus'] = None,
        patient_sex: Optional[str] = None,
        patient_age: Optional[int] = None,
        location_city: Optional[str] = None,
        blood_group: Optional[str] = None,
        patient_timezone: Optional[str] = None,
        patient_conditions: Optional[List[str]] = None,
        active_insights: Optional[List[Dict[str, Any]]] = None,
        device_battery_level: Optional[int] = None,
        device_is_charging: Optional[bool] = None,
        setup_prefs: Optional[Dict[str, Any]] = None,
        preferences: Optional[List[Dict[str, Any]]] = None,
        symptoms: Optional[List[Dict[str, Any]]] = None,
        agreed_actions: Optional[List[Dict[str, Any]]] = None,
        suggested_actions: Optional[List[Dict[str, Any]]] = None,
        active_medications: Optional[List[Dict[str, Any]]] = None,
    ):
        self.patient_id = patient_id
        self.vitals = vitals
        self.labs = labs
        self.meds = meds
        self.baseline_status = baseline_status
        self.patient_sex = patient_sex  # "male" | "female" | None
        self.patient_age = patient_age
        self.location_city = location_city
        self.blood_group = blood_group
        self.patient_timezone = patient_timezone
        self.patient_conditions = patient_conditions or []
        self.active_insights = active_insights or []
        self.device_battery_level = device_battery_level
        self.device_is_charging = device_is_charging
        self.setup_prefs = setup_prefs or {}
        self.preferences = preferences or []
        self.symptoms = symptoms or []
        self.agreed_actions = agreed_actions or []
        self.suggested_actions = suggested_actions or []
        self.active_medications = active_medications or []
    
    @property
    def is_any_baseline_established(self) -> bool:
        """Returns True if at least one metric has an established baseline."""
        if self.baseline_status is None:
            return False
        return self.baseline_status.overall_status in ("established", "partial")
    
    @property
    def calibration_message(self) -> Optional[str]:
        """Returns a user-facing message if baselines are still calibrating."""
        if self.baseline_status is None:
            return "Baseline data not available. Please ensure data is being recorded."
        if self.baseline_status.overall_status == "calibrating":
            days = self.baseline_status.max_days_until_ready
            return f"We're learning this patient's normal patterns. Full health insights will be available in approximately {days} more day{'s' if days != 1 else ''} of data."
        return None
