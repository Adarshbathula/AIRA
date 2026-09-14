"""Root Cause Generator node.

Grounded generation only:

  * deterministic mode  - causes are *extracted* from retrieved evidence:
      explicit "root cause" statements inside RCA/postmortem/incident chunks
      (CONFIRMED when the source is a resolved RCA that matches this incident),
      otherwise taxonomy scoring over chunks decides PROBABLE/POSSIBLE causes,
      with a sentence of the supporting chunk used as the explanation.
  * LLM mode            - Groq proposes causes *restricted to supplied
      citations*; every proposal is validated afterwards by the Evidence
      Validator, so unsupported suggestions get flagged, not silently trusted.
"""
from __future__ import annotations

import json
import re
from typing import Any

from app.graph.nodes import first_line, llm_of, runtime_of, safe_json, settings_of
from app.graph.taxonomy import ROOT_CAUSE_TAXONOMY, classify_text, TAXON_LABELS
from app.rag.grading.lexicon import content_tokens

_ROOT_LINE = re.compile(
    r"(root cause|probable cause|primary cause|confirmed cause)\s*[:\-]?\s*(.{15,320})", re.I
)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")


def _probability_and_status(hits: int, doc_count: int, confirmed: bool) -> tuple[str, str]:
    if confirmed:
        return "High", "CONFIRMED"
    if hits >= 3 or (hits >= 2 and doc_count >= 2):
        return "High", "PROBABLE"
    if hits >= 2 or doc_count >= 2:
        return "Medium", "PROBABLE"
    return "Low", "POSSIBLE"


def extract_causes_from_chunks(chunks: list[dict[str, Any]], analysis: dict[str, Any]) -> list[dict[str, Any]]:
    """Deterministic, evidence-bound root-cause candidates."""
    svc = (analysis.get("service") or "").lower()
    explicit: list[dict[str, Any]] = []
    stats: dict[str, dict[str, Any]] = {}

    for c in chunks:
        text = c.get("text") or ""
        cat = c.get("category") or ""
        cit = c.get("citation") or c.get("document_no") or c.get("chunk_ref")
        blob_low = text.lower()
        # a chunk from a *different* service is never treated as confirmed
        cross_service = bool(svc) and bool(c.get("service")) and svc not in str(c.get("service")).lower()
        # 1) explicit statements -------------------------------------------------
        for m in _ROOT_LINE.finditer(text):
            stmt = re.split(r"\n", m.group(2).strip())[0].strip(" .;")
            if len(stmt) < 15 or stmt.lower().startswith(("unknown", "not determin", "tbd", "n/a")):
                continue
            label, hits = classify_text(stmt)
            confirmed = (
                not cross_service
                and c.get("score", 0.0) >= 0.32
                and cat in {"RCA", "POSTMORTEM", "INCIDENT_REPORT", "JIRA_INCIDENT"}
                and bool(re.search(r"(confirmed|resolved by|fix(?:ed)? by|due to)", blob_low))
            )
            explicit.append(
                {
                    "label": label if label != "Other" else first_line(stmt, 60),
                    "description": stmt[:280],
                    "status": "CONFIRMED" if confirmed else "PROBABLE",
                    "probability": "High" if confirmed else "Medium",
                    "evidence": [cit],
                    "_score": (3 if confirmed else 2) + c.get("score", 0) + (0.5 if svc and svc in blob_low else 0),
                }
            )
        # 2) taxonomy scoring ------------------------------------------------------
        for taxon in ROOT_CAUSE_TAXONOMY:
            h = taxon.matches(blob_low)
            if not h:
                continue
            entry = stats.setdefault(
                taxon.label,
                {"label": taxon.label, "hits": 0, "evidence": [], "docs": set(), "example": None, "score": 0.0},
            )
            penalty = 0.55 if cross_service else 1.0
            entry["hits"] += h
            entry["score"] += h * (0.5 + c.get("score", 0)) * penalty
            entry["docs"].add(c.get("document_no") or cit)
            if cit not in entry["evidence"]:
                entry["evidence"].append(cit)
            if entry["example"] is None:
                for s in _SENTENCE_SPLIT.split(text):
                    if taxon.matches(s) and len(s) > 40:
                        entry["example"] = s.strip()[:260]
                        break

    derived: list[dict[str, Any]] = []
    for label, e in sorted(stats.items(), key=lambda kv: -kv[1]["score"]):
        prob, status = _probability_and_status(e["hits"], len(e["docs"]), confirmed=False)
        derived.append(
            {
                "label": label,
                "description": e["example"] or f"Signals for '{label}' appear across retrieved {', '.join(sorted(e['docs']))}.",
                "status": status,
                "probability": prob,
                "evidence": e["evidence"][:4],
                "_score": e["score"],
            }
        )

    merged: list[dict[str, Any]] = []
    used_refs: set[tuple[str, str]] = set()
    for item in sorted(explicit, key=lambda d: -d["_score"]) + derived:
        key = (item["label"], (item.get("description") or "")[:60])
        if key in used_refs:
            for prev in merged:
                if (prev["label"], prev["description"][:60]) == key:
                    for ev in item["evidence"]:
                        if ev not in prev["evidence"]:
                            prev["evidence"].append(ev)
                    if item["status"] == "CONFIRMED":
                        prev["status"], prev["probability"] = "CONFIRMED", "High"
            continue
        used_refs.add(key)
        item = {k: v for k, v in item.items() if not k.startswith("_")}
        merged.append(item)

    status_rank = {"CONFIRMED": 3, "PROBABLE": 2, "POSSIBLE": 1, "INSUFFICIENT_EVIDENCE": 0}
    merged.sort(key=lambda d: (status_rank.get(d["status"], 0), len(d["evidence"])), reverse=True)

    # one entry per cause label - merge evidence citations into the strongest entry
    by_label: dict[str, dict] = {}
    for item in merged:
        key = item["label"][:48].lower()
        cur = by_label.get(key)
        if cur is None:
            by_label[key] = item
            continue
        cur["evidence"] = list(dict.fromkeys(cur["evidence"] + item.get("evidence", [])))[:4]
        if status_rank.get(item["status"], 0) > status_rank.get(cur["status"], 0):
            cur["status"], cur["probability"] = item["status"], item["probability"]
        if len(item.get("description") or "") > len(cur.get("description") or ""):
            cur["description"] = item["description"]
    result = sorted(by_label.values(), key=lambda d: (status_rank.get(d["status"], 0), len(d["evidence"]), d.get("score", 0)), reverse=True)
    return result[:5]


_LLM_SYSTEM = (
    "You are an SRE root-cause analyst. Using ONLY the provided evidence excerpts, list probable "
    "root causes for the incident. Every cause MUST cite at least one evidence ref (citation field) "
    "from the provided list; if the evidence does not support a cause, say so with status "
    "'INSUFFICIENT_EVIDENCE'. Never invent runbook names, commands or incidents. Return JSON: "
    '{"causes": [{"label": "...", "description": "...", "status": "CONFIRMED|PROBABLE|POSSIBLE",'
    ' "probability": "High|Medium|Low", "evidence": ["REF1","REF2"]}]}'
)


def run(state: dict[str, Any]) -> dict[str, Any]:
    settings = settings_of(state)
    analysis = state.get("analysis") or {}
    chunks = state.get("chunks") or []

    causes = extract_causes_from_chunks(chunks, analysis)
    llm_used = state.get("llm_used", False)

    llm = llm_of(state)
    if llm is not None and getattr(llm, "available", False) and chunks:
        try:
            payload = {
                "incident": state.get("user_input", "")[:900],
                "analysis": analysis,
                "evidence": [
                    {"citation": c.get("citation"), "category": c.get("category"), "text": (c.get("text") or "")[:700]}
                    for c in chunks[:10]
                ],
            }
            out = llm.complete_json(_LLM_SYSTEM, safe_json(payload, 9000), max_tokens=1200)
            allowed = {c.get("citation") for c in chunks}
            llm_causes = []
            for c in out.get("causes", [])[:5]:
                refs = [r for r in (c.get("evidence") or []) if r in allowed]
                if not refs:
                    continue  # unsupported LLM invention -> dropped by design
                llm_causes.append(
                    {
                        "label": str(c.get("label"))[:80],
                        "description": str(c.get("description"))[:300],
                        "status": c.get("status") if c.get("status") in {"CONFIRMED", "PROBABLE", "POSSIBLE"} else "PROBABLE",
                        "probability": c.get("probability") if c.get("probability") in {"High", "Medium", "Low"} else "Medium",
                        "evidence": refs,
                    }
                )
            if llm_causes:
                causes = _dedupe_causes(llm_causes + causes)
                llm_used = True
        except Exception:
            pass

    if not causes:
        causes = [
            {
                "label": "Insufficient Evidence",
                "description": "The knowledge base did not contain information that identifies a probable cause.",
                "status": "INSUFFICIENT_EVIDENCE",
                "probability": "Low",
                "evidence": [],
            }
        ]

    top_taxonomy = causes[0]["label"] if causes and causes[0]["status"] != "INSUFFICIENT_EVIDENCE" else "Other"
    return {
        "causes": causes,
        "cause_taxonomy": top_taxonomy,
        "llm_used": llm_used,
        "trace": (state.get("trace") or [])
        + [{"node": "root_cause", "status": "ok", "detail": f"{len(causes)} causes; primary={top_taxonomy}"}],
    }


def _dedupe_causes(causes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for c in causes:
        key = re.sub(r"\W+", "", c["label"].lower())
        if key in seen:
            for ev in c.get("evidence", []):
                target = next((o for o in out if re.sub(r"\W+", "", o["label"].lower()) == key), None)
                if target is not None and ev not in target["evidence"]:
                    target["evidence"].append(ev)
            continue
        seen.add(key)
        out.append(c)
    return out[:5]
