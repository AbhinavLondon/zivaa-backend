from enum import Enum
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.insights.context import EvalContext
class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"

class InsightCategory(str, Enum):
    CARDIAC = "CARDIAC"
    METABOLIC = "METABOLIC"
    RESPIRATORY = "RESPIRATORY"
    RENAL = "RENAL"
    HEMATOLOGY = "HEMATOLOGY"
    THYROID = "THYROID"
    NUTRITION = "NUTRITION"
    MENTAL_HEALTH = "MENTAL_HEALTH"
    GENERAL = "GENERAL"
    IMMUNE = "IMMUNE"
    SLEEP = "SLEEP"
    NEUROLOGICAL = "NEUROLOGICAL"

class InsightTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"

class InsightResult(BaseModel):
    rule_id: str
    name: str
    triggered: bool
    skipped: bool = False
    skip_reason: str = ""
    severity: RiskLevel
    category: InsightCategory
    message: str
    is_historical: bool = False
    is_stale: bool = False
    effective_datetime: Optional[str] = None
    evidence: Dict[str, Any] = Field(default_factory=dict)

class InsightRule:
    id: str = "base_rule"
    name: str = "Base Rule"
    category: InsightCategory = InsightCategory.GENERAL
    tier: InsightTier = InsightTier.TIER_1
    requires_baseline: bool = True
    evaluation_mode: str = "realtime"
    
    def evaluate(self, ctx: 'EvalContext') -> InsightResult:
        """Evaluate the rule against the context. Override in subclasses."""
        return self.pass_rule()
        
    def trigger(self, severity: RiskLevel, message: str, evidence: Dict[str, Any] = None, is_historical: bool = False, is_stale: bool = False, effective_datetime: Optional[str] = None) -> InsightResult:
        return InsightResult(
            rule_id=self.id,
            name=self.name,
            triggered=True,
            severity=severity,
            category=self.category,
            message=message,
            is_historical=is_historical,
            is_stale=is_stale,
            effective_datetime=effective_datetime,
            evidence=evidence or {}
        )
        
    def pass_rule(self) -> InsightResult:
        return InsightResult(
            rule_id=self.id,
            name=self.name,
            triggered=False,
            severity=RiskLevel.LOW,
            category=self.category,
            message="",
            evidence={}
        )

    def skip_rule(self, reason: str) -> InsightResult:
        """Return when required data is missing and the rule cannot be evaluated."""
        return InsightResult(
            rule_id=self.id,
            name=self.name,
            triggered=False,
            skipped=True,
            skip_reason=reason,
            severity=RiskLevel.LOW,
            category=self.category,
            message="",
            evidence={}
        )
