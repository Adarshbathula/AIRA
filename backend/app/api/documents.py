"""Document management endpoints (knowledge base)."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import ROLE_ADMIN, get_current_user, require_admin
from app.models.document import DOCUMENT_CATEGORIES, Document, DocumentChunk
from app.models.evidence import DocumentAccess
from app.schemas.api import DocumentDetail, DocumentOut, DocumentUpdate, IngestDirectoryRequest
from app.services import document_service

router = APIRouter(prefix="/documents", tags=["documents"])


def _to_out(db: Session, doc: Document) -> DocumentOut:
    chunk_count = db.scalar(select(func.count(DocumentChunk.id)).where(DocumentChunk.document_id == doc.id)) or 0
    return DocumentOut(
        id=doc.id,
        document_no=doc.document_no,
        name=doc.name,
        title=doc.title,
        type=doc.type,
        category=doc.category,
        service=doc.service,
        department=doc.department,
        author=doc.author,
        version=doc.version,
        file_size=doc.file_size,
        page_count=doc.page_count,
        created_at=doc.created_at,
        chunk_count=int(chunk_count),
        citation_label=doc.citation_label,
    )


@router.post("/upload", response_model=DocumentOut, status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    category: str | None = Form(default=None),
    service: str | None = Form(default=None),
    department: str | None = Form(default=None),
    author: str | None = Form(default=None),
    version: str | None = Form(default=None),
    title: str | None = Form(default=None),
    db: Session = Depends(get_db),
    user=Depends(require_admin),
):
    """Admin ingestion: any supported format -> parse -> chunk -> embed -> FAISS."""
    if category and category.upper() not in DOCUMENT_CATEGORIES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown category '{category}'")
    doc = await document_service.ingest_upload(
        db, file, user_id=user.id, category=category, service=service,
        department=department, author=author, version=version, title=title,
    )
    return _to_out(db, doc)


@router.get("", response_model=dict)
def list_documents(
    search: str | None = None,
    category: str | None = None,
    service: str | None = None,
    department: str | None = None,
    type: str | None = Query(default=None, alias="type"),
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Browse the knowledge base (all authenticated roles); admins get extra filters via query."""
    conds = []
    if search:
        like = f"%{search.strip()}%"
        conds.append(
            (Document.name.ilike(like) | Document.title.ilike(like))
            | (Document.document_no.ilike(like) | Document.service.ilike(like))
        )
    if category:
        conds.append(Document.category == category.upper())
    if service:
        conds.append(Document.service == service)
    if department:
        conds.append(Document.department == department)
    if type:
        conds.append(Document.type == type.lower().lstrip("."))
    if from_date:
        conds.append(Document.created_at >= from_date)
    if to_date:
        conds.append(Document.created_at <= to_date)
    where = None
    if conds:
        from sqlalchemy import and_

        where = and_(*conds)
    stmt = select(Document)
    count_stmt = select(func.count(Document.id))
    if where is not None:
        stmt, count_stmt = stmt.where(where), count_stmt.where(where)
    total = db.scalar(count_stmt) or 0
    docs = db.scalars(stmt.order_by(Document.created_at.desc(), Document.id.desc()).offset(offset).limit(limit)).all()
    return {"total": int(total), "items": [_to_out(db, d).model_dump() for d in docs]}


@router.get("/categories", response_model=list[str])
def categories(user=Depends(get_current_user)):
    return DOCUMENT_CATEGORIES


@router.get("/{document_id}", response_model=DocumentDetail)
def get_document(
    document_id: int,
    include_chunks: bool = Query(default=True),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    db.add(DocumentAccess(document_id=doc.id, user_id=user.id, event="viewed"))
    db.commit()
    base = _to_out(db, doc)
    chunks: list[dict] = []
    if include_chunks:
        rows = db.scalars(
            select(DocumentChunk).where(DocumentChunk.document_id == doc.id).order_by(DocumentChunk.chunk_index).limit(200)
        ).all()
        chunks = [
            {"chunk_ref": c.chunk_ref, "index": c.chunk_index, "section": c.section, "page": c.page,
             "tokens": c.token_estimate, "preview": c.text[:600]}
            for c in rows
        ]
    return DocumentDetail(**base.model_dump(), metadata_json=doc.metadata_json, chunks=chunks)


@router.patch("/{document_id}", response_model=DocumentOut)
def update_document(
    document_id: int,
    payload: DocumentUpdate,
    db: Session = Depends(get_db),
    user=Depends(require_admin),
):
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    doc = document_service.update_document(db, doc, payload.model_dump(exclude_none=True), user.id)
    return _to_out(db, doc)


@router.delete("/{document_id}", status_code=204)
def delete_document(document_id: int, db: Session = Depends(get_db), user=Depends(require_admin)):
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    document_service.delete_document(db, doc, user.id)


@router.post("/ingest-directory", response_model=dict, status_code=202)
def ingest_directory(payload: IngestDirectoryRequest, db: Session = Depends(get_db), user=Depends(require_admin)):
    """Bulk-ingest a local folder of enterprise documents (admin, demo/seed helper)."""
    report = document_service.ingest_directory(db, payload.path, user_id=user.id)
    return {"stored": report.stored, "skipped": report.skipped[:20], "errors": report.errors[:20]}
