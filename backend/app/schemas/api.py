"""API schemas for documents, conversations and chat responses."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

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


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_no: str
    name: str
    title: str | None = None
    type: str
    category: str
    service: str | None = None
    department: str | None = None
    author: str | None = None
    version: str | None = None
    file_size: int = 0
    page_count: int | None = None
    created_at: datetime
    chunk_count: int = 0
    citation_label: str = ""


class DocumentUpdate(BaseModel):
    category: str | None = None
    service: str | None = None
    department: str | None = None
    author: str | None = None
    version: str | None = None
    title: str | None = None


class DocumentDetail(DocumentOut):
    metadata_json: dict | None = None
    chunks: list[dict] = Field(default_factory=list)


class IngestDirectoryRequest(BaseModel):
    path: str = Field(min_length=1, max_length=512)
    reindex: bool = True


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: str
    content: str
    created_at: datetime
    incident_id: int | None = None


class IncidentSummaryOut(BaseModel):
    id: int
    public_id: str
    service: str | None = None
    category: str | None = None
    severity: str | None = None
    description: str
    probable_root_cause: str | None = None
    confidence_score: float
    retrieval_quality: str
    retrieval_attempts: int
    supporting_document_count: int
    evidence_status: str
    resolution_status: str
    created_at: datetime


class ConversationOut(BaseModel):
    id: int
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0
    incident_count: int = 0
    last_incident: IncidentSummaryOut | None = None


class ConversationDetail(BaseModel):
    id: int
    title: str
    created_at: datetime
    updated_at: datetime
    messages: list[MessageOut] = Field(default_factory=list)
    incidents: list[IncidentSummaryOut] = Field(default_factory=list)


class ConversationRename(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class AIResponse(BaseModel):
    """Structured, user-facing pipeline output (no chain-of-thought)."""

    incident_id: int
    public_id: str
    conversation_id: int | None = None
    analysis: IncidentAnalysis
    final_text: str
    summary: str
    root_causes: list[Cause] = Field(default_factory=list)
    troubleshooting: list[TroubleshootingStep] = Field(default_factory=list)
    similar_incidents: list[SimilarIncident] = Field(default_factory=list)
    evidence: list[RetrievedChunk] = Field(default_factory=list)
    evidence_claims: list[EvidenceClaim] = Field(default_factory=list)
    evidence_status: str = "SUPPORTED"
    cause_taxonomy: str = "Other"
    confidence_score: float = 0.0
    confidence_label: str = "Low"
    confidence_breakdown: ConfidenceBreakdown = Field(default_factory=ConfidenceBreakdown)
    retrieval: RetrievalInfo = Field(default_factory=RetrievalInfo)
    retrieval_quality: str = "POOR"
    retrieval_attempts: int = 1
    supporting_document_count: int = 0
    insufficient_evidence: bool = False
    llm_used: bool = False
    embedding_backend: str = ""
    trace: list[NodeTrace] = Field(default_factory=list)
    timestamp: datetime | None = None


class ChatResponse(BaseModel):
    conversation_id: int
    user_message: MessageOut
    assistant_message: MessageOut
    ai: AIResponse


class IncidentDetailOut(AIResponse):
    pass


class KnowledgeSearchResponse(BaseModel):
    query: str
    chunks: list[RetrievedChunk] = Field(default_factory=list)
    by_category: dict[str, int] = Field(default_factory=dict)
    took_ms: float = 0.0


class HealthOut(BaseModel):
    status: str = "ok"
    app: str
    version: str
    llm: dict[str, Any] = Field(default_factory=dict)
    embeddings: dict[str, Any] = Field(default_factory=dict)
    vector_store: dict[str, Any] = Field(default_factory=dict)
    database: str = "ok"
