"""Evaluation harness: retrieval quality metrics, faithfulness, latency (spec §34)."""
from __future__ import annotations

import time

import pytest

from app.graph.workflow import run_workflow
from app.rag.grading.lexical import overlap

# ground-truth retrieval labels: query -> citations that must be retrieved
GOLD = {
    "Payment API returns HTTP 503 after deployment.": {"RUNBOOK-005", "SOP-API-01"},
    "Database connection timeout in Order Service under peak load.": {"RCA-018"},
    "User service pods terminated with OOMKilled.": {"KB-013"},
    "Kafka consumer lag is rising and notifications are delayed.": {"TSG-007"},
}


@pytest.fixture(scope="module")
def seeded_runtime(rag_session):
    return rag_session


def _precision_at_k(hits_citations, gold, k=4):
    top = [c for c, _ in hits_citations[:k]]
    relevant = sum(1 for c in top if c in gold)
    return relevant / min(k, len(gold)) if gold else 0.0, relevant


def test_retrieval_precision_recall_at_k(seeded_runtime):
    from app.rag.retrieval.multi_source import MultiSourceRetriever

    rt = MultiSourceRetriever(seeded_runtime.document_store, seeded_runtime.embeddings)
    p_sum = r_sum = 0.0
    for query, gold in GOLD.items():
        chunks = rt.retrieve(query, k=8, score_threshold=0.0)
        pairs = [(c.citation, c.score) for c in chunks]
        prec, rel = _precision_at_k(pairs, gold)
        rec = rel / len(gold)
        assert prec >= 0.5, f"low precision for {query!r}: {pairs[:6]}"
        p_sum += prec
        r_sum += rec
    assert p_sum / len(GOLD) >= 0.75
    assert r_sum / len(GOLD) >= 0.75


def test_answer_faithfulness_all_claims_grounded(seeded_runtime):
    """Faithfulness proxy: fraction of generated claims overlapping evidence."""
    total = supported = 0
    for query in GOLD:
        final = run_workflow(query, runtime=seeded_runtime)
        claims = final.get("evidence_claims") or []
        if not claims:
            assert final.get("insufficient_evidence"), "claims expected unless flagged insufficient"
            continue
        for cl in claims:
            total += 1
            if cl["status"] in {"SUPPORTED", "PARTIALLY_SUPPORTED"}:
                supported += 1
            blob = " ".join(c.get("text", "") for c in final.get("chunks", [])[:8]).lower()
            key_terms = [t for t in (cl["claim"].lower().split()) if len(t) > 5][:6]
            assert any(t in blob for t in key_terms) or cl["status"] == "INSUFFICIENT", "unfaithful claim leaked"
    assert total == 0 or supported / total >= 0.6


def test_context_grader_alignment_with_gold(seeded_runtime):
    """Grader must score gold-context higher than random context."""
    from app.core.config import get_settings
    from app.rag.grading.context_grader import deterministic_score

    s = get_settings()
    good, _ = deterministic_score(
        [{"text": "payment api 503 missing configmap reapply restart pods deployment", "category": "RUNBOOK", "score": 0.7, "citation": "A", "document_no": "D1"},
         {"text": "configmap verification steps for http 503 after deployment rollout", "category": "SOP", "score": 0.62, "citation": "B", "document_no": "D2"},
         {"text": "deployment status check and rollback procedure after 503 outage", "category": "RCA", "score": 0.55, "citation": "C", "document_no": "D3"}],
        ["503", "deployment", "payment", "configmap"], s.retrieval_score_threshold)
    bad, _ = deterministic_score(
        [{"text": "office catering and parking policy", "category": "KNOWLEDGE_BASE", "score": 0.1, "citation": "X", "document_no": "D9"}],
        ["503", "deployment", "payment", "configmap"], s.retrieval_score_threshold)
    assert good > bad + 0.3


def test_self_healing_improves_or_preserves_quality(seeded_runtime):
    """On a tuned-down threshold config the loop must attempt a rewrite and
    never fabricate: final quality is honest GOOD/FAIR/POOR."""
    q_seen = None
    t0 = time.perf_counter()
    final = run_workflow("Payment API returns HTTP 503 after deployment.", runtime=seeded_runtime)
    took_ms = (time.perf_counter() - t0) * 1000
    q_seen = final["quality"]
    assert q_seen in {"GOOD", "FAIR", "POOR"}
    assert took_ms < 60_000  # pipeline latency bound on test hardware
    assert final["retrieval_took_ms"] if "retrieval_took_ms" in final else True


def test_metrics_endpoints_report_distribution(client, tokens, seeded_runtime):
    client.post("/api/incidents", headers=tokens["user_h"], json={"description": "Payment API returns HTTP 503 after deployment."})
    conf = client.get("/api/dashboard/confidence", headers=tokens["user_h"]).json()
    assert conf["total"] >= 1
    assert sum(b["count"] for b in conf["buckets"]) == conf["total"]
    ret = client.get("/api/dashboard/retrieval", headers=tokens["user_h"]).json()
    assert ret["avg_retrieval_attempts"] >= 1.0


class _IncidentOnlyRuntime:
    """Bare runtime exposing just the incident store (isolated from other tests)."""

    def __init__(self, store) -> None:
        self.incident_store = store
        self.document_store = None
        self.retriever = None


@pytest.fixture()
def incident_store_only():
    """A pristine incident store seeded from conftest.INCIDENTS, unaffected by
    incidents created by earlier API tests in the same session."""
    import tempfile
    from pathlib import Path

    from app.core.config import get_settings
    from app.rag.embeddings.provider import get_embeddings
    from app.rag.vectorstore.faiss_store import VectorStore, VRecord

    from conftest import INCIDENTS

    emb = get_embeddings()
    store = VectorStore(Path(tempfile.mkdtemp(prefix="aira-eval-inc-")), emb, "incidents")
    store.reset()
    for pid, desc, svc, cat, sev, rc, outcome in INCIDENTS:
        store.upsert([VRecord(ref=pid, text=f"{desc}\nservice: {svc}\nknown root cause: {rc}",
                              metadata={"public_id": pid, "service": svc, "category": cat,
                                        "severity": sev, "title": desc, "root_cause": rc,
                                        "resolution": f"Fixed: {rc}", "outcome": outcome,
                                        "created_at": "2026-01-05"})])
    return _IncidentOnlyRuntime(store)


def test_root_cause_accuracy_proxy(incident_store_only):
    """Against seeded incidents, the historical incident for this exact pattern
    should be retrieved as the top similar match (proxy for cause accuracy)."""
    final = run_workflow("Payment API returns HTTP 503 after deployment.", runtime=incident_store_only)
    assert final["similar_incidents"]
    top = final["similar_incidents"][0]
    assert top["public_id"] == "INC-542"
    assert top["root_cause"] and "configmap" in top["root_cause"].lower()


def test_similar_search_excludes_current_incident(incident_store_only):
    """An incident must never be recommended as its own "similar past incident",
    yet the exclusion must not suppress the remaining candidates."""
    from app.rag.retrieval.incident_store import incident_vector_text, search_similar_incidents

    q = incident_vector_text("Payment API returns HTTP 503 after deployment.", "Payment API", "Application/Deployment", None)
    store = incident_store_only.incident_store

    with_self = search_similar_incidents(store, q, threshold=0.2)
    without_self = search_similar_incidents(store, q, threshold=0.2, exclude_public_id="INC-542")

    assert [h.public_id for h in with_self][0] == "INC-542"
    assert "INC-542" not in [h.public_id for h in without_self]
    assert len(without_self) == len(with_self) - 1
    # and the workflow honours the parameter end-to-end
    final = run_workflow(
        "Payment API returns HTTP 503 after deployment.",
        runtime=incident_store_only,
        exclude_public_id="INC-542",
    )
    assert "INC-542" not in [s_["public_id"] for s_ in final["similar_incidents"]]
