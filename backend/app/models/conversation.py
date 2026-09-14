"""SQLAlchemy models: conversations, messages, incidents, recommendations, evidence, audit."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.user import utcnow


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(255), default="New incident")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    user: Mapped["User"] = relationship(back_populates="conversations")  # noqa: F821
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="Message.id"
    )
    incidents: Mapped[list["Incident"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))  # user|assistant|system
    content: Mapped[str] = mapped_column(Text)
    incident_id: Mapped[int | None] = mapped_column(
        ForeignKey("incidents.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(24), unique=True, index=True)  # INC-000123
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    description: Mapped[str] = mapped_column(Text)
    service: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    category: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    severity: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    environment: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error: Mapped[str | None] = mapped_column(String(255), nullable=True)
    probable_root_cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolution_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcome: Mapped[str] = mapped_column(String(24), default="UNRESOLVED")  # RESOLVED|UNRESOLVED
    source: Mapped[str] = mapped_column(String(24), default="assistant", index=True)  # assistant|seed
    cause_taxonomy: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)
    retrieval_quality: Mapped[str] = mapped_column(String(16), default="POOR")  # GOOD|FAIR|POOR
    retrieval_attempts: Mapped[int] = mapped_column(Integer, default=1)
    supporting_document_count: Mapped[int] = mapped_column(Integer, default=0)
    evidence_status: Mapped[str] = mapped_column(String(24), default="INSUFFICIENT")
    resolution_status: Mapped[str] = mapped_column(String(24), default="OPEN", index=True)
    pipeline_state: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # user-facing artifacts (no CoT)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

    conversation: Mapped["Conversation | None"] = relationship(back_populates="incidents")
    recommendations: Mapped[list["Recommendation"]] = relationship(
        back_populates="incident", cascade="all, delete-orphan", order_by="Recommendation.priority"
    )
    evidence: Mapped[list["Evidence"]] = relationship(
        back_populates="incident", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_incidents_service_created", "service", "created_at"),)

