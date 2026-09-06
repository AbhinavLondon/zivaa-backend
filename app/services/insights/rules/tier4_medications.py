"""
Tier 4 — Medications Interaction Rules

Evaluates patient medications for Drug-Drug Interactions (DDI) 
and Drug-Condition contraindications.
"""

from app.services.insights.core import InsightRule, RiskLevel, InsightCategory, InsightTier, InsightResult
from app.services.insights.context import EvalContext
import os
import json
import httpx
import asyncio
from app.config import settings

class MedicationInteractionRule(InsightRule):
    """
    Evaluates current active medications against other medications,
    allergies, and known baseline conditions to flag severe interactions.
    """
    category = InsightCategory.MEDICATIONS
    tier = InsightTier.TIER_4
    code = "med_interaction_01"
    name = "Medication Interaction Check"

    async def evaluate_async(self, ctx: EvalContext) -> InsightResult | None:
        """Async evaluation using LLM for interaction check."""
        from app.services.insights.data_fetcher import supabase
        from app.utils.crypto import decrypt_text
        
        # 1. Fetch medications (use ctx.active_medications if available, else fetch & decrypt)
        if ctx.active_medications:
            meds = ctx.active_medications
        else:
            meds_res = supabase.table("patient_medications").select("name, dose, frequency").eq("patient_id", ctx.patient_id).eq("status", "Active").execute()
            meds = meds_res.data or []
            for m in meds:
                if m.get("name"):
                    try: m["name"] = decrypt_text(m["name"])
                    except Exception: pass
                if m.get("dose"):
                    try: m["dose"] = decrypt_text(m["dose"])
                    except Exception: pass
        
        if len(meds) == 0:
            return None # Nothing to check
            
        # 2. Fetch allergies from preferences
        pref_res = supabase.table("patient_preferences").select("constraint_text").eq("patient_id", ctx.patient_id).eq("domain", "Clinical").execute()
        clinical_prefs = [p["constraint_text"] for p in (pref_res.data or [])]
        
        conditions = ctx.patient_conditions
        
        # 3. Call LLM to evaluate DDI and contraindications
        prompt = (
            f"You are a clinical pharmacist AI. Evaluate the following for severe/moderate Drug-Drug Interactions (DDI) "
            f"or Drug-Condition/Allergy contraindications.\n\n"
            f"MEDICATIONS: {json.dumps(meds)}\n"
            f"CONDITIONS: {json.dumps(conditions)}\n"
            f"CLINICAL PREFERENCES (e.g. Allergies): {json.dumps(clinical_prefs)}\n\n"
            f"If there is a SEVERE or MODERATE interaction, output a JSON object: "
            f'{{"has_interaction": true, "severity": "HIGH", "message": "Explanation of interaction", "evidence": "List of drugs involved"}}. '
            f"If it's safe or only mild, output: "
            f'{{"has_interaction": false}}.\n'
            f"Output purely JSON."
        )

        api_key = os.environ.get("GEMINI_API_KEY", settings.GEMINI_API_KEY)
        if not api_key:
            return None
            
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key={api_key}"
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.1, "response_mime_type": "application/json"}
        }

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, json=payload, timeout=20.0)
                if resp.status_code == 200:
                    data = resp.json()
                    raw_text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                    parsed = json.loads(raw_text)
                    
                    if parsed.get("has_interaction"):
                        sev_str = parsed.get("severity", "MEDIUM")
                        risk = RiskLevel.HIGH if sev_str == "HIGH" else RiskLevel.MEDIUM
                        
                        return self.trigger(
                            severity=risk,
                            message=parsed.get("message", "Medication interaction detected."),
                            evidence={"drugs_involved": parsed.get("evidence", "")}
                        )
        except Exception as e:
            print(f"Failed to evaluate medication interaction: {e}")
            
        return None

    def evaluate(self, ctx: EvalContext) -> InsightResult | None:
        """Sync wrapper for the rules engine."""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        if loop.is_running():
            # In a real app we'd handle nested event loops properly if needed,
            # but usually the insights engine evaluates rules synchronously or runs them in a pool.
            # We'll just return None here for now to avoid crashing, and assume the engine
            # is adapted for async or run it via a thread. 
            import nest_asyncio
            nest_asyncio.apply()
            return loop.run_until_complete(self.evaluate_async(ctx))
        return loop.run_until_complete(self.evaluate_async(ctx))
