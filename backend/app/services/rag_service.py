"""Index management: keeps PostgreSQL and the FAISS stores in sync.

* ``sync_stores`` rebuilds vector stores from the DB when indexes are missing
  or stale (fresh clone / cleared cache).
* ``index_document`` adds/replaces a document's chunks in the store.
* ``index_incident`` keeps the similar-incident store current as incidents are
  created or resolved.
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.conversation import Incident
from app.models.document import Document, DocumentChunk
from app.rag.retrieval.incident_store import incident_vector_text
from app.rag.runtime import get_runtime
from app.rag.vectorstore.faiss_store import VRecord

logger = logging.getLogger("aira.index")


def document_record_meta(doc: Document, chunk: DocumentChunk) -> dict:
    return {
        "document_id": doc.id,
        "document_no": doc.document_no,
        "citation": doc.citation_label,
        "document_name": doc.name,
        "category": doc.category,
        "service": doc.service,
        "department": doc.department,
        "chunk_index": chunk.chunk_index,
        "section": chunk.section,
        "page": chunk.page,
    }


def index_document(db: Session, doc: Document, *, embed: bool = True) -> int:
    rt = get_runtime()
    chunks = list(doc.chunks) if doc.chunks is not None else list(
        db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == doc.id).order_by(DocumentChunk.chunk_index))
    )
    with rt.lock:
        if not embed:
            return 0
        records = [
            VRecord(ref=c.chunk_ref, text=c.text, metadata=document_record_meta(doc, c)) for c in chunks
        ]
        if records:
            rt.document_store.upsert(records)
            rt.document_store.commit()
    return len(records)


def remove_document_from_store(db: Session, doc_id: int) -> None:
    rt = get_runtime()
    refs = {r for (r,) in db.execute(select(DocumentChunk.chunk_ref).where(DocumentChunk.document_id == doc_id))}
    if refs:
        with rt.lock:
            rt.document_store.delete_refs(refs)


def incident_public_id(inc: Incident) -> str:
    return inc.public_id


def incident_record(inc: Incident) -> VRecord:
    meta = {
        "public_id": inc.public_id,
        "incident_id": inc.id,
        "service": inc.service,
        "category": inc.category,
        "severity": inc.severity,
        "title": (inc.description or "").splitlines()[0][:140] if inc.description else "",
        "root_cause": inc.probable_root_cause,
        "resolution": inc.resolution_summary,
        "outcome": inc.outcome,
        "created_at": inc.created_at.strftime("%Y-%m-%d") if inc.created_at else None,
        "source": inc.source,
    }
    text = incident_vector_text(inc.description or "", inc.service, inc.category, inc.probable_root_cause)
    return VRecord(ref=inc.public_id, text=text, metadata=meta)


def index_incident(inc: Incident) -> None:
    rt = get_runtime()
    with rt.lock:
        rt.incident_store.upsert([incident_record(inc)])
        rt.incident_store.commit()


def remove_incident_from_store(inc: Incident) -> None:
    rt = get_runtime()
    with rt.lock:
        rt.incident_store.delete_refs({inc.public_id})


def sync_stores(db: Session) -> dict:
    """Ensure FAISS stores mirror the database. Cheap no-op when in sync."""
    s = get_settings()
    rt = get_runtime()
    doc_count = db.scalar(select(Document).limit(1)) is not None
    stats = {"documents_indexed": 0, "incidents_indexed": 0, "rebuilt": False}

    with rt.lock:
        docs_in_store = rt.document_store.records
        need_doc_rebuild = doc_count and len(docs_in_store) == 0
        if need_doc_rebuild:
            rt.document_store.reset()
            for doc in db.scalars(select(Document)):
                chunks = list(db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == doc.id).order_by(DocumentChunk.chunk_index)))
                recs = [VRecord(ref=c.chunk_ref, text=c.text, metadata=document_record_meta(doc, c)) for c in chunks]
                if recs:
                    rt.document_store.add(recs)
                    stats["documents_indexed"] += len(recs)
            rt.document_store.commit()
            stats["rebuilt"] = True

        inc_rows = list(db.scalars(select(Incident).where(Incident.description.is_not(None))))
        store_refs = {r.ref for r in rt.incident_store.records}
        missing = [i for i in inc_rows if i.public_id not in store_refs]
        if missing:
            rt.incident_store.add([incident_record(i) for i in missing])
            rt.incident_store.commit()
            stats["incidents_indexed"] = len(missing)

    logger.info("store sync: %s (embedding=%s)", stats, rt.embeddings.model_name)
    return stats
