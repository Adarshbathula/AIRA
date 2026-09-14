"""Context Grader: judges whether retrieved context can answer the incident.

Hybrid strategy:
  * deterministic scoring (top similarity, threshold pass ratio, document
    coverage, category coverage, keyword coverage) - always available;
  * optional LLM grading when Groq is configured, which can only *demote*
    GOOD -> POOR (it never inflates retrieval quality).
"""
from __future__ import annotations

import json
import logging

from app.rag.grading.lexicon import content_tokens
from app.schemas.incident import GraderResult

logger = logging.getLogger("aira.grader")


def deterministic_score(chunks: list[dict], query_keywords: list[str], threshold: float) -> tuple[float, dict]:
    """chunks: [{text, category, score}]. Returns (0..1 score, signals)."""
    if not chunks:
        return 0.0, {"reason": "no chunks retrieved"}
    scores = [c.get("score", 0.0) for c in chunks]
    top = max(scores)
    pass_ratio = sum(1 for s in scores if s >= threshold) / len(scores)
    docs = {c.get("citation") or c.get("document_no") for c in chunks}
    doc_coverage = min(1.0, len(docs) / 3.0)
    cats = {c.get("category") for c in chunks}
    wanted = {"RUNBOOK", "SOP", "RCA", "POSTMORTEM", "TROUBLESHOOTING_GUIDE", "INCIDENT_REPORT"}
    cat_coverage = min(1.0, len(cats & wanted) / 2.0)
    context_blob = " ".join(c.get("text", "") for c in chunks[:12])
    kw = {t.lower() for t in query_keywords if len(t) > 2}
    keyword_coverage = (len({t for t in kw if t in context_blob}) / len(kw)) if kw else 0.5
    length_signal = min(1.0, sum(len(c.get("text", "")) for c in chunks) / 2500)

    score = (
        0.30 * min(1.0, top / 0.75)
        + 0.20 * pass_ratio
        + 0.15 * doc_coverage
        + 0.15 * cat_coverage
        + 0.12 * keyword_coverage
        + 0.08 * length_signal
    )
    signals = {
        "top_score": round(top, 3),
        "pass_ratio": round(pass_ratio, 3),
        "distinct_documents": len(docs),
        "categories": sorted(c for c in cats if c),
        "keyword_coverage": round(keyword_coverage, 3),
        "context_chars": sum(len(c.get("text", "")) for c in chunks),
    }
    return round(min(1.0, score), 4), signals


def grade_context(
    chunks: list[dict],
    query_keywords: list[str],
    *,
    settings,
    llm=None,
    attempt: int = 1,
) -> GraderResult:
    score, signals = deterministic_score(chunks, query_keywords, settings.retrieval_score_threshold)
    feedback_bits = []

    if llm is not None and getattr(llm, "available", False) and chunks:
        try:
            verdict = _llm_grade(llm, chunks, query_keywords)
            if verdict:
                llm_score = float(verdict.get("score", 0))
                score = 0.65 * score + 0.35 * max(0.0, min(1.0, llm_score))
                signals["llm_feedback"] = str(verdict.get("feedback", ""))[:280]
        except Exception as exc:  # never let grading crash the pipeline
            logger.debug("LLM grading skipped: %s", exc)

    if signals.get("distinct_documents", 0) < 2:
        feedback_bits.append("evidence comes from fewer than 2 documents")
    if score < 0.45:
        feedback_bits.append("similarity to the incident is weak")
    if attempt >= settings.max_retrieval_attempts:
        feedback_bits.append("retry budget exhausted")

    if score >= settings.context_good_threshold:
        quality = "GOOD"
    elif score >= settings.context_poor_threshold:
        quality = "FAIR"
    else:
        quality = "POOR"

    return GraderResult(
        quality=quality,
        score=score,
        signals=signals,
        feedback="; ".join(feedback_bits) or "context is relevant and diverse",
    )


_LLM_GRADE_PROMPT = (
    "You grade retrieval context quality for an IT incident assistant. "
    "Given an incident's key terms and a list of retrieved excerpts, decide if the excerpts "
    "contain information useful for diagnosing the incident. Be strict. "
    'Return JSON: {"score": 0.0-1.0, "feedback": "one short sentence"}. '
    "score=1.0 means the excerpts directly address the incident; 0.2 means mostly irrelevant."
)


def _llm_grade(llm, chunks: list[dict], keywords: list[str]) -> dict | None:
    payload = {
        "incident_keywords": keywords[:14],
        "excerpts": [
            {"ref": c.get("citation"), "category": c.get("category"), "text": (c.get("text") or "")[:500]}
            for c in chunks[:8]
        ],
    }
    raw = llm.complete_json(_LLM_GRADE_PROMPT, json.dumps(payload)[:6000])
    return raw if isinstance(raw, dict) else None
