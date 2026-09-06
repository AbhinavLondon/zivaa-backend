import os
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("Supabase credentials not found in .env")
    exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def run():
    print("Fetching patients with unlinked actions...")
    
    # 1. Get all actions that are unlinked
    res_actions = supabase.table("patient_memory").select("*").in_("category", ["agreed_action", "suggested_action"]).is_("linked_symptom_id", "null").execute()
    
    if not res_actions.data:
        print("No unlinked actions found.")
        return
        
    actions = res_actions.data
    
    # Group actions by patient
    patient_actions = {}
    for a in actions:
        pid = a["patient_id"]
        if pid not in patient_actions:
            patient_actions[pid] = []
        patient_actions[pid].append(a)
        
    for pid, acts in patient_actions.items():
        # Get the most recent symptom for this patient
        res_symp = supabase.table("patient_memory").select("id").eq("patient_id", pid).eq("category", "symptom").order("created_at", desc=True).limit(1).execute()
        
        if res_symp.data:
            latest_symptom_id = res_symp.data[0]["id"]
            print(f"Linking {len(acts)} actions for patient {pid} to symptom {latest_symptom_id}")
            
            # Update the actions
            for a in acts:
                supabase.table("patient_memory").update({"linked_symptom_id": latest_symptom_id}).eq("id", a["id"]).execute()
        else:
            print(f"Patient {pid} has {len(acts)} actions but no symptoms to link to. Skipping.")
            
    print("Migration of historical actions complete!")

if __name__ == "__main__":
    run()
