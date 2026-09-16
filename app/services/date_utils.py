import zoneinfo
from datetime import datetime, timezone
from typing import Optional


def get_local_date_str(patient_tz: Optional[str] = None) -> str:
    """
    Returns the ISO-formatted date string (YYYY-MM-DD) for current moment
    in the patient's local timezone (or UTC if unspecified/invalid).
    """
    try:
        tz = zoneinfo.ZoneInfo(patient_tz) if patient_tz else zoneinfo.ZoneInfo("UTC")
    except Exception:
        tz = zoneinfo.ZoneInfo("UTC")
    return datetime.now(timezone.utc).astimezone(tz).date().isoformat()
