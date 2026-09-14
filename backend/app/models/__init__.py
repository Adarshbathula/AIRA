"""ORM model registry - import all models so Base.metadata is complete."""
from app.models.conversation import (  # noqa: F401
    Conversation,
    Incident,
    Message,
)
from app.models.document import DOCUMENT_CATEGORIES, Document, DocumentChunk  # noqa: F401
from app.models.evidence import AuditLog, DocumentAccess, Evidence, Recommendation  # noqa: F401
from app.models.user import Role, User  # noqa: F401

__all__ = [
    "Role", "User",
    "Conversation", "Message", "Incident",
    "Document", "DocumentChunk", "DOCUMENT_CATEGORIES",
    "Recommendation", "Evidence", "DocumentAccess", "AuditLog",
]
