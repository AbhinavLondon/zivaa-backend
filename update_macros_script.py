import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.services.llm_plan import build_plan_context
from app.services.macro_calculator import calculate_daily_macros

def main():
    patient_id = "0c445588-b36c-478f-9be3-2addfc77dc1c"
    print(f"Fetching context for patient {patient_id}...")
    context = build_plan_context(patient_id)
    
    patient = context.get("patient", {})
    setup_prefs = context.get("setup_prefs", {})
    
    print(f"Patient Info: {patient}")
    print(f"Setup Prefs: {setup_prefs}")
    
    print("\nCalculating and saving macros...")
    result = calculate_daily_macros(patient, setup_prefs)
    
    print("\nResult:")
    print(result)

if __name__ == "__main__":
    main()
