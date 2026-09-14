"""Embedding providers.

Production default: HuggingFace sentence transformers running through
``fastembed`` (ONNX - light on RAM). ``sentence-transformers`` is supported via
config when torch is installed. ``lightweight`` is a deterministic hashed
TF-IDF fallback so the system (and the test suite) works on machines without
model downloads; it produces *weaker but valid* semantic-free vectors and the
API always reports which backend is active.
"""
from __future__ import annotations

import hashlib
import logging
import math
import re
from functools import lru_cache

import numpy as np

from app.core.config import get_settings

logger = logging.getLogger("aira.embeddings")

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_.+#-]*")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall((text or "").lower())


class BaseEmbeddings:
    name = "base"
    model_name = "n/a"
    dimension = 0

    def embed_texts(self, texts: list[str]) -> np.ndarray:  # pragma: no cover
        raise NotImplementedError

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed_texts([text])[0]

    def status(self) -> dict:
        return {
            "provider": self.name,
            "model": self.model_name,
            "dimension": self.dimension,
            "semantic": self.name != "lightweight-hash",
        }


class FastEmbeddings(BaseEmbeddings):
    """HuggingFace models via qdrant/fastembed (ONNX runtime)."""

    name = "fastembed"

    def __init__(self, model_name: str) -> None:
        from fastembed import TextEmbedding  # lazy import

        self.model_name = model_name
        self._model = TextEmbedding(model_name=model_name)
        probe = list(self._model.embed(["dimension probe"]))
        self.dimension = len(probe[0])

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dimension), dtype="float32")
        return np.asarray(list(self._model.embed(texts)), dtype="float32")


class SentenceTransformerEmbeddings(BaseEmbeddings):
    name = "sentence-transformers"

    def __init__(self, model_name: str) -> None:
        from sentence_transformers import SentenceTransformer  # type: ignore

        self.model_name = model_name
        self._model = SentenceTransformer(model_name)
        self.dimension = int(self._model.get_sentence_embedding_dimension())

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dimension), dtype="float32")
        return np.asarray(self._model.encode(texts, normalize_embeddings=True), dtype="float32")


class LightweightHashEmbeddings(BaseEmbeddings):
    """Deterministic hashed bag-of-words with sub-word grams + IDF weighting.

    Not a semantic model: captures lexical similarity only. Used when model
    downloads are impossible (air-gapped demo boxes, CI sandboxes).
    """

    name = "lightweight-hash"
    model_name = "hashed-tfidf-384d"
    dimension = 384
    _N_DF = 100_000  # pseudo corpus size for IDF smoothing

    def __init__(self) -> None:
        self._idf_docs = 0
        self._idf: dict[int, int] = {}

    # hash helpers ------------------------------------------------------------
    @staticmethod
    def _slot(term: str) -> int:
        h = hashlib.blake2b(term.encode("utf-8"), digest_size=4).digest()
        return int.from_bytes(h, "big") % LightweightHashEmbeddings.dimension

    @staticmethod
    def _features(text: str) -> list[str]:
        toks = _tokenize(text)
        feats = list(toks)
        for t in toks:
            if len(t) >= 5:
                feats.extend(t[i : i + 4] for i in range(0, min(len(t) - 3, 6)))
        for i in range(len(toks) - 1):
            feats.append(f"{toks[i]}_{toks[i + 1]}")
        return feats

    def _fit_partial(self, texts: list[str]) -> None:
        """Accumulate document frequency (streaming, for reproducibility)."""
        for t in texts:
            self._idf_docs += 1
            for slot in {self._slot(f) for f in self._features(t)}:
                self._idf[slot] = self._idf.get(slot, 0) + 1

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dimension), dtype="float32")
        self._fit_partial(texts)
        for i, text in enumerate(texts):
            feats = self._features(text)
            if not feats:
                continue
            counts: dict[int, int] = {}
            for f in feats:
                s = self._slot(f)
                counts[s] = counts.get(s, 0) + 1
            for s, c in counts.items():
                df = self._idf.get(s, 1)
                idf = math.log(1 + self._N_DF / (1 + df))
                out[i, s] = (1 + math.log(c)) * idf
            nrm = float(np.linalg.norm(out[i]))
            if nrm > 0:
                out[i] /= nrm
        return out


def _build() -> BaseEmbeddings:
    s = get_settings()
    provider = (s.embedding_provider or "auto").lower()
    if provider == "lightweight":
        logger.warning("Using lightweight hashed embeddings (no semantic model).")
        return LightweightHashEmbeddings()
    if provider == "auto":
        try:
            import fastembed  # noqa: F401

            provider = "fastembed"
        except Exception:
            logger.warning("fastembed not installed - using lightweight hashed embeddings.")
            return LightweightHashEmbeddings()
    try:
        if provider == "sentence-transformers":
            return SentenceTransformerEmbeddings(s.embedding_model)
        return FastEmbeddings(s.embedding_model)
    except Exception as exc:
        if provider == "lightweight":
            raise
        logger.warning(
            "Embedding backend '%s' failed to initialise (%s); "
            "falling back to lightweight hashed embeddings.",
            provider,
            exc,
        )
        return LightweightHashEmbeddings()


@lru_cache
def get_embeddings() -> BaseEmbeddings:
    return _build()
