"""FastAPI backend for the AMS console.

Thin routers over the same pure Python modules the Streamlit views already
called (see CLAUDE.md's Working style note on the React/FastAPI migration).
Serves the built React app as static files in production so deployment
stays one process, one port — the same story Streamlit had.

Every API route lives under `/api` — deliberately, so a frontend client
route like `/s1` or `/s2` never collides with the backend router of the same
name. Without that split, a dev-server proxy rule for `/s2` (backend) would
also intercept a hard browser navigation to the React `/s2` page, and in
production a browser refresh on `/s1` would hit the API router (404, no
matching route there) instead of the SPA.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from apps.console.api import auth
from apps.console.api.routers import admin, s3

CONSOLE_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIST = CONSOLE_ROOT / "web" / "dist"

app = FastAPI(title="MapleSure AMS Console API")

# Dev-only: the Vite dev server runs on a different port than uvicorn. Once
# the frontend is built and served by this same process (mounted below),
# requests are same-origin and this middleware is inert.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(s3.router, prefix="/api")
# Manager-only demo operations (reset/services/onboarding). Mounted before the
# SPA catch-all below, like every other API router.
app.include_router(admin.router, prefix="/api")


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


if FRONTEND_DIST.exists():

    @app.get("/{full_path:path}")
    def spa(full_path: str) -> FileResponse:
        """SPA history-mode fallback: serve the real asset if `full_path`
        matches one on disk (JS/CSS bundles, favicon, ...), otherwise fall
        back to index.html so React Router's client-side routing can take
        over — the same "load the app shell, then route" story a hard
        refresh on any client route (e.g. `/s1`) needs to keep working, not
        just first-load navigation from `/`. Registered last, after every
        `/api/*` router above, so it only ever catches non-API paths.
        """
        candidate = FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")
