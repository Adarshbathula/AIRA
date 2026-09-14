"""FAISS Retrieval node (multi-source)."""
from __future__ import annotations

from typing import Any

from app.graph.nodes import runtime_of, settings_of


def run(state: dict[str, Any]) -> dict[str, Any]:
    settings = settings_of(state)
    rt = runtime_of(state)
    queries = list(state.get("queries") or [])
    query = queries[-1] if queries else state.get("user_input", "")
    analysis = state.get("analysis") or {}

    attempt = int(state.get("attempt") or 0) + 1
    if rt is None:  # unit-test mode with no runtime: empty context -> poor
        return {
            "attempt": attempt,
            "chunks": [],
            "scores": [],
            "trace": (state.get("trace") or []) + [{"node": "retriever", "status": "fail", "detail": "no runtime"}],
        }

    # Union retrieval: the synthesised keyword query and the raw incident text
    # are both sent to FAISS and merged, so a lossy keyword query can never
    # hide a chunk that the verbatim report would have matched (also used for
    # self-healing retries with rewritten queries).
    search_queries = [query, (state.get("user_input") or "").strip()[:600]]
    search_queries = list(dict.fromkeys(q for q in search_queries if q))

    seen: dict[str, dict[str, Any]] = {}
    took = 0.0
    for q in search_queries:
        chunks = rt.retriever.retrieve(
            q,
            categories=state.get("retrieval_categories") or None,
            service=analysis.get("service"),
            k=settings.retrieval_k,
        )
        took += getattr(rt.retriever, "last_took_ms", 0.0)
        for c in chunks:
            d = c.model_dump()
            if d["chunk_ref"] not in seen or d["score"] > seen[d["chunk_ref"]]["score"]:
                seen[d["chunk_ref"]] = d

    merged = sorted(seen.values(), key=lambda d: d["score"], reverse=True)[: settings.retrieval_k]
    return {
        "attempt": attempt,
        "retrieval_took_ms": round(took, 2),
        "chunks": merged,
        "scores": [round(c["score"], 4) for c in merged],
        "trace": (state.get("trace") or [])
        + [
            {
                "node": "retriever",
                "status": "ok" if merged else "fail",
                "detail": f"attempt={attempt} chunks={len(merged)} top_score={merged[0]['score'] if merged else 0:.3f}",
            }
        ],
    }
