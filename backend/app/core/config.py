"""Application configuration.

All secrets/credentials come from environment variables or a local ``.env``
file (see ``.env.example``). Nothing security-sensitive is hard-coded.
"""
from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT_DEFAULT = BACKEND_DIR.parent


def _env_file() -> Path | None:
    """Pick .env (local override), .env.dev (committed demo defaults) or
    .env.test (pytest / AIRA_ENV=test).

    .env is git-ignored, so an ephemeral sandbox that loses it still gets the
    same data dir, database path and demo accounts from .env.dev.
    """
    if os.environ.get("AIRA_ENV", "").lower() == "test":
        p = BACKEND_DIR / ".env.test"
        return p if p.exists() else None
    for name in (".env", ".env.dev"):
        p = BACKEND_DIR / name
        if p.exists():
            return p
    return None


_env_path = _env_file()
if _env_path:
    load_dotenv(_env_path, override=False)


def _default_data_dir() -> Path:
    return Path(os.environ.get("DATA_DIR", str(PROJECT_ROOT_DEFAULT))).resolve() / "data"


def _default_database_url() -> str:
    """Absolute-by-default SQLite URL.

    A URL relative to the current working directory silently creates (or fails
    to find) a different database depending on where uvicorn was started from -
    which looks exactly like "my account does not exist".
    """
    env = os.environ.get("DATABASE_URL")
    if env:
        return env
    # 4 slashes: the 3-slash form is interpreted relative to the CWD
    return "sqlite:///" + str(_default_data_dir() / "aira.db")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_env_path) if _env_path else None,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- app ---
    app_name: str = "AI Incident Resolution Assistant"
    environment: str = "development"
    api_prefix: str = "/api"
    frontend_origin: str = "http://localhost:5173"
    # when frontend/dist exists it is served by this process (single origin, no
    # dev proxy needed); set SERVE_FRONTEND=false to keep API-only mode
    serve_frontend: bool = True
    frontend_dist_dir: Path = BACKEND_DIR.parent / "frontend" / "dist"
    log_level: str = "INFO"

    # --- storage ---
    data_dir: Path = _default_data_dir()
    database_url: str = _default_database_url()

    # --- security ---
    # >=32 bytes: PyJWT warns (and RFC 7518 discourages) shorter HMAC keys
    secret_key: str = "insecure-dev-secret-change-me-rotate-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 720
    bootstrap_admin_email: str = "admin@aira.test"
    bootstrap_admin_password: str = "Admin@12345"
    # optional demo engineer account (created on first seed/startup if set)
    bootstrap_user_email: str = ""
    bootstrap_user_password: str = "Engineer@123"

    # --- LLM (Groq via LangChain) ---
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    llm_enabled: str = "auto"  # auto|true|false
    llm_timeout_seconds: int = 45

    # --- embeddings ---
    # auto = fastembed if importable else lightweight-hash (never crashes on missing models)
    embedding_provider: str = "auto"  # auto|fastembed|sentence-transformers|lightweight
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    # --- chunking / retrieval ---
    chunk_size: int = 900
    chunk_overlap: int = 140
    retrieval_k: int = 24
    retrieval_score_threshold: float = 0.28
    retrieval_max_per_category: int = 4
    max_retrieval_attempts: int = 3
    similar_incident_top_k: int = 5
    similar_incident_score_threshold: float = 0.45

    # --- grading / validation / confidence ---
    context_good_threshold: float = 0.72     # grader score above which context is GOOD
    context_poor_threshold: float = 0.45     # grader score below which context is POOR
    evidence_min_score: float = 0.3          # chunk score below which evidence is weak
    min_evidence_overlap: float = 0.18       # lexical overlap needed to mark SUPPORTED
    confidence_good_threshold: float = 0.72

    # --- uploads ---
    max_upload_mb: int = 15
    max_chunks_per_document: int = 300
    allowed_extensions: str = (
        ".pdf,.docx,.doc,.txt,.md,.markdown,.html,.htm,.csv,.tsv,.xlsx,.xls,.json,.log"
    )

    # ------------------------------------------------------------------ paths
    @property
    def documents_dir(self) -> Path:
        p = self.data_dir / "documents"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def vectorstore_dir(self) -> Path:
        p = self.data_dir / "vectorstore"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def incidents_data_dir(self) -> Path:
        p = self.data_dir / "incidents"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def sqlite_path(self) -> Path | None:
        """Resolve the SQLite file for either URL form:
        sqlite:///relative.db  sqlite:////absolute.db (extra slashes are tolerated)."""
        if not self.database_url.startswith("sqlite"):
            return None
        tail = self.database_url.split("://", 1)[1] if "://" in self.database_url else ""
        tail = tail.lstrip(":")                      # tolerate the :memory: marker
        if tail.startswith(":memory:") or tail == "memory:":
            return None                              # in-memory DB: nothing to resolve on disk
        # 4-slash URL form (sqlite:////abs/path) keeps a leading slash after '://'
        abs_style = tail.startswith("//")
        tail = re.sub(r"^[/\\]+", "", tail)
        if not tail:
            return None
        raw = ("/" + tail) if abs_style else tail
        path_part = Path(raw)
        p = path_part if path_part.is_absolute() else (BACKEND_DIR / raw).resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        return p
    
    # --------------------------------------------------------------- switches
    @property
    def resolved_llm_enabled(self) -> bool:
        flag = (self.llm_enabled or "auto").lower()
        if flag in {"1", "true", "yes", "on"}:
            return bool(self.groq_api_key)
        if flag in {"0", "false", "no", "off"}:
            return False
        return bool(self.groq_api_key)

    @property
    def allowed_extensions_set(self) -> set[str]:
        return {e.strip().lower() for e in self.allowed_extensions.split(",") if e.strip()}

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
