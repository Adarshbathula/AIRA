"""Knowledge search endpoint: direct semantic search over the corpus."""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.rag.runtime import get_runtime
from app.schemas.api import KnowledgeSearchResponse
from app.schemas.incident import KnowledgeSearchRequest
from app.services import rag_service

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.post("/search", response_model=KnowledgeSearchResponse)
def search(payload: KnowledgeSearchRequest, db: Session = Depends(get_db), user=Depends(get_current_user)):
    t0 = time.perf_counter()
    rt = get_runtime()
    rag_service.sync_stores(db)
    if not len(rt.document_store):
        return KnowledgeSearchResponse(query=payload.query, chunks=[], by_category={}, took_ms=0.0)
    chunks = rt.retriever.retrieve(
        payload.query,
        k=payload.top_k,
        categories=payload.categories,
        service=payload.service,
        score_threshold=0.18,  # browsing is more permissive than answer generation
    )
    by_cat: dict[str, int] = {}
    for c in chunks:
        by_cat[c.category] = by_cat.get(c.category, 0) + 1
    return KnowledgeSearchResponse(
        query=payload.query,
        chunks=chunks,
        by_category=by_cat,
        took_ms=round((time.perf_counter() - t0) * 1000, 2),
    )
