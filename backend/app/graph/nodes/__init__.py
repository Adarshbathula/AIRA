"""LangGraph nodes. Each module exposes ``run(state) -> partial state``."""
from __future__ import annotations

import json
from typing import Any

from app.core.config import Settings, get_settings


def cfg(state: dict[str, Any]) -> dict[str, Any]:
    """Runtime bundle shared by nodes: {settings, runtime, llm, embeddings}."""
    conf = state.get("pipeline_config") or {}
    conf.setdefault("settings", get_settings())
    return conf


def settings_of(state: dict[str, Any]) -> Settings:
    return cfg(state)["settings"]


def runtime_of(state: dict[str, Any]):
    """The RagRuntime (embeddings/stores/llm); None in isolated unit tests."""
    return cfg(state).get("runtime")


def llm_of(state: dict[str, Any]):
    rt = runtime_of(state)
    return getattr(rt, "llm", None) if rt is not None else None


def safe_json(obj: Any, limit: int = 5500) -> str:
    text = json.dumps(obj, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[:limit] + "...(truncated)"


def first_line(text: str, limit: int = 240) -> str:
    for ln in (text or "").splitlines():
        ln = ln.strip(" -•*\t")
        if len(ln) >= 24:
            return ln[:limit]
    return (text or "").strip()[:limit]


_SUBMODULES = {
    "incident_analyzer", "query_constructor", "retriever", "context_grader",
    "query_rewriter", "similar_incidents", "root_cause", "recommendations",
    "evidence_validator", "confidence", "summarizer", "assemble",
}


def __getattr__(name: str):
    """Lazily expose node submodules as attributes (avoids the import cycle
    created by submodules importing helpers from this package)."""
    if name in _SUBMODULES:
        import importlib

        mod = importlib.import_module(f"{__name__}.{name}")
        globals()[name] = mod
        return mod
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
