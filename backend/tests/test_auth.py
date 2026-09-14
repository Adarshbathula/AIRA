"""Authentication, password hashing and RBAC tests."""
from __future__ import annotations


def test_register_and_login(client):
    r = client.post("/api/auth/register", json={"name": "New Eng", "email": "new.eng@aira.test", "password": "Passw0rd!"})
    assert r.status_code == 201, r.text
    assert r.json()["role"] == "user"
    r = client.post("/api/auth/login", json={"email": "new.eng@aira.test", "password": "Passw0rd!"})
    assert r.status_code == 200
    assert r.json()["access_token"]


def test_duplicate_email_rejected(client):
    r = client.post("/api/auth/register", json={"name": "Dup", "email": "new.eng@aira.test", "password": "Passw0rd!"})
    assert r.status_code == 409


def test_weak_password_rejected(client):
    r = client.post("/api/auth/register", json={"name": "Weak", "email": "weak@aira.test", "password": "123"})
    assert r.status_code == 422


def test_invalid_credentials(client):
    r = client.post("/api/auth/login", json={"email": "new.eng@aira.test", "password": "wrong-password"})
    assert r.status_code == 401


def test_me_requires_token(client):
    client.cookies.clear()  # the login tests set a fallback session cookie
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_me_returns_profile(client, tokens):
    me = client.get("/api/auth/me", headers=tokens["user_h"]).json()
    assert me["email"] == "t_user@aira.test"
    assert me["role"] == "user"


def test_passwords_are_hashed(client, db, tokens):
    from app.models.user import User

    user = db.query(User).filter_by(email="t_user@aira.test").first()
    assert user is not None
    assert "Engineer@123" not in user.password_hash
    assert user.password_hash.startswith("$2")  # bcrypt
    from app.core.security import verify_password

    assert verify_password("Engineer@123", user.password_hash)


def test_rbac_admin_endpoints_blocked_for_user(client, tokens):
    assert client.get("/api/users", headers=tokens["user_h"]).status_code == 403
    assert client.get("/api/dashboard/system", headers=tokens["user_h"]).status_code == 403
    assert client.post(
        "/api/documents/upload", headers=tokens["user_h"],
        files={"file": ("x.txt", b"hello", "text/plain")},
    ).status_code == 403


def test_rbac_admin_allowed(client, tokens):
    assert client.get("/api/users", headers=tokens["admin_h"]).status_code == 200
    assert client.get("/api/dashboard/system", headers=tokens["admin_h"]).status_code == 200


def test_demo_engineer_bootstrap_is_env_driven_and_idempotent(db, monkeypatch):
    """The non-admin demo login is created from env only, and never duplicated."""
    from app.core.config import get_settings
    from app.core.security import ROLE_USER, verify_password
    from app.models.user import User
    from app.services import auth_service
    from sqlalchemy import select

    def patch(**updates):
        monkeypatch.setattr("app.services.auth_service.get_settings", lambda: get_settings().model_copy(update=updates))

    patch(bootstrap_user_email="")
    assert auth_service.ensure_demo_user(db) is None  # not configured -> no-op

    patch(bootstrap_user_email="demo-eng@aira.test", bootstrap_user_password="Engineer@123")
    user = auth_service.ensure_demo_user(db)
    assert user is not None and user.email == "demo-eng@aira.test" and user.role == ROLE_USER
    assert verify_password("Engineer@123", user.password_hash)

    again = auth_service.ensure_demo_user(db)  # idempotent
    assert again.id == user.id
    assert len(db.scalars(select(User).where(User.email == "demo-eng@aira.test")).all()) == 1


def test_token_survives_stripped_authorization_header(client):
    """Proxies/tunnels sometimes drop the Authorization header; the session
    cookie and the X-Aira-Token header must keep an authenticated session."""
    body = {"email": "t_user@aira.test", "password": "Engineer@123"}
    client.cookies.clear()
    r = client.post("/api/auth/login", json=body)
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    assert client.cookies.get("aira_session"), "login should set a fallback session cookie"

    # 1) bearer header (the normal path)
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 200

    # 2) cookie only - no Authorization header at all
    plain = client.__class__(client.app)
    plain.cookies.set("aira_session", token)
    me = plain.get("/api/auth/me")
    assert me.status_code == 200 and me.json()["email"] == "t_user@aira.test"

    # 3) custom header only
    alt = client.get("/api/auth/me", headers={"X-Aira-Token": token})
    assert alt.status_code == 200

    # 4) a garbage cookie must not authenticate anyone
    bad = client.__class__(client.app)
    bad.cookies.set("aira_session", "not-a-jwt")
    assert bad.get("/api/auth/me").status_code in (401, 422)

    # 5) logout clears the cookie
    assert client.post("/api/auth/logout").status_code == 204
    fresh = client.__class__(client.app)
    assert fresh.get("/api/auth/me").status_code == 401
