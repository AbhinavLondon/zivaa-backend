import os
import sys
import json
from dotenv import load_dotenv
from supabase import create_client, Client

root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(root_dir)
load_dotenv(os.path.join(root_dir, '.env'))

from app.utils.crypto import encrypt_text, decrypt_text

url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
if not url or not key:
    print("Missing Supabase credentials")
    sys.exit(1)

supabase: Client = create_client(url, key)

def encrypt_table_field(table_name, id_col, field_name):
    print(f"Encrypting {table_name}.{field_name}...")
    try:
        res = supabase.table(table_name).select(f"{id_col}, {field_name}").execute()
        for row in res.data:
            val = row.get(field_name)
            if val and isinstance(val, str) and not val.startswith('gAAAAA'):
                new_val = encrypt_text(val)
                supabase.table(table_name).update({field_name: new_val}).eq(id_col, row[id_col]).execute()
        print(f"Done encrypting {table_name}.{field_name}.")
    except Exception as e:
        print(f"Failed to encrypt {table_name}.{field_name}: {e}")

def encrypt_jsonb_protocols(table_name):
    print(f"Encrypting {table_name}.protocols...")
    try:
        res = supabase.table(table_name).select("id, protocols").execute()
        for row in res.data:
            protocols = row.get("protocols")
            if protocols and isinstance(protocols, list):
                changed = False
                for p in protocols:
                    for k in ["title", "description", "reasoning", "modification_note"]:
                        if k in p and p[k] and isinstance(p[k], str) and not p[k].startswith('gAAAAA'):
                            p[k] = encrypt_text(p[k])
                            changed = True
                if changed:
                    supabase.table(table_name).update({"protocols": protocols}).eq("id", row["id"]).execute()
        print(f"Done encrypting {table_name}.protocols.")
    except Exception as e:
        print(f"Failed to encrypt {table_name}.protocols: {e}")

def main():
    print("Starting encryption migration...")
    encrypt_table_field("coach_chat_logs", "id", "message")
    encrypt_table_field("patient_memory", "id", "fact")
    encrypt_table_field("patient_symptoms", "id", "name")
    
    try:
        encrypt_table_field("patient_medications", "id", "name")
        encrypt_table_field("patient_medications", "id", "dose")
    except Exception:
        print("patient_medications table might not exist or field missing, skipping.")
        
    encrypt_jsonb_protocols("patient_longevity_protocols")
    print("Migration complete!")

if __name__ == '__main__':
    main()
