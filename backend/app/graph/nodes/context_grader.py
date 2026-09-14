"""Context Grader node: GOOD vs POOR decides whether retrieval must self-heal."""
from __future__ import annotations

from typing import Any

from app.graph.nodes import llm_of, settings_of
from app.rag.grading.context_grader import grade_context


def run(state: dict[str, Any]) -> dict[str, Any]:
    settings = settings_of(state)
    chunks = state.get("chunks") or []
    analysis = state.get("analysis") or {}
    keywords = list(analysis.get("keywords") or [])

    grader = grade_context(
        chunks,
        keywords,
        settings=settings,
        llm=llm_of(state),
        attempt=int(state.get("attempt") or 1),
    )
    # A hard safety net: nothing retrieved is always POOR regardless of score.
    quality = "POOR" if not chunks else grader.quality

    return {
        "grader": grader.model_dump(),
        "quality": quality,
        "trace": (state.get("trace") or [])
        + [{"node": "context_grader", "status": "ok", "detail": f"{quality} (score={grader.score:.2f}) — {grader.feedback}"}],
    }
