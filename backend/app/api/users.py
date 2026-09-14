"""Admin user management endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import hash_password, require_admin
from app.models.user import User
from app.schemas.user import RegisterRequest, UserAdminUpdate, UserOut
from app.services import auth_service
from app.services.audit_service import record_audit

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserOut])
def list_users(search: str | None = None, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    stmt = select(User).order_by(User.id)
    if search:
        like = f"%{search.strip()}%"
        stmt = stmt.where(or_(User.name.ilike(like), User.email.ilike(like)))
    return list(db.scalars(stmt))


@router.post("", response_model=UserOut, status_code=201)
def create_user(payload: RegisterRequest, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    user = auth_service.register(db, payload)
    record_audit(db, admin.id, "user.create", "user", str(user.id), {"email": user.email, "role": user.role})
    return user


@router.patch("/{user_id}", response_model=UserOut)
def update_user(user_id: int, payload: UserAdminUpdate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if user.id == admin.id and (payload.is_active is False or (payload.role and payload.role != "admin")):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot demote or deactivate your own admin account")
    if payload.role is not None:
        auth_service.set_role(db, user, payload.role)
    if payload.is_active is not None:
        user.is_active = payload.is_active
    if payload.password:
        user.password_hash = hash_password(payload.password)
    db.commit()
    db.refresh(user)
    record_audit(db, admin.id, "user.update", "user", str(user.id), payload.model_dump(exclude_none=True, exclude={"password"}))
    return user


@router.delete("/{user_id}", status_code=204)
def delete_user(user_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if user.id == admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot delete your own account")
    db.delete(user)
    db.commit()
    record_audit(db, admin.id, "user.delete", "user", str(user_id), {"email": user.email})
