"""FAISS vector store + retrieval + grading + self-healing loop tests."""
from __future__ import annotations

import numpy as np

from app.core.config import get_settings
from app.rag.grading.context_grader import deterministic_score, grade_context
from app.rag.grading.lexical import bm25, overlap, sentence_split
from app.rag.retrieval.incident_store import incident_vector_text, search_similar_incidents
from app.rag.retrieval.multi_source import MultiSourceRetriever
from app.rag.vectorstore.faiss_store import VRecord, VectorStore


def test_vector_store_add_search_delete_persist(tmp_path, runtime):
    store = VectorStore(tmp_path, runtime.embeddings, "unittest")
    recs = [
        VRecord("A-1", "database connection pool exhaustion causes timeouts in orders", {"category": "RCA"}),
        VRecord("A-2", "kubernetes pod crashloopbackoff restart loop after bad image", {"category": "RUNBOOK"}),
    ]
    store.add(recs)
    assert len(store) == 2

    hits = store.search("database pool exhausted causing timeouts", k=2)
    assert hits and hits[0][0].ref == "A-1"

    filtered = store.search("database pool exhausted causing timeouts", k=2, filters={"category": "RUNBOOK"})
    assert all(h[0].metadata["category"] == "RUNBOOK" for h in filtered)

    assert store.delete_refs({"A-1"}) == 1
    store.commit()
    reloaded = VectorStore(tmp_path, runtime.embeddings, "unittest")
    assert [r.ref for r in reloaded.records] == ["A-2"]


def test_upsert_replaces_text_keeps_single_record(runtime):
    from app.rag.runtime import get_runtime

    rt = get_runtime()
    n_before = len(rt.document_store)
    rec = VRecord("DOC-0001-C000", "updated text about configmap validation steps for payments", {
        "document_id": 1, "document_no": "DOC-0001", "citation": "RUNBOOK-005", "category": "RUNBOOK",
        "service": "Payment API", "document_name": "x", "section": "s", "chunk_index": 0})
    rt.document_store.upsert([rec])
    assert len(rt.document_store) == n_before  # replaced, not appended
    stored = next(r for r in rt.document_store.records if r.ref == "DOC-0001-C000")
    assert stored.text.startswith("updated text")
    # restore original
    rt.document_store.upsert([VRecord("DOC-0001-C000",
        "Missing ConfigMap in the production namespace causes HTTP 503 responses. Verify ConfigMap availability with kubectl get configmap. Reapply the ConfigMap and restart affected pods.",
        stored.metadata)])


def test_multi_source_retrieval_categories_and_thresholds(runtime):
    rt = MultiSourceRetriever(runtime.document_store, runtime.embeddings)
    chunks = rt.retrieve("payment api http 503 deployment configmap", categories=["RUNBOOK", "RCA"], service="Payment API")
    assert chunks, "expected retrieved context"
    assert all(c.category in {"RUNBOOK", "RCA"} for c in chunks)
    assert all(c.score >= get_settings().retrieval_score_threshold * 0.85 for c in chunks)
    per_cat = {}
    for c in chunks:
        per_cat[c.category] = per_cat.get(c.category, 0) + 1
    assert max(per_cat.values()) <= max(get_settings().retrieval_max_per_category, 2)


def test_empty_store_returns_no_results():
    class Emb:
        model_name = "x"; dimension = 4

        def embed_texts(self, texts):
            return np.ones((len(texts), 4), dtype="float32")

        def embed_query(self, text):
            return np.ones(4, dtype="float32")

    store = VectorStore.__new__(VectorStore)
    store.records, store._matrix, store._index = [], None, None
    store.embeddings = Emb()
    store.index_dir = __import__("pathlib").Path("/tmp/aira_pytest/vs_empty")
    store.store_name = "empty"
    store.backend = "numpy-fallback"
    assert store.search("anything", k=3) == []


def test_context_grader_good_vs_poor():
    s = get_settings()
    good_chunks = [
        {"text": "Missing ConfigMap causes HTTP 503. Verify configmap restart pods deployment", "category": "RUNBOOK", "score": 0.72, "citation": "R1", "document_no": "D1"},
        {"text": "HTTP 503 after deployment: reapply ConfigMap and validate endpoints with kubectl", "category": "SOP", "score": 0.66, "citation": "R2", "document_no": "D2"},
        {"text": "Deployment rollout history and readiness probes failing during 503 window", "category": "RCA", "score": 0.6, "citation": "R3", "document_no": "D3"},
    ]
    score, signals = deterministic_score(good_chunks, ["503", "deployment", "configmap"], s.retrieval_score_threshold)
    assert score > s.context_good_threshold
    graded = grade_context(good_chunks, ["503", "deployment", "configmap"], settings=s)
    assert graded.quality == "GOOD"

    weak = [{"text": "quarterly catering menu options and office plants", "category": "KNOWLEDGE_BASE", "score": 0.05, "citation": "W1", "document_no": "W"}]
    graded2 = grade_context(weak, ["503", "deployment", "configmap"], settings=s)
    assert graded2.quality == "POOR"
    assert grade_context([], ["503"], settings=s).quality == "POOR"


def test_similar_incident_semantic_search(runtime):
    q = incident_vector_text("Database connection timeout in Order Service", "Order Service", "Database", None)
    hits = search_similar_incidents(runtime.incident_store, q, top_k=3, threshold=0.0)
    assert hits, "expected similar incidents"
    assert hits[0].public_id == "INC-231"
    assert 0 <= hits[0].similarity <= 1


def test_lexical_helpers():
    assert overlap("verify ConfigMap availability in namespace", "Missing ConfigMap in the namespace. Verify ConfigMap availability with kubectl.") > 0.4
    assert overlap("restart pods", "completely unrelated sentence about catering") < 0.1
    scores = bm25("configmap 503", ["verify configmap before 503 escalation", "lunch menu for friday"], )
    assert scores[0] > scores[1]
    assert sentence_split("First sentence here long enough. Second one is also long enough to pass.") == [
        "First sentence here long enough.", "Second one is also long enough to pass."
    ]


def test_self_healing_retry_loop(runtime):
    """POOR context must trigger rewrite + re-retrieval until GOOD or budget exhausted."""
    from app.core.config import Settings
    from app.graph.workflow import run_workflow

    strict = Settings()
    # Force the first pass to fail: temporarily raise the threshold so retrieval yields nothing useful.
    object.__setattr__(strict, "retrieval_score_threshold", 0.95)
    object.__setattr__(strict, "context_good_threshold", 0.99)
    object.__setattr__(strict, "context_poor_threshold", 0.98)
    import app.core.config as cfgmod

    orig = cfgmod.get_settings
    cfgmod.get_settings = lambda: strict
    try:
        state = run_workflow("Quantum harmonic desync in the mainframe", runtime=runtime)
    finally:
        cfgmod.get_settings = orig
        cfgmod.get_settings.cache_clear()
    assert state.get("attempt", 1) > 1, "workflow should retry when context is POOR"
    assert any(t["node"] == "query_rewriter" and t["status"] == "retry" for t in state.get("trace", []))
    assert state.get("quality") in {"POOR", "FAIR"}  # still weak data, honest quality
    assert len(state.get("queries", [])) >= 2
