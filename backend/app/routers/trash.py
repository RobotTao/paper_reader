"""The trash bin: list, restore, purge."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from ..db import get_conn
from ..hashes import find_duplicate
from ..trash import drop_from_trash, restore_from_trash, trash_entries
from .papers import decorate, remove_pdf

router = APIRouter(prefix="/api", tags=["trash"])


@router.get("/trash")
def list_trash() -> dict[str, Any]:
    """Everything in the trash, newest first."""
    with get_conn() as conn:
        items = trash_entries(conn)
    return {
        "items": items,
        "total": len(items),
        "totalSize": sum(item["sizeBytes"] for item in items),
    }


@router.post("/trash/{trash_id}/restore")
def restore_trash(trash_id: int) -> dict[str, Any]:
    """Bring a paper back. It comes back without any folder."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT content_hash, size_bytes FROM trash WHERE id = ?", (trash_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="not found in the trash")
        # The file of the paper may have been added again in the meantime:
        # the paper was trashed, the very same PDF was uploaded once more, and
        # now the trash already holds a paper with that file. Restoring it
        # would put the same file into the library twice, so it is reported
        # as a duplicate instead - just like the upload path does.
        if row["content_hash"]:
            duplicate = find_duplicate(conn, row["content_hash"], row["size_bytes"] or None)
            if duplicate is not None:
                existing_row = conn.execute(
                    "SELECT * FROM papers WHERE id = ?", (duplicate["id"],)
                ).fetchone()
                existing = decorate(conn, [existing_row])[0]
                raise HTTPException(
                    status_code=409, detail=f"这篇已经在库里了：《{existing['title']}》"
                )
        paper_id = restore_from_trash(conn, trash_id)
        if paper_id is None:
            raise HTTPException(status_code=404, detail="not found in the trash")
        conn.commit()
        restored = conn.execute("SELECT * FROM papers WHERE id = ?", (paper_id,)).fetchone()
        return {"ok": True, "paper": decorate(conn, [restored])[0]}


@router.delete("/trash/{trash_id}")
def purge_trash(trash_id: int) -> dict[str, Any]:
    """Delete a trashed paper for good - the file goes away with it."""
    with get_conn() as conn:
        found, file_path = drop_from_trash(conn, trash_id)
        if not found:
            raise HTTPException(status_code=404, detail="not found in the trash")
        conn.commit()
    remove_pdf(file_path)
    return {"ok": True}


@router.post("/trash/empty")
def empty_trash() -> dict[str, Any]:
    """Empty the whole trash - every file in it is deleted."""
    with get_conn() as conn:
        rows = conn.execute("SELECT id, file_path FROM trash").fetchall()
        conn.execute("DELETE FROM trash")
        conn.commit()
    for row in rows:
        remove_pdf(row["file_path"])
    return {"ok": True, "purged": len(rows)}
