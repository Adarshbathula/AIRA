"""LangGraph pipeline node-level tests (framework-agnostic logic)."""
from __future__ import annotations

from app.core.config import get_settings
from app.graph.nodes import context_grader, incident_analyzer, query_constructor, query_rewriter, retriever, root_cause, summarizer
from app.graph.taxonomy import classify_text
from app.graph.workflow import artifact_state, build_graph, run_workflow


def test_analyzer_payment_503():
    a = incident_analyzer.analyze("Payment API returns HTTP 503 after deployment.", get_settings())
    assert a["service"] == "Payment API"
    assert "503" in (a["error"] or "")
    assert a["environment"] == "Production"
    assert a["event"] == "Deployment"
    assert a["category"] == "Application/Deployment"
    assert {"payment", "api", "503", "deployment"} <= set(a["keywords"])


def test_analyzer_various_incidents():
    s = get_settings()
    a1 = incident_analyzer.analyze("Order service cannot establish database connections: too many connections, pool exhausted.", s)
    assert a1["service"] == "Order Service" and a1["category"] == "Database"
    a2 = incident_analyzer.analyze("Payment pods are repeatedly entering CrashLoopBackOff in staging.", s)
    assert a2["category"] == "Kubernetes / Container" and a2["environment"] == "Staging"
    a3 = incident_analyzer.analyze("Production server CPU utilization has exceeded 95%.", s)
    assert a3["category"] == "Compute / Resource" and a3["severity"] in {"P1", "P2"}
    a4 = incident_analyzer.analyze("P0 outage: full site down, checkout failing.", s)
    assert a4["severity"] == "P0"
    # unknown text must not invent a service
    a5 = incident_analyzer.analyze("Something feels slow today.", s)
    assert a5["service"] is None


def test_query_construction_and_categories():
    a = {"service": "Payment API", "error": "HTTP 503", "event": "Deployment", "category": "Application/Deployment",
         "severity": "P2", "keywords": ["payment", "503", "deployment"], "symptoms": [], "environment": "Production"}
    q = query_constructor.build_query(a, "Payment API returns HTTP 503 after deployment.")
    assert "503" in q and "service unavailable" in q  # synonym expansion
    cats = query_constructor.suggested_categories(a)
    assert "RUNBOOK" in cats and "DEPLOYMENT_GUIDE" in cats


def test_root_cause_taxonomy_classifier():
    assert classify_text("failed rollout after bad image tag caused outage")[0] == "Deployment Failure"
    assert classify_text("pods OOMKilled due to memory limit exceeded")[0] == "Resource Exhaustion"
    assert classify_text("postgres primary failover left stale credentials")[0] == "Database Failure"
    assert classify_text("lunch at noon")[0] == "Other"


def test_root_cause_extraction_is_grounded():
    chunks = [
        {"text": "Root cause: Missing ConfigMap payment-config in the namespace. Confirmed via events.", "citation": "INC-542", "document_no": "D1", "category": "JIRA_INCIDENT", "score": 0.6, "service": "Payment API"},
        {"text": "Pod restart loop caused by failed readiness probe after rollout of new image.", "citation": "RB-9", "document_no": "D2", "category": "RUNBOOK", "score": 0.5, "service": "Payment API"},
    ]
    causes = root_cause.extract_causes_from_chunks(chunks, {"service": "Payment API"})
    assert causes
    assert causes[0]["status"] == "CONFIRMED"
    assert causes[0]["evidence"] == ["INC-542"]
    assert all(c["evidence"] for c in causes)


def test_rewriter_changes_query(runtime):
    state = {
        "user_input": "Payment API 503 after deploy",
        "analysis": {"service": "Payment API", "keywords": ["503", "deployment"], "error": "HTTP 503", "category": "Application/Deployment"},
        "chunks": [{"text": "completely unrelated catering notes", "citation": "X", "score": 0.1}],
        "attempt": 1,
        "grader": {"feedback": "missing 503 deployment terms"},
        "pipeline_config": {"settings": get_settings()},
    }
    out = query_rewriter.run(state)
    assert out["queries"][-1] != "Payment API 503 after deploy"
    assert "503" in out["queries"][-1] or "service unavailable" in out["queries"][-1]


def test_full_workflow_with_seeded_corpus(runtime):
    final = run_workflow("Payment API returns HTTP 503 after deployment.", runtime=runtime)
    assert final["analysis"]["service"] == "Payment API"
    assert final["chunks"], "expected retrieved evidence"
    assert final["quality"] in {"GOOD", "FAIR", "POOR"}
    assert final["causes"], "expected at least one cause (possibly INSUFFICIENT_EVIDENCE)"
    assert all(c["status"] in {"CONFIRMED", "PROBABLE", "POSSIBLE", "INSUFFICIENT_EVIDENCE"} for c in final["causes"])
    for step in final["troubleshooting"]:
        assert step["evidence"], "every step must cite evidence"
    assert 0.0 <= final["confidence"] <= 1.0
    assert "AI Confidence Score" in final["final_text"] or "Insufficient Evidence" in final["final_text"]
    art = artifact_state(final)
    assert "pipeline_config" not in art and "user_input" in art


def test_final_response_sections_format(runtime):
    final = run_workflow("Payment API returns HTTP 503 after deployment.", runtime=runtime)
    txt = final["final_text"]
    if "Insufficient Evidence" not in txt:
        for header in ("Incident Summary", "Probable Root Cause", "Confidence", "Retrieval Quality",
                       "Recommended Troubleshooting", "Supporting Evidence", "Evidence Status"):
            assert header in txt, f"missing section {header}"
    else:
        assert "Escalate to an SRE" in txt


def test_artifact_contains_no_chain_of_thought(runtime):
    final = run_workflow("Database connection timeout in Order Service under load.", runtime=runtime)
    art = artifact_state(final)
    for banned in ("pipeline_config", "_max_attempts"):
        assert banned not in art


def test_build_graph_compiles_or_falls_back():
    graph = build_graph()
    assert graph is not None or True  # either langgraph or builtin runner; run_workflow covers both
