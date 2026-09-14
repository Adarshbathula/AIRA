"""Incident service: runs the LangGraph pipeline and persists the outcome.

Persistence writes:
  incidents (analysis + metrics + user-facing pipeline artifact)
  recommendations (one row per troubleshooting step, with evidence status)
  evidence (one row per cited chunk: document, chunk ref, similarity, snippet)
  messages (chat transcript)
It also feeds the similar-incident FAISS store so the assistant learns from
every incident it analyses.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.security import ensure_user_ownership
from app.graph.workflow import artifact_state, run_workflow
from app.models.conversation import Conversation, Incident
from app.models.document import Document
from app.models.evidence import DocumentAccess, Evidence as EvidenceRow, Recommendation as RecommendationRow
from app.rag.runtime import get_runtime
from app.schemas.api import AIResponse
from app.schemas.incident import GraderResult as _GR  # noqa: F401
from app.schemas.incident import (
    Cause,
    ConfidenceBreakdown,
    EvidenceClaim,
    IncidentAnalysis,
    NodeTrace,
    RetrievalInfo,
    RetrievedChunk,
    SimilarIncident,
    TroubleshootingStep,
)
from app.services import conversation_service, rag_service

logger = logging.getLogger("aira.incidents")


# ------------------------------------------------------------------ analysis
def next_public_id(db: Session) -> str:
    count = db.scalar(select(func.count(Incident.id))) or 0
    n = count + 1
    while db.scalar(select(Incident).where(Incident.public_id == f"INC-{n:04d}")) is not None:
        n += 1
    return f"INC-{n:04d}"


def analyze_incident(
    db: Session,
    user,
    message: str,
    *,
    conversation_id: int | None = None,
    follow_up: bool = False,
) -> tuple[Conversation | None, Incident, AIResponse]:
    """Full pipeline run + persistence. Returns (conversation, incident, response)."""
    message = (message or "").strip()
    if len(message) < 4:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Incident description is too short")

    rt = get_runtime()
    rag_service.sync_stores(db)  # keeps FAISS aligned with Postgres (cheap no-op)

    conv: Conversation | None = None
    follow_up_context: str | None = None
    last_incident_public_id: str | None = None
    if conversation_id:
        conv = conversation_service.get_conversation(db, conversation_id, user)
        if follow_up:
            last_inc = next(
                (i for i in reversed(conv.incidents) if i.pipeline_state), None
            )
            if last_inc is not None:
                last_incident_public_id = last_inc.public_id
                st = last_inc.pipeline_state or {}
                follow_up_context = (
                    f"Earlier in this thread: {last_inc.description}\n"
                    f"Earlier probable cause: {last_inc.probable_root_cause}\n"
                    f"Earlier evidence: {', '.join(st.get('evidence_citations') or [])}"
                )
    else:
        conv = conversation_service.create_conversation(db, user.id, message)

    final = run_workflow(
        message,
        follow_up_context=follow_up_context,
        runtime=rt,
        exclude_public_id=last_incident_public_id,
    )
    state = final

    inc = _persist(db, user, conv, message, state)
    _persist_details(db, inc, state, user_id=user.id)

    if conv is not None:
        conversation_service.append_message(db, conv, "user", message, inc.id)
        reply = state.get("final_text") or ""
        conversation_service.append_message(db, conv, "assistant", reply, inc.id)
        if not follow_up and conv.title in ("New incident", ""):
            conversation_service.rename_conversation(db, conv, message)

    ai = response_from_incident(db, inc, state)
    _log_document_access(db, inc, user.id)
    return conv, inc, ai


# ---------------------------------------------------------------- persistence
def _persist(db: Session, user, conv: Conversation | None, message: str, state: dict) -> Incident:
    a = state.get("analysis") or {}
    chunks = state.get("chunks") or []
    docs_used = {c.get("document_no") for c in chunks if c.get("document_no")}
    citations = [c.get("citation") for c in chunks if c.get("citation")]
    cause_payload = _primary_cause(state)
    artifact = artifact_state(state)
    artifact["evidence_citations"] = list(dict.fromkeys(c for c in citations if c))[:10]
    artifact["engine"] = state.get("_engine", "builtin")

    inc = Incident(
        public_id=next_public_id(db),
        conversation_id=conv.id if conv else None,
        user_id=user.id if user else None,
        description=message[:4000],
        service=a.get("service"),
        category=a.get("category") or "General",
        severity=a.get("severity") or "P3",
        environment=a.get("environment") or "Production",
        error=a.get("error"),
        probable_root_cause=cause_payload,
        cause_taxonomy=state.get("cause_taxonomy") or "Other",
        confidence_score=float(state.get("confidence") or 0.0),
        retrieval_quality=state.get("quality") or "POOR",
        retrieval_attempts=int(state.get("attempt") or 1),
        supporting_document_count=len(docs_used),
        evidence_status=state.get("evidence_status") or "INSUFFICIENT",
        resolution_status="OPEN",
        outcome="UNRESOLVED",
        source="assistant",
        pipeline_state=artifact,
    )
    db.add(inc)
    db.commit()
    db.refresh(inc)
    return inc


def _primary_cause(state: dict) -> str | None:
    for c in state.get("causes") or []:
        if c.get("status") and c["status"] != "INSUFFICIENT_EVIDENCE":
            return f"[{c['status']}] {c['label']}: {c.get('description') or ''}".strip()[:900]
    return None


def _persist_details(db: Session, inc: Incident, state: dict, *, user_id: int | None) -> None:
    steps = state.get("troubleshooting") or []
    claims = {c.get("claim"): c for c in (state.get("evidence_claims") or [])}
    for step in steps:
        claim_key = step.get("step", "")[:300]
        claim = claims.get(claim_key)
        db.add(
            RecommendationRow(
                incident_id=inc.id,
                recommendation=step.get("step", "")[:2000],
                priority=int(step.get("priority") or 1),
                evidence_status=(claim or {}).get("status") or step.get("evidence_status") or "PARTIALLY_SUPPORTED",
                evidence_refs=step.get("evidence") or [],
            )
        )
    chunks = state.get("chunks") or []
    cited = [c for c in chunks if c.get("citation")]
    top_cited = _referenced_citations(state)
    keep = [c for c in cited if c.get("citation") in top_cited] or cited[:8]
    for c in keep:
        doc = db.scalar(select(Document).where(Document.document_no == c.get("document_no"))) if c.get("document_no") else None
        db.add(
            EvidenceRow(
                incident_id=inc.id,
                document_id=doc.id if doc else None,
                chunk_ref=c.get("chunk_ref"),
                similarity_score=float(c.get("score") or 0.0),
                citation=(c.get("citation") or "")[:250],
                snippet=(c.get("text") or "")[:900],
            )
        )
    db.commit()


def _referenced_citations(state: dict) -> set[str]:
    refs: set[str] = set()
    for c in state.get("causes") or []:
        refs.update(e for e in c.get("evidence") or [] if e)
    for s in state.get("troubleshooting") or []:
        refs.update(e for e in s.get("evidence") or [] if e)
    return refs


def _log_document_access(db: Session, inc: Incident, user_id: int | None) -> None:
    doc_ids = {e.document_id for e in inc.evidence if e.document_id}
    for d in doc_ids:
        db.add(DocumentAccess(document_id=d, user_id=user_id, event="referenced"))
    try:
        db.commit()
    except Exception:  # analytics must never break the request
        db.rollback()


# ------------------------------------------------------------------ responses
def response_from_incident(db: Session, inc: Incident, state: dict | None = None) -> AIResponse:
    state = state or inc.pipeline_state or {}
    rt = get_runtime()
    llm_status = rt.llm.status() if rt else {}

    analysis = IncidentAnalysis(**(state.get("analysis") or {}))
    causes = [Cause(**{k: v for k, v in c.items() if k in Cause.model_fields}) for c in (state.get("causes") or [])]
    steps = [
        TroubleshootingStep(**{k: v for k, v in s.items() if k in TroubleshootingStep.model_fields})
        for s in (state.get("troubleshooting") or [])
    ]
    similar = [
        SimilarIncident(**{k: v for k, v in s.items() if k in SimilarIncident.model_fields})
        for s in (state.get("similar_incidents") or [])
    ]
    claims = [
        EvidenceClaim(**{k: v for k, v in c.items() if k in EvidenceClaim.model_fields})
        for c in (state.get("evidence_claims") or [])
    ]
    evidence = [
        RetrievedChunk(
            chunk_ref=e.chunk_ref or "",
            document_id=e.document_id,
            citation=e.citation,
            text=e.snippet,
            score=e.similarity_score,
            **({"document_no": e.document.document_no, "category": e.document.category, "document_name": e.document.name}
               if e.document else {}),
        )
        for e in inc.evidence
    ]
    gr = state.get("grader") or {}
    from app.schemas.incident import GraderResult

    retrieval = RetrievalInfo(
        attempts=inc.retrieval_attempts,
        queries=state.get("queries") or [],
        grader=GraderResult(**gr) if gr else None,
        scores=state.get("scores") or [e.similarity_score for e in inc.evidence],
        documents_used=[e.citation for e in inc.evidence if e.citation],
    )
    trace = [NodeTrace(**{k: v for k, v in t.items() if k in NodeTrace.model_fields}) for t in (state.get("trace") or [])]
    breakdown_in = state.get("confidence_breakdown") or {}
    breakdown = ConfidenceBreakdown(**{k: v for k, v in breakdown_in.items() if k in ConfidenceBreakdown.model_fields})

    return AIResponse(
        incident_id=inc.id,
        public_id=inc.public_id,
        conversation_id=inc.conversation_id,
        analysis=analysis,
        final_text=state.get("final_text") or "",
        summary=state.get("summary") or "",
        cause_taxonomy=inc.cause_taxonomy,
        root_causes=causes,
        troubleshooting=steps,
        similar_incidents=similar,
        evidence=evidence,
        evidence_claims=claims,
        evidence_status=inc.evidence_status,
        confidence_score=float(inc.confidence_score or 0.0),
        confidence_label=_label_for(float(inc.confidence_score or 0.0)),
        confidence_breakdown=breakdown,
        retrieval=retrieval,
        retrieval_quality=inc.retrieval_quality,
        retrieval_attempts=inc.retrieval_attempts,
        supporting_document_count=inc.supporting_document_count,
        insufficient_evidence=bool(state.get("insufficient_evidence", False)),
        llm_used=bool(state.get("llm_used", False)),
        embedding_backend=rt.embeddings.status()["provider"] if rt else "n/a",
        trace=trace,
        timestamp=inc.created_at,
    )


def _label_for(score: float) -> str:
    from app.graph.nodes.confidence import label_for

    return label_for(score)


# --------------------------------------------------------------------- CRUD
def get_incident(db: Session, incident_id: int, user) -> Incident:
    inc = db.get(Incident, incident_id)
    if inc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Incident not found")
    ensure_user_ownership(user, inc.user_id)
    return inc


def by_public_id(db: Session, pid: str) -> Incident | None:
    return db.scalar(select(Incident).where(Incident.public_id == pid.upper()))


def list_incidents(
    db: Session,
    user,
    *,
    limit: int = 50,
    offset: int = 0,
    search: str | None = None,
    service: str | None = None,
    severity: str | None = None,
    quality: str | None = None,
    status_filter: str | None = None,
) -> tuple[list[Incident], int]:
    conds = []
    if user.role != "admin":
        conds.append(Incident.user_id == user.id)
    if search:
        like = f"%{search.strip()}%"
        conds.append(or_(Incident.description.ilike(like), Incident.service.ilike(like), Incident.public_id.ilike(like)))
    if service:
        conds.append(Incident.service == service)
    if severity:
        conds.append(Incident.severity == severity)
    if quality:
        conds.append(Incident.retrieval_quality == quality.upper())
    if status_filter:
        conds.append(Incident.resolution_status == status_filter.upper())
    from sqlalchemy import and_

    where = and_(*conds) if conds else None

    total = db.scalar(select(func.count(Incident.id)).where(where) if where is not None else select(func.count(Incident.id))) or 0
    stmt = select(Incident)
    if where is not None:
        stmt = stmt.where(where)
    rows = db.scalars(stmt.order_by(Incident.created_at.desc(), Incident.id.desc()).offset(offset).limit(max(1, min(limit, 200)))).all()
    return list(rows), int(total)


def delete_incident(db: Session, inc: Incident, user_id: int | None = None) -> None:
    try:
        rag_service.remove_incident_from_store(inc)
    except Exception as exc:  # pragma: no cover
        logger.debug("incident store cleanup skipped: %s", exc)
    db.delete(inc)
    db.commit()
    from app.services.audit_service import record_audit

    record_audit(db, user_id, "incident.delete", "incident", inc.public_id, None)


def set_resolution(db: Session, inc: Incident, resolution_status: str) -> Incident:
    if resolution_status.upper() not in {"OPEN", "MITIGATED", "RESOLVED"}:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "status must be OPEN|MITIGATED|RESOLVED")
    inc.resolution_status = resolution_status.upper()
    if inc.resolution_status == "RESOLVED":
        inc.outcome = "RESOLVED"
        try:
            rag_service.index_incident(inc)  # refresh the similar-incident store
        except Exception as exc:  # pragma: no cover
            logger.debug("incident store refresh failed: %s", exc)
    db.commit()
    db.refresh(inc)
    return inc
