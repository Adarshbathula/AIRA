"""Query Rewriter node (the self-healing half of Self-Healing RAG).

When the grader says the context is weak, the retrieval query is *transformed*
before the next FAISS pass:

  1. feedback-driven: terms the grader found missing get promoted;
  2. synonym expansion via the ops lexicon (503 -> "service unavailable", ...);
  3. strategy shifts by attempt number:
       attempt 1 -> broaden   (keywords + synonyms, whole KB)
       attempt 2 -> narrow    (exact incident text, service-focused categories)
       attempt 3 -> pivot     (document-type focused: RUNBOOK/SOP phrasing)
  4. optional LLM rewrite (Groq) merged on top when available.
"""
from __future__ import annotations

from typing import Any

from app.graph.nodes import llm_of, settings_of
from app.rag.grading.lexicon import content_tokens, expand_tokens
from app.graph.nodes.query_constructor import build_query


def _missing_terms(state: dict[str, Any]) -> list[str]:
    """Keyword tokens that never appeared in the retrieved context."""
    analysis = state.get("analysis") or {}
    blob = " ".join(c.get("text", "") for c in (state.get("chunks") or [])).lower()
    missing = []
    for kw in analysis.get("keywords") or []:
        t = str(kw).lower()
        if len(t) > 3 and t not in blob:
            missing.append(t)
    return missing[:8]


def rewrite(state: dict[str, Any]) -> str:
    settings = settings_of(state)
    attempt = int(state.get("attempt") or 1)
    analysis = state.get("analysis") or {}
    base_query = build_query(analysis, state.get("user_input", ""))
    raw = (state.get("user_input") or "").strip()
    missing = _missing_terms(state)

    if attempt <= 1:
        expansion = " ".join(expand_tokens([str(k) for k in (analysis.get("keywords") or [])]))
        query = f"{base_query} {expansion} {' '.join(missing)}".strip()
    elif attempt == 2:
        svc = analysis.get("service") or ""
        query = f"{svc} {raw[:320]} {' '.join(missing)}".strip()
    else:
        query = (
            f"{base_query} troubleshooting procedure steps runbook resolution "
            f"{' '.join(missing)}".strip()
        )

    # collapse repeated tokens while keeping order
    toks = list(dict.fromkeys(content_tokens(query)))
    query = " ".join(toks[:48]) or raw[:400]
    return query


_LLM_SYSTEM = (
    "You rewrite IT incident searches for a retrieval system. The previous search "
    "retrieved weak results. Produce ONE better keyword query (max 30 words) using terms likely "
    "to appear in runbooks/SOPs/RCA reports. No explanations."
)


def run(state: dict[str, Any]) -> dict[str, Any]:
    settings = settings_of(state)
    query = rewrite(state)

    llm = llm_of(state)
    detail = f"strategy={'broaden' if (state.get('attempt') or 1) <= 1 else ('narrow' if state.get('attempt') == 2 else 'pivot')}"
    if llm is not None and getattr(llm, "available", False):
        try:
            gr = state.get("grader") or {}
            user = (
                f"Incident: {state.get('user_input','')[:400]}\n"
                f"Previous query: {query}\n"
                f"Grader feedback: {gr.get('feedback','')}\n"
                f"Analyzed fields: service={ (state.get('analysis') or {}).get('service') },"
                f" error={ (state.get('analysis') or {}).get('error') }"
            )
            better = (llm.complete(_LLM_SYSTEM, user) or "").strip().splitlines()[0][:400]
            if len(better.split()) >= 3:
                query = f"{query} {better}"[:900]
                detail += " +llm-rewrite"
        except Exception:
            pass

    queries = list(state.get("queries") or [])
    if query and query not in queries:
        queries.append(query)
    return {
        "queries": queries,
        "trace": (state.get("trace") or [])
        + [{"node": "query_rewriter", "status": "retry", "detail": f"{detail} — next query: {query[:90]}..."}],
    }
