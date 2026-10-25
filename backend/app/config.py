"""Runtime configuration, driven by environment variables."""

from __future__ import annotations

import os
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_ROOT.parent

#: Root of the data directory. It holds everything:
#:   pdfs/    - every PDF of the library (imported and uploaded alike)
#:   db/      - the SQLite database
PDF_ROOT = Path(os.environ.get("PDF_ROOT", PROJECT_ROOT / "local_data")).resolve()

#: Writable directory for the SQLite database.
DATA_DIR = Path(os.environ.get("DATA_DIR", PDF_ROOT / "db")).resolve()

#: The single PDF store. Imported and uploaded PDFs live side by side here,
#: so a PDF is only ever stored once, no matter how many folders reference it.
PDF_DIR = (PDF_ROOT / "pdfs").resolve()

DB_PATH = DATA_DIR / "library.db"

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8080"))

MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "200"))

#: Where the built frontend lives (mounted/copied into the image).
FRONTEND_DIR = Path(os.environ.get("FRONTEND_DIR", PROJECT_ROOT / "frontend")).resolve()


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PDF_DIR.mkdir(parents=True, exist_ok=True)
