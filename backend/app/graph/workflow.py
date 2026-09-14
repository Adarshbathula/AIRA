"""LangGraph workflow assembly + fallback runner.

Graph (mirrors the Self-Healing RAG design):

    analyze -> construct_query -> retrieve -> grade_context
        ├─[good]─> similar_incidents -> root_cause -> troubleshoot
        └─[poor]─> rewrite_query -> retrieve            -> validate_evidence
                                                                -> estimate_confidence
                                                                -> summarize -> END

``build_graph()`` compiles a real LangGraph ``StateGraph``. If LangGraph is
unavailable, ``run_workflow`` transparently executes the same node functions
with an equivalent loop - node logic is framework-agnostic by design.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable

from app.core.config import get_settings
from app.graph import nodes
from app.graph.nodes import assemble
from app.graph.router import route_after_grader
from app.graph.state import WorkflowState, public_state

logger = logging.getLogger("aira.graph")

NODES: dict[str, Callable[[dict], dict]] = {
    "analyze": nodes.incident_analyzer.run,
    "construct_query": nodes.query_constructor.run,
    "retrieve": nodes.retriever.run,
    "grade_context": nodes.context_grader.run,
    "rewrite_query": nodes.query_rewriter.run,
    "similar_incidents": nodes.similar_incidents.run,
    "root_cause": nodes.root_cause.run,
    "troubleshoot": nodes.recommendations.run,
    "validate_evidence": nodes.evidence_validator.run,
    "estimate_confidence": nodes.confidence.run,
    "summarize": nodes.summarizer.run,
    "assemble": assemble.run,
}


def _timed(name: str, fn: Callable[[dict], dict]) -> Callable[[dict], dict]:
    def wrapper(state: dict) -> dict:
        t0 = time.perf_counter()
        try:
            update = fn(state)
        except Exception as exc:  # node-level failure must not kill the pipeline
            logger.exception("node %s failed", name)
            update = {
                "errors": (state.get("errors") or []) + [f"{name}: {exc}"],
                "trace": (state.get("trace") or []) + [{"node": name, "status": "fail", "detail": str(exc)[:160]}],
            }
        update["_ms_" + name] = round((time.perf_counter() - t0) * 1000, 1)
        return update

    return wrapper


# --------------------------------------------------------------------- graph
_compiled = None
_build_attempted = False


def build_graph():
    """Compile the LangGraph state graph (cached)."""
    global _compiled, _build_attempted
    if _build_attempted:
        return _compiled
    _build_attempted = True
    try:
        from langgraph.graph import END, START, StateGraph

        g = StateGraph(WorkflowState)
        for name, fn in NODES.items():
            g.add_node(name, _timed(name, fn))
        g.add_edge(START, "analyze")
        g.add_edge("analyze", "construct_query")
        g.add_edge("construct_query", "retrieve")
        g.add_edge("retrieve", "grade_context")
        g.add_conditional_edges(
            "grade_context",
            lambda s: route_after_grader(s, allow_retry=True),
            {"good": "similar_incidents", "poor": "rewrite_query"},
        )
        g.add_edge("rewrite_query", "retrieve")
        g.add_edge("similar_incidents", "root_cause")
        g.add_edge("root_cause", "troubleshoot")
        g.add_edge("troubleshoot", "validate_evidence")
        g.add_edge("validate_evidence", "estimate_confidence")
        g.add_edge("estimate_confidence", "summarize")
        g.add_edge("summarize", "assemble")
        g.add_edge("assemble", END)
        _compiled = g.compile()
        logger.info("LangGraph workflow compiled (%d nodes)", len(NODES))
    except Exception as exc:  # pragma: no cover - fallback path
        logger.warning("LangGraph compile failed (%s); using built-in runner", exc)
        _compiled = None
    return _compiled


# --------------------------------------------------------------- fallback run
def _run_local(state: dict[str, Any]) -> dict[str, Any]:
    for name in ("analyze", "construct_query", "retrieve", "grade_context"):
        state = _apply(state, name)
    s = get_settings()
    max_attempts = int(state.get("_max_attempts") or s.max_retrieval_attempts)
    guard = 0
    while route_after_grader(state, allow_retry=True) == "poor" and guard < max_attempts + 2:
        guard += 1
        state = _apply(state, "rewrite_query")
        state = _apply(state, "retrieve")
        state = _apply(state, "grade_context")
    for name in (
        "similar_incidents",
        "root_cause",
        "troubleshoot",
        "validate_evidence",
        "estimate_confidence",
        "summarize",
        "assemble",
    ):
        state = _apply(state, name)
    return state


def _apply(state: dict[str, Any], name: str) -> dict[str, Any]:
    t0 = time.perf_counter()
    try:
        update = NODES[name](state)
    except Exception as exc:  # pragma: no cover
        logger.exception("node %s failed", name)
        update = {"errors": (state.get("errors") or []) + [f"{name}: {exc}"]}
    merged = {**state, **update}
    merged.setdefault("trace", state.get("trace"))
    merged["_ms_" + name] = round((time.perf_counter() - t0) * 1000, 1)
    return merged


# ------------------------------------------------------------------- runner
def run_workflow(
    user_input: str,
    *,
    follow_up_context: str | None = None,
    runtime=None,
    exclude_public_id: str | None = None,
) -> dict[str, Any]:
    """Execute the incident-resolution workflow and return the public state."""
    s = get_settings()
    state: dict[str, Any] = {
        "user_input": user_input.strip(),
        "follow_up_context": follow_up_context,
        "exclude_public_id": exclude_public_id,
        "attempt": 0,
        "queries": [],
        "chunks": [],
        "trace": [],
        "errors": [],
        "_max_attempts": s.max_retrieval_attempts,
        "pipeline_config": {"settings": s, "runtime": runtime},
    }
    graph = build_graph()
    if graph is not None:
        try:
            final = graph.invoke(state, config={"recursion_limit": 25})
        except Exception as exc:  # pragma: no cover
            logger.exception("LangGraph invoke failed; running fallback")
            state["errors"] = state["errors"] + [f"langgraph: {exc}"]
            final = _run_local(state)
    else:
        final = _run_local(state)
    final["_engine"] = "langgraph" if graph is not None else "builtin"
    return final


def artifact_state(state: dict[str, Any]) -> dict[str, Any]:
    """User-facing pipeline artifact persisted to Postgres (no chain-of-thought)."""
    out = public_state(state)
    out.pop("chunks", None)  # full chunk text is stored in the evidence table
    for k in list(out):
        if k.startswith("_"):
            out.pop(k)
    return out
