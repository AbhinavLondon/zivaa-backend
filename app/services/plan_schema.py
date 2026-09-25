import uuid
from pydantic import BaseModel, Field, model_validator
from typing import List, Optional, Dict, Any

def is_valid_uuid(val: Any) -> bool:
    if not val:
        return False
    try:
        uuid.UUID(str(val))
        return True
    except (ValueError, TypeError, AttributeError):
        return False

class TaskProvenance(BaseModel):
    source: Optional[str] = Field(default=None, description="Origin: 'system', 'coach', 'prescription', 'habit'.")
    badge_text: Optional[str] = Field(default=None, description="Optional visual badge: 'NEW', 'UPDATED', 'From Coach Zivaa', 'Habit', 'Errand'.")
    badge: Optional[str] = Field(default=None, description="Alias for badge_text.")
    reason: Optional[str] = Field(default=None, description="Explainability rationale for why this task is in the plan.")

    @model_validator(mode="before")
    @classmethod
    def sync_badge(cls, data: Any) -> Any:
        if isinstance(data, dict):
            b_text = data.get("badge_text") or data.get("badge")
            if b_text:
                data["badge_text"] = b_text
                data["badge"] = b_text
        return data

class TaskAction(BaseModel):
    action_type: str = Field(default="CHECKBOX_ONLY", description="Action type: 'FOLLOW_EXERCISE', 'LOG_VITALS', 'LOG_MEAL', 'COACH_CHAT', 'START_TIMER', 'CALL_PHONE', 'CHECKBOX_ONLY'.")
    type: str = Field(default="CHECKBOX_ONLY", description="Alias for action_type.")
    target: Optional[str] = Field(default=None, description="Action target identifier (e.g. 'blood_pressure', 'nutrition', 'Knee').")
    routine_title: Optional[str] = Field(default=None, description="Title of exercise routine.")
    target_body_part: Optional[str] = Field(default=None, description="Target body part for exercises.")
    cta_label: Optional[str] = Field(default=None, description="Button label for senior action CTA, e.g. 'Start Routine', 'Log Vitals', 'Log Meal', 'Ask Zivaa'.")
    exercise_ids: Optional[List[str]] = Field(default=None, description="List of IDs from zivaa_exercise_repository for guided follow-along routine.")
    prefilled_prompt: Optional[str] = Field(default=None, description="Pre-seeded message for Coach Chat.")
    instructions: Optional[str] = Field(default=None, description="Brief step instructions.")

    @model_validator(mode="before")
    @classmethod
    def sync_type(cls, data: Any) -> Any:
        if isinstance(data, dict):
            a_type = data.get("action_type") or data.get("type") or "CHECKBOX_ONLY"
            data["action_type"] = a_type
            data["type"] = a_type
            if "exercise_ids" in data and isinstance(data["exercise_ids"], list):
                data["exercise_ids"] = [str(x) for x in data["exercise_ids"]]
        return data

class TaskItem(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique task UUID string.")
    task: str = Field(..., description="A specific and descriptive task action, not more than 1 short sentence.")
    time: str = Field(..., description="The specific time for this task (e.g., '8:00 AM')")
    completed: bool = Field(default=False)
    period: Optional[str] = Field(default=None, description="Time slot: morning, afternoon, evening, night.")
    category: str = Field(..., description="Canonical category: 'vitals', 'medication', 'diet', 'activity', 'mindfulness', 'hydration', 'sleep', 'coach'.")
    tier: str = Field(default="lifestyle", description="'clinical', 'lifestyle', or 'coach'.")
    anchor_type: str = Field(default="lifestyle", description="'symptom', 'one_off', 'habit', 'periodic', 'clinical_rule', 'lifestyle'.")
    anchor_id: Optional[str] = Field(default=None, description="Optional foreign key or rule_id.")
    care_plan_action_id: Optional[str] = Field(default=None, description="UUID of linked care_plan_actions record.")
    symptom_id: Optional[str] = Field(default=None, description="UUID of linked patient_symptoms record.")
    canonical_key: Optional[str] = Field(default=None, description="Clinical taxonomy canonical key, e.g. MSK_KNEE_OA_FLARE.")
    status: str = Field(default="pending", description="'pending', 'completed', 'dismissed', 'needs_checkin'.")
    details: str = Field(..., description="One sentence explaining the why and how of the task. Easy to read and follow.")
    provenance: Optional[TaskProvenance] = Field(default=None)
    action: Optional[TaskAction] = Field(default=None)

    @model_validator(mode="before")
    @classmethod
    def set_defaults(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Ensure task ID is a valid RFC-4122 UUID; replace hallucinated or malformed IDs
            task_id = data.get("id")
            if not task_id or not is_valid_uuid(task_id):
                data["id"] = str(uuid.uuid4())

            # Sanitize symptom_id and care_plan_action_id if present but not valid UUIDs
            if data.get("symptom_id") and not is_valid_uuid(data.get("symptom_id")):
                data["symptom_id"] = None
            if data.get("care_plan_action_id") and not is_valid_uuid(data.get("care_plan_action_id")):
                data["care_plan_action_id"] = None

            # Ensure action defaults sensibly based on category if omitted
            if not data.get("action"):
                cat = str(data.get("category", "")).lower()
                task_txt = str(data.get("task", "")).lower()
                if "blood pressure" in task_txt or "bp" in task_txt or cat == "vitals":
                    data["action"] = {"type": "LOG_VITALS", "target": "blood_pressure", "cta_label": "Record BP"}
                elif "glucose" in task_txt or "sugar" in task_txt:
                    data["action"] = {"type": "LOG_VITALS", "target": "glucose", "cta_label": "Log Sugar"}
                elif cat in ["diet", "nutrition"] or any(w in task_txt for w in ["lunch", "breakfast", "dinner", "meal", "food"]):
                    data["action"] = {"type": "LOG_MEAL", "target": "nutrition", "cta_label": "Snap Meal"}
                elif cat in ["activity", "movement", "exercise"] or any(w in task_txt for w in ["stretch", "walk", "knee", "exercise", "squat"]):
                    data["action"] = {"type": "FOLLOW_EXERCISE", "target": "routine", "cta_label": "Follow Exercises"}
                elif cat == "coach" or "coach" in task_txt or "zivaa" in task_txt:
                    data["action"] = {"type": "COACH_CHAT", "cta_label": "Ask Zivaa"}
                else:
                    data["action"] = {"type": "CHECKBOX_ONLY", "cta_label": "Done"}
        return data

class DailySchedule(BaseModel):
    morning: List[TaskItem] = Field(default_factory=list)
    afternoon: List[TaskItem] = Field(default_factory=list)
    evening: List[TaskItem] = Field(default_factory=list)
    night: List[TaskItem] = Field(default_factory=list)

class DailyPlanResponse(BaseModel):
    summary: str
    schedule: DailySchedule
    health_context: dict = Field(default_factory=dict)
    active_alerts: List[str] = Field(default_factory=list)

def get_gemini_schema():
    task_item_schema = {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "Unique UUID for the task."},
            "task": {"type": "string", "description": "A specific, atomic task action, max 4 words."},
            "time": {"type": "string", "description": "The specific time for this task (e.g., '8:00 AM')"},
            "completed": {"type": "boolean"},
            "category": {"type": "string", "description": "Canonical category: 'vitals', 'medication', 'diet', 'activity', 'mindfulness', 'hydration', 'sleep', 'coach'."},
            "tier": {"type": "string", "description": "'clinical', 'lifestyle', or 'coach'."},
            "anchor_type": {"type": "string", "description": "'symptom', 'one_off', 'habit', 'periodic', 'clinical_rule', or 'lifestyle'."},
            "anchor_id": {"type": "string", "description": "Optional linked symptom UUID, care plan action UUID, or clinical rule ID."},
            "care_plan_action_id": {"type": "string", "description": "UUID of linked care_plan_actions record, if applicable."},
            "symptom_id": {"type": "string", "description": "UUID of linked patient_symptoms record, if applicable."},
            "canonical_key": {"type": "string", "description": "Clinical taxonomy canonical key, e.g. MSK_KNEE_OA_FLARE."},
            "status": {"type": "string", "description": "'pending', 'completed', 'dismissed', 'needs_checkin'."},
            "details": {"type": "string", "description": "One sentence explaining the why and how of the task."},
            "provenance": {
                "type": "object",
                "properties": {
                    "badge": {"type": "string", "description": "Badge: 'NEW', 'UPDATED', 'COACH AGREED', 'HABIT', 'ERRAND'."},
                    "reason": {"type": "string", "description": "1 sentence explainability rationale."}
                }
            },
            "action": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "description": "'FOLLOW_EXERCISE', 'LOG_VITALS', 'LOG_MEAL', 'COACH_CHAT', 'START_TIMER', 'CALL_PHONE', 'CHECKBOX_ONLY'."},
                    "target": {"type": "string", "description": "Action target (e.g. 'blood_pressure', 'nutrition', 'Knee')."},
                    "cta_label": {"type": "string", "description": "Senior CTA button label, e.g. 'Follow Exercises', 'Record BP', 'Snap Meal', 'Ask Zivaa'."},
                    "exercise_ids": {"type": "array", "items": {"type": "string"}, "description": "UUIDs of relevant exercises from repository."},
                    "prefilled_prompt": {"type": "string", "description": "Prompt for Coach Chat."}
                }
            }
        },
        "required": ["task", "time", "completed", "category", "details"]
    }
    
    return {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "schedule": {
                "type": "object",
                "properties": {
                    "morning": {"type": "array", "items": task_item_schema},
                    "afternoon": {"type": "array", "items": task_item_schema},
                    "evening": {"type": "array", "items": task_item_schema},
                    "night": {"type": "array", "items": task_item_schema}
                },
                "required": ["morning", "afternoon", "evening", "night"]
            }
        },
        "required": ["summary", "schedule"]
    }
