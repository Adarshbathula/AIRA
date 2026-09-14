"""Evidence validation, citation integrity and confidence tests."""
from __future__ import annotations

from app.core.config import get_settings
from app.graph.nodes import confidence as confidence_node
from app.graph.nodes import evidence_validator
from app.graph.workflow import run_workflow


def _state_with(**kw):
    base = {"chunks": [], "causes": [], "troubleshooting": [], "analysis": {}, "trace": [],
            "pipeline_config": {"settings": get_settings()}}
    base.update(kw)
    return base


def test_supported_claim():
    chunk = {"chunk_ref": "C1", "citation": "RUNBOOK-005", "document_no": "D1", "text": "Restart affected pods using kubectl rollout restart deployment after config change.", "score": 0.6}
    st = _state_with(
        chunks=[chunk],
        troubleshooting=[{"step": "Restart affected pods using kubectl rollout restart deployment", "evidence": ["RUNBOOK-005"]}],
    )
    out = evidence_validator.run(st)
    assert out["evidence_status"] == "SUPPORTED"
    assert out["evidence_claims"][0]["status"] == "SUPPORTED"


def test_hallucinated_step_flagged():
    chunk = {"chunk_ref": "C1", "citation": "RUNBOOK-005", "document_no": "D1", "text": "Verify ConfigMap checksum before rollout of the payment api.", "score": 0.6}
    st = _state_with(
        chunks=[chunk],
        troubleshooting=[{"step": "Reboot the entire production cluster and flush all DNS caches immediately", "evidence": ["RUNBOOK-005"]}],
    )
    out = evidence_validator.run(st)
    assert out["evidence_claims"][0]["status"] == "INSUFFICIENT"
    assert out["evidence_status"] in {"INSUFFICIENT", "PARTIALLY_SUPPORTED"}
    assert out["unsupported_claims"]


def test_dangling_citation_flagged():
    st = _state_with(
        chunks=[{"chunk_ref": "C1", "citation": "RUNBOOK-005", "document_no": "D1", "text": "Check deployment status after rollout.", "score": 0.6}],
        causes=[{"label": "X", "description": "check deployment status after rollout", "status": "PROBABLE", "evidence": ["FAKE-DOC-999"]}],
    )
    out = evidence_validator.run(st)
    assert "dangling refs" in out["evidence_claims"][0]["detail"]


def test_confidence_monotonic_and_capped():
    weak = _state_with(quality="POOR", grader={"score": 0.2}, chunks=[])
    score_weak, _ = confidence_node.compute_confidence(weak)
    assert score_weak <= 0.06  # no chunks -> floor

    strong_chunks = [
        {"citation": f"C{i}", "document_no": f"D{i}", "score": 0.72, "text": "configmap 503 deployment verification"} for i in range(4)
    ]
    strong = _state_with(
        quality="GOOD",
        grader={"score": 0.85},
        chunks=strong_chunks,
        causes=[{"label": "Configuration Error", "status": "CONFIRMED", "evidence": ["C1", "C2", "C3"], "description": "missing configmap"}],
        troubleshooting=[{"step": "s", "evidence": ["C1"]}],
        evidence_claims=[{"status": "SUPPORTED"}],
        similar_incidents=[{"similarity": 0.9, "outcome": "RESOLVED"}],
    )
    score_strong, breakdown = confidence_node.compute_confidence(strong)
    assert score_strong > score_weak
    assert 0.5 < score_strong <= 0.97
    assert breakdown.retrieval_quality > 0.5


def test_penalty_for_retries():
    chunks = [{"citation": "C1", "document_no": "D1", "score": 0.7, "text": "t"}]
    a = _state_with(quality="GOOD", grader={"score": 0.8}, chunks=chunks, attempt=1,
                    causes=[{"label": "L", "status": "PROBABLE", "evidence": ["C1"], "description": "d"}],
                    evidence_claims=[{"status": "SUPPORTED"}])
    b = dict(a, attempt=3)
    sa, _ = confidence_node.compute_confidence(a)
    sb, _ = confidence_node.compute_confidence(b)
    assert sb < sa


def test_confidence_label_bounds():
    assert confidence_node.label_for(0.9) == "High"
    assert confidence_node.label_for(0.5) == "Medium"
    assert confidence_node.label_for(0.1) == "Low"


def test_pipeline_reports_insufficient_evidence_for_unknown_incident(runtime):
    final = run_workflow("Zylograph network harmonic in the widgetbus mainframe", runtime=runtime)
    assert final.get("insufficient_evidence") or final.get("quality") == "POOR"
    assert "Insufficient Evidence" in final["final_text"] or "confidence" in final["final_text"].lower()


def test_every_recommendation_and_cause_has_evidence_ref(runtime):
    final = run_workflow("Payment API returns HTTP 503 after deployment.", runtime=runtime)
    citations = {c.get("citation") for c in final.get("chunks", [])}
    for step in final.get("troubleshooting", []):
        assert step["evidence"] and set(step["evidence"]) <= citations
    for cause in final.get("causes", []):
        if cause["status"] != "INSUFFICIENT_EVIDENCE":
            assert set(cause["evidence"]) <= citations
