#!/usr/bin/env python3
"""End-to-end API smoke test against the seeded demo database (no pytest needed).

    python scripts/smoke_api.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("AIRA_ENV", "test")
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

c = TestClient(app)
ok = 0


def check(label: str, cond: bool, extra: str = "") -> None:
    global ok
    print(f"{'PASS' if cond else 'FAIL'} - {label} {extra}")
    if not cond:
        raise SystemExit(f"SMOKE FAILED at: {label}")
    ok += 1


r = c.get("/api/health")
check("GET /health", r.status_code == 200, f"| llm={r.json()['llm']['mode']} vectors={r.json()['vector_store']['vectors']}")

# ------------------------------------------------------------ auth + RBAC
r = c.post("/api/auth/login", json={"email": "admin@aira.test", "password": "Admin@12345"})
check("admin login", r.status_code == 200, f"| role={r.json().get('role')}")
admin_tok = r.json()["access_token"]
r = c.post("/api/auth/login", json={"email": "priya@aira.test", "password": "Engineer@123"})
user_tok = r.json()["access_token"]
check("user login", r.status_code == 200)
check("bad password -> 401", c.post("/api/auth/login", json={"email": "admin@aira.test", "password": "nope"}).status_code == 401)
check("missing token -> 401", c.get("/api/auth/me").status_code == 401)
check("GET /auth/me", c.get("/api/auth/me", headers={"Authorization": f"Bearer {admin_tok}"}).json()["role"] == "admin")

AH = {"Authorization": f"Bearer {admin_tok}"}
UH = {"Authorization": f"Bearer {user_tok}"}
check("user blocked from /users (403)", c.get("/api/users", headers=UH).status_code == 403)
check("user blocked from admin analytics (403)", c.get("/api/dashboard/system", headers=UH).status_code == 403)
check("admin can list users", c.get("/api/users", headers=AH).status_code == 200)

# ------------------------------------------------------------ documents
r = c.get("/api/documents", headers=UH, params={"category": "RUNBOOK"})
body = r.json()
check("knowledge list filtered by category", r.status_code == 200 and body["total"] >= 1,
      f"| {body['total']} runbook docs, first={body['items'][0]['name']}")
check("upload forbidden for user", c.post(
    "/api/documents/upload", headers=UH, files={"file": ("x.md", b"# Test\nshort", "text/markdown")}
).status_code == 403)

import time as _t

_nonce = int(_t.time())
payload = (
    "# HI-001 High CPU Troubleshooting\n\n"
    "## 1 Diagnosis\nCheck top processes and CPU saturation. Inspect load average per core. "
    "Verify CPU throttling with kubectl top pod. Review recent deployments that changed resource requests.\n\n"
    "## 2 Remediation\nScale replicas horizontally and raise the CPU limit. Restart affected pods "
    "after the quota change. If load persists enable HPA at 70 percent CPU.\n\n"
    f"## 3 Evidence\nSmoke run marker {_nonce}: attach profiling output and node CPU pressure "
    f"events to the ticket before closing the incident.\n"
).encode()
_upload = lambda: c.post(
    "/api/documents/upload", headers=AH,
    files={"file": ("High_CPU_Troubleshooting.md", payload, "text/markdown")},
    data={"category": "TROUBLESHOOTING_GUIDE", "service": "Application Server", "department": "SRE"},
)
r = _upload()
check("admin upload markdown", r.status_code == 201, f"| {r.json().get('document_no')}")
newdoc = r.json()
check("new document is chunked", (newdoc.get("chunk_count") or 0) >= 1, f"| chunks={newdoc.get('chunk_count')}")
r_dupe = _upload()
check("duplicate content -> 409", r_dupe.status_code == 409, f"| {r_dupe.json().get('detail')}")
check("unsupported type -> 415", c.post(
    "/api/documents/upload", headers=AH, files={"file": ("evil.exe", b"MZ\x90\x00", "application/octet-stream")}
).status_code == 415)
check("empty file -> 400", c.post(
    "/api/documents/upload", headers=AH, files={"file": ("empty.txt", b"", "text/plain")}
).status_code == 400)

# ------------------------------------------------------------ chat pipeline
r = c.post("/api/chat", headers=UH, json={"message": "Payment API returns HTTP 503 after deployment."})
check("POST /chat 200", r.status_code == 200, r.text[:200] if r.status_code != 200 else "")
chat = r.json()
ai = chat["ai"]
check("structured response", all(k in ai for k in
      ("analysis", "root_causes", "troubleshooting", "similar_incidents", "evidence", "confidence_score", "retrieval")))
check("analyzer extracted service", ai["analysis"]["service"] == "Payment API", f"| {ai['analysis']}")
check("evidence citations present", len(ai["evidence"]) >= 1, f"| {[e['citation'] for e in ai['evidence']][:4]}")
check("root causes grounded", all(c["evidence"] or c["status"] == "INSUFFICIENT_EVIDENCE" for c in ai["root_causes"]))
check("steps carry evidence", all(s["evidence"] for s in ai["troubleshooting"]))
check("pipeline trace complete", {t["node"] for t in ai["trace"]} >= {"incident_analyzer", "retriever", "context_grader", "confidence", "summarizer"},
      f"| {[(t['node'], t['status']) for t in ai['trace']]}")
print("\n--- sample final answer (first 900 chars) ---\n" + ai["final_text"][:900] + "\n---\n")

r = c.post("/api/chat", headers=UH, json={"message": "Also check database connectivity", "conversation_id": chat["conversation_id"], "follow_up": True})
check("follow-up in same conversation", r.status_code == 200 and r.json()["conversation_id"] == chat["conversation_id"])

# ------------------------------------------------------------ conversations
convs = c.get("/api/conversations", headers=UH).json()
check("conversation list", len(convs) >= 1, f"| title={convs[0]['title']!r}")
detail = c.get(f"/api/conversations/{convs[0]['id']}", headers=UH).json()
check("conversation detail has messages+incidents", len(detail["messages"]) >= 4 and len(detail["incidents"]) >= 1)
c.post("/api/auth/register", json={"name": "Eve Tester", "email": "eve@aira.test", "password": "Eve@123456"})
eve = c.post("/api/auth/login", json={"email": "eve@aira.test", "password": "Eve@123456"}).json()["access_token"]
check("cross-user access blocked (403)",
      c.get(f"/api/conversations/{convs[0]['id']}", headers={"Authorization": f"Bearer {eve}"}).status_code == 403)
check("rename conversation", c.patch(f"/api/conversations/{convs[0]['id']}", headers=UH, json={"title": "Payment 503 triage"}).status_code == 200)

# ------------------------------------------------------------ incidents
inc_id = ai["incident_id"]
det = c.get(f"/api/incidents/{inc_id}", headers=UH).json()
check("incident detail", det["public_id"] == ai["public_id"] and "confidence_score" in det)
lst = c.get("/api/incidents", headers=UH, params={"limit": 5}).json()
check("incident list paginated", lst["total"] >= 1, f"| total={lst['total']}")
sim = c.post("/api/incidents/similar", headers=UH, json={"description": "Database connection timeout in Order Service", "top_k": 3}).json()
check("similar incidents semantic match", any(s["public_id"].startswith("INC-") for s in sim),
      f"| {[(s['public_id'], s['similarity']) for s in sim]}")
r = c.post("/api/incidents", headers=UH, json={"description": "Order service cannot establish database connections. Connection pool exhausted."})
check("POST /incidents (no chat)", r.status_code == 201, f"| quality={r.json()['retrieval_quality']} conf={r.json()['confidence_score']}")
second_inc = r.json()["incident_id"]
check("mark resolved feeds history store", c.post(f"/api/incidents/{second_inc}/resolution", headers=UH, json={"resolution_status": "RESOLVED"}).status_code == 200)

weird = c.post("/api/incidents", headers=UH, json={"description": "Quantum flux capacitor harmonic desync in the mainframe"}).json()
check("insufficient-evidence honesty", weird["insufficient_evidence"] or weird["retrieval_quality"] in {"POOR", "FAIR"},
      f"| quality={weird['retrieval_quality']} conf={weird['confidence_score']}")

# ------------------------------------------------------------ knowledge + dashboards
ks = c.post("/api/knowledge/search", headers=UH, json={"query": "OOMKilled memory limit pods", "top_k": 5}).json()
check("knowledge search", ks["chunks"], f"| top={ks['chunks'][0]['citation'] if ks['chunks'] else None}")
for ep in ("overview", "incidents", "root-causes", "confidence", "documents", "retrieval"):
    check(f"dashboard/{ep}", c.get(f"/api/dashboard/{ep}", headers=UH).status_code == 200)
usage = c.get("/api/dashboard/usage", headers=AH).json()
check("admin usage stats", "most_referenced" in usage, f"| {len(usage['most_referenced'])} tracked docs")
sysd = c.get("/api/dashboard/system", headers=AH).json()
check("admin system stats", sysd["total_incidents"] >= 2, f"| {sysd}")

# ------------------------------------------------------------ admin cleanup
check("doc category update", c.patch(f"/api/documents/{newdoc['id']}", headers=AH, json={"category": "RUNBOOK"}).json()["category"] == "RUNBOOK")
check("doc delete", c.delete(f"/api/documents/{newdoc['id']}", headers=AH).status_code == 204)
check("incident delete", c.delete(f"/api/incidents/{second_inc}", headers=UH).status_code == 204)

print(f"\nALL {ok} API SMOKE CHECKS PASSED ✅")
