"""Assemble node: guarantees every response-critical field exists, even when an
upstream node failed, so the API can always return a well-formed, honest answer.
"""
from __future__ import annotations

from typing import Any

from app.graph.nodes.summarizer import INSUFFICIENT_TEXT


def run(state: dict[str, Any]) -> dict[str, Any]:
    chunks = state.get("chunks") or []
    causes = [c for c in (state.get("causes") or []) if c.get("status") != "INSUFFICIENT_EVIDENCE"]

    updates: dict[str, Any] = {}

    def ensure(key: str, value: Any) -> None:
        if state.get(key) in (None, "", []):
            updates[key] = value

    ensure(
        "analysis",
        {
            "service": None, "error": None, "environment": "Production", "event": None,
            "category": "General", "severity": "P3", "symptoms": [], "keywords": [], "confidence": 0.0,
        },
    )
    ensure("causes", [{"label": "Insufficient Evidence", "description": "No retrievable evidence in the knowledge base.", "status": "INSUFFICIENT_EVIDENCE", "probability": "Low", "evidence": []}])
    ensure("evidence_status", "INSUFFICIENT")
    ensure("confidence_label", "Low")
    ensure("quality", "POOR")
    ensure("cause_taxonomy", "Other")

    if int(updates.get("confidence", state.get("confidence") or 0) or 0) <= 0 and not state.get("confidence"):
        ensure("confidence", 0.05)

    if not (state.get("final_text") or "").strip():
        updates["final_text"] = INSUFFICIENT_TEXT
    if not chunks and not causes:
        updates["insufficient_evidence"] = True
        if not (state.get("final_text") or "").strip():
            updates["final_text"] = INSUFFICIENT_TEXT

    updates["trace"] = (state.get("trace") or []) + [
        {"node": "assemble", "status": "ok", "detail": "response packaged for API/UI"}
    ]
    return updates
