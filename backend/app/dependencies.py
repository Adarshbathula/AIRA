"""Shared FastAPI dependencies (re-exported for convenience in routers/tests)."""
from __future__ import annotations

from app.core.database import get_db
from app.core.security import ensure_user_ownership, get_current_user, require_admin

__all__ = ["get_db", "get_current_user", "require_admin", "ensure_user_ownership"]
