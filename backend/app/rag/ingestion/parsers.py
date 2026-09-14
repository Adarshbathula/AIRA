"""Format-independent document parsing.

Every parser converts a binary/text file into plain text (+ optional hints
such as page counts or structured records). Supported: PDF, DOCX, DOC, TXT,
Markdown, HTML, CSV/TSV, XLSX/XLS, JSON, LOG.

Security notes: no shell tools are executed on uploads, archive-style formats
are rejected, sizes are capped upstream, and all parse errors surface as
``DocumentParseError`` so the API can return clean 4xx responses.
"""
from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from dataclasses import dataclass, field

CSV_SEP = " || "


class DocumentParseError(ValueError):
    """Raised for unsupported, corrupted, or empty documents."""


@dataclass
class ParsedFile:
    text: str = ""
    page_count: int | None = None
    hints: dict = field(default_factory=dict)  # e.g. extracted title, incident records


# --------------------------------------------------------------------- plain
def parse_text(data: bytes, filename: str) -> ParsedFile:
    return ParsedFile(text=_decode(data, filename))


def parse_markdown(data: bytes, filename: str) -> ParsedFile:
    text = _decode(data, filename)
    text = re.sub(r"```(?:[\w+-]*)\n(.*?)```", r"\1", text, flags=re.S)  # keep code, drop fences
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)                    # drop images
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)                # keep link labels
    return ParsedFile(text=text)


def parse_html(data: bytes, filename: str) -> ParsedFile:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(_decode(data, filename), "lxml" if _has_lxml() else "html.parser")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    title = (soup.title.get_text(strip=True) if soup.title else None) or None
    text = soup.get_text("\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    pf = ParsedFile(text=text)
    if title:
        pf.hints["title"] = title
    return pf


# ---------------------------------------------------------------- office doc
def parse_pdf(data: bytes, filename: str) -> ParsedFile:
    try:
        from pypdf import PdfReader
    except Exception as exc:  # pragma: no cover
        raise DocumentParseError("PDF support requires the 'pypdf' package") from exc
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception as exc:
                raise DocumentParseError("PDF is password protected") from exc
        parts: list[str] = []
        for i, page in enumerate(reader.pages):
            parts.append(f"\n--- Page {i + 1} ---\n" + page.extract_text() or "")
        text = "\n".join(parts).strip()
    except DocumentParseError:
        raise
    except Exception as exc:
        raise DocumentParseError(f"Could not parse PDF ({type(exc).__name__}): it may be corrupted") from exc
    if not text:
        raise DocumentParseError("PDF contains no extractable text (image-only PDF?); OCR is not enabled")
    pf = ParsedFile(text=text, page_count=len(reader.pages))
    try:
        meta = {str(k): str(v) for k, v in (reader.metadata or {}).items()}
    except Exception:
        meta = {}
    title = meta.get("/Title")
    if title and title.strip():
        pf.hints["title"] = title.strip()
    if meta.get("/Author", "").strip():
        pf.hints["author"] = meta["/Author"].strip()
    return pf


def parse_docx(data: bytes, filename: str) -> ParsedFile:
    try:
        import docx  # python-docx
    except Exception as exc:  # pragma: no cover
        raise DocumentParseError("DOCX support requires the 'python-docx' package") from exc
    try:
        d = docx.Document(io.BytesIO(data))
    except Exception as exc:
        raise DocumentParseError(f"Could not parse DOCX ({type(exc).__name__})") from exc
    parts: list[str] = []
    for para in d.paragraphs:
        t = para.text.strip()
        if not t:
            continue
        style = (para.style.name or "").lower() if para.style else ""
        if style.startswith("heading") or style == "title":
            parts.append(f"\n{t}\n")
        else:
            parts.append(t)
    for table in d.tables:
        rows = [" | ".join(c.text.strip() for c in row.cells) for row in table.rows if any(c.text.strip() for c in row.cells)]
        if rows:
            parts.append("\n".join(rows))
    text = "\n".join(parts).strip()
    if not text:
        raise DocumentParseError("DOCX contains no extractable text")
    core = d.core_properties
    pf = ParsedFile(text=text)
    if core.title:
        pf.hints["title"] = str(core.title)
    if core.author:
        pf.hints["author"] = str(core.author)
    return pf


def parse_doc(data: bytes, filename: str) -> ParsedFile:
    """Legacy .doc: OLE container -> try docx fallback, else raw-string sweep."""
    if data[:2] == b"PK":  # mislabelled .docx
        return parse_docx(data, filename)
    text = _sweep_ascii(data)
    if len(text) < 200:
        raise DocumentParseError(
            "Legacy .doc binary could not be read reliably. Convert it to .docx and re-upload."
        )
    pf = ParsedFile(text=text)
    pf.hints["parser"] = "raw-sweep"
    return pf


def _sweep_ascii(data: bytes) -> str:
    out: list[str] = []
    for m in re.finditer(rb"[\x20-\x7e\x0a\x0d\x09]{40,}", data):
        chunk = m.group(0).decode("latin-1", "ignore")
        chunk = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", chunk)
        if sum(ch.isalpha() for ch in chunk) > len(chunk) * 0.35:
            out.append(chunk)
    return clean_join(out)


def clean_join(parts: list[str]) -> str:
    return re.sub(r"[ \t]{2,}", " ", "\n".join(parts)).strip()


# ----------------------------------------------------------- tabular/struct
def parse_csv(data: bytes, filename: str) -> ParsedFile:
    text = _decode(data, filename)
    sample = text[:4096]
    delim = ","
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        delim = dialect.delimiter
    except csv.Error:
        if "\t" in sample[:200]:
            delim = "\t"
    rows: list[list[str]] = []
    try:
        reader = csv.reader(io.StringIO(text), delimiter=delim)
        for r in reader:
            rows.append([c.strip() for c in r])
    except csv.Error as exc:
        raise DocumentParseError(f"Malformed CSV: {exc}") from exc
    rows = [r for r in rows if any(r)]
    if not rows:
        raise DocumentParseError("CSV file has no data rows")
    header, body = rows[0], rows[1:] or [header]
    lines = [" | ".join(h for h in header if h)]
    for r in body:
        pairs = [f"{h}={v}" for h, v in zip(header, r) if v != ""]
        if pairs:
            lines.append(CSV_SEP.join(pairs))
    pf = ParsedFile(text="\n".join(lines))
    records = [dict(zip(header, r)) for r in body]
    if _looks_like_incidents(header, records):
        pf.hints["incident_records"] = records
    return pf


def parse_xlsx(data: bytes, filename: str) -> ParsedFile:
    if data[:2] != b"PK":
        raise DocumentParseError("Corrupted or legacy .xls workbook (re-save as .xlsx)")
    try:
        import openpyxl
    except Exception as exc:  # pragma: no cover
        raise DocumentParseError("XLSX support requires 'openpyxl'") from exc
    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except zipfile.BadZipFile as exc:
        raise DocumentParseError("Corrupted XLSX archive") from exc
    lines: list[str] = []
    for ws in wb.worksheets:
        rows: list[list[str]] = []
        for row in ws.iter_rows(values_only=True):
            vals = ["" if v is None else str(v).strip() for v in row]
            if any(vals):
                rows.append(vals)
            if len(rows) >= 2000:
                break
        if not rows:
            continue
        lines.append(f"## Sheet: {ws.title}")
        header = rows[0]
        lines.append(" | ".join(h for h in header if h))
        for r in rows[1:]:
            pairs = [f"{h}={v}" for h, v in zip(header, r) if v]
            if pairs:
                lines.append(CSV_SEP.join(pairs))
    wb.close()
    if len(lines) == 0:
        raise DocumentParseError("Workbook contains no readable cells")
    return ParsedFile(text="\n".join(lines))


def parse_json(data: bytes, filename: str) -> ParsedFile:
    try:
        obj = json.loads(_decode(data, filename))
    except json.JSONDecodeError as exc:
        raise DocumentParseError(f"Invalid JSON: {exc}") from exc
    pf = ParsedFile(text=_json_to_text(obj))
    recs = _incident_records(obj)
    if recs:
        pf.hints["incident_records"] = recs
    for k in ("title", "document_name", "name"):
        if isinstance(obj, dict) and isinstance(obj.get(k), str):
            pf.hints["title"] = obj[k]
            break
    for k in ("document_type", "category"):
        if isinstance(obj, dict) and isinstance(obj.get(k), str):
            pf.hints["category"] = obj[k].upper()
            break
    if isinstance(obj, dict):
        for k in ("service", "department", "author", "version"):
            if isinstance(obj.get(k), str):
                pf.hints[k] = obj[k]
    return pf


def _json_to_text(obj, prefix: str = "") -> str:
    lines: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}{k}"
            if isinstance(v, (dict, list)):
                lines.append(_json_to_text(v, f"{key}.") + "")
            else:
                lines.append(f"{key}: {_scalar(v)}")
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            if isinstance(item, dict):
                lines.append(f"[{i}] " + _json_to_text(item, "").replace("\n", CSV_SEP))
            else:
                lines.append(f"[{i}] {_scalar(item)}")
    else:
        lines.append(_scalar(obj))
    return "\n".join(l for l in lines if l.strip())


def _scalar(v) -> str:
    return "" if v is None else str(v)


def _looks_like_incidents(header: list[str], records: list[dict]) -> bool:
    if not records:
        return False
    keys = {h.lower() for h in header}
    return bool({"id", "title"} & keys or {"incident_id"} & keys) and len(records) <= 5000


def _incident_records(obj) -> list[dict] | None:
    items: list | None = None
    if isinstance(obj, list):
        items = obj
    elif isinstance(obj, dict) and isinstance(obj.get("incidents"), list):
        items = obj["incidents"]
    if not items:
        return None
    recs = [r for r in items if isinstance(r, dict) and (r.get("title") or r.get("summary"))]
    return recs or None


# --------------------------------------------------------------------- logs
_LOG_NOISE = re.compile(
    r"(GET|POST|PUT|DELETE)\s+/healthz|liveness|readiness|heartbeat|agent\.ping", re.I
)
_LOG_MEANINGFUL = re.compile(r"\b(error|warn|fatal|panic|exception|timeout|refused|oom|kill|crash|fail|5\d\d|4[029]|backoff|evict|restart)\b", re.I)


def parse_log(data: bytes, filename: str) -> ParsedFile:
    text = _decode(data, filename)
    if len(text) < 3:
        raise DocumentParseError("Log file is empty")
    lines = text.splitlines()
    kept = [ln.strip() for ln in lines if ln.strip() and not _LOG_NOISE.search(ln)]
    meaningful = [ln for ln in kept if _LOG_MEANINGFUL.search(ln)]
    selected = meaningful if len(meaningful) >= 8 else kept
    sample_note = ""
    if len(selected) > 2000:
        selected = selected[-2000:]
        sample_note = "(truncated to most recent 2000 meaningful lines)"
    body = "\n".join(selected)
    if not body:
        raise DocumentParseError("Log file contains no readable lines")
    pf = ParsedFile(text=f"{filename}: analysed log lines {sample_note}\n{body}")
    pf.hints["raw_line_count"] = len(lines)
    return pf


# ------------------------------------------------------------------ helpers
def _decode(data: bytes, filename: str) -> str:
    if data[:4] == b"\x1f\x8b":
        import gzip

        try:
            data = gzip.decompress(data)
        except OSError as exc:
            raise DocumentParseError("Corrupted gzip stream") from exc
    for enc in ("utf-8", "utf-16", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return data.decode("utf-8", "replace")


def _has_lxml() -> bool:
    try:
        import lxml  # noqa: F401

        return True
    except Exception:
        return False


PARSERS = {
    ".pdf": parse_pdf,
    ".docx": parse_docx,
    ".doc": parse_doc,
    ".txt": parse_text,
    ".text": parse_text,
    ".md": parse_markdown,
    ".markdown": parse_markdown,
    ".html": parse_html,
    ".htm": parse_html,
    ".csv": parse_csv,
    ".tsv": parse_csv,
    ".xlsx": parse_xlsx,
    ".xls": parse_xlsx,
    ".json": parse_json,
    ".log": parse_log,
}


def parse_bytes(data: bytes, filename: str) -> ParsedFile:
    """File-type detection by extension + magic bytes, then dispatch."""
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename and not filename.endswith(".") else ""
    if ext not in PARSERS:
        raise DocumentParseError(
            f"Unsupported file type '{ext or 'unknown'}'. Supported: {', '.join(sorted(PARSERS))}"
        )
    lowered = data[:8].lower()
    if lowered.startswith((b"<!doctype html", b"<html", b"<?xml")):
        return parse_html(data, filename)
    if lowered.startswith(b"%pdf"):
        return parse_pdf(data, filename)
    if lowered.startswith(b"pk\x03\x04") and ext not in {".docx", ".xlsx", ".doc"}:
        raise DocumentParseError("Zip archives are not accepted for security reasons")
    return PARSERS[ext](data, filename)
