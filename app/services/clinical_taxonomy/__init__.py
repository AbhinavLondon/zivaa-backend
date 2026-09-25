"""Clinical Taxonomy Domain for Closed-Loop Symptom Management.
Provides evidence-based clinical ontology, geriatric vulnerability modifiers, and deterministic entity resolution.
"""

from .catalog import CLINICAL_TAXONOMY, get_canonical_symptom, match_canonical_symptom, classify_symptom_with_llm
from .modifiers import apply_geriatric_modifiers
from .resolver import resolve_symptom_and_actions, record_task_micro_feedback, severity_to_score, score_to_severity

__all__ = [
    "CLINICAL_TAXONOMY",
    "get_canonical_symptom",
    "match_canonical_symptom",
    "classify_symptom_with_llm",
    "apply_geriatric_modifiers",
    "resolve_symptom_and_actions",
    "record_task_micro_feedback",
    "severity_to_score",
    "score_to_severity",
]
