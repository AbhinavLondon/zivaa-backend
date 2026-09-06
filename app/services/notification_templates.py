from enum import Enum
from typing import Dict, Any, Optional
from app.services.firebase_service import send_push_notification

class NotificationType(Enum):
    MORNING_BRIEFING = "morning_briefing"
    DAILY_PLAN = "daily_plan"
    MIDDAY_CHECKIN = "midday_checkin"
    EVENING_CHECKIN = "evening_checkin"
    CAREGIVER_NUDGE = "caregiver_nudge"
    LAB_REPORT_READY = "lab_report_ready"
    COACH_MESSAGE = "coach_message"
    SYMPTOM_CHECKIN = "symptom_checkin"

def dispatch_notification(
    fcm_token: str, 
    notification_type: NotificationType, 
    patient_name: str = "Patient",
    dynamic_body: str = "",
    dynamic_title: str = "",
    extra_data: Optional[Dict[str, Any]] = None
):
    """
    Centralized dispatcher for push notifications to ensure consistent formatting and easy maintenance.
    """
    title = ""
    body = ""
    data = {"type": notification_type.value}
    if extra_data:
        import json
        for k, v in extra_data.items():
            if isinstance(v, (dict, list)):
                data[k] = json.dumps(v)
            else:
                data[k] = str(v)

    if notification_type == NotificationType.MORNING_BRIEFING:
        title = "Morning Briefing Ready \u2600\ufe0f"
        body_content = dynamic_body if len(dynamic_body) <= 100 else dynamic_body[:97] + "..."
        body = f"Here is how you are doing today: {body_content}"
    elif notification_type == NotificationType.DAILY_PLAN:
        title = "Daily Plan Ready \ud83d\udccb"
        body = f"Here is what's planned for you today: {dynamic_body}"
    elif notification_type == NotificationType.MIDDAY_CHECKIN:
        title = "Midday Check-in 🌞"
        body = dynamic_body if len(dynamic_body) <= 250 else dynamic_body[:247] + "..."
    elif notification_type == NotificationType.EVENING_CHECKIN:
        title = "Evening Wind-down 🌙"
        body = dynamic_body if len(dynamic_body) <= 250 else dynamic_body[:247] + "..."
    elif notification_type == NotificationType.CAREGIVER_NUDGE:
        title = dynamic_title or "New Health Insight"
        body = dynamic_body or "Tap to view details."
    elif notification_type == NotificationType.LAB_REPORT_READY:
        title = "Lab Report Ready 📄"
        body = "Your lab report is ready to view and understand"
    elif notification_type == NotificationType.COACH_MESSAGE:
        title = "Message from your Health Coach 💬"
        body = dynamic_body if len(dynamic_body) <= 250 else dynamic_body[:247] + "..."
    elif notification_type == NotificationType.SYMPTOM_CHECKIN:
        title = "Symptom Check-in 🩺"
        body = dynamic_body if len(dynamic_body) <= 250 else dynamic_body[:247] + "..."
        
    return send_push_notification(fcm_token, title, body, data)
