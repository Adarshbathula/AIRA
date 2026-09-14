"""RAG runtime: lazily-initialised singletons shared by API + services.

Holds embeddings, the document vector store, the incident vector store, the
multi-source retriever and the LLM wrapper. Rebuilt automatically from the
database if FAISS indexes are missing (e.g. fresh clone, cleared cache).
"""
from __future__ import annotations

import logging
import threading

from app.core.config import get_settings
from app.rag.embeddings.provider import get_embeddings
from app.rag.llm import GroqLLM
from app.rag.retrieval.multi_source import MultiSourceRetriever
from app.rag.vectorstore.faiss_store import VectorStore

logger = logging.getLogger("aira.runtime")


class RagRuntime:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.embeddings = get_embeddings()
        self.llm = GroqLLM()
        self.document_store = VectorStore(self.settings.vectorstore_dir, self.embeddings, "documents")
        self.incident_store = VectorStore(self.settings.vectorstore_dir, self.embeddings, "incidents")
        self.retriever = MultiSourceRetriever(self.document_store, self.embeddings)
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ locks
    @property
    def lock(self) -> threading.RLock:
        return self._lock

    def status(self) -> dict:
        return {
            "llm": self.llm.status(),
            "embeddings": self.embeddings.status(),
            "documents_store": self.document_store.stats(),
            "incidents_store": self.incident_store.stats(),
        }


_runtime: RagRuntime | None = None
_runtime_lock = threading.Lock()


def get_runtime() -> RagRuntime:
    global _runtime
    with _runtime_lock:
        if _runtime is None:
            _runtime = RagRuntime()
            logger.info(
                "RAG runtime ready: embeddings=%s docs=%d incidents=%d backend=%s",
                _runtime.embeddings.model_name,
                len(_runtime.document_store),
                len(_runtime.incident_store),
                _runtime.document_store.backend,
            )
        return _runtime


def reset_runtime() -> None:
    """Used by tests to rebuild singletons after env overrides."""
    global _runtime
    with _runtime_lock:
        _runtime = None
