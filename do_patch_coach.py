import re

file_path = 'app/api/endpoints/coach.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

if 'from app.utils.crypto import encrypt_text, decrypt_text' not in content:
    content = content.replace('from fastapi import APIRouter', 'from fastapi import APIRouter\nfrom app.utils.crypto import encrypt_text, decrypt_text')

# Patch stream history fetch
old_fetch = '''        if res.data:
            chat_history = list(reversed(res.data))'''
new_fetch = '''        if res.data:
            for row in res.data:
                if 'message' in row:
                    row['message'] = decrypt_text(row['message'])
            chat_history = list(reversed(res.data))'''
content = content.replace(old_fetch, new_fetch)

# Patch stream save
old_save = '''        try:
            supabase.table("coach_chat_logs").insert(
                {"patient_id": payload.patient_id, "role": "user", "message": payload.message}
            ).execute()
            supabase.table("coach_chat_logs").insert(
                {"patient_id": payload.patient_id, "role": "assistant", "message": full_reply}
            ).execute()
        except Exception as e:'''

new_save = '''        try:
            supabase.table("coach_chat_logs").insert(
                {"patient_id": payload.patient_id, "role": "user", "message": encrypt_text(payload.message)}
            ).execute()
            supabase.table("coach_chat_logs").insert(
                {"patient_id": payload.patient_id, "role": "assistant", "message": encrypt_text(full_reply)}
            ).execute()
        except Exception as e:'''
content = content.replace(old_save, new_save)

# Patch symptom reply read
old_symp_read = '''        symptom_name = "your symptom"
        if res.data:
            symptom_name = res.data[0]["fact"]'''
new_symp_read = '''        symptom_name = "your symptom"
        if res.data:
            symptom_name = decrypt_text(res.data[0]["fact"])'''
content = content.replace(old_symp_read, new_symp_read)

# Patch symptom reply save
old_symp_save_user = '''        supabase.table("coach_chat_logs").insert({
            "patient_id": payload.patient_id,
            "role": "user",
            "message": user_msg_text
        }).execute()'''
new_symp_save_user = '''        supabase.table("coach_chat_logs").insert({
            "patient_id": payload.patient_id,
            "role": "user",
            "message": encrypt_text(user_msg_text)
        }).execute()'''
content = content.replace(old_symp_save_user, new_symp_save_user)

old_symp_save_ai = '''        supabase.table("coach_chat_logs").insert({
            "patient_id": payload.patient_id,
            "role": "assistant",
            "message": ai_reply
        }).execute()'''
new_symp_save_ai = '''        supabase.table("coach_chat_logs").insert({
            "patient_id": payload.patient_id,
            "role": "assistant",
            "message": encrypt_text(ai_reply)
        }).execute()'''
content = content.replace(old_symp_save_ai, new_symp_save_ai)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
