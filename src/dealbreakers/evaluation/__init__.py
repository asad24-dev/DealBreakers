"""Evaluation utilities (Phase 8G)."""

from dealbreakers.evaluation.failure_classification import FailureCategory, classify_failure
from dealbreakers.evaluation.scoring import RunMetrics, compute_estimated_score, summarize_runs

__all__ = [
    "FailureCategory",
    "RunMetrics",
    "classify_failure",
    "compute_estimated_score",
    "summarize_runs",
]
