"""Conditional routing for the self-healing retrieval loop."""
from __future__ import annotations

from typing import Any


def route_after_grader(state: dict[str, Any], *, allow_retry: bool = True) -> str:
    """GOOD/FAIR -> validate evidence; POOR (with retry budget left) -> rewrite query.

    FAIR is accepted to save an LLM round-trip only when it is the *final*
    attempt; mid-loop FAIR still triggers a rewrite so quality can improve.
    """
    quality = state.get("quality", "POOR")
    attempt = int(state.get("attempt") or 1)
    max_attempts = int(state.get("_max_attempts") or 3)
    if quality == "GOOD":
        return "good"
    if quality == "FAIR" and (attempt >= max_attempts or not allow_retry):
        return "good"
    if allow_retry and attempt < max_attempts:
        return "poor"
    return "good"  # out of budget: proceed with best-effort context


def route_final(state: dict[str, Any]) -> str:  # kept for graph symmetry/debug
    return "end"
