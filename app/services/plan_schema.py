from pydantic import BaseModel, Field
from typing import List

class TaskItem(BaseModel):
    task: str = Field(..., description="A specific and descriptive task action, not more than 1 short sentence.")
    time: str = Field(..., description="The specific time for this task (e.g., '8:00 AM')")
    completed: bool = Field(default=False)
    category: str = Field(..., description="A short 1-2 word canonical category for this task (e.g., 'Walking', 'Meditation', 'Breakfast').")
    details: str = Field(..., description="One sentence explaining the why and how of the task. Easy to read and follow.")

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
            "task": {"type": "string", "description": "A specific and descriptive task action, not more than 1 short sentence."},
            "time": {"type": "string", "description": "The specific time for this task (e.g., '8:00 AM')"},
            "completed": {"type": "boolean"},
            "category": {"type": "string", "description": "A short 1-2 word canonical category for this task (e.g., 'Walking', 'Meditation', 'Breakfast')."},
            "details": {"type": "string", "description": "One sentence explaining the why and how of the task. Easy to read and follow."}
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
