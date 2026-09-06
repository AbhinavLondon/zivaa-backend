import sys
sys.path.insert(0, ".")
from app.services.insights.data_fetcher import supabase

pid = "0c445588-b36c-478f-9be3-2addfc77dc1c" # Shyam
today_str = "2026-09-06"

for t in ["nudge_alerts", "user_insights", "active_clinical_insights"]:
    print(f"\n==================== {t} (today {today_str}) ====================")
    res = supabase.table(t).select("*").eq("patient_id", pid).gte("created_at", today_str).order("created_at", desc=False).execute()
    print(f"Total rows today: {len(res.data)}")
    for r in res.data:
        print(f"ID: {r.get('id')} | Created: {r.get('created_at')}")
        for k in ['insight_type', 'headline', 'title', 'name', 'rule_id', 'severity', 'summary', 'message', 'insight_text', 'why_flagged']:
            if r.get(k):
                val = str(r.get(k))[:150]
                print(f"   {k}: {val}")
