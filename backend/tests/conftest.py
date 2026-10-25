"""Test setup: every test runs against a throw-away library.

The app reads its paths from the environment when it is imported, so the
environment has to be set before anything from ``app`` is imported. The
directory is created once for the whole run; every test starts with an
empty database and an empty PDF store.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest

#: The throw-away library. Must be set before `app` is imported below.
TEST_ROOT = Path(tempfile.mkdtemp(prefix="paper_reader_tests_"))
os.environ["PDF_ROOT"] = str(TEST_ROOT)
os.environ["DATA_DIR"] = str(TEST_ROOT / "db")

from fastapi.testclient import TestClient

from app.config import PDF_DIR, PDF_ROOT
from app.db import get_conn, init_db
from app.main import app

# The real library is the one thing the tests must never touch. The
# environment above points the app at a throw-away directory; this makes
# sure of it, so a mistake in the setup cannot reach the user's data.
_REAL_LIBRARY = (Path(__file__).resolve().parents[2] / "local_data").resolve()
if PDF_ROOT == _REAL_LIBRARY or _REAL_LIBRARY in PDF_ROOT.parents:
    raise RuntimeError(f"the tests would run against the real library: {PDF_ROOT}")

#: A PDF that is small enough to keep in the repository and complete enough
#: for the backend, which never looks inside the file.
MINIMAL_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
    b"trailer<</Root 1 0 R>>\n"
    b"%%EOF\n"
)


def pdf_bytes(marker: str = "") -> bytes:
    """A PDF whose content depends on the marker.

    Two different markers give two different files, so their hashes differ.
    """
    return MINIMAL_PDF + f"% {marker}\n".encode()


@pytest.fixture(scope="session", autouse=True)
def _library() -> None:
    init_db()
    yield
    shutil.rmtree(TEST_ROOT, ignore_errors=True)


@pytest.fixture(autouse=True)
def clean_library():
    """An empty library for every test."""
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        conn.executescript(
            "DELETE FROM annotations; DELETE FROM paper_tags; DELETE FROM paper_folders;"
            "DELETE FROM papers; DELETE FROM tags; DELETE FROM folders; DELETE FROM trash;"
            "DELETE FROM sqlite_sequence;"
        )
        conn.commit()
    for path in PDF_DIR.iterdir():
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
    yield


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def upload(client):
    """Upload a PDF and return the answer of the API."""
    from io import BytesIO

    def _upload(
        marker: str = "paper",
        filename: str = "paper.pdf",
        title: str = "",
        **fields: str,
    ):
        data = {"title": title}
        data.update(fields)
        return client.post(
            "/api/papers",
            files={"file": (filename, BytesIO(pdf_bytes(marker)), "application/pdf")},
            data=data,
        )

    return _upload
