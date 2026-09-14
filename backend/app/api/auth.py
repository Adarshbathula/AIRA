"""Auth endpoints: register, login, me."""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.config import get_settings
from app.core.security import SESSION_COOKIE, get_current_user
from app.schemas.user import LoginRequest, RegisterRequest, TokenResponse, UserOut
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    """Public registration always creates the low-privilege 'user' role;
    admins are bootstrapped from env or promoted by another admin."""
    payload = payload.model_copy(update={"role": "user"})
    return auth_service.register(db, payload)


def _set_session_cookie(response: Response, token: str) -> None:
    s = get_settings()
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=int(timedelta(minutes=s.access_token_expire_minutes).total_seconds()),
        httponly=False,  # the SPA interceptor reads it as a fallback
        samesite="lax",
        secure=s.environment.lower() in {"production", "prod"},
        path="/",
    )


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    result = auth_service.login(db, payload)
    _set_session_cookie(response, result.access_token)
    return result


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/me", response_model=UserOut)
def me(user=Depends(get_current_user)):
    return user
