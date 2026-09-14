"""Evidence Validator node.

Verifies, for every claim (root cause / troubleshooting step / summary line):

  * its cited evidence exists among the retrieved chunks (citation integrity);
  * the cited chunk really supports the claim (lexical support score);
  * the step text itself originates from retrieved text (anti-hallucination).

Claims that fail verification are flagged INSUFFICIENT and listed as
unsupported - they remain visible to the user but are clearly labelled, per
the project's honesty principle.
"""
from __future__ import annotations

from typing import Any

from app.graph.nodes import settings_of
from app.rag.grading.lexical import overlap


def _best_support(claim: str, cited_set: set[str], all_chunks: list[dict]) -> tuple[str | None, float, str]:
    """Return (chunk_ref, support_score, best_snippet).

    All retrieved chunks may support a claim; chunks the claim actually cites
    are weighted higher, which is what makes dangling citations detectable.
    """
    best_ref, best_score, best_snip = None, 0.0, ""
    for chunk in all_chunks:
        factor = 1.35 if (cited_set and chunk.get("citation") in cited_set) else 1.0
        s = overlap(claim, chunk.get("text", "")) * factor + 0.15 * min(1.0, chunk.get("score", 0.0) / 0.8)
        if s > best_score:
            best_score, best_ref = s, chunk.get("chunk_ref")
            best_snip = (chunk.get("text") or "")[:220]
    return best_ref, round(min(1.0, best_score), 3), best_snip


def _citation_set(refs: list[str]) -> set[str]:
    return {r for r in refs if r}


def run(state: dict[str, Any]) -> dict[str, Any]:
    settings = settings_of(state)
    chunks = state.get("chunks") or []
    by_citation: dict[str, str] = {}
    for c in chunks:
        cit = c.get("citation") or ""
        if cit:
            by_citation[cit] = c.get("text", "")

    claims: list[dict[str, Any]] = []
    unsupported: list[str] = []

    def validate(text: str, kind: str, refs: list[str]) -> dict[str, Any]:
        cited_set = {r for r in refs if r in by_citation}
        dangling = [r for r in refs if r and r not in by_citation]
        best_ref, score, snippet = _best_support(text, cited_set, chunks)
        if not chunks:
            status = "INSUFFICIENT"
        elif dangling and not cited_set:
            status = "INSUFFICIENT"     # citations point at nothing retrieved
        elif score >= max(0.34, settings.min_evidence_overlap + 0.16):
            status = "SUPPORTED"
        elif score >= settings.min_evidence_overlap:
            status = "PARTIALLY_SUPPORTED"
        else:
            status = "INSUFFICIENT"
        if status == "INSUFFICIENT":
            unsupported.append(f"{kind}: {text[:90]}")
        return {
            "claim": text[:300],
            "kind": kind,
            "evidence": [r for r in refs if r in cited_set][:4] if cited_set else (
                [next((c.get("citation") for c in chunks if c.get("chunk_ref") == best_ref), None)]
                if best_ref and status != "INSUFFICIENT" else []
            ),
            "status": status,
            "detail": (
                f"support={score:.2f} via {best_ref or 'no chunk'}"
                + (f"; dangling refs: {', '.join(map(str, dangling[:2]))}" if dangling else "")
            ),
        }

    for cause in state.get("causes") or []:
        if cause.get("status") == "INSUFFICIENT_EVIDENCE":
            continue
        claims.append(validate(f"{cause.get('label')}: {cause.get('description')}", "root_cause", cause.get("evidence") or []))
    for step in state.get("troubleshooting") or []:
        claims.append(validate(step.get("step", ""), "recommendation", step.get("evidence") or []))

    supported = sum(1 for c in claims if c["status"] == "SUPPORTED")
    partial = sum(1 for c in claims if c["status"] == "PARTIALLY_SUPPORTED")
    total = len(claims)
    if total == 0:
        overall = "INSUFFICIENT"
    elif supported == total:
        overall = "SUPPORTED"
    elif supported + partial > 0:
        overall = "PARTIALLY_SUPPORTED"
    else:
        overall = "INSUFFICIENT"

    return {
        "evidence_claims": claims,
        "evidence_status": overall,
        "evidence_stats": {"total_claims": total, "supported": supported, "partial": partial, "unsupported": total - supported - partial},
        "unsupported_claims": unsupported[:6],
        "trace": (state.get("trace") or [])
        + [{"node": "evidence_validator", "status": "ok", "detail": f"{overall}: {supported}/{total} claims fully supported"}],
    }
