"""FastAPI application: API + static frontend."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .config import DATA_DIR, FRONTEND_DIR, PDF_ROOT, ensure_dirs
from .db import init_db
from .importer import import_readpaper
from .routers import library, papers, trash


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    ensure_dirs()
    init_db()
    yield


app = FastAPI(title="Paper Reader", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(papers.router)
app.include_router(library.router)
app.include_router(trash.router)


@app.middleware("http")
async def no_cache_static(request, call_next):
    """Make the browser revalidate static assets instead of guessing.

    StaticFiles only sends ETag/Last-Modified, so browsers apply *heuristic*
    caching and may serve a stale app.js for a while after you edited it.
    "no-cache" still allows caching, but forces a revalidation on every use.
    """
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.get("/api/healthz")
def healthz() -> dict:
    return {"ok": True, "pdfRoot": str(PDF_ROOT), "dataDir": str(DATA_DIR)}


@app.post("/api/import")
def run_import(payload: dict) -> dict:
    data_path = Path(payload.get("dataPath") or (PDF_ROOT / "data.json"))
    if not data_path.exists():
        raise HTTPException(status_code=400, detail=f"data.json not found at {data_path}")
    try:
        stats = import_readpaper(data_path, reset=bool(payload.get("reset")))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True, **stats}


# ------------------------------- frontend --------------------------------- #

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR / "static"), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(FRONTEND_DIR / "index.html")

    @app.get("/paper/{paper_id}")
    def reader_page(paper_id: int) -> FileResponse:
        return FileResponse(FRONTEND_DIR / "reader.html")

    @app.get("/{path:path}")
    def spa(path: str) -> Response:
        if path.startswith("api/"):
            return JSONResponse({"error": "not found"}, status_code=404)
        candidate = (FRONTEND_DIR / path).resolve()
        if candidate.is_file() and FRONTEND_DIR.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIR / "index.html")
