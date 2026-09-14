"""Similar-incident discovery over a dedicated FAISS incident store.

Every historical incident (seeded or produced by the assistant) contributes one
vector built from its description + service + root cause, so "has this happened
before?" is answered semantically, not by keyword grep.
"""
from __future__ import annotations

from app.rag.vectorstore.faiss_store import VectorStore
from app.schemas.incident import SimilarIncident
from app.core.config import get_settings


def incident_vector_text(description: str, service: str | None, category: str | None, root_cause: str | None) -> str:
    parts = [description or ""]
    if service:
        parts.append(f"service: {service}")
    if category:
        parts.append(f"category: {category}")
    if root_cause:
        parts.append(f"known root cause: {root_cause}")
    return "\n".join(p for p in parts if p)


def search_similar_incidents(
    store: VectorStore,
    query_text: str,
    *,
    top_k: int | None = None,
    threshold: float | None = None,
    exclude_public_id: str | None = None,
) -> list[SimilarIncident]:
    s = get_settings()
    top_k = top_k or s.similar_incident_top_k
    threshold = s.similar_incident_score_threshold if threshold is None else threshold
    hits = store.search(query_text, k=top_k * 4, score_threshold=threshold)

    out: list[SimilarIncident] = []
    seen: set[str] = set()
    for rec, score in hits:
        m = rec.metadata or {}
        pid = m.get("public_id", rec.ref)
        if pid == exclude_public_id or pid in seen:
            continue
        seen.add(pid)
        out.append(
            SimilarIncident(
                public_id=pid,
                title=m.get("title") or (rec.text.splitlines() or [""])[0][:140],
                service=m.get("service"),
                severity=m.get("severity"),
                similarity=round(max(0.0, min(1.0, score)), 4),
                root_cause=m.get("root_cause"),
                resolution=m.get("resolution"),
                outcome=m.get("outcome", "UNRESOLVED"),
                created_at=m.get("created_at"),
            )
        )
        if len(out) >= top_k:
            break
    return out
