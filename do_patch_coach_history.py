import re

file_path = 'app/api/endpoints/coach.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

new_endpoint = '''@router.get("/chat/history/{patient_id}")
async def get_chat_history(patient_id: str):
    from app.services.insights.data_fetcher import supabase
    try:
        res = supabase.table("coach_chat_logs") \\
            .select("*") \\
            .eq("patient_id", patient_id) \\
            .order("created_at", desc=True) \\
            .execute()
            
        logs = res.data or []
        for log in logs:
            if 'message' in log and log['message']:
                log['message'] = decrypt_text(log['message'])
                
        return logs
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

'''

if 'def get_chat_history' not in content:
    content = content.replace('@router.post("/chat", response_model=ChatResponse)', new_endpoint + '@router.post("/chat", response_model=ChatResponse)')
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
