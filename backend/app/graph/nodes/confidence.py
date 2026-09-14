"""Confidence Estimator node.

A transparent, deterministic 0..1 score labelled **AI Confidence Score**
(it is deliberately not presented as a calibrated probability). Signals:

    retrieval quality (top similarity & grader), document support breadth,
    evidence consistency (cross-document agreement on the primary cause),
    historical-signal strength (similar incidents), grader score,
    evidence validation ratio, plus a small penalty per failed retrieval
    attempt.
"""
from __future__ import annotations

from typing import Any

from app.graph.nodes import settings_of
from app.schemas.incident import ConfidenceBreakdown


def _sig(x: float, lo: float, hi: float) -> float:
    if hi <= lo:
        return 0.0
    return max(0.0, min(1.0, (x - lo) / (hi - lo)))


def compute_confidence(state: dict[str, Any]) -> tuple[float, ConfidenceBreakdown]:
    chunks = state.get("chunks") or []
    grader = state.get("grader") or {}
    similar = state.get("similar_incidents") or []
    causes = [c for c in (state.get("causes") or []) if c.get("status") != "INSUFFICIENT_EVIDENCE"]
    claims = state.get("evidence_claims") or []
    attempts = max(1, int(state.get("attempt") or 1))
    quality = state.get("quality") or "POOR"

    scores = [c.get("score", 0.0) for c in chunks] or [0.0]
    top = max(scores)

    sig_quality = {"GOOD": 1.0, "FAIR": 0.62, "POOR": 0.22}[quality]
    sig_top = _sig(top, 0.25, 0.8)
    s_ret = 0.65 * sig_quality + 0.35 * sig_top

    docs = {c.get("document_no") or c.get("citation") for c in chunks if c.get("document_no") or c.get("citation")}
    s_docs = _sig(len(docs), 0, 5)

    # evidence consistency: primary cause corroborated across documents & chunk score strength
    s_cons = 0.0
    primary_cites: list[str] = []
    if causes and chunks:
        primary = causes[0]
        primary_cites = [e for e in (primary.get("evidence") or []) if e]
        cat_bonus = {"CONFIRMED": 1.0, "PROBABLE": 0.7, "POSSIBLE": 0.4}.get(primary.get("status"), 0.2)
        s_cons = min(1.0, cat_bonus * _sig(len(set(primary_cites)), 0, 3))
        if primary_cites:
            s_cons = min(1.0, s_cons + 0.12 * _sig(top, 0.45, 0.85))

    # historical signal: best similar-incident similarity + corroboration count
    if similar:
        best_sim = max(s.get("similarity", 0.0) for s in similar)
        resolved_bonus = 0.15 if any(s.get("outcome") == "RESOLVED" for s in similar[:3]) else 0.0
        s_hist = min(1.0, _sig(best_sim, 0.45, 0.95) * (1 + 0.12 * (len(similar) - 1)) + resolved_bonus)
    else:
        s_hist = 0.0

    s_grader = max(0.0, min(1.0, float(grader.get("score", 0.0))))
    if claims:
        w = {"SUPPORTED": 1.0, "PARTIALLY_SUPPORTED": 0.55, "INSUFFICIENT": 0.0}
        s_val = sum(w.get(c.get("status", "INSUFFICIENT"), 0.0) for c in claims) / len(claims)
    else:
        s_val = 0.25 if chunks else 0.0

    breakdown = ConfidenceBreakdown(
        retrieval_quality=round(s_ret, 3),
        supporting_documents=round(s_docs, 3),
        evidence_consistency=round(s_cons, 3),
        similar_incidents=round(s_hist, 3),
        grader_score=round(s_grader, 3),
        evidence_validation=round(s_val, 3),
        notes=[
            f"top similarity {top:.2f}",
            f"{len(docs)} supporting documents",
            f"attempts={attempts}",
            f"{len(similar)} similar incidents",
        ],
    )

    score = (
        0.24 * s_ret
        + 0.16 * s_docs
        + 0.18 * s_cons
        + 0.14 * s_hist
        + 0.10 * s_grader
        + 0.18 * s_val
    )
    score -= 0.05 * max(0, attempts - 1)  # mild penalty: retrieval needed self-healing
    if not chunks:
        score = 0.05

    if quality == "POOR":
        score = min(score, 0.45)
    if not causes:
        score = min(score, 0.35)
    score = round(max(0.05, min(0.97, score)), 3)

    notes = breakdown.notes
    if attempts > 1:
        notes.append(f"self-healed after {attempts - 1} rewrite(s)")
    if not similar:
        notes.append("no historical match found")
    if any(c.get("status") == "CONFIRMED" for c in causes):
        notes.append("primary cause CONFIRMED by an RCA/postmortem")
    return score, ConfidenceBreakdown(**{**breakdown.model_dump(), "notes": notes})


def label_for(score: float) -> str:
    if score >= 0.85:
        return "High"
    if score >= 0.65:
        return "Medium-High"
    if score >= 0.45:
        return "Medium"
    return "Low"


def run(state: dict[str, Any]) -> dict[str, Any]:
    score, breakdown = compute_confidence(state)
    return {
        "confidence": score,
        "confidence_label": label_for(score),
        "confidence_breakdown": breakdown.model_dump(),
        "trace": (state.get("trace") or [])
        + [{"node": "confidence", "status": "ok", "detail": f"AI confidence {score:.0%} ({label_for(score)})"}],
    }
