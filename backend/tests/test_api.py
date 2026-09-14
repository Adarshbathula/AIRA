"""FastAPI endpoint tests against the seeded test runtime."""
from __future__ import annotations

import pytest


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["database"] == "ok"
    assert body["embeddings"]["provider"] == "lightweight-hash"  # deterministic in CI


def test_chat_pipeline_persists_everything(client, tokens, runtime, db_session_fixture):
    db = db_session_fixture
    r = client.post("/api/chat", headers=tokens["user_h"], json={"message": "Payment API returns HTTP 503 after deployment."})
    assert r.status_code == 200, r.text
    body = r.json()
    ai = body["ai"]
    assert ai["analysis"]["service"] == "Payment API"
    assert ai["conversation_id"] == body["conversation_id"]

    from app.models.conversation import Incident, Message
    from app.models.evidence import Evidence, Recommendation

    inc = db.get(Incident, ai["incident_id"])
    assert inc is not None and inc.public_id.startswith("INC-")
    assert inc.retrieval_quality in {"GOOD", "FAIR", "POOR"}
    assert db.query(Message).filter_by(conversation_id=body["conversation_id"]).count() >= 2
    assert db.query(Recommendation).filter_by(incident_id=inc.id).count() == len(ai["troubleshooting"])
    ev_rows = db.query(Evidence).filter_by(incident_id=inc.id).all()
    assert len(ev_rows) >= 1
    assert all(e.snippet for e in ev_rows)
    assert inc.pipeline_state and "chunks" not in inc.pipeline_state  # no raw context persisted, no CoT

    # history visibility
    conv = client.get(f"/api/conversations/{body['conversation_id']}", headers=tokens["user_h"]).json()
    assert conv["incidents"][0]["public_id"] == ai["public_id"]
    # incident detail reconstructs from persistence alone
    det = client.get(f"/api/incidents/{ai['incident_id']}", headers=tokens["user_h"]).json()
    assert det["public_id"] == ai["public_id"]
    assert det["evidence"] and det["retrieval"]["attempts"] == ai["retrieval_attempts"]


def test_followup_reuses_conversation(client, tokens, runtime):
    r1 = client.post("/api/chat", headers=tokens["user_h"], json={"message": "Order service cannot establish database connections."}).json()
    r2 = client.post("/api/chat", headers=tokens["user_h"],
                     json={"message": "and the connection pool is exhausted under load", "conversation_id": r1["conversation_id"], "follow_up": True}).json()
    assert r2["conversation_id"] == r1["conversation_id"]
    assert r2["ai"]["incident_id"] != r1["ai"]["incident_id"]


def test_incident_crud_and_resolution(client, tokens, runtime):
    inc = client.post("/api/incidents", headers=tokens["user_h"],
                      json={"description": "Payment pods are repeatedly entering CrashLoopBackOff."}).json()
    iid = inc["incident_id"]
    assert client.get(f"/api/incidents/{iid}", headers=tokens["user_h"]).status_code == 200
    assert client.get("/api/incidents", headers=tokens["user_h"]).json()["total"] >= 1
    r = client.post(f"/api/incidents/{iid}/resolution", headers=tokens["user_h"], json={"resolution_status": "RESOLVED"})
    assert r.status_code == 200 and r.json()["resolution_status"] == "RESOLVED"
    assert client.post(f"/api/incidents/{iid}/resolution", headers=tokens["user_h"], json={"resolution_status": "BOGUS"}).status_code == 400
    assert client.delete(f"/api/incidents/{iid}", headers=tokens["user_h"]).status_code == 204
    assert client.get(f"/api/incidents/{iid}", headers=tokens["user_h"]).status_code == 404


def test_short_message_rejected(client, tokens):
    assert client.post("/api/chat", headers=tokens["user_h"], json={"message": "hi"}).status_code == 422


def test_similar_incidents_endpoint(client, tokens, runtime):
    r = client.post("/api/incidents/similar", headers=tokens["user_h"],
                    json={"description": "Database connection timeout in Order Service", "top_k": 4})
    assert r.status_code == 200
    hits = r.json()
    assert hits and hits[0]["public_id"] == "INC-231"
    assert 0 <= hits[0]["similarity"] <= 1


def test_document_endpoints(client, tokens):
    content = (
        "# RUNBOOK-X High Memory Runbook\n\n"
        "1 Check pod memory working set with kubectl top pod and container limits\n"
        "2 Raise memory limit above the working set, then restart affected pods\n"
        "3 Verify no OOMKilled events remain after the change\n"
        "4 Close the incident once the error rate is zero for 30 minutes\n"
    )
    r = client.post(
        "/api/documents/upload", headers=tokens["admin_h"],
        files={"file": ("Runbook_X.md", content.encode(), "text/markdown")},
        data={"category": "RUNBOOK", "service": "User Service"},
    )
    assert r.status_code == 201, r.text
    doc = r.json()
    assert doc["category"] == "RUNBOOK"
    assert doc["chunk_count"] >= 1
    assert doc["citation_label"] == "RUNBOOK-X"

    got = client.get(f"/api/documents/{doc['id']}", headers=tokens["user_h"]).json()
    assert got["chunks"]
    upd = client.patch(f"/api/documents/{doc['id']}", headers=tokens["admin_h"], json={"category": "TROUBLESHOOTING_GUIDE"}).json()
    assert upd["category"] == "TROUBLESHOOTING_GUIDE"
    assert client.patch(f"/api/documents/{doc['id']}", headers=tokens["admin_h"], json={"category": "NOPE"}).status_code == 400
    dupe = client.post(
        "/api/documents/upload", headers=tokens["admin_h"],
        files={"file": ("Runbook_X_copy.md", content.encode(), "text/markdown")},
        data={"category": "RUNBOOK"},
    )
    assert dupe.status_code == 409, dupe.text
    assert "already in the knowledge base" in dupe.json()["detail"]
    assert client.delete(f"/api/documents/{doc['id']}", headers=tokens["user_h"]).status_code == 403
    assert client.delete(f"/api/documents/{doc['id']}", headers=tokens["admin_h"]).status_code == 204
    assert client.get(f"/api/documents/{doc['id']}", headers=tokens["user_h"]).status_code == 404


def test_knowledge_search_endpoint(client, tokens, runtime):
    r = client.post("/api/knowledge/search", headers=tokens["user_h"], json={"query": "kafka consumer lag restart stalled consumers", "top_k": 5})
    assert r.status_code == 200
    body = r.json()
    assert body["chunks"]
    assert all(0 <= c["score"] <= 1.2 for c in body["chunks"])


def test_dashboard_endpoints(client, tokens, runtime):
    ov = client.get("/api/dashboard/overview", headers=tokens["user_h"]).json()
    assert ov["total_incidents"] >= 1
    for ep in ("incidents", "root-causes", "confidence", "documents", "retrieval"):
        assert client.get(f"/api/dashboard/{ep}", headers=tokens["user_h"]).status_code == 200
    assert client.get("/api/dashboard/usage", headers=tokens["user_h"]).status_code == 403  # admin-only
    assert client.get("/api/dashboard/usage", headers=tokens["admin_h"]).status_code == 200


def test_conversation_ownership_isolation(client, tokens, runtime):
    mine = client.post("/api/chat", headers=tokens["user_h"], json={"message": "Users cannot log in after the latest deployment."}).json()
    # admin registered user 't_admin' may view; a third user may not
    from app.core.security import hash_password
    from app.core.database import SessionLocal
    from app.models.user import User

    with SessionLocal() as s:
        if s.query(User).filter_by(email="intruder@aira.test").first() is None:
            s.add(User(name="Intruder", email="intruder@aira.test", role="user", password_hash=hash_password("Intruder@123")))
            s.commit()
    tok = client.post("/api/auth/login", json={"email": "intruder@aira.test", "password": "Intruder@123"}).json()["access_token"]
    r = client.get(f"/api/conversations/{mine['conversation_id']}", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 403
    assert client.get(f"/api/incidents/{mine['ai']['incident_id']}", headers={"Authorization": f"Bearer {tok}"}).status_code == 403
    assert client.get(f"/api/conversations/{mine['conversation_id']}", headers=tokens["admin_h"]).status_code == 200


def test_user_management_rbac(client, tokens):
    created = client.post("/api/users", headers=tokens["admin_h"],
                          json={"name": "Managed User", "email": "managed@aira.test", "password": "Managed@123", "role": "admin"})
    assert created.status_code == 201 and created.json()["role"] == "admin"  # admin endpoint may grant admin
    uid = created.json()["id"]
    promoted = client.patch(f"/api/users/{uid}", headers=tokens["admin_h"], json={"role": "admin"}).json()
    assert promoted["role"] == "admin"
    disabled = client.patch(f"/api/users/{uid}", headers=tokens["admin_h"], json={"is_active": False}).json()
    assert disabled["is_active"] is False
    assert client.post("/api/auth/login", json={"email": "managed@aira.test", "password": "Managed@123"}).status_code == 403
    assert client.delete(f"/api/users/{uid}", headers=tokens["admin_h"]).status_code == 204


# ------------------------------------------------------- SPA static hosting
def test_frontend_static_hosting(client):
    """When a UI build exists the API also serves it, without shadowing /api."""
    from app.core.static import resolve_dist

    dist = resolve_dist()
    if dist is None:
        pytest.skip("no frontend build present (npm run build to create one)")
    r = client.get("/")
    assert r.status_code == 200 and "<div id=\"root\">" in r.text
    assert 'src="/assets/' in r.text, "built index should reference hashed assets"
    # client-side routes fall through to the SPA shell
    assert client.get("/assistant").status_code == 200
    assert client.get("/incidents/12").status_code == 200
    # assets are served with their real content type
    asset = [l for l in r.text.splitlines() if "/assets/" in l][0]
    name = asset.split('"/assets/')[1].split('"')[0]
    a = client.get(f"/assets/{name}")
    assert a.status_code == 200 and len(a.content) > 1000
    # API routes keep priority
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/nope-not-here").status_code == 404
    # path traversal must not escape the build directory. httpx (like every
    # browser) normalises dot-segments, so the raw percent-encoded path is sent.
    import asyncio

    import httpx

    async def _raw_traversal():
        transport = httpx.ASGITransport(app=client.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as raw:
            return await raw.get("/assets/%2e%2e/%2e%2e/etc/passwd")

    r = asyncio.run(_raw_traversal())
    assert r.status_code in (400, 404), (r.status_code, r.text[:120])
