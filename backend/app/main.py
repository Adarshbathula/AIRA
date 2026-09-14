"""FastAPI application entrypoint.

Wires: CORS, routers under /api, DB schema bootstrap, admin bootstrap, RAG
runtime initialisation (embeddings + FAISS stores) and graceful degradation
when a subsystem is unavailable.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.static import mount_frontend
from app.core.database import Base, engine
from app.schemas.api import HealthOut

settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
logger = logging.getLogger("aira")

app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description=(
        "Enterprise AI Incident Resolution Assistant: Self-Healing RAG over SOPs, runbooks, "
        "RCAs and incident history, orchestrated by LangGraph, with evidence validation, "
        "confidence scoring, RBAC and analytics."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin, "http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc: Exception):  # pragma: no cover
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error", "error": type(exc).__name__})


def _include_routers() -> None:
    from app.api import auth, chat, dashboard, documents, incidents, knowledge, users

    for r in (auth.router, users.router, chat.router, incidents.router,
              documents.router, knowledge.router, dashboard.router):
        app.include_router(r, prefix=settings.api_prefix)


_include_routers()


@app.on_event("startup")
def startup() -> None:
    import app.models  # noqa: F401 - register models on Base.metadata

    Base.metadata.create_all(bind=engine)

    from app.core.database import db_session, ensure_columns

    added = ensure_columns()
    if added:
        logger.info("schema: added missing columns %s", ", ".join(added))
    from app.services import auth_service, rag_service

    with db_session() as db:
        auth_service.ensure_roles(db)
        auth_service.bootstrap_admin(db)
        auth_service.ensure_demo_user(db)
        try:
            stats = rag_service.sync_stores(db)
            logger.info("vector store sync on startup: %s", stats)
        except Exception as exc:  # never let index problems block the API
            logger.warning("Vector store sync skipped: %s", exc)
        try:
            rt = None
            from app.rag.runtime import get_runtime

            rt = get_runtime()
            logger.info(
                "RAG ready | embeddings=%s | llm=%s | doc_vectors=%d incident_vectors=%d",
                rt.embeddings.status(), rt.llm.status()["mode"], len(rt.document_store), len(rt.incident_store),
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("RAG runtime deferred: %s", exc)


@app.on_event("shutdown")
def shutdown() -> None:
    try:
        from app.rag.runtime import _runtime

        if _runtime is not None:
            _runtime.document_store.commit()
            _runtime.incident_store.commit()
    except Exception:  # pragma: no cover
        pass


@app.get(f"{settings.api_prefix}/health", response_model=HealthOut, tags=["system"])
def health():
    llm = {"provider": "none", "mode": "uninitialised"}
    emb = {"provider": "uninitialised"}
    vs: dict = {}
    try:
        from app.rag.runtime import get_runtime

        st = get_runtime().status()
        llm, emb = st["llm"], st["embeddings"]
        vs = st["documents_store"]
    except Exception as exc:  # pragma: no cover
        vs = {"error": str(exc)}
    db_ok = "ok"
    try:
        from sqlalchemy import text

        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        db_ok = "unavailable"
    return HealthOut(
        app=settings.app_name,
        version="1.0.0",
        llm=llm,
        embeddings=emb,
        vector_store=vs,
        database=db_ok,
    )


# --- IMPORTANT: keep this last -------------------------------------------------
# The SPA catch-all is a path-prefix route, so it must be registered after every
# API route (including the ones declared below in this module); otherwise
# /api/health and friends fall through to the HTML shell.
mount_frontend(app)
