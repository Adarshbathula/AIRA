#!/usr/bin/env python3
"""Housekeeping helpers for the AIRA database.

    python scripts/maintenance.py dedupe            # remove duplicate documents/incidents
    python scripts/maintenance.py backfill-hashes   # compute content_hash for pre-existing rows
    python scripts/maintenance.py status            # row counts

Safe to run repeatedly; the API/seed flow no longer creates duplicates because
ingestion is content-hashed (see app/services/document_service.py).
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import select  # noqa: E402

from app.core.config import get_settings  # noqa: E402


def _session():
    from app.core.database import Base, SessionLocal, engine, ensure_columns
    import app.models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    added = ensure_columns()
    if added:
        print("added columns:", ", ".join(added))
    return SessionLocal()


def backfill_hashes() -> None:
    from app.models.document import Document
    from app.rag.ingestion.chunking import clean_text

    db = _session()
    try:
        n = 0
        for doc in db.scalars(select(Document).where(Document.content_hash.is_(None))):
            text = "\n".join(c.text for c in sorted(doc.chunks, key=lambda c: c.chunk_index))
            if not text and doc.source_path and Path(doc.source_path).exists():
                raw = Path(doc.source_path).read_bytes()
                from app.rag.ingestion.parsers import DocumentParseError, parse_bytes

                try:
                    text = clean_text(parse_bytes(raw, doc.name).text)
                except DocumentParseError:
                    text = ""
            doc.content_hash = hashlib.sha256(text.lower().encode("utf-8")).hexdigest() if text else None
            n += 1
        db.commit()
        print(f"backfilled content_hash for {n} document(s)")
    finally:
        db.close()


def dedupe() -> None:
    """Drop later copies of documents (same content_hash/name) and incidents (same public_id)."""
    from app.models.conversation import Incident
    from app.models.document import Document
    from app.services import rag_service

    db = _session()
    try:
        removed_docs = 0
        seen: dict[tuple, int] = {}
        for doc in db.scalars(select(Document).order_by(Document.id)):
            key = (doc.content_hash, doc.name)
            if key in seen:
                db.delete(doc)  # chunks cascade (document_id FK ondelete cascade + ORM cascade)
                removed_docs += 1
            else:
                seen[key] = doc.id
        db.commit()

        removed_inc = 0
        seen_inc: set[str] = set()
        for inc in db.scalars(select(Incident).order_by(Incident.id)):
            if inc.public_id in seen_inc:
                db.delete(inc)
                removed_inc += 1
            else:
                seen_inc.add(inc.public_id)
        db.commit()

        stats = rag_service.sync_stores(db)
        print(f"removed {removed_docs} duplicate document(s), {removed_inc} duplicate incident(s); resync -> {stats}")
    finally:
        db.close()


def status() -> None:
    from sqlalchemy import func

    from app.models.conversation import Conversation, Incident, Message
    from app.models.document import Document, DocumentChunk
    from app.models.evidence import Evidence, Recommendation
    from app.models.user import User

    db = _session()
    try:
        for model in (User, Document, DocumentChunk, Incident, Conversation, Message, Recommendation, Evidence):
            name = model.__tablename__
            print(f"  {name:20s} {db.scalar(select(func.count()).select_from(model))}")
        dupes = db.execute(
            select(Document.content_hash, func.count()).group_by(Document.content_hash).having(func.count() > 1)
        ).all()
        print(f"  duplicate content hashes: {len(dupes)}")
    finally:
        db.close()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    {"dedupe": dedupe, "backfill-hashes": backfill_hashes, "status": status}.get(cmd, status)()
