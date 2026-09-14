"""Text cleaning + structure-aware chunking.

Sections are detected first (numbered headings, markdown headings, ALL-CAPS
titles); chunks never span sections. LangChain's recursive splitter does the
final sizing when installed; a compatible splitter keeps things working if
not.
"""
from __future__ import annotations

import re
import unicodedata

_SECTION_RES = [
    # numbered headings must carry an explicit separator: "3." "3)" "2.1."
    re.compile(r"^(?P<num>\d{1,2}(?:\.\d{1,2}){0,2})[.)]\s+(?P<title>[A-Z0-9][^\n]{2,110})$"),
    re.compile(r"^#+\s+(?P<num>\d{1,2}(?:\.\d{1,2}){0,2})?\s*(?P<title>.{2,110})$"),
    re.compile(r"^(?P<num>)(?P<title>[A-Z][A-Z0-9 ,&/\-\.']{4,80})$"),
]
_WS_RE = re.compile(r"[ \t\f\v]+")


def clean_text(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "".join(ch if (ch == "\n" or ch == "\t" or unicodedata.category(ch)[0] != "C") else " " for ch in text)
    lines = [_WS_RE.sub(" ", ln).strip() for ln in text.split("\n")]
    out: list[str] = []
    blank = 0
    for ln in lines:
        if not ln:
            blank += 1
            if blank <= 1:
                out.append("")
            continue
        blank = 0
        out.append(ln)
    return "\n".join(out).strip()


def split_sections(text: str, max_section_chars: int = 4000) -> list[tuple[str, str]]:
    """Return [(section_title, section_text), ...] preserving order."""
    lines = text.split("\n")
    sections: list[tuple[str, list[str]]] = []
    current_title, buf = "Overview", []
    for ln in lines:
        title = _as_section_title(ln)
        if title:
            if any(s.strip() for s in buf):
                sections.append((current_title, buf))
            current_title, buf = title, []
        else:
            buf.append(ln)
        if len("\n".join(buf)) > max_section_chars:  # hard guard on monster sections
            sections.append((current_title, buf))
            current_title, buf = f"{current_title} (cont.)", []
    if any(s.strip() for s in buf):
        sections.append((current_title, buf))
    return [(t, "\n".join(b).strip()) for t, b in sections if len("\n".join(b).strip()) > 0]


def _as_section_title(line: str) -> str | None:
    line = line.strip().rstrip(":")
    if not line or len(line) > 120 or "||" in line or line.startswith("|"):
        return None
    for rx in _SECTION_RES:
        m = rx.match(line)
        if m:
            gd = m.groupdict()
            num = gd.get("num") or ""
            title = f"{num} {gd.get('title', '')}".strip()
            return title[:120] or None
    return None


def get_splitter(chunk_size: int, chunk_overlap: int):
    try:
        from langchain_text_splitters import RecursiveCharacterTextSplitter

        return RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", ". ", "; ", " ", ""],
            length_function=len,
        )
    except Exception:  # pragma: no cover
        return _SimpleSplitter(chunk_size, chunk_overlap)


class _SimpleSplitter:
    def __init__(self, chunk_size: int, chunk_overlap: int) -> None:
        self.chunk_size, self.chunk_overlap = chunk_size, chunk_overlap

    def split_text(self, text: str) -> list[str]:
        if len(text) <= self.chunk_size:
            return [text] if text.strip() else []
        start, step, out = 0, max(50, self.chunk_size - self.chunk_overlap), []
        while start < len(text):
            piece = text[start : start + self.chunk_size]
            cut = piece.rfind("\n")
            if cut > self.chunk_size * 0.5:
                piece = piece[:cut]
            if piece.strip():
                out.append(piece.strip())
            start += max(50, len(piece) - self.chunk_overlap)
        return out


def chunk_document_text(
    text: str, chunk_size: int, chunk_overlap: int, max_chunks: int = 300
) -> list[tuple[int, str | None, str]]:
    """-> [(chunk_index, section_title, chunk_text)]"""
    splitter = get_splitter(chunk_size, chunk_overlap)
    chunks: list[tuple[int, str | None, str]] = []
    for sec_title, sec_text in split_sections(text):
        for piece in splitter.split_text(sec_text):
            if len(piece) < 40 and chunks:  # skip crumbs
                continue
            chunks.append((len(chunks), sec_title, piece))
            if len(chunks) >= max_chunks:
                return chunks
    return chunks
