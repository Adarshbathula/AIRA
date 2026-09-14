"""Pytest fixtures: isolated test DB, lightweight embeddings, seeded runtime stores.

AIRA_ENV=test makes app.core.config load backend/.env.test (SQLite in /tmp,
deterministic mode). We additionally isolate the DB file for the session.
"""
from __future__ import annotations

import os
import pathlib
import sys

pathlib.Path("/tmp/aira_pytest").mkdir(parents=True, exist_ok=True)
pathlib.Path("/tmp/aira_pytest/vectorstore").mkdir(parents=True, exist_ok=True)

os.environ["AIRA_ENV"] = "test"
TEST_DB = "/tmp/aira_pytest/aira.db"
os.environ["DATA_DIR"] = "/tmp/aira_pytest"
os.environ["DATABASE_URL"] = f"sqlite:////{TEST_DB.lstrip('/')}"
os.environ["EMBEDDING_PROVIDER"] = "lightweight"
os.environ["LLM_ENABLED"] = "false"

BACKEND = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

import pytest  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _setup_env():
    for k, v in {
        "DATABASE_URL": f"sqlite:////{TEST_DB.lstrip('/')}",
        "DATA_DIR": "/tmp/aira_pytest",
        "EMBEDDING_PROVIDER": "lightweight",
        "LLM_ENABLED": "false",
    }.items():
        os.environ[k] = v
    yield


@pytest.fixture(scope="session")
def app_engine():
    from app.core.database import Base, engine
    import app.models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="session")
def db_session_fixture(app_engine):
    from app.core.database import SessionLocal

    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture()
def db(app_engine):
    from sqlalchemy.orm import Session

    from app.core.database import SessionLocal

    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture(scope="session")
def client(app_engine):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def tokens(client):
    from app.core.security import hash_password
    from app.core.database import SessionLocal
    from app.models.user import User

    with SessionLocal() as s:
        for email, name, role, pw in (
            ("t_admin@aira.test", "Test Admin", "admin", "Admin@12345"),
            ("t_user@aira.test", "Test Engineer", "user", "Engineer@123"),
        ):
            if s.query(User).filter_by(email=email).first() is None:
                s.add(User(name=name, email=email, role=role, password_hash=hash_password(pw)))
        s.commit()

    admin = client.post("/api/auth/login", json={"email": "t_admin@aira.test", "password": "Admin@12345"}).json()["access_token"]
    user = client.post("/api/auth/login", json={"email": "t_user@aira.test", "password": "Engineer@123"}).json()["access_token"]
    return {"admin": admin, "user": user, "admin_h": {"Authorization": f"Bearer {admin}"}, "user_h": {"Authorization": f"Bearer {user}"}}


CORPUS = [
    ("DOC-0001", "RUNBOOK-005", "RUNBOOK", "Payment API",
     "Missing ConfigMap in the production namespace causes HTTP 503 responses. Verify ConfigMap availability with kubectl get configmap. Reapply the ConfigMap and restart affected pods."),
    ("DOC-0001", "RUNBOOK-005", "RUNBOOK", "Payment API",
     "Restart affected Kubernetes pods with kubectl rollout restart deployment. Validate Kubernetes service endpoints. Check deployment status after failed rollouts."),
    ("DOC-0002", "SOP-API-01", "SOP", "Payment API",
     "Incorrect Kubernetes Secret values break the payment API. Compare secret checksums against the vault. Root cause: secret rotation not applied to the namespace."),
    ("DOC-0003", "RCA-018", "RCA", "Order Service",
     "Root cause: connection pool exhaustion during a locked database migration. Increase pool size and raise max_connections. Resolved by killing long transactions."),
    ("DOC-0004", "KB-013", "KNOWLEDGE_BASE", "User Service",
     "Pods are terminated with OOMKilled when the memory limit is below the working set. Raise the memory limit and cap the cache size."),
    ("DOC-0005", "TSG-007", "TROUBLESHOOTING_GUIDE", "Notification Service",
     "Scale consumer group to partition count. Check kafka consumer lag per partition. Restart stalled consumers and verify the lag trend."),
]

INCIDENTS = [
    ("INC-231", "Database connection timeout in Order Service", "Order Service", "Database", "P1", "Connection pool exhaustion", "RESOLVED"),
    ("INC-542", "Payment API returns HTTP 503 after deployment", "Payment API", "Application/Deployment", "P1", "Missing ConfigMap", "RESOLVED"),
    ("INC-731", "Payment pods in CrashLoopBackOff after image upgrade", "Payment API", "Kubernetes / Container", "P1", "Liveness probe timeout too low", "RESOLVED"),
    ("INC-044", "User service pods OOMKilled during traffic surge", "User Service", "Compute / Resource", "P2", "Memory limit below working set", "RESOLVED"),
]


@pytest.fixture(scope="session")
def rag_session(app_engine, db_session_fixture):
    db = db_session_fixture
    """Runtime with an in-memory seeded corpus for RAG/graph/API tests."""
    from app.core.security import hash_password
    from app.models.conversation import Incident
    from app.models.document import Document, DocumentChunk
    from app.models.user import User
    from app.rag.runtime import get_runtime
    from app.rag.vectorstore.faiss_store import VRecord

    rt = get_runtime()
    with rt.lock:
        rt.document_store.reset()
        rt.incident_store.reset()
        recs = []
        for i, (dno, cit, cat, svc, text) in enumerate(CORPUS):
            recs.append(VRecord(ref=f"{dno}-C{i:03d}", text=text, metadata={
                "document_id": i + 1, "document_no": dno, "citation": cit, "category": cat,
                "service": svc, "document_name": f"{cit}.md", "section": f"Section {i}", "chunk_index": i,
            }))
            if db.query(Document).filter_by(document_no=dno).first() is None:
                d = Document(document_no=dno, name=f"{cit}.md", type="md", category=cat, service=svc,
                             source="test", metadata_json={"ref": cit})
                db.add(d)
                db.flush()
                db.add(DocumentChunk(chunk_ref=f"{dno}-C{i:03d}", document_id=d.id, chunk_index=i, text=text, section=f"Section {i}"))
        rt.document_store.add(recs)

        for pid, desc, svc, cat, sev, rc, outcome in INCIDENTS:
            if db.query(Incident).filter_by(public_id=pid).first() is None:
                db.add(Incident(public_id=pid, description=desc, service=svc, category=cat, severity=sev,
                                environment="Production", probable_root_cause=rc, cause_taxonomy="Configuration Error",
                                outcome=outcome, resolution_summary=f"Fixed: {rc}", source="seed",
                                confidence_score=0.7, retrieval_quality="GOOD", retrieval_attempts=1,
                                supporting_document_count=2, evidence_status="SUPPORTED", resolution_status="RESOLVED"))
            rt.incident_store.upsert([VRecord(ref=pid, text=f"{desc}\nservice: {svc}\nknown root cause: {rc}",
                                              metadata={"public_id": pid, "service": svc, "category": cat,
                                                        "severity": sev, "title": desc, "root_cause": rc,
                                                        "resolution": f"Fixed: {rc}", "outcome": outcome, "created_at": "2026-01-05"})])
        rt.document_store.commit()
        rt.incident_store.commit()
        db.commit()
    return rt


@pytest.fixture()
def runtime(rag_session):
    return rag_session
