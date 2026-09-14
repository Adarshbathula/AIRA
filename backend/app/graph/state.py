"""LangGraph workflow state.

TypedDict state shared by every node. ``pipeline_config`` carries the
non-serialisable runtime (RagRuntime); everything else is JSON-safe so the
final state can be persisted to PostgreSQL for the Incident Details UI.
"""
from __future__ import annotations

from typing import Any, TypedDict


class WorkflowState(TypedDict, total=False):
    # inputs
    user_input: str
    follow_up_context: str | None
    exclude_public_id: str | None      # current incident must not list itself as "similar"

    # analyzer
    analysis: dict[str, Any]

    # retrieval loop
    queries: list[str]
    retrieval_categories: list[str]
    retrieval_took_ms: float
    chunks: list[dict[str, Any]]
    scores: list[float]
    attempt: int
    grader: dict[str, Any] | None
    quality: str                      # GOOD | FAIR | POOR

    # downstream
    similar_incidents: list[dict[str, Any]]
    causes: list[dict[str, Any]]
    cause_taxonomy: str
    troubleshooting: list[dict[str, Any]]
    evidence_claims: list[dict[str, Any]]
    evidence_status: str
    confidence: float
    confidence_label: str
    confidence_breakdown: dict[str, Any]
    insufficient_evidence: bool
    summary: str
    final_text: str
    llm_used: bool
    errors: list[str]
    trace: list[dict[str, Any]]

    # runtime (stripped before persistence/API serialisation)
    pipeline_config: dict[str, Any]


def public_state(state: dict[str, Any]) -> dict[str, Any]:
    """Strip runtime objects, producing the user-facing artifact payload.

    This is deliberately an *output snapshot* (evidence, causes, scores). The
    graph's intermediate reasoning is never stored or exposed.
    """
    return {k: v for k, v in state.items() if k != "pipeline_config" and not k.startswith("_")}
