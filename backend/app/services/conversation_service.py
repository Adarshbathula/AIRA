"""Conversation management: titles, history, search, deletion."""
from __future__ import annotations

import re

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.security import ensure_user_ownership
from app.models.conversation import Conversation, Incident, Message
from app.schemas.api import ConversationDetail, ConversationOut, IncidentSummaryOut

_TITLE_CLEAN = re.compile(r"\s+")


def clean_title(text: str, limit: int = 72) -> str:
    t = _TITLE_CLEAN.sub(" ", (text or "")).strip().rstrip(" .,;")
    t = t[:1].upper() + t[1:] if t else "New incident"
    return (t[: limit - 1] + "…") if len(t) > limit else t


def create_conversation(db: Session, user_id: int, first_message: str) -> Conversation:
    conv = Conversation(user_id=user_id, title=clean_title(first_message))
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return conv


def get_conversation(db: Session, conv_id: int, user) -> Conversation:
    conv = db.get(Conversation, conv_id)
    if conv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    ensure_user_ownership(user, conv.user_id)
    return conv


def list_conversations(db: Session, user, *, search: str | None = None, limit: int = 100) -> list[ConversationOut]:
    stmt = select(Conversation).where(Conversation.user_id == user.id if user.role != "admin" else True)
    if search:
        like = f"%{search.strip()}%"
        conv_ids = select(Message.conversation_id).where(Message.content.ilike(like))
        stmt = stmt.where(or_(Conversation.title.ilike(like), Conversation.id.in_(conv_ids)))
    stmt = stmt.order_by(Conversation.updated_at.desc()).limit(max(1, min(limit, 200)))
    out: list[ConversationOut] = []
    for conv in db.scalars(stmt):
        msg_count = db.scalar(select(func.count(Message.id)).where(Message.conversation_id == conv.id)) or 0
        inc_count = db.scalar(select(func.count(Incident.id)).where(Incident.conversation_id == conv.id)) or 0
        last_inc = db.scalar(
            select(Incident).where(Incident.conversation_id == conv.id).order_by(Incident.id.desc()).limit(1)
        )
        out.append(
            ConversationOut(
                id=conv.id,
                title=conv.title,
                created_at=conv.created_at,
                updated_at=conv.updated_at,
                message_count=msg_count,
                incident_count=inc_count,
                last_incident=_incident_brief(last_inc) if last_inc else None,
            )
        )
    return out


def conversation_detail(db: Session, conv: Conversation) -> ConversationDetail:
    from app.schemas.api import MessageOut

    msgs = [
        MessageOut(id=m.id, role=m.role, content=m.content, created_at=m.created_at, incident_id=m.incident_id)
        for m in conv.messages
    ]
    incs = [_incident_brief(i) for i in sorted(conv.incidents, key=lambda i: i.id)]
    return ConversationDetail(
        id=conv.id, title=conv.title, created_at=conv.created_at, updated_at=conv.updated_at,
        messages=msgs, incidents=incs,
    )


def rename_conversation(db: Session, conv: Conversation, title: str) -> Conversation:
    conv.title = clean_title(title, 200)
    db.commit()
    db.refresh(conv)
    return conv


def delete_conversation(db: Session, conv: Conversation) -> None:
    db.delete(conv)
    db.commit()


def append_message(db: Session, conv: Conversation, role: str, content: str, incident_id: int | None = None) -> Message:
    msg = Message(conversation_id=conv.id, role=role, content=content, incident_id=incident_id)
    db.add(msg)
    from datetime import datetime, timezone

    conv.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    db.refresh(msg)
    return msg


def _incident_brief(inc: Incident) -> IncidentSummaryOut:
    return IncidentSummaryOut(
        id=inc.id,
        public_id=inc.public_id,
        service=inc.service,
        category=inc.category,
        severity=inc.severity,
        description=(inc.description or "")[:600],
        probable_root_cause=(inc.probable_root_cause or "")[:400] or None,
        confidence_score=round(float(inc.confidence_score or 0.0), 4),
        retrieval_quality=inc.retrieval_quality,
        retrieval_attempts=inc.retrieval_attempts,
        supporting_document_count=inc.supporting_document_count,
        evidence_status=inc.evidence_status,
        resolution_status=inc.resolution_status,
        created_at=inc.created_at,
    )
