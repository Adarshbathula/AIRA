"""LLM provider: Groq via LangChain, with an explicit deterministic fallback.

Design rule: the application must run fully offline. When no GROQ_API_KEY is
configured, ``GroqLLM.available`` is False and every LangGraph node falls back
to grounded, evidence-derived logic instead of silently inventing text.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger("aira.llm")


class LLMError(RuntimeError):
    pass


class GroqLLM:
    """Thin wrapper around ``langchain_groq.ChatGroq`` (imported lazily)."""

    def __init__(self) -> None:
        s = get_settings()
        self.model = s.groq_model
        self.api_key = s.groq_api_key
        self._enabled = s.resolved_llm_enabled
        self._chat = None

    # ------------------------------------------------------------------ state
    @property
    def available(self) -> bool:
        if not self._enabled or not self.api_key:
            return False
        if self._chat is None:
            try:
                from langchain_groq import ChatGroq  # type: ignore

                self._chat = ChatGroq(
                    model=self.model,
                    api_key=self.api_key,
                    temperature=0,
                    timeout=int(get_settings().llm_timeout_seconds),
                    max_retries=1,
                )
            except Exception as exc:  # pragma: no cover - env dependent
                logger.warning("Groq LLM unavailable (%s); deterministic mode active", exc)
                self._enabled = False
        return self._chat is not None

    def status(self) -> dict[str, Any]:
        return {
            "provider": "groq" if self.available else "none",
            "model": self.model if self.available else None,
            "mode": "llm-grounded" if self.available else "deterministic-grounded",
            "note": (
                "Groq LLM active"
                if self.available
                else "No GROQ_API_KEY configured - answers are evidence-derived (deterministic mode)"
            ),
        }

    # ---------------------------------------------------------------- invoke
    def complete(self, system: str, user: str, max_tokens: int = 900) -> str:
        if not self.available:
            raise LLMError("LLM not available")
        try:
            msg = self._chat.invoke(
                [("system", system), ("human", user)]  # type: ignore[union-attr]
            )
            return (msg.content or "").strip()
        except Exception as exc:  # network/quota failures
            raise LLMError(f"LLM invocation failed: {exc}") from exc

    def complete_json(self, system: str, user: str, max_tokens: int = 1200) -> dict:
        raw = self.complete(system + "\nRespond with valid JSON only.", user, max_tokens)
        return extract_json(raw)


def extract_json(text: str) -> dict:
    """Best-effort JSON extraction from an LLM response."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise LLMError(f"LLM returned non-JSON: {exc}") from exc
    raise LLMError("LLM returned no JSON object")
