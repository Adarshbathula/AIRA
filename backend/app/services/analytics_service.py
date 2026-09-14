"""Analytics service backing the user and admin dashboards."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session

from app.core.security import ROLE_ADMIN
from app.models.conversation import Conversation, Incident, Message
from app.models.document import Document, DocumentChunk
from app.models.evidence import AuditLog, DocumentAccess, Evidence
from app.models.user import User
from app.graph.taxonomy import TAXON_LABELS


def _day(dt: datetime | None) -> str:
    return dt.strftime("%Y-%m-%d") if dt else ""


def overview(db: Session, user) -> dict:
    conds = [] if user.role == ROLE_ADMIN else [Incident.user_id == user.id]
    where = and_(*conds) if conds else None

    q = select(Incident)
    if where is not None:
        q = q.where(where)
    rows = list(db.scalars(q))
    n = len(rows)

    conf = [r.confidence_score or 0.0 for r in rows]
    good = sum(1 for r in rows if (r.retrieval_quality or "").upper() == "GOOD")
    attempts = [r.retrieval_attempts or 1 for r in rows]
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=7)
    recent = sum(1 for r in rows if r.created_at and r.created_at >= since)

    doc_q = select(func.count(Document.id))
    docs = db.scalar(doc_q) or 0
    chunks = db.scalar(select(func.count(DocumentChunk.id))) or 0
    users = db.scalar(select(func.count(User.id))) or 0

    return {
        "role": user.role,
        "total_incidents": n,
        "incidents_last_7_days": recent,
        "avg_confidence": round(sum(conf) / n, 4) if n else 0.0,
        "good_retrieval_pct": round(100.0 * good / n, 1) if n else 0.0,
        "avg_retrieval_attempts": round(sum(attempts) / n, 2) if n else 0.0,
        "resolved_incidents": sum(1 for r in rows if r.resolution_status == "RESOLVED"),
        "insufficient_evidence": sum(1 for r in rows if r.evidence_status == "INSUFFICIENT"),
        "high_severity": sum(1 for r in rows if (r.severity or "") in {"P0", "P1"}),
        "documents": docs,
        "document_chunks": chunks,
        "users": users if user.role == ROLE_ADMIN else None,
    }


def incident_trends(db: Session, user, days: int = 14) -> dict:
    conds = [] if user.role == ROLE_ADMIN else [Incident.user_id == user.id]
    where = and_(*conds) if conds else None
    q = select(Incident)
    if where is not None:
        q = q.where(where)
    rows = list(db.scalars(q))
    by_day: Counter[str] = Counter()
    conf_by_day: defaultdict[str, list[float]] = defaultdict(list)
    for r in rows:
        key = _day(r.created_at)
        by_day[key] += 1
        conf_by_day[key].append(r.confidence_score or 0.0)
    start = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days - 1)
    series = []
    for i in range(days):
        d = (start + timedelta(days=i)).strftime("%Y-%m-%d")
        cs = conf_by_day.get(d) or []
        series.append(
            {
                "date": d,
                "incidents": by_day.get(d, 0),
                "avg_confidence": round(sum(cs) / len(cs), 3) if cs else 0.0,
            }
        )
    return {"days": days, "series": series}


def top_services(db: Session, user, limit: int = 6) -> list[dict]:
    conds = [Incident.service.is_not(None)]
    if user.role != ROLE_ADMIN:
        conds.append(Incident.user_id == user.id)
    rows = db.execute(
        select(Incident.service, func.count(Incident.id), func.avg(Incident.confidence_score))
        .where(and_(*conds))
        .group_by(Incident.service)
        .order_by(func.count(Incident.id).desc())
        .limit(limit)
    ).all()
    return [
        {"service": s, "count": c, "avg_confidence": round(float(ac or 0), 3)}
        for s, c, ac in rows
    ]


def recent_incidents(db: Session, user, limit: int = 10) -> list[dict]:
    conds = [] if user.role == ROLE_ADMIN else [Incident.user_id == user.id]
    where = and_(*conds) if conds else None
    q = select(Incident)
    if where is not None:
        q = q.where(where)
    rows = db.scalars(q.order_by(Incident.created_at.desc(), Incident.id.desc()).limit(limit))
    return [
        {
            "id": r.id,
            "public_id": r.public_id,
            "description": (r.description or "")[:180],
            "service": r.service,
            "severity": r.severity,
            "category": r.category,
            "confidence_score": round(float(r.confidence_score or 0), 3),
            "retrieval_quality": r.retrieval_quality,
            "evidence_status": r.evidence_status,
            "resolution_status": r.resolution_status,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


def root_cause_stats(db: Session, user) -> dict:
    conds = [Incident.source == "assistant"]
    if user.role != ROLE_ADMIN:
        conds.append(Incident.user_id == user.id)
    rows = db.execute(
        select(Incident.cause_taxonomy, func.count(Incident.id))
        .where(and_(*conds))
        .group_by(Incident.cause_taxonomy)
        .order_by(func.count(Incident.id).desc())
    ).all()
    total = sum(c for _, c in rows) or 0
    buckets = [{"label": lbl or "Other", "count": cnt, "pct": round(100.0 * cnt / total, 1) if total else 0.0} for lbl, cnt in rows]
    known = [b for b in buckets if b["label"] in TAXON_LABELS]
    return {"total": total, "distribution": known or buckets}


def confidence_distribution(db: Session, user) -> dict:
    conds = [] if user.role == ROLE_ADMIN else [Incident.user_id == user.id]
    where = and_(*conds) if conds else None
    q = select(Incident.confidence_score)
    if where is not None:
        q = q.where(where)
    scores = [float(s or 0.0) for (s,) in db.execute(q)]
    buckets = {"90-100": 0, "80-89": 0, "70-79": 0, "50-69": 0, "<50": 0}
    for s in scores:
        p = s * 100
        if p >= 90:
            buckets["90-100"] += 1
        elif p >= 80:
            buckets["80-89"] += 1
        elif p >= 70:
            buckets["70-79"] += 1
        elif p >= 50:
            buckets["50-69"] += 1
        else:
            buckets["<50"] += 1
    return {
        "total": len(scores),
        "avg": round(sum(scores) / len(scores), 3) if scores else 0.0,
        "buckets": [{"bucket": k, "count": v} for k, v in buckets.items()],
    }


def retrieval_stats(db: Session, user) -> dict:
    conds = [Incident.source == "assistant"]
    if user.role != ROLE_ADMIN:
        conds.append(Incident.user_id == user.id)
    rows = db.execute(
        select(
            func.count(Incident.id),
            func.avg(Incident.retrieval_attempts),
            func.avg(Incident.confidence_score),
            func.avg(Incident.supporting_document_count),
            func.sum(case((Incident.retrieval_quality == "GOOD", 1), else_=0)),
            func.sum(case((Incident.retrieval_quality == "POOR", 1), else_=0)),
        ).where(and_(*conds))
    ).one()
    total, avg_attempts, avg_conf, avg_docs, good, poor = rows
    total = int(total or 0)
    return {
        "total": total,
        "avg_retrieval_attempts": round(float(avg_attempts or 0), 2),
        "avg_confidence": round(float(avg_conf or 0), 3),
        "avg_supporting_documents": round(float(avg_docs or 0), 2),
        "good_pct": round(100.0 * int(good or 0) / total, 1) if total else 0.0,
        "poor_pct": round(100.0 * int(poor or 0) / total, 1) if total else 0.0,
    }


def document_usage(db: Session, limit: int = 8) -> dict:
    top_ref = db.execute(
        select(Document.document_no, Document.name, Document.category, Document.service, func.count(Evidence.id).label("refs"))
        .join(Evidence, Evidence.document_id == Document.id)
        .group_by(Document.id)
        .order_by(func.count(Evidence.id).desc())
        .limit(limit)
    ).all()
    access_counts = db.execute(
        select(DocumentAccess.document_id, func.count(DocumentAccess.id))
        .group_by(DocumentAccess.document_id)
        .order_by(func.count(DocumentAccess.id).desc())
        .limit(limit)
    ).all()
    acc_map = {d: c for d, c in access_counts}
    by_category = db.execute(select(Document.category, func.count(Document.id)).group_by(Document.category)).all()

    per_cat: dict[str, list[dict]] = defaultdict(list)
    for doc_no, name, category, service, refs in top_ref:
        per_cat[category].append(
            {"document_no": doc_no, "name": name, "service": service, "references": int(refs), "access": int(acc_map.get(_doc_id(db, doc_no), 0))}
        )
    return {
        "most_referenced": [
            {"document_no": d, "name": n, "category": c, "service": s, "references": int(r)} for d, n, c, s, r in top_ref
        ],
        "by_category": dict(by_category and {c: int(cnt) for c, cnt in by_category} or {}),
        "runbooks": per_cat.get("RUNBOOK", [])[:5],
        "sops": per_cat.get("SOP", [])[:5],
        "rcas": per_cat.get("RCA", [])[:5],
    }


def _doc_id(db: Session, document_no: str) -> int | None:
    return db.scalar(select(Document.id).where(Document.document_no == document_no))


def documents_stats(db: Session) -> dict:
    total = db.scalar(select(func.count(Document.id))) or 0
    by_type = db.execute(select(Document.type, func.count(Document.id)).group_by(Document.type)).all()
    by_category = db.execute(select(Document.category, func.count(Document.id)).group_by(Document.category)).all()
    chunks = db.scalar(select(func.count(DocumentChunk.id))) or 0
    services = db.execute(
        select(Document.service, func.count(Document.id)).where(Document.service.is_not(None)).group_by(Document.service).order_by(func.count(Document.id).desc()).limit(8)
    ).all()
    return {
        "total": int(total),
        "total_chunks": int(chunks),
        "by_type": [{"type": t or "?", "count": int(c)} for t, c in by_type],
        "by_category": [{"category": cat, "count": int(c)} for cat, c in by_category],
        "top_services": [{"service": s, "count": int(c)} for s, c in services],
    }


def system_stats(db: Session) -> dict:
    total_incidents = db.scalar(select(func.count(Incident.id))) or 0
    resolved = db.scalar(select(func.count(Incident.id)).where(Incident.resolution_status == "RESOLVED")) or 0
    high = db.scalar(select(func.count(Incident.id)).where(Incident.severity.in_(["P0", "P1"]))) or 0
    return {
        "total_incidents": int(total_incidents),
        "resolved": int(resolved),
        "high_severity": int(high),
        "users": int(db.scalar(select(func.count(User.id))) or 0),
        "conversations": int(db.scalar(select(func.count(Conversation.id))) or 0),
        "messages": int(db.scalar(select(func.count(Message.id))) or 0),
        "documents": int(db.scalar(select(func.count(Document.id))) or 0),
    }


def audit_feed(db: Session, limit: int = 50) -> list[dict]:
    rows = db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)).all()
    return [
        {
            "id": a.id,
            "user_id": a.user_id,
            "action": a.action,
            "entity_type": a.entity_type,
            "entity_id": a.entity_id,
            "detail": a.detail,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in rows
    ]
