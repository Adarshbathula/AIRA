"""Authentication service: register / login / bootstrap accounts."""
from __future__ import annotations

import logging

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import ROLE_ADMIN, ROLE_USER, VALID_ROLES, create_access_token, hash_password, verify_password
from app.models.user import Role, User
from app.schemas.user import LoginRequest, RegisterRequest, TokenResponse
from app.services.audit_service import record_audit

logger = logging.getLogger("aira.auth")


def ensure_roles(db: Session) -> None:
    for name, desc in ((ROLE_USER, "Engineer - can analyze incidents and search the knowledge base"),
                       (ROLE_ADMIN, "Administrator - full access incl. documents, users, analytics")):
        if db.scalar(select(Role).where(Role.name == name)) is None:
            db.add(Role(name=name, description=desc))
    db.commit()


def bootstrap_admin(db: Session) -> User | None:
    """Create the initial admin account if no users exist yet (from .env, never hard-coded)."""
    s = get_settings()
    ensure_roles(db)
    count = db.scalar(select(func.count(User.id))) or 0
    if count > 0:
        return None
    admin = User(
        name="Platform Admin",
        email=s.bootstrap_admin_email.lower(),
        password_hash=hash_password(s.bootstrap_admin_password),
        role=ROLE_ADMIN,
    )
    db.add(admin)
    try:
        db.commit()
    except IntegrityError:  # pragma: no cover - race guard
        db.rollback()
        return None
    db.refresh(admin)
    logger.info("Bootstrapped admin user '%s'", admin.email)
    return admin


def ensure_demo_user(db: Session) -> User | None:
    """Create the demo engineer account from env (used by the seed script/dev setup).

    Unlike ``bootstrap_admin`` this is deliberately idempotent *after* users exist:
    a demo environment should always end up with a non-admin login, so the account
    is created if missing and left untouched otherwise.
    """
    s = get_settings()
    email = (s.bootstrap_user_email or "").strip().lower()
    if not email:
        return None
    user = db.scalar(select(User).where(User.email == email))
    if user is not None:
        return user
    ensure_roles(db)
    user = User(
        name="Site Reliability Engineer",
        email=email,
        password_hash=hash_password(s.bootstrap_user_password),
        role=ROLE_USER,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:  # pragma: no cover - race guard
        db.rollback()
        return db.scalar(select(User).where(User.email == email))
    db.refresh(user)
    logger.info("Bootstrapped demo user '%s' (role=%s)", user.email, user.role)
    return user


def register(db: Session, payload: RegisterRequest) -> User:
    ensure_roles(db)
    email = payload.email.lower().strip()
    if db.scalar(select(User).where(User.email == email)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists")
    if len(payload.password) < 8:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Password must be at least 8 characters")
    user = User(name=payload.name.strip(), email=email, password_hash=hash_password(payload.password), role=payload.role)
    user.role_id = db.scalar(select(Role.id).where(Role.name == payload.role))
    db.add(user)
    db.commit()
    db.refresh(user)
    record_audit(db, user.id, "auth.register", "user", str(user.id), {"role": user.role})
    return user


def login(db: Session, payload: LoginRequest) -> TokenResponse:
    user = db.scalar(select(User).where(User.email == payload.email.lower().strip()))
    if user is None or not verify_password(payload.password, user.password_hash):
        # constant-ish behaviour: identical error for unknown email vs wrong password
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account is disabled - contact an administrator")
    token = create_access_token(str(user.id), user.role)
    record_audit(db, user.id, "auth.login", "user", str(user.id), None)
    return TokenResponse(access_token=token, role=user.role)


def set_role(db: Session, user: User, role: str) -> User:
    if role not in VALID_ROLES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown role")
    user.role = role
    user.role_id = db.scalar(select(Role.id).where(Role.name == role))
    db.commit()
    db.refresh(user)
    return user
