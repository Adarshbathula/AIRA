"""Query Construction node: turns the analysis into a retrieval-optimised query."""
from __future__ import annotations

from typing import Any

from app.graph.nodes import settings_of
from app.rag.grading.lexicon import DOMAIN_SYNONYMS, expand_tokens


def build_query(analysis: dict[str, Any], user_text: str, *, synonym_budget: int = 12) -> str:
    parts: list[str] = []
    for key in ("error", "event", "service", "category"):
        v = analysis.get(key)
        if v:
            parts.append(str(v))
    keywords = [k for k in (analysis.get("keywords") or []) if k]
    parts.extend(keywords[:10])
    for tok in keywords[:12]:
        for syn in DOMAIN_SYNONYMS.get(str(tok).lower(), [])[:2]:
            parts.append(syn)
    parts = parts[: 12 + synonym_budget]
    if not parts:  # degenerate input -> raw text is the query
        return (user_text or "").strip()[:600]
    return " ".join(dict.fromkeys(p.lower() for p in parts if p)).strip()


def suggested_categories(analysis: dict[str, Any]) -> list[str]:
    """Category fan-out plan for multi-source retrieval."""
    cat = analysis.get("category") or "General"
    plan = {
        "Database": ["RCA", "RUNBOOK", "SOP", "TROUBLESHOOTING_GUIDE", "INCIDENT_REPORT", "POSTMORTEM"],
        "Kubernetes / Container": ["RUNBOOK", "SOP", "INCIDENT_REPORT", "RCA", "POSTMORTEM", "CHANGE_REQUEST"],
        "Compute / Resource": ["RUNBOOK", "SOP", "RCA", "TROUBLESHOOTING_GUIDE", "LOG", "POSTMORTEM"],
        "Network": ["RUNBOOK", "SOP", "RCA", "ARCHITECTURE", "INCIDENT_REPORT", "POSTMORTEM"],
        "Security / Auth": ["SOP", "RUNBOOK", "INCIDENT_REPORT", "RCA", "KNOWLEDGE_BASE", "CHANGE_REQUEST"],
        "Middleware": ["RUNBOOK", "RCA", "INCIDENT_REPORT", "TROUBLESHOOTING_GUIDE", "POSTMORTEM", "SOP"],
        "Application/Deployment": ["RUNBOOK", "DEPLOYMENT_GUIDE", "CHANGE_REQUEST", "RCA", "INCIDENT_REPORT", "POSTMORTEM", "SOP"],
        "Storage": ["RUNBOOK", "SOP", "RCA", "ARCHITECTURE", "POSTMORTEM", "LOG"],
    }.get(cat, ["RUNBOOK", "SOP", "RCA", "INCIDENT_REPORT", "TROUBLESHOOTING_GUIDE"])
    extras = list(analysis.get("keywords") or [])
    joined = " ".join(str(k).lower() for k in extras)
    if "deploy" in joined or "config" in joined:
        for c in ("DEPLOYMENT_GUIDE", "CHANGE_REQUEST"):
            if c not in plan:
                plan.insert(1, c)
    if "architecture" in joined or "depend" in joined:
        if "ARCHITECTURE" not in plan:
            plan.append("ARCHITECTURE")
    return plan[:8]


def run(state: dict[str, Any]) -> dict[str, Any]:
    settings = settings_of(state)
    analysis = state.get("analysis") or {}
    query = build_query(analysis, state.get("user_input", ""), synonym_budget=12)
    categories = suggested_categories(analysis)
    queries = list(state.get("queries") or [])
    if query not in queries:
        queries.append(query)
    return {
        "queries": queries,
        "retrieval_categories": categories,
        "trace": (state.get("trace") or [])
        + [{"node": "query_constructor", "status": "ok", "detail": f"{len(query.split())} terms; categories={','.join(categories[:5])}"}],
    }
