"""Schemas describing the AI pipeline artifacts (also used as LangGraph payloads)."""
from __future__ import annotations

from pydantic import BaseModel, Field


class IncidentAnalysis(BaseModel):
    """Structured extraction produced by the Incident Analyzer node."""

    service: str | None = None
    error: str | None = None
    environment: str | None = None
    event: str | None = None
    category: str = "General"
    severity: str = "P3"
    symptoms: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    confidence: float = 0.5


class RetrievedChunk(BaseModel):
    chunk_ref: str
    document_id: int | None = None
    document_no: str | None = None
    citation: str = ""
    document_name: str = ""
    category: str = "KNOWLEDGE_BASE"
    service: str | None = None
    section: str | None = None
    page: int | None = None
    text: str = ""
    score: float = 0.0


class GraderResult(BaseModel):
    quality: str = "POOR"          # GOOD | FAIR | POOR
    score: float = 0.0             # 0..1
    signals: dict = Field(default_factory=dict)
    feedback: str = ""


class SimilarIncident(BaseModel):
    public_id: str
    title: str = ""
    service: str | None = None
    severity: str | None = None
    similarity: float = 0.0        # 0..1 (shown as %)
    root_cause: str | None = None
    resolution: str | None = None
    outcome: str = "UNRESOLVED"
    created_at: str | None = None


class Cause(BaseModel):
    label: str = ""
    description: str = ""
    status: str = "POSSIBLE"       # CONFIRMED | PROBABLE | POSSIBLE | INSUFFICIENT_EVIDENCE
    probability: str = "Low"       # High | Medium | Low
    evidence: list[str] = Field(default_factory=list)


class TroubleshootingStep(BaseModel):
    step: str
    evidence: list[str] = Field(default_factory=list)
    evidence_status: str = "INSUFFICIENT"   # SUPPORTED | PARTIALLY_SUPPORTED | INSUFFICIENT
    source_categories: list[str] = Field(default_factory=list)
    priority: int = 1


class ConfidenceBreakdown(BaseModel):
    retrieval_quality: float = 0.0
    supporting_documents: float = 0.0
    evidence_consistency: float = 0.0
    similar_incidents: float = 0.0
    grader_score: float = 0.0
    evidence_validation: float = 0.0
    notes: list[str] = Field(default_factory=list)


class EvidenceClaim(BaseModel):
    claim: str
    kind: str = "recommendation"    # recommendation | root_cause | summary
    evidence: list[str] = Field(default_factory=list)
    status: str = "INSUFFICIENT"    # SUPPORTED | PARTIALLY_SUPPORTED | INSUFFICIENT
    detail: str | None = None


class RetrievalInfo(BaseModel):
    attempts: int = 1
    queries: list[str] = Field(default_factory=list)
    grader: GraderResult | None = None
    scores: list[float] = Field(default_factory=list)
    documents_used: list[str] = Field(default_factory=list)


class NodeTrace(BaseModel):
    node: str
    status: str = "ok"              # ok|retry|fail|skipped
    ms: float = 0.0
    detail: str | None = None


class ChatRequest(BaseModel):
    message: str = Field(min_length=4, max_length=6000)
    conversation_id: int | None = None
    follow_up: bool = False


class SimilarIncidentRequest(BaseModel):
    incident_id: int | None = None
    description: str | None = None
    top_k: int = Field(default=5, ge=1, le=20)


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=1000)
    categories: list[str] | None = None
    service: str | None = None
    top_k: int = Field(default=10, ge=1, le=30)
