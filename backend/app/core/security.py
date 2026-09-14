"""Security: password hashing (bcrypt) + JWT tokens + RBAC dependencies."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db

settings = get_settings()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

#: header + cookie names used when the Authorization header cannot be used
#: (reverse proxies / preview tunnels that strip it)
API_TOKEN_HEADER = "X-Aira-Token"
SESSION_COOKIE = "aira_session"

ROLE_ADMIN = "admin"
ROLE_USER = "user"
VALID_ROLES = {ROLE_ADMIN, ROLE_USER}


# --------------------------------------------------------------- passwords
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


# -------------------------------------------------------------------- JWT
def create_access_token(subject: str, role: str, expires_minutes: int | None = None) -> str:
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=expires_minutes or settings.access_token_expire_minutes)
    payload = {
        "sub": str(subject),
        "role": role,
        "iat": now,
        "exp": exp,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token expired") from None
    except jwt.InvalidTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token") from None


# ------------------------------------------------------ auth dependencies
def extract_token(request: Request, header_token: str | None = None) -> str | None:
    """Bearer header -> X-Aira-Token header -> session cookie, in that order.

    The fallbacks exist because some hosts (tunnels, corporate proxies, sandbox
    preview gateways) drop or rewrite the Authorization header; a signed JWT in a
    same-site cookie keeps the session alive there without weakening anything:
    SameSite=Lax blocks cross-site attachment and the value is still validated
    exactly like the bearer token.
    """
    if header_token:
        return header_token
    raw = request.headers.get("authorization") or ""
    if raw.lower().startswith("bearer "):
        return raw[7:].strip() or None
    alt = request.headers.get(API_TOKEN_HEADER.lower())
    if alt:
        return alt.strip()
    return request.cookies.get(SESSION_COOKIE) or None


def get_current_user(
    request: Request,
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
):
    from app.models.user import User  # local import avoids circulars

    token = extract_token(request, token)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated",
                            headers={"WWW-Authenticate": "Bearer"})
    payload = decode_access_token(token)
    user = db.get(User, int(payload.get("sub", 0)))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found or inactive")
    return user


def require_admin(user=Depends(get_current_user)):
    if user.role != ROLE_ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin privileges required")
    return user


def ensure_user_ownership(user, owner_id: int | None) -> None:
    """Admins may access everything; users only their own rows."""
    if user.role == ROLE_ADMIN:
        return
    if owner_id is not None and owner_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed to access this resource")
