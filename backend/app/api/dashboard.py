"""Dashboard endpoints (user + admin analytics)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user, require_admin
from app.services import analytics_service

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/overview")
def overview(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """KPI cards for both roles; admin-only fields are pruned server-side."""
    return analytics_service.overview(db, user)


@router.get("/incidents")
def incidents(days: int = Query(default=14, ge=3, le=90), db: Session = Depends(get_db), user=Depends(get_current_user)):
    return {
        "trends": analytics_service.incident_trends(db, user, days=days),
        "recent": analytics_service.recent_incidents(db, user, limit=10),
        "top_services": analytics_service.top_services(db, user),
    }


@router.get("/root-causes")
def root_causes(db: Session = Depends(get_db), user=Depends(get_current_user)):
    return analytics_service.root_cause_stats(db, user)


@router.get("/confidence")
def confidence(db: Session = Depends(get_db), user=Depends(get_current_user)):
    return analytics_service.confidence_distribution(db, user)


@router.get("/documents")
def documents(db: Session = Depends(get_db), user=Depends(get_current_user)):
    return analytics_service.documents_stats(db)


@router.get("/retrieval")
def retrieval(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Retrieval quality stats (admin-grade metrics; safe to expose)."""
    return analytics_service.retrieval_stats(db, user)


# --------------------------------------------------------------- admin-only
@router.get("/usage")
def usage(limit: int = Query(default=8, ge=3, le=25), db: Session = Depends(get_db), admin=Depends(require_admin)):
    """Knowledge-base usage: most referenced runbooks/SOPs/RCA reports."""
    return analytics_service.document_usage(db, limit=limit)


@router.get("/system")
def system(db: Session = Depends(get_db), admin=Depends(require_admin)):
    return analytics_service.system_stats(db)


@router.get("/audit")
def audit(limit: int = Query(default=50, ge=5, le=200), db: Session = Depends(get_db), admin=Depends(require_admin)):
    return analytics_service.audit_feed(db, limit=limit)
