"""Incident endpoints: analysis, history, details, similarity."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.document import Document
from app.rag.retrieval.incident_store import incident_vector_text, search_similar_incidents
from app.rag.runtime import get_runtime
from app.schemas.api import AIResponse, IncidentDetailOut, IncidentSummaryOut
from app.schemas.incident import SimilarIncident, SimilarIncidentRequest
from app.services import incident_service, rag_service

router = APIRouter(prefix="/incidents", tags=["incidents"])


@router.post("", response_model=IncidentDetailOut, status_code=201)
def create_incident(
    payload: dict,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Analyze a raw incident description without a chat conversation."""
    message = str(payload.get("description") or payload.get("message") or "").strip()
    if len(message) < 4:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "'description' is required (min 4 chars)")
    _, inc, ai = incident_service.analyze_incident(db, user, message, conversation_id=None)
    return ai


@router.get("", response_model=dict)
def list_incidents(
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    search: str | None = None,
    service: str | None = None,
    severity: str | None = None,
    quality: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    include_seed: bool = True,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    rows, total = incident_service.list_incidents(
        db, user, limit=limit, offset=offset, search=search,
        service=service, severity=severity, quality=quality, status_filter=status_filter,
    )
    items = [
        IncidentSummaryOut.model_validate(
            {
                "id": r.id, "public_id": r.public_id, "service": r.service, "category": r.category,
                "severity": r.severity, "description": (r.description or "")[:600],
                "probable_root_cause": (r.probable_root_cause or "")[:400] or None,
                "confidence_score": round(float(r.confidence_score or 0), 4), "retrieval_quality": r.retrieval_quality,
                "retrieval_attempts": r.retrieval_attempts, "supporting_document_count": r.supporting_document_count,
                "evidence_status": r.evidence_status, "resolution_status": r.resolution_status, "created_at": r.created_at,
            }
        )
        for r in rows
        if include_seed or r.source != "seed"
    ]
    return {"total": total, "items": [i.model_dump() for i in items], "limit": limit, "offset": offset}


@router.post("/similar", response_model=list[SimilarIncident])
def similar_incidents(payload: SimilarIncidentRequest, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Standalone similar-incident discovery endpoint."""
    rt = get_runtime()
    rag_service.sync_stores(db)
    exclude = None
    if payload.incident_id:
        inc = incident_service.get_incident(db, payload.incident_id, user)
        exclude = inc.public_id
        text = inc.description or ""
        svc, cat, cause = inc.service, inc.category, inc.probable_root_cause
    elif payload.description and len(payload.description.strip()) >= 4:
        text = payload.description.strip()
        svc = cat = cause = None
    else:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Provide incident_id or description")
    query = incident_vector_text(text, svc, cat, cause)
    return search_similar_incidents(
        rt.incident_store,
        query,
        top_k=payload.top_k,
        exclude_public_id=exclude,
    )


@router.get("/{incident_id}", response_model=IncidentDetailOut)
def get_incident(incident_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    inc = incident_service.get_incident(db, incident_id, user)
    return incident_service.response_from_incident(db, inc)


@router.get("/by-public-id/{public_id}", response_model=IncidentDetailOut)
def get_incident_by_public(public_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    inc = incident_service.by_public_id(db, public_id)
    if inc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Incident not found")
    from app.core.security import ensure_user_ownership

    ensure_user_ownership(user, inc.user_id)
    return incident_service.response_from_incident(db, inc)


@router.delete("/{incident_id}", status_code=204)
def delete_incident(incident_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    inc = incident_service.get_incident(db, incident_id, user)
    incident_service.delete_incident(db, inc, user.id)


@router.post("/{incident_id}/resolution", response_model=IncidentSummaryOut)
def set_resolution(
    incident_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Engineers/admins mark an incident OPEN|MITIGATED|RESOLVED; RESOLVED feeds the history store."""
    inc = incident_service.get_incident(db, incident_id, user)
    inc = incident_service.set_resolution(db, inc, str(payload.get("resolution_status", "OPEN")))
    if note := str(payload.get("note") or "").strip():
        inc.resolution_summary = ((inc.resolution_summary or "") + f"\n[engineer note] {note}")[:2000]
        db.commit()
    return {
        "id": inc.id, "public_id": inc.public_id, "resolution_status": inc.resolution_status,
        "outcome": inc.outcome, "service": inc.service, "severity": inc.severity, "category": inc.category,
        "description": (inc.description or "")[:600],
        "retrieval_attempts": inc.retrieval_attempts,
        "supporting_document_count": inc.supporting_document_count,
        "retrieval_quality": inc.retrieval_quality,
        "confidence_score": inc.confidence_score,
        "created_at": inc.created_at, "probable_root_cause": inc.probable_root_cause,
        "evidence_status": inc.evidence_status,
    }


