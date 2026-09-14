"""Lexical scoring helpers used by the grader / evidence validator.

Deliberately model-free so validation is deterministic and cheap: it checks
that generated claims actually overlap retrieved evidence, not that another
LLM *believes* they do.
"""
from __future__ import annotations

from collections import Counter
import math
import re

_STOP = set(
    """a an and are as at be been by for from has have if in into is it its of on or
    per that the their them then this to was were will with you your we our not no
    can could should would may might must when while which who whom how why all any
    both each few more most other some such only own same so than too very just also""".split()
)
_WORD = re.compile(r"[a-z0-9][a-z0-9_.+#/-]*")


def content_terms(text: str) -> list[str]:
    toks = _WORD.findall((text or "").lower())
    return [t for t in toks if t not in _STOP and len(t) > 1]


def term_set(text: str) -> set[str]:
    return set(content_terms(text))


def overlap(claim: str, evidence: str) -> float:
    """Directional coverage: fraction of claim terms present in evidence (0..1)."""
    c, e = term_set(claim), term_set(evidence)
    if not c or not e:
        return 0.0
    inter = len(c & e)
    return inter / max(1, len(c))


def jaccard(a: str, b: str) -> float:
    sa, sb = term_set(a), term_set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def bm25(query: str, docs: list[str], k1: float = 1.4, b: float = 0.7) -> list[float]:
    """Compact BM25 over the provided documents (used to rank evidence sentences)."""
    q_terms = content_terms(query)
    if not docs or not q_terms:
        return [0.0] * len(docs)
    doc_terms = [content_terms(d) for d in docs]
    n = len(docs)
    avgdl = sum(len(d) for d in doc_terms) / max(1, n)
    df: Counter[str] = Counter()
    for d in doc_terms:
        df.update(set(d))
    scores: list[float] = []
    for d in doc_terms:
        tf = Counter(d)
        s = 0.0
        for t in q_terms:
            f = tf.get(t, 0)
            if not f:
                continue
            idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
            s += idf * (f * (k1 + 1)) / (f + k1 * (1 - b + b * len(d) / max(1.0, avgdl)))
        scores.append(round(s, 4))
    return scores


def sentence_split(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text or "")
    return [p.strip() for p in parts if len(p.strip()) > 25]
