"""Incident Summarizer node: renders the structured final response block."""
from __future__ import annotations

from typing import Any

from app.graph.nodes import settings_of

INSUFFICIENT_TEXT = (
    "Insufficient Evidence\n"
    "The knowledge base does not contain enough relevant information to confidently recommend a resolution.\n\n"
    "Suggested Action:\n"
    "Escalate to an SRE/IT operations engineer and review the incident manually."
)


def build_summary(state: dict[str, Any]) -> str:
    a = state.get("analysis") or {}
    svc = a.get("service") or "The affected service"
    err = a.get("error") or "is experiencing degraded behaviour"
    env = a.get("environment") or "Production"
    event = a.get("event")
    causes = [c for c in (state.get("causes") or []) if c.get("status") != "INSUFFICIENT_EVIDENCE"]
    err_s = str(err)
    line = f"{svc}: {err_s[0].upper() + err_s[1:]}" if err_s and not err_s.isupper() else f"{svc} {err_s}"
    line += f" in {env}"
    if event:
        line += f" ({event.lower()})"
    line += f". Severity {a.get('severity', 'P2')}, category {a.get('category', 'General')}."
    if causes:
        c = causes[0]
        line += f" Probable root cause ({c['status'].lower()}): {c['description'].rstrip('.')}."
    return line


def build_final_text(state: dict[str, Any]) -> str:
    settings = settings_of(state)
    a = state.get("analysis") or {}
    causes = [c for c in (state.get("causes") or []) if c.get("status") != "INSUFFICIENT_EVIDENCE"]
    steps = state.get("troubleshooting") or []
    similar = state.get("similar_incidents") or []
    chunks = state.get("chunks") or []
    conf = float(state.get("confidence") or 0.0)
    docs_used = list(dict.fromkeys(c.get("citation") for c in chunks if c.get("citation")))[:8]

    rule = "\u2500" * 20
    if not chunks or not causes and not steps:
        return INSUFFICIENT_TEXT + f"\n\n{rule}\nConfidence: {conf:.0%}   Retrieval Quality: {state.get('quality', 'POOR')}"

    lines: list[str] = []
    add = lines.append
    add(f"Incident: {state.get('user_input', '').strip()[:240]}")
    add(rule)
    add("Incident Summary")
    add(rule)
    add(state.get("summary") or build_summary(state))
    add("")
    add("Probable Root Cause")
    add(rule)
    for i, c in enumerate(causes[:3], start=1):
        ev = f"\n   Evidence: {', '.join(c.get('evidence') or [])}" if c.get("evidence") else ""
        add(f"{i}. {c['label']} [{c['status']}] - {c['description']}{ev}")
    add("")
    add("Confidence")
    add(rule)
    add(f"AI Confidence Score: {conf:.0%} ({state.get('confidence_label', 'Low')})")
    add("(heuristic signal blend, not a calibrated probability)")
    add("")
    add("Retrieval Quality")
    add(rule)
    add(f"{state.get('quality', 'POOR')}   Retrieval Attempts: {state.get('attempt', 1)}")
    gr = state.get("grader") or {}
    if gr.get("score") is not None:
        add(f"Grader Score: {gr['score']:.2f}   Supporting Documents: {len({c.get('document_no') for c in chunks})}")
    add("")
    if similar:
        add("Similar Incidents")
        add(rule)
        for s in similar[:5]:
            add(f"{s['public_id']} - {s['similarity']:.0%} similarity - {s['title'][:90]}")
        add("")
    add("Recommended Troubleshooting")
    add(rule)
    for i, s in enumerate(steps[:7], start=1):
        ev = f"\n   Evidence: {', '.join(s.get('evidence') or [])}" if s.get("evidence") else ""
        add(f"{i}. {s['step']}{ev}")
    add("")
    add("Supporting Evidence")
    add(rule)
    add(", ".join(docs_used) or "None")
    add("")
    add("Evidence Status")
    add(rule)
    st = state.get("evidence_status", "INSUFFICIENT")
    add(st)
    if st != "SUPPORTED":
        add("Some recommendations could not be fully grounded in retrieved documents - verify before executing.")
    return "\n".join(lines)


def run(state: dict[str, Any]) -> dict[str, Any]:
    chunks = state.get("chunks") or []
    causes = [c for c in (state.get("causes") or []) if c.get("status") != "INSUFFICIENT_EVIDENCE"]
    steps = state.get("troubleshooting") or []
    summary = build_summary(state)
    final_text = build_final_text({**state, "summary": summary})
    insufficient = (not chunks) or (not causes and not steps)
    return {
        "summary": summary,
        "final_text": final_text,
        "insufficient_evidence": bool(insufficient),
        "trace": (state.get("trace") or [])
        + [{"node": "summarizer", "status": "ok", "detail": "insufficient-evidence message" if insufficient else "structured response rendered"}],
    }
