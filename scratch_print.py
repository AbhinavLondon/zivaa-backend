import asyncio
import sys

from app.services.scheduler_jobs import _build_checkin_context

async def print_prompt(patient_id):
    patient_name = "Ranjit" # Assuming it is Ranjit
    vitals_bullet, mood_text, adherence_text, patient_conditions, patient_age, patient_sex = await _build_checkin_context(patient_id)
    
    conditions_str = ", ".join(patient_conditions) if patient_conditions else "None recorded"
    age_str = f"{patient_age} years old" if patient_age else "Unknown"
    sex_str = patient_sex.capitalize() if patient_sex else "Unknown"
    prompt = f"""You are MedGemma, writing a soothing, encouraging evening wind-down message addressed directly to an elderly senior user.

Here is their full day summary:
- Age: {age_str}
- Sex: {sex_str}
- Vitals: {vitals_bullet}
- Mood/Feeling: {mood_text}
- Tasks/Plan: {adherence_text}
- Known Chronic Conditions: {conditions_str}

RULES:
1. Write EXACTLY 2 sentences. No more.
2. First sentence: A warm congratulatory recap of what they achieved today.
3. Second sentence: A soothing tip preparing them for a restful night of sleep. Gently tailor this tip to their known conditions if relevant.
4. Do NOT use medical jargon, numbers, or symbols. Translate numbers into words.
5. Return ONLY the 2 sentences as plain text. No JSON, no markdown.
"""
    print("-------------------- PROMPT START --------------------")
    print(prompt)
    print("-------------------- PROMPT END --------------------")

if __name__ == "__main__":
    asyncio.run(print_prompt("0c445588-b36c-478f-9be3-2addfc77dc1c"))
