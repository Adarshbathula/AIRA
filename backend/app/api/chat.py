"""Chat endpoints: incident conversation with the AI assistant."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.conversation import Message
from app.schemas.api import ChatResponse, ConversationDetail, ConversationOut, ConversationRename, MessageOut
from app.schemas.incident import ChatRequest
from app.services import conversation_service, incident_service

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Submit an incident (or follow-up) and receive the structured AI answer.

    Runs the full Self-Healing RAG LangGraph workflow, persists the
    conversation, incident, recommendations and evidence, and returns the
    user-facing reasoning artifacts (never chain-of-thought).
    """
    conv, inc, ai = incident_service.analyze_incident(
        db,
        user,
        payload.message,
        conversation_id=payload.conversation_id,
        follow_up=payload.follow_up,
    )
    if conv is None:  # defensive: analyze always creates one when missing
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Conversation could not be created")
    return ChatResponse(
        conversation_id=conv.id,
        user_message=_last_message(db, conv.id, "user"),
        assistant_message=_last_message(db, conv.id, "assistant"),
        ai=ai,
    )


def _last_message(db: Session, conv_id: int, role: str) -> MessageOut:
    m = db.scalar(
        select(Message)
        .where(Message.conversation_id == conv_id, Message.role == role)
        .order_by(Message.id.desc())
        .limit(1)
    )
    return MessageOut(id=m.id, role=m.role, content=m.content, created_at=m.created_at, incident_id=m.incident_id)


@router.get("/conversations", response_model=list[ConversationOut])
def list_conversations(
    search: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return conversation_service.list_conversations(db, user, search=search, limit=limit)


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
def get_conversation(conversation_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    conv = conversation_service.get_conversation(db, conversation_id, user)
    return conversation_service.conversation_detail(db, conv)


@router.patch("/conversations/{conversation_id}", response_model=ConversationOut)
def rename_conversation(
    conversation_id: int,
    payload: ConversationRename,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    conv = conversation_service.get_conversation(db, conversation_id, user)
    conv = conversation_service.rename_conversation(db, conv, payload.title)
    return next((c for c in conversation_service.list_conversations(db, user, limit=200) if c.id == conv.id),
                ConversationOut(id=conv.id, title=conv.title, created_at=conv.created_at, updated_at=conv.updated_at))


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    conv = conversation_service.get_conversation(db, conversation_id, user)
    conversation_service.delete_conversation(db, conv)
