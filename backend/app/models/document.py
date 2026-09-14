"""SQLAlchemy models: enterprise knowledge documents and their chunks."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.user import utcnow

DOCUMENT_CATEGORIES = [
    "SOP",
    "RUNBOOK",
    "JIRA_INCIDENT",
    "RCA",
    "INCIDENT_REPORT",
    "ARCHITECTURE",
    "DEPLOYMENT_GUIDE",
    "TROUBLESHOOTING_GUIDE",
    "KNOWLEDGE_BASE",
    "CHANGE_REQUEST",
    "POSTMORTEM",
    "LOG",
]


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)  # DOC-0001
    name: Mapped[str] = mapped_column(String(512))  # file name
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    type: Mapped[str] = mapped_column(String(64), default="txt")  # file extension
    category: Mapped[str] = mapped_column(String(32), default="KNOWLEDGE_BASE", index=True)
    service: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    department: Mapped[str | None] = mapped_column(String(120), nullable=True)
    author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)  # upload|seed
    source_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)  # sha256 of extracted text
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    uploaded_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    uploader: Mapped["User | None"] = relationship(back_populates="documents")  # noqa: F821
    chunks: Mapped[list["DocumentChunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="DocumentChunk.chunk_index"
    )

    __table_args__ = (Index("ix_documents_category_service", "category", "service"),)

    @property
    def citation_label(self) -> str:
        """Human-readable citation used across the UI and AI answers."""
        meta = self.metadata_json or {}
        if meta.get("ref"):
            return str(meta["ref"])
        return self.document_no


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chunk_ref: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # DOC-0001-C004
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text)
    section: Mapped[str | None] = mapped_column(String(255), nullable=True)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_estimate: Mapped[int] = mapped_column(Integer, default=0)
    embedding_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    document: Mapped["Document"] = relationship(back_populates="chunks")
