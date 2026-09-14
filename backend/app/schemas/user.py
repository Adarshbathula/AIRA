"""Request/response schemas for auth & user management."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from pydantic import EmailStr  # kept for docs; validation uses permissive pattern below

EmailField = Field(pattern=r"^[^@\s]+@[^@\s]+\.[A-Za-z][A-Za-z0-9-]{1,62}$", max_length=254)


class RegisterRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: str = EmailField
    password: str = Field(min_length=8, max_length=128)
    role: str = Field(default="user", pattern="^(user|admin)$")


class LoginRequest(BaseModel):
    email: str = EmailField
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    role: str
    is_active: bool
    created_at: datetime


class UserAdminUpdate(BaseModel):
    role: str | None = Field(default=None, pattern="^(user|admin)$")
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)
