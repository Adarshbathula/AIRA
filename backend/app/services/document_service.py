"""Document ingestion service: upload -> parse -> metadata -> chunk -> embed -> FAISS."""
from __future__ import annotations

import hashlib
import logging
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.conversation import Incident
from app.models.document import DOCUMENT_CATEGORIES, Document, DocumentChunk
from app.rag.ingestion.chunking import chunk_document_text, clean_text
from app.rag.ingestion.parsers import DocumentParseError, parse_bytes
from app.services import rag_service
from app.services.audit_service import record_audit

logger = logging.getLogger("aira.documents")

_CATEGORY_HINTS = {
    "runbook": "RUNBOOK",
    "sop": "SOP",
    "rca": "RCA",
    "jira": "JIRA_INCIDENT",
    "postmortem": "POSTMORTEM",
    "deployment": "DEPLOYMENT_GUIDE",
    "troubleshoot": "TROUBLESHOOTING_GUIDE",
    "architecture": "ARCHITECTURE",
    "knowledge": "KNOWLEDGE_BASE",
    "kb": "KNOWLEDGE_BASE",
    "change": "CHANGE_REQUEST",
    "incident": "INCIDENT_REPORT",
    "log": "LOG",
}
_REF_RE = re.compile(r"\b((?:RUNBOOK|SOP|RCA|INC|CHG|DOC|POST|KB)[-_][A-Z0-9\-]{1,20})", re.I)


@dataclass
class IngestReport:
    stored: int = 0
    incidents: int = 0
    skipped: list[str] = None  # type: ignore[assignment]
    errors: list[str] = None   # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.skipped = self.skipped or []
        self.errors = self.errors or []


def guess_category(name: str) -> str:
    low = name.lower()
    for hint, cat in _CATEGORY_HINTS.items():
        if hint in low:
            return cat
    return "KNOWLEDGE_BASE"


def extract_reference(name: str, text: str) -> str | None:
    """A stable citation label like RUNBOOK-005 / INC-542 from filename or head."""
    m = _REF_RE.search(Path(name).stem)
    if m:
        return m.group(1).upper().replace("_", "-")
    head = "\n".join(text.splitlines()[:14])
    m = _REF_RE.search(head)
    if m:
        return m.group(1).upper().replace("_", "-")
    return None


def sanitize_filename(filename: str | None) -> str:
    name = Path(filename or "document").name
    name = re.sub(r"[^A-Za-z0-9._\- ]+", "_", name).strip(" .") or "document.txt"
    return name[:180]


def next_document_no(db: Session) -> str:
    count = db.scalar(select(func.count(Document.id))) or 0
    n = count + 1
    while db.scalar(select(Document).where(Document.document_no == f"DOC-{n:04d}")) is not None:
        n += 1
    return f"DOC-{n:04d}"


async def ingest_upload(
    db: Session,
    file: UploadFile,
    *,
    user_id: int,
    category: str | None = None,
    service: str | None = None,
    department: str | None = None,
    author: str | None = None,
    version: str | None = None,
    title: str | None = None,
) -> Document:
    s = get_settings()
    filename = sanitize_filename(file.filename)
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    if ext not in s.allowed_extensions_set:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"Unsupported file type '{ext or 'unknown'}'. Allowed: {', '.join(sorted(s.allowed_extensions_set))}",
        )
    data = await file.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Uploaded file is empty")
    if len(data) > s.max_upload_bytes:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"File exceeds the {s.max_upload_mb} MB limit",
        )

    try:
        parsed = parse_bytes(data, filename)
    except DocumentParseError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    text = clean_text(parsed.text)
    if len(text) < 40:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Document contains too little extractable text to be useful (empty or binary-only file)",
        )

    content_hash = hashlib.sha256(text.lower().encode("utf-8")).hexdigest()
    dupe = db.scalar(select(Document).where(Document.content_hash == content_hash))
    if dupe is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Identical content is already in the knowledge base as {dupe.document_no} ({dupe.name})",
        )

    stored_path = s.documents_dir / f"{int(time.time() * 1000)}_{filename}"
    try:
        stored_path.write_bytes(data)
    except OSError as exc:  # pragma: no cover
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Could not persist file: {exc}") from exc

    doc = _store_parsed(
        db,
        filename=filename,
        ext=ext,
        text=text,
        hints=parsed.hints,
        page_count=parsed.page_count,
        size=len(data),
        stored_path=stored_path,
        user_id=user_id,
        category=category,
        service=service,
        department=department,
        author=author,
        version=version,
        title=title,
    )
    record_audit(db, user_id, "document.upload", "document", doc.document_no, {"name": filename, "chunks": len(doc.chunks)})
    return doc


def _store_parsed(
    db: Session,
    *,
    filename: str,
    ext: str,
    text: str,
    hints: dict,
    page_count: int | None,
    size: int,
    stored_path: Path | None,
    user_id: int | None,
    content_hash: str | None = None,
    category: str | None = None,
    service: str | None = None,
    department: str | None = None,
    author: str | None = None,
    version: str | None = None,
    title: str | None = None,
) -> Document:
    s = get_settings()
    cat = (category or hints.get("category") or guess_category(filename)).upper()
    if cat not in DOCUMENT_CATEGORIES:
        cat = "KNOWLEDGE_BASE"
    ref = extract_reference(filename, text)
    digest = content_hash or hashlib.sha256(text.lower().encode("utf-8")).hexdigest()
    existing = db.scalar(select(Document).where(Document.content_hash == digest))
    if existing is not None:  # bulk re-seeding must be idempotent
        return existing
    doc_no = next_document_no(db)
    doc = Document(
        document_no=doc_no,
        name=filename,
        title=title or hints.get("title") or Path(filename).stem.replace("_", " ").replace("-", " ")[:200],
        type=ext.lstrip("."),
        category=cat,
        service=service or hints.get("service"),
        department=department or hints.get("department"),
        author=author or hints.get("author"),
        version=version or hints.get("version"),
        source="upload" if user_id else "seed",
        source_path=str(stored_path) if stored_path else None,
        file_size=size,
        page_count=page_count,
        content_hash=digest,
        uploaded_by=user_id,
        metadata_json={"ref": ref} if ref else {},
    )
    db.add(doc)
    db.flush()

    _chunk_and_store(db, doc, text)
    db.refresh(doc)
    rag_service.index_document(db, doc)
    db.commit()
    db.refresh(doc)

    # structured incident records (JSON/CSV knowledge sources) feed history search
    for rec in (hints.get("incident_records") or [])[:500]:
        _upsert_seed_incident(db, rec)
    return doc


def _chunk_and_store(db: Session, doc: Document, text: str) -> list[DocumentChunk]:
    s = get_settings()
    out: list[DocumentChunk] = []
    for idx, section, chunk in chunk_document_text(text, s.chunk_size, s.chunk_overlap, s.max_chunks_per_document):
        ref = f"{doc.document_no}-C{idx:03d}"
        page = None
        m = re.search(r"---\s*Page\s+(\d+)\s*---", chunk)
        if m:
            page = int(m.group(1))
        dc = DocumentChunk(
            chunk_ref=ref,
            document_id=doc.id,
            chunk_index=idx,
            text=chunk,
            section=section,
            page=page,
            token_estimate=max(1, len(chunk) // 4),
            embedding_model=get_settings().embedding_model if s.embedding_provider != "lightweight" else "lightweight-hash",
        )
        db.add(dc)
        out.append(dc)
    db.flush()
    return out


_INCIDENT_FIELDS = ("id", "incident_id", "public_id", "title", "summary", "description", "service", "severity", "category", "root_cause", "resolution", "outcome", "date", "created_at")


def _upsert_seed_incident(db: Session, rec: dict) -> Incident | None:
    getter = lambda *keys: next((rec[k] for k in keys if isinstance(rec.get(k), (str, int)) and str(rec[k]).strip()), None)  # noqa: E731
    pid = getter("id", "incident_id", "public_id")
    desc = getter("description", "summary", "title")
    if not pid or not desc:
        return None
    pid = str(pid)
    existing = db.scalar(select(Incident).where(Incident.public_id == pid))
    if existing:
        return None  # already in the history store: nothing new added
    inc = Incident(
        public_id=pid,
        description=str(desc),
        service=getter("service"),
        category=getter("category") or "General",
        severity=(getter("severity") or "P3"),
        environment=getter("environment") or "Production",
        probable_root_cause=getter("root_cause", "probable_root_cause"),
        resolution_summary=getter("resolution", "root_cause"),
        outcome="RESOLVED" if (getter("resolution") or getter("outcome") == "RESOLVED") else "UNRESOLVED",
        source="seed",
        confidence_score=float(rec.get("confidence_score") or 0.0),
    )
    db.add(inc)
    db.flush()
    rag_service.index_incident(inc)
    return inc


def delete_document(db: Session, doc: Document, user_id: int | None = None) -> None:
    rag_service.remove_document_from_store(db, doc.id)
    path = doc.source_path  # only set for uploads, which own their stored copy
    if path is not None:
        # belt and braces: never unlink the curated sample corpus (older rows may
        # still point at seed files that bulk ingestion owns, not us)
        stored = Path(path)
        if stored.parent != get_settings().documents_dir or not re.match(r"^\d{10,}_", stored.name):
            path = None
    db.delete(doc)
    db.commit()
    if path:
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:
            logger.warning("Could not remove stored file %s", path)
    record_audit(db, user_id, "document.delete", "document", doc.document_no, {"name": doc.name})


def update_document(db: Session, doc: Document, changes: dict, user_id: int | None = None) -> Document:
    meta = dict(doc.metadata_json or {})
    for k, v in changes.items():
        if v is None:
            continue
        if k == "category":
            v = str(v).upper()
            if v not in DOCUMENT_CATEGORIES:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown category '{v}'")
        if k == "ref":
            meta["ref"] = str(v).strip()[:40] or None
            continue
        setattr(doc, k, v)
    doc.metadata_json = meta
    db.commit()
    db.refresh(doc)
    # category/service/citation changes must be visible to retrieval immediately
    rag_service.index_document(db, doc)
    db.commit()
    record_audit(db, user_id, "document.update", "document", doc.document_no, changes)
    return doc


def ingest_directory(db: Session, path: str | Path, *, user_id: int | None = None, pattern: str = "*", only_incidents: bool = False) -> IngestReport:
    """Bulk ingestion used by the seed script and the admin ingest endpoint."""
    report = IngestReport()
    root = Path(path)
    if not root.exists() or not root.is_dir():
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Directory not found: {root}")
    s = get_settings()
    upload_copy = re.compile(r"^\d{10,}_")  # timestamped copies written by the upload API
    for f in sorted(root.rglob(pattern)):
        if not f.is_file():
            continue
        if root == s.documents_dir and upload_copy.match(f.name):
            report.skipped.append(f"{f.name} (upload copy)")  # already owned by an upload row
            continue
        ext = f.suffix.lower()
        if ext not in s.allowed_extensions_set or f.name.startswith("."):
            report.skipped.append(f.name)
            continue
        try:
            data = f.read_bytes()
            parsed = parse_bytes(data, f.name)
            text = clean_text(parsed.text)
            if len(text) < 40:
                report.skipped.append(f"{f.name} (too little text)")
                continue
            digest = hashlib.sha256(text.lower().encode("utf-8")).hexdigest()
            if db.scalar(select(Document).where(Document.content_hash == digest)) is not None:
                report.skipped.append(f"{f.name} (already ingested)")
                continue
            # incident-export files feed the *history* store, not the KB corpus
            if only_incidents:
                recs = (parsed.hints or {}).get("incident_records") or []
                if not recs:
                    report.skipped.append(f"{f.name} (no incident records)")
                    continue
                n = 0
                for rec in recs[:1000]:
                    if _upsert_seed_incident(db, rec):
                        n += 1
                db.commit()
                report.stored += 1
                report.incidents += n
                report.skipped.append(f"{f.name}: {n} incident records")
                continue
            _store_parsed(
                db,
                content_hash=digest,
                filename=f.name,
                ext=ext,
                text=text,
                hints=parsed.hints,
                page_count=parsed.page_count,
                size=len(data),
                stored_path=None,  # seed corpus: we never copy or own these files
                user_id=user_id,
            )
            report.stored += 1
        except DocumentParseError as exc:
            report.errors.append(f"{f.name}: {exc}")
        except Exception as exc:  # corrupted file etc.: record and continue
            logger.warning("Ingestion failed for %s: %s", f, exc)
            report.errors.append(f"{f.name}: {type(exc).__name__}")
    if report.stored:
        rag_service.sync_stores(db)
    return report


def reindex_everything(db: Session) -> dict:
    """Force rebuild of both vector stores from the DB (admin action)."""
    from app.rag.runtime import get_runtime

    rt = get_runtime()
    with rt.lock:
        rt.document_store.reset()
        rt.incident_store.reset()
    # after reset() every DB row counts as missing, so sync_stores performs a full rebuild
    return rag_service.sync_stores(db)
