"""Troubleshooting Generator node.

Rules over the retrieved evidence: every emitted step is a verbatim-ish
instruction lifted from a RUNBOOK / SOP / TROUBLESHOOTING_GUIDE / POSTMORTEM
chunk and carries its citation. LLM-generated steps are only accepted when they
reuse evidence wording (validated downstream by the Evidence Validator).
"""
from __future__ import annotations

import json
import re
from typing import Any

from app.graph.nodes import llm_of, safe_json, settings_of
from app.rag.grading.lexicon import content_tokens
from app.rag.grading.lexical import overlap

PROCEDURE_CATEGORIES = {"RUNBOOK", "SOP", "TROUBLESHOOTING_GUIDE", "DEPLOYMENT_GUIDE", "POSTMORTEM", "KNOWLEDGE_BASE"}
_STEP_RES = [
    re.compile(r"^\s*(?:step\s*)?\d{1,2}[.)\-]?\s+(?P<s>.{12,220})$", re.I),
    re.compile(r"^\s*[-*\u2022]\s+(?P<s>.{12,220})$"),
    re.compile(r"^\s*(?:(?:first|next|then|finally|also|if so|if not)[,:]?\s+)?(?P<s>(?:check|verify|inspect|confirm|restart|roll\s*back|review|validate|increase|reduce|clear|flush|scale|redeploy|reapply|enable|disable|compare|list|describe|grep|tail|run|apply|rollback)\b.{8,220})$", re.I),
]
_SKIP = re.compile(r"^(note|warning|important|owner|author|version|effective date|scope|purpose|summary|context)\s*[:\-]", re.I)


def _is_actionable(line: str) -> bool:
    line = line.strip()
    if len(line) < 14 or _SKIP.match(line):
        return False
    if re.match(r"^(https?://|---|\|)", line):
        return False
    return True


def extract_steps(chunks: list[dict[str, Any]], analysis: dict[str, Any]) -> list[dict[str, Any]]:
    kw = {t.lower() for t in content_tokens(" ".join(str(k) for k in (analysis.get("keywords") or [])))}
    svc = (analysis.get("service") or "").lower()
    collected: dict[str, dict[str, Any]] = {}

    from app.rag.grading.lexical import sentence_split

    for c in chunks:
        cat = c.get("category") or ""
        cit = c.get("citation") or ""
        text = c.get("text") or ""
        if len(text.splitlines()) < 2:  # paragraph-style evidence: scan sentences too
            candidates = [text] + sentence_split(text)
        else:
            candidates = text.splitlines()
        for raw_line in candidates:
            line = raw_line.strip()
            if not _is_actionable(line):
                continue
            matched = None
            for rx in _STEP_RES:
                m = rx.match(line)
                if m:
                    matched = m.group("s").strip(" .;:")
                    break
            if not matched or len(matched) < 12:
                continue
            terms = {t.lower() for t in content_tokens(matched)}
            rel = len(terms & kw) / max(3, len(kw)) if kw else 0.0
            if svc and svc.split() and svc.split()[0] in matched.lower():
                rel += 0.3
            if cat in PROCEDURE_CATEGORIES:
                rel += 0.25
            base = c.get("score", 0.0)
            score = 0.55 * base + 0.45 * min(1.0, rel)
            key = re.sub(r"\W+", " ", matched.lower())[:70]
            prev = collected.get(key)
            if prev is None or score > prev["_score"]:
                entry = dict(prev or {})
                entry.update(
                    {
                        "step": matched[:200],
                        "evidence": sorted(set(entry.get("evidence", []) + [cit]))[:4] if entry.get("evidence") else [cit],
                        "source_categories": sorted(set(entry.get("source_categories", []) + [cat]))[:4] if cat else entry.get("source_categories", []),
                        "_score": round(score, 4),
                        "_base": max(entry.get("_base", 0.0), base),
                    }
                )
                collected[key] = entry

    ranked = sorted(collected.values(), key=lambda d: -d["_score"])
    max_per_cat: dict[str, int] = {}
    out: list[dict[str, Any]] = []
    for item in ranked:
        cats = item.get("source_categories") or ["KNOWLEDGE_BASE"]
        main_cat = cats[0]
        if max_per_cat.get(main_cat, 0) >= 4:
            continue
        max_per_cat[main_cat] = max_per_cat.get(main_cat, 0) + 1
        out.append(
            {
                "step": item["step"],
                "evidence": item["evidence"],
                "source_categories": cats,
                "_base": item["_base"],
            }
        )
        if len(out) >= 8:
            break
    return out


_LLM_SYSTEM = (
    "You are an SRE recommending troubleshooting steps. Use ONLY the evidence excerpts provided. "
    "Each step must be actionable, short, and quote-or-paraphrase an instruction from the evidence. "
    "Attach evidence refs (the citation fields) to every step. If evidence is insufficient, return an "
    'empty list. Return JSON: {"steps":[{"step":"...","evidence":["REF"]}]} Max 6 steps.'
)


def run(state: dict[str, Any]) -> dict[str, Any]:
    settings = settings_of(state)
    analysis = state.get("analysis") or {}
    chunks = state.get("chunks") or []
    llm_used = state.get("llm_used", False)

    steps = extract_steps(chunks, analysis)

    llm = llm_of(state)
    if llm is not None and getattr(llm, "available", False) and chunks:
        try:
            payload = {
                "incident": state.get("user_input", "")[:700],
                "analysis": analysis,
                "root_causes": [c["label"] for c in (state.get("causes") or [])[:3]],
                "evidence": [
                    {"citation": c.get("citation"), "category": c.get("category"), "text": (c.get("text") or "")[:600]}
                    for c in chunks[:10]
                ],
            }
            out = llm.complete_json(_LLM_SYSTEM, safe_json(payload, 9000), max_tokens=1100)
            allowed = {c.get("citation"): c for c in chunks}
            accepted = []
            for s in out.get("steps", [])[:6]:
                refs = [r for r in (s.get("evidence") or []) if r in allowed]
                if not refs:
                    continue
                # anti-hallucination: LLM step must lexically resemble some cited chunk
                blob = " ".join(allowed[r]["text"] for r in refs)[:1200]
                if overlap(s.get("step", ""), blob) < 0.25:
                    continue
                accepted.append(
                    {"step": str(s["step"])[:200], "evidence": refs, "source_categories": sorted({allowed[r]["category"] for r in refs})}
                )
            if accepted:
                steps = accepted + [s for s in steps if not any(s["step"][:40] == a["step"][:40] for a in accepted)]
                llm_used = True
        except Exception:
            pass

    # priority order + evidence status placeholder (validator refines it)
    for i, s in enumerate(steps, start=1):
        s["priority"] = i
        s.setdefault("evidence_status", "PARTIALLY_SUPPORTED")

    return {
        "troubleshooting": steps[:6],
        "llm_used": llm_used,
        "trace": (state.get("trace") or [])
        + [{"node": "recommendations", "status": "ok" if steps else "fail", "detail": f"{len(steps)} grounded steps"}],
    }
