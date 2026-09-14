"""Similar Incident Search node (semantic discovery over the incident store)."""
from __future__ import annotations

from typing import Any

from app.graph.nodes import runtime_of, settings_of
from app.rag.retrieval.incident_store import incident_vector_text, search_similar_incidents


def run(state: dict[str, Any]) -> dict[str, Any]:
    settings = settings_of(state)
    rt = runtime_of(state)
    analysis = state.get("analysis") or {}
    query = incident_vector_text(
        state.get("user_input", ""),
        analysis.get("service"),
        analysis.get("category"),
        None,
    )
    similar: list[dict[str, Any]] = []
    if rt is not None and len(rt.incident_store):
        hits = search_similar_incidents(
            rt.incident_store,
            query,
            exclude_public_id=state.get("exclude_public_id"),
            top_k=settings.similar_incident_top_k,
            threshold=settings.similar_incident_score_threshold,
        )
        similar = [h.model_dump() for h in hits]

    return {
        "similar_incidents": similar,
        "trace": (state.get("trace") or [])
        + [
            {
                "node": "similar_incidents",
                "status": "ok" if similar else "skipped",
                "detail": f"{len(similar)} matches" + (f", top {similar[0]['similarity']:.0%}" if similar else ""),
            }
        ],
    }
