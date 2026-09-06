from typing import List, Dict, Any, Optional
from datetime import datetime
from app.services.insights.data_fetcher import supabase
from app.services.insights.core import InsightRule, InsightResult, RiskLevel
from app.services.insights.data_fetcher import fetch_patient_context
from app.services.insights.rules.tier1_vitals import TIER_1_RULES
from app.services.insights.rules.tier2_sensors import TIER_2_RULES
from app.services.insights.rules.tier2_mental_health import MENTAL_HEALTH_RULES
from app.services.insights.rules.tier3_labs import TIER_3_RULES

from app.services.insights.context import EvalContext

class EngineOutput:
    def __init__(
        self, 
        active: List[InsightResult], 
        skipped: List[InsightResult],
        calibration_message: Optional[str] = None,
        baseline_status: Optional[Dict[str, Any]] = None
    ):
        self.active_insights = active
        self.skipped_rules = skipped
        self.calibration_message = calibration_message
        self.baseline_status = baseline_status

class InsightEngine:
    def __init__(self):
        self.rules: List[InsightRule] = []
        self.rules.extend(TIER_1_RULES)
        self.rules.extend(TIER_2_RULES)
        self.rules.extend(MENTAL_HEALTH_RULES)
        self.rules.extend(TIER_3_RULES)
        
    def evaluate_patient(self, patient_id: str, ctx: Optional[EvalContext] = None, evaluation_mode: str = "all") -> EngineOutput:
        """
        Fetches patient data context and evaluates all registered rules.
        Returns an EngineOutput with active insights (sorted by severity),
        a list of skipped rules (with reasons for transparency),
        and calibration status if baselines are not yet established.
        """
        # Fetch data and build context (now includes baseline computation)
        if ctx is None:
            ctx = fetch_patient_context(patient_id)
        
        # Pre-evaluation baseline extraction
        calibration_message = ctx.calibration_message if not ctx.is_any_baseline_established else None
        
        # Evaluate all rules
        active_insights = []
        skipped_rules = []
        
        for rule in self.rules:
            # Filter by evaluation mode
            if evaluation_mode != "all" and getattr(rule, "evaluation_mode", "realtime") != evaluation_mode:
                continue
                
            # Gate: skip baseline-dependent rules if baselines are not established
            if rule.requires_baseline and not ctx.is_any_baseline_established:
                skipped_rules.append(rule.skip_rule("Patient vitals are still calibrating"))
                continue
                
            try:
                result = rule.evaluate(ctx)
                if result.triggered:
                    active_insights.append(result)
                elif result.skipped:
                    skipped_rules.append(result)
            except Exception as e:
                print(f"Error evaluating rule {rule.id}: {e}")
                
        # Sort active insights by severity: HIGH > MEDIUM > LOW
        severity_order = {
            RiskLevel.HIGH: 0,
            RiskLevel.MEDIUM: 1,
            RiskLevel.LOW: 2
        }
        
        sorted_insights = sorted(
            active_insights,
            key=lambda x: severity_order.get(x.severity, 3)
        )
        
        # Save triggered deterministic insights to the database
        try:
            # 1. Fetch today's already-logged insights to deduplicate
            today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
            existing_res = supabase.table("deterministic_rules_insight") \
                .select("rule_id, severity") \
                .eq("patient_id", patient_id) \
                .gte("timestamp", today_start) \
                .execute()
                
            # Track the max severity logged today for each rule
            existing_max_severity = {}
            severity_rank = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
            
            for row in (existing_res.data or []):
                rid = row["rule_id"]
                sev = row.get("severity", "LOW").upper()
                if severity_rank.get(sev, 1) > severity_rank.get(existing_max_severity.get(rid, "LOW"), 0):
                    existing_max_severity[rid] = sev
            
            records = []
            for insight in sorted_insights:
                # Deduplication check: skip if we've already logged this rule today at an EQUAL or HIGHER severity
                new_sev = insight.severity.value.upper()
                existing_sev = existing_max_severity.get(insight.rule_id)
                
                if existing_sev and severity_rank.get(existing_sev, 1) >= severity_rank.get(new_sev, 1):
                    continue
                    
                records.append({
                    "patient_id": patient_id,
                    "rule_id": insight.rule_id,
                    "severity": insight.severity.value,
                    "message": insight.message,
                    "evidence": insight.evidence,
                    "timestamp": datetime.utcnow().isoformat()
                })
            
            if records:
                supabase.table("deterministic_rules_insight").insert(records).execute()
        except Exception as e:
            print(f"Failed to log deterministic insights to database: {e}")
        
        return EngineOutput(
            active=sorted_insights, 
            skipped=skipped_rules,
            calibration_message=calibration_message,
            baseline_status=ctx.baseline_status.to_dict() if ctx.baseline_status else None
        )

# Global instance for easy importing
engine = InsightEngine()
