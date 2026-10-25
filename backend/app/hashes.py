"""Content hashes of the PDF files.

Two papers with the same file are the same paper, so the hash of the file is
what the library compares: uploading a PDF that is already in the library
must not create a second copy of it.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from .db import resolve_pdf_path

#: How much of a file is read at a time. A big PDF never lands in memory.
CHUNK_SIZE = 1024 * 1024


def sha256_file(path: Path) -> str:
    """The sha256 of a file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def find_duplicate(
    conn: sqlite3.Connection, digest: str, size: int | None = None
) -> sqlite3.Row | None:
    """The paper that already holds this file, if there is one.

    Only the papers that are in the library count: a file that sits in the
    trash can be uploaded again on purpose.

    ``size`` is the size of the file that is being added. When the paper that
    was found has a file of a different size, it is not the same file - a
    hash collision would have to be astronomically unlikely, but a different
    size settles it.
    """
    row = conn.execute(
        "SELECT id, title, authors, year, file_path FROM papers "
        "WHERE content_hash = ? LIMIT 1",
        (digest,),
    ).fetchone()
    if row is not None:
        if size is not None:
            existing = resolve_pdf_path(row["file_path"])
            if existing is not None and existing.exists() and existing.stat().st_size != size:
                return None
        return row

    if size is None:
        return None
    return _find_unhashed_duplicate(conn, digest, size)


def _find_unhashed_duplicate(
    conn: sqlite3.Connection, digest: str, size: int
) -> sqlite3.Row | None:
    """Look for the file among the papers that have no hash yet.

    A paper that was imported before the hashes existed is only found by
    hashing its file. The size decides which files are worth hashing, and
    the hash that is found is written down, so this gets cheaper over time.
    """
    candidates = conn.execute(
        "SELECT id, title, authors, year, file_path FROM papers "
        "WHERE content_hash IS NULL AND file_path IS NOT NULL AND file_path != ''"
    ).fetchall()
    for candidate in candidates:
        path = resolve_pdf_path(candidate["file_path"])
        if path is None or not path.exists():
            continue
        if path.stat().st_size != size:
            continue
        if sha256_file(path) != digest:
            continue
        conn.execute(
            "UPDATE papers SET content_hash = ? WHERE id = ?", (digest, candidate["id"])
        )
        # The write is saved right away: the caller may return without
        # committing anything else, and the hash must not be lost.
        conn.commit()
        return candidate
    return None
