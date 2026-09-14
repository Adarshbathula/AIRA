"""FAISS-backed vector store with metadata payloads.

Vectors live in a FAISS IndexFlatIP over L2-normalised embeddings (dot
product == cosine similarity). Metadata sidecars are persisted as JSONL next
to the index. A pure-numpy brute-force search is used automatically when the
``faiss`` package is unavailable so the system degrades gracefully.

Two stores exist at runtime:
  * documents store  -> every knowledge document chunk (SOP, RUNBOOK, RCA...)
  * incidents store  -> one vector per historical incident description
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from app.rag.embeddings.provider import BaseEmbeddings

logger = logging.getLogger("aira.vectorstore")

try:  # pragma: no cover - environment dependent
    import faiss  # type: ignore

    _HAS_FAISS = True
except Exception:  # pragma: no cover
    faiss = None
    _HAS_FAISS = False


@dataclass
class VRecord:
    ref: str                      # unique ref: chunk_ref or incident public id
    text: str
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "VRecord":
        return VRecord(ref=d["ref"], text=d.get("text", ""), metadata=d.get("metadata", {}))


class VectorStore:
    """Add/delete/search over FAISS with an internal rebuild on mutation."""

    def __init__(self, index_dir: Path, embeddings: BaseEmbeddings, store_name: str = "store") -> None:
        self.index_dir = Path(index_dir)
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self.embeddings = embeddings
        self.store_name = store_name
        self.records: list[VRecord] = []
        self._matrix: np.ndarray | None = None       # rows aligned with records
        self._index = None
        self.backend = "faiss" if _HAS_FAISS else "numpy-fallback"
        self._load()

    # ------------------------------------------------------------- persistence
    @property
    def _meta_path(self) -> Path:
        return self.index_dir / f"{self.store_name}_metadata.jsonl"

    @property
    def _vec_path(self) -> Path:
        return self.index_dir / f"{self.store_name}_vectors.npy"

    def _load(self) -> None:
        if not (self._meta_path.exists() and self._vec_path.exists()):
            return
        try:
            records = [
                VRecord.from_dict(json.loads(line))
                for line in self._meta_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            matrix = np.load(self._vec_path)
            if len(records) == matrix.shape[0]:
                self.records = records
                self._matrix = matrix.astype("float32")
                self._rebuild_index()
                logger.info("Loaded %s store: %d vectors", self.store_name, len(records))
            else:
                logger.warning("Metadata/vector mismatch in %s - starting empty", self.store_name)
        except Exception as exc:  # corrupted sidecar -> start empty, never crash
            logger.warning("Failed to load %s store (%s)", self.store_name, exc)

    def _persist(self) -> None:
        try:
            with self._meta_path.open("w", encoding="utf-8") as fh:
                for r in self.records:
                    fh.write(json.dumps(r.to_dict(), ensure_ascii=False) + "\n")
            if self._matrix is not None:
                np.save(self._vec_path, self._matrix)
        except OSError as exc:  # pragma: no cover
            logger.warning("Could not persist %s store: %s", self.store_name, exc)

    # ------------------------------------------------------------- index build
    def _rebuild_index(self) -> None:
        if self._matrix is None or len(self.records) == 0:
            self._index = None
            return
        if _HAS_FAISS:
            dim = self._matrix.shape[1]
            index = faiss.IndexFlatIP(dim)
            index.add(np.ascontiguousarray(self._matrix))
            self._index = index
        else:
            self._index = None

    # --------------------------------------------------------------- mutations
    def add(self, records: list[VRecord], texts: list[str] | None = None) -> None:
        if not records:
            return
        texts = texts if texts is not None else [r.text for r in records]
        try:
            vecs = self.embeddings.embed_texts(texts)
        except Exception as exc:
            raise RuntimeError(f"Embedding failure during ingestion: {exc}") from exc
        vecs = np.asarray(vecs, dtype="float32")
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        vecs = vecs / norms
        self.records.extend(records)
        self._matrix = vecs if self._matrix is None else np.vstack([self._matrix, vecs])
        self._rebuild_index()

    def upsert(self, records: list[VRecord]) -> None:
        """Insert-or-replace by record ref (keeps the store idempotent on re-ingest).

        Replacing an existing ref updates only the metadata sidecar: the stored
        vector is reused when the text is unchanged and re-embedded otherwise.
        """
        by_ref = {r.ref: i for i, r in enumerate(self.records)}
        new: list[VRecord] = []
        re_embed: list[VRecord] = []
        for r in records:
            i = by_ref.get(r.ref)
            if i is None:
                new.append(r)
            elif self.records[i].text != r.text:
                # text changed: drop old row, insert fresh vector
                self.records.pop(i)
                if self._matrix is not None:
                    self._matrix = np.delete(self._matrix, i, axis=0)
                    if len(self._matrix) == 0:
                        self._matrix = None
                re_embed.append(r)
            else:
                self.records[i] = r  # metadata-only edit
        if new or re_embed:
            self.add(new + re_embed)
        if not (new or re_embed):
            self._rebuild_index()  # keep index aligned after metadata swap

    def delete_refs(self, refs: set[str]) -> int:
        before = len(self.records)
        keep_pairs = [(r, i) for i, r in enumerate(self.records) if r.ref not in refs]
        removed = before - len(keep_pairs)
        if removed:
            self.records = [r for r, _ in keep_pairs]
            if self._matrix is not None and keep_pairs:
                self._matrix = self._matrix[[i for _, i in keep_pairs]]
            else:
                self._matrix = None
            self._rebuild_index()
            self._persist()
        return removed

    def commit(self) -> None:
        self._persist()

    def reset(self) -> None:
        self.records = []
        self._matrix = None
        self._index = None
        for p in (self._meta_path, self._vec_path):
            p.unlink(missing_ok=True)

    # ----------------------------------------------------------------- search
    def search_raw(self, query: str, k: int) -> list[tuple[VRecord, float]]:
        if not self.records:
            return []
        q = np.asarray(self.embeddings.embed_query(query), dtype="float32").reshape(1, -1)
        n = float(np.linalg.norm(q))
        if n > 0:
            q = q / n
        k = min(k, len(self.records))
        matrix = self._matrix
        if matrix is None:
            try:
                self.add(list(self.records))  # matrix lost (e.g. partial write): re-embed
                matrix = self._matrix
            except Exception as exc:  # pragma: no cover
                logger.warning("Vector matrix rebuild failed: %s", exc)
        if matrix is None or not self.records:
            return []
        if self._index is not None:
            scores, ids = self._index.search(np.ascontiguousarray(q), k)
            pairs = [(int(ids[0][j]), float(scores[0][j])) for j in range(k) if ids[0][j] >= 0]
        else:  # numpy fallback
            sims = (matrix @ q.T).ravel()
            order = np.argsort(-sims)[:k]
            pairs = [(int(i), float(sims[i])) for i in order]
        return [(self.records[i], s) for i, s in pairs]

    def search(
        self,
        query: str,
        k: int = 10,
        filters: dict | None = None,
        score_threshold: float = 0.0,
    ) -> list[tuple[VRecord, float]]:
        """Similarity search with post-filtering (filters: {meta_key: value|[values]})."""
        fetch_k = k if not filters else min(len(self.records) or 1, max(k * 4, 32))
        hits = self.search_raw(query, fetch_k)
        out: list[tuple[VRecord, float]] = []
        for rec, score in hits:
            if score < score_threshold:
                continue
            if filters and not _match(rec.metadata, filters):
                continue
            out.append((rec, score))
            if len(out) >= k:
                break
        return out

    # ------------------------------------------------------------------ misc
    def find_by_meta(self, **kwargs) -> list[tuple[VRecord, None]]:
        out = []
        for r in self.records:
            if all(r.metadata.get(k) == v for k, v in kwargs.items()):
                out.append((r, None))
        return out

    def stats(self) -> dict:
        return {
            "store": self.store_name,
            "backend": self.backend,
            "vectors": len(self.records),
            "dimension": int(self._matrix.shape[1]) if self._matrix is not None else self.embeddings.dimension,
            "embedding_model": self.embeddings.model_name,
            "path": str(self.index_dir),
        }

    def __len__(self) -> int:
        return len(self.records)


def _match(meta: dict, filters: dict) -> bool:
    for key, expected in filters.items():
        value = meta.get(key)
        if isinstance(expected, (list, tuple, set)):
            if value not in expected:
                return False
        elif value != expected:
            return False
    return True
