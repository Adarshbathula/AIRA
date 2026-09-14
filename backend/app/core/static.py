"""Serves the built React SPA from the API process.

Why: during development Vite proxies ``/api`` (frontend on :5173), but any
environment where ``node_modules`` is transient - CI, ephemeral sandboxes, an
air-gapped server - can lose the dev server while ``frontend/dist`` (a plain
build artefact) survives. Hosting the static build on the same origin removes
the second process, the proxy and the CORS question entirely.
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import get_settings

logger = logging.getLogger("aira.static")

# paths owned by the API layer (matched against the *stripped* catch-all path)
API_PREFIXES = ("api/", "docs", "redoc", "openapi.json", "assets/")


def resolve_dist(override: str | Path | None = None) -> Path | None:
    """Locate a build: explicit dir, ``frontend/dist``, or repo-root ``dist``."""
    s = get_settings()
    candidates = [Path(override)] if override else [s.frontend_dist_dir, Path("dist")]
    for c in candidates:
        try:
            if c.is_dir() and (c / "index.html").exists():
                return c
        except OSError:  # pragma: no cover
            continue
    return None


def mount_frontend(app: FastAPI, dist_dir: str | Path | None = None) -> Path | None:
    """Mount hashed assets + SPA history fallback. Returns the served directory."""
    s = get_settings()
    if not s.serve_frontend:
        return None
    dist = resolve_dist(dist_dir)
    if dist is None:
        logger.info("no frontend build found (expected %s) - serving API only", s.frontend_dist_dir)
        return None

    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="spa-assets")

    index = dist / "index.html"

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):  # noqa: ANN401 - catch-all for client-side routing
        # never shadow the API surface: the routers are registered first, but a
        # missing/redirected path would otherwise fall through and return HTML.
        if full_path.startswith(API_PREFIXES):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        candidate = (dist / full_path).resolve() if full_path else index
        if full_path and candidate.is_file() and candidate.is_relative_to(dist.resolve()):
            return FileResponse(candidate)
        return FileResponse(index)

    logger.info("serving frontend build from %s", dist)
    return dist
