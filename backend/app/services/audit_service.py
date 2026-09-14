"""Audit logging for security-relevant mutations."""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models.evidence import AuditLog

logger = logging.getLogger("aira.audit")


def record_audit(
    db: Session,
    user_id: int | None,
    action: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
    detail: dict | None = None,
    ip: str | None = None,
) -> None:
    try:
        db.add(
            AuditLog(
                user_id=user_id,
                action=action,
                entity_type=entity_type,
                entity_id=str(entity_id) if entity_id is not None else None,
                detail=detail,
                ip=ip,
            )
        )
        db.commit()
    except Exception as exc:  # audit must never break the main flow
        logger.warning("audit write failed (%s): %s", action, exc)
        db.rollback()
