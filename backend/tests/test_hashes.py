"""The content hash: how it is written, and how a duplicate is found."""

from __future__ import annotations

import hashlib
import shutil

from app.cli import cmd_index_hashes
from app.config import PDF_DIR
from app.db import get_conn
from tests.conftest import pdf_bytes


def test_index_hashes_fills_the_column_of_every_paper(client, upload):
    upload(marker="one", title="第一篇")
    upload(marker="two", title="第二篇")
    with get_conn() as conn:
        conn.execute("UPDATE papers SET content_hash = NULL")
        conn.commit()

    cmd_index_hashes(None)

    with get_conn() as conn:
        rows = conn.execute("SELECT content_hash FROM papers").fetchall()
    assert all(row["content_hash"] for row in rows)


def test_index_hashes_reports_the_duplicates_it_finds(client, upload, capsys):
    upload(marker="one", title="第一篇")
    # A second paper with the same file, but no hash yet.
    same = PDF_DIR / "copy.pdf"
    shutil.copy(next(PDF_DIR.glob("*.pdf")), same)
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO papers (title, file_path) VALUES ('第二篇', 'pdfs/copy.pdf')"
        )
        conn.commit()

    cmd_index_hashes(None)

    out = capsys.readouterr().out
    assert "groups of papers with the same file" in out
    assert "第一篇" in out and "第二篇" in out


def test_a_paper_without_a_hash_is_still_recognised(client, upload):
    upload(marker="one", title="第一篇")
    # Pretend the paper was imported before hashes existed.
    with get_conn() as conn:
        conn.execute("UPDATE papers SET content_hash = NULL")
        conn.commit()

    response = upload(marker="one", title="再来一次")

    assert response.status_code == 409
    assert response.json()["paper"]["title"] == "第一篇"
    # The hash is written down while the duplicate is found.
    with get_conn() as conn:
        row = conn.execute("SELECT content_hash FROM papers").fetchone()
    assert row["content_hash"] == hashlib.sha256(pdf_bytes("one")).hexdigest()


def test_a_different_size_is_not_a_duplicate(client, upload):
    upload(marker="one", title="第一篇")
    with get_conn() as conn:
        conn.execute("UPDATE papers SET content_hash = NULL")
        conn.commit()

    # Same hash, different length: not the same file.
    bigger = pdf_bytes("one") + b"% padding\n" * 10
    response = client.post(
        "/api/papers",
        files={"file": ("other.pdf", bigger, "application/pdf")},
        data={"title": "另一个"},
    )

    assert response.status_code == 201


def test_a_paper_in_the_trash_does_not_block_the_upload(client, upload):
    first = upload(marker="one", title="第一篇")
    client.delete(f"/api/papers/{first.json()['id']}")

    # The file is still on disk, but the paper is gone: uploading it again
    # is allowed on purpose.
    assert upload(marker="one", title="再来一次").status_code == 201
