"""Multi-source retrieval over the FAISS document store.

One unified vector index holds all chunks; retrieval fans the query across
knowledge categories (SOP, RUNBOOK, RCA, ...) by running a filtered search
per category when a category list is requested, merging, de-duplicating and
re-ranking the results.
"""
from __future__ import annotations

import time

from app.rag.grading.lexicon import content_tokens
from app.schemas.incident import RetrievedChunk
from app.core.config import get_settings


def _to_retrieved(rec, score: float) -> RetrievedChunk:
    m = rec.metadata or {}
    return RetrievedChunk(
        chunk_ref=rec.ref,
        document_id=m.get("document_id"),
        document_no=m.get("document_no"),
        citation=m.get("citation") or m.get("document_no") or rec.ref,
        document_name=m.get("document_name", ""),
        category=m.get("category", "KNOWLEDGE_BASE"),
        service=m.get("service"),
        section=m.get("section"),
        page=m.get("page"),
        text=rec.text,
        score=round(float(score), 4),
    )


class MultiSourceRetriever:
    def __init__(self, store, embeddings) -> None:
        self.store = store
        self.embeddings = embeddings

    def retrieve(
        self,
        query: str,
        *,
        k: int | None = None,
        categories: list[str] | None = None,
        service: str | None = None,
        score_threshold: float | None = None,
    ) -> list[RetrievedChunk]:
        s = get_settings()
        k = k or s.retrieval_k
        score_threshold = s.retrieval_score_threshold if score_threshold is None else score_threshold

        t0 = time.perf_counter()
        if categories:
            hits: list[tuple[object, float]] = []
            for cat in categories:
                hits.extend(
                    self.store.search(
                        query,
                        k=max(s.retrieval_max_per_category * 3, 6),
                        filters={"category": cat},
                        score_threshold=score_threshold * 0.85,
                    )
                )
        else:
            hits = self.store.search(query, k=k * 2, score_threshold=score_threshold * 0.85)

        merged: dict[str, RetrievedChunk] = {}
        for rec, score in hits:
            rc = _to_retrieved(rec, score)
            prev = merged.get(rc.chunk_ref)
            if prev is None or rc.score > prev.score:
                merged[rc.chunk_ref] = rc
        results = list(merged.values())

        if service:
            svc = service.lower()
            for rc in results:
                if rc.service and svc in rc.service.lower():
                    rc.score = min(1.0, rc.score + 0.06)      # service affinity boost
                if svc in rc.text.lower()[:400]:
                    rc.score = min(1.0, rc.score + 0.02)
        results.sort(key=lambda r: r.score, reverse=True)

        # keep category diversity: cap per category, prefer top chunks per doc
        capped: list[RetrievedChunk] = []
        per_cat: dict[str, int] = {}
        per_doc: dict[str, int] = {}
        for rc in results:
            if per_cat.get(rc.category, 0) >= max(s.retrieval_max_per_category, 2 if categories else 99):
                continue
            if per_doc.get(rc.chunk_ref.split("-C")[0], 0) >= 2:
                continue
            per_cat[rc.category] = per_cat.get(rc.category, 0) + 1
            per_doc[rc.chunk_ref.split("-C")[0]] = per_doc.get(rc.chunk_ref.split("-C")[0], 0) + 1
            capped.append(rc)
            if len(capped) >= k:
                break

        self.last_took_ms = round((time.perf_counter() - t0) * 1000, 2)
        return capped


def keyword_overlap(query: str, text: str) -> float:
    q = {t.lower() for t in content_tokens(query)}
    t = {t.lower() for t in content_tokens(text)}
    if not q or not t:
        return 0.0
    return len(q & t) / len(q)
