"""The trash bin.

Deleting a paper takes it out of the library completely: its row and
everything pointing at it (folder links, tags, annotations) are gone. The
PDF file stays on disk, though - the trash remembers where it is, so the
paper can be restored later (it comes back unfiled) or purged for good
(the file goes away then).
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from .db import drop_orphan_tags, resolve_pdf_path, set_tags

#: The columns of a paper that the trash keeps.
PAPER_COLUMNS = (
    "title",
    "authors",
    "year",
    "source",
    "file_path",
    "url",
    "abstract",
    "remark",
    "notes",
    "importance",
    "reading_status",
    "is_read",
    "progress",
    "read_count",
    "last_read_at",
    "created_at",
    "updated_at",
    # The hash of the file, so a restored paper is found again by the
    # duplicate check right away.
    "content_hash",
)


def _json_list(raw: str | None) -> list:
    """Read a JSON list from the trash; broken data reads as empty."""
    try:
        value = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return value if isinstance(value, list) else []


def move_to_trash(conn: sqlite3.Connection, paper_id: int) -> dict[str, Any] | None:
    """Move a paper into the trash; the file stays where it is.

    Returns what was trashed, or None when there is no such paper.
    """
    row = conn.execute("SELECT * FROM papers WHERE id = ?", (paper_id,)).fetchone()
    if row is None:
        return None

    tags = [
        r["name"]
        for r in conn.execute(
            "SELECT t.name FROM paper_tags pt JOIN tags t ON t.id = pt.tag_id "
            "WHERE pt.paper_id = ? ORDER BY t.name",
            (paper_id,),
        )
    ]
    annotations = [
        {
            "pageNumber": r["page_number"],
            "text": r["text"],
            "idea": r["idea"],
            "rects": r["rects"],
            "color": r["color"],
        }
        for r in conn.execute(
            "SELECT page_number, text, idea, rects, color FROM annotations"
            " WHERE paper_id = ? ORDER BY id",
            (paper_id,),
        )
    ]

    size = 0
    target = resolve_pdf_path(row["file_path"])
    if target and target.exists():
        size = target.stat().st_size

    placeholders = ", ".join("?" * len(PAPER_COLUMNS))
    conn.execute(
        f"""INSERT INTO trash (paper_id, legacy_id, {", ".join(PAPER_COLUMNS)},
                size_bytes, tags, annotations)
            VALUES (?, ?, {placeholders}, ?, ?, ?)""",
        (
            row["id"],
            row["legacy_id"],
            *(row[column] for column in PAPER_COLUMNS),
            size,
            json.dumps(tags, ensure_ascii=False),
            json.dumps(annotations, ensure_ascii=False),
        ),
    )

    # The metadata leaves the library; the file stays where it is.
    tag_ids = [
        r["tag_id"]
        for r in conn.execute(
            "SELECT tag_id FROM paper_tags WHERE paper_id = ?", (paper_id,)
        ).fetchall()
    ]
    conn.execute("DELETE FROM papers WHERE id = ?", (paper_id,))
    # A tag that just lost its last paper goes away with it.
    drop_orphan_tags(conn, tag_ids)
    return {
        "id": paper_id,
        "title": row["title"],
        "filePath": row["file_path"],
        "sizeBytes": size,
    }


def restore_from_trash(conn: sqlite3.Connection, trash_id: int) -> int | None:
    """Put a trashed paper back into the library, without any folder.

    Returns the id of the restored paper, or None when there is no such
    entry.
    """
    row = conn.execute("SELECT * FROM trash WHERE id = ?", (trash_id,)).fetchone()
    if row is None:
        return None

    paper_id = int(row["paper_id"])
    legacy_id = row["legacy_id"]
    # The id may have been taken again in the meantime (a re-import, say).
    id_taken = conn.execute("SELECT 1 FROM papers WHERE id = ?", (paper_id,)).fetchone()
    if legacy_id and conn.execute(
        "SELECT 1 FROM papers WHERE legacy_id = ?", (legacy_id,)
    ).fetchone():
        legacy_id = None

    values = [row[column] for column in PAPER_COLUMNS]
    columns = ", ".join(PAPER_COLUMNS)
    placeholders = ", ".join("?" * len(PAPER_COLUMNS))
    if id_taken:
        cur = conn.execute(
            f"INSERT INTO papers (legacy_id, {columns}) VALUES (?, {placeholders})",
            [legacy_id, *values],
        )
        paper_id = int(cur.lastrowid)
    else:
        cur = conn.execute(
            f"INSERT INTO papers (id, legacy_id, {columns}) VALUES (?, ?, {placeholders})",
            [paper_id, legacy_id, *values],
        )
        paper_id = int(cur.lastrowid)

    # The tags and the highlights come back with it.
    try:
        tag_names = json.loads(row["tags"] or "[]")
    except json.JSONDecodeError:
        tag_names = []
    set_tags(conn, paper_id, [str(name) for name in tag_names])

    try:
        notes = json.loads(row["annotations"] or "[]")
    except json.JSONDecodeError:
        notes = []
    for note in notes:
        conn.execute(
            """INSERT INTO annotations (paper_id, page_number, text, idea, rects, color)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                paper_id,
                note.get("pageNumber"),
                note.get("text", ""),
                note.get("idea", ""),
                note.get("rects", "[]"),
                note.get("color", "yellow"),
            ),
        )

    conn.execute("DELETE FROM trash WHERE id = ?", (trash_id,))
    return paper_id


def drop_from_trash(conn: sqlite3.Connection, trash_id: int) -> tuple[bool, str | None]:
    """Forget a trashed paper.

    Returns whether the entry was there and the path of the file to delete.
    A paper that is only a link has no file, and "no file" is not the same
    thing as "no such entry" - both answers can be None otherwise.
    """
    row = conn.execute("SELECT file_path FROM trash WHERE id = ?", (trash_id,)).fetchone()
    if row is None:
        return False, None
    conn.execute("DELETE FROM trash WHERE id = ?", (trash_id,))
    return True, row["file_path"]


def trash_entries(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Everything that is in the trash, newest first."""
    rows = conn.execute(
        """SELECT id, paper_id, title, authors, year, source, file_path, url,
                  importance, deleted_at, size_bytes, tags, annotations
           FROM trash ORDER BY deleted_at DESC, id DESC"""
    ).fetchall()
    items = []
    for row in rows:
        items.append(
            {
                "id": row["id"],
                "paperId": row["paper_id"],
                "title": row["title"],
                "authors": row["authors"],
                "year": row["year"],
                "source": row["source"],
                "filePath": row["file_path"],
                "url": row["url"],
                "importance": row["importance"],
                "deletedAt": row["deleted_at"],
                "sizeBytes": row["size_bytes"],
                "hasFile": bool(row["file_path"]),
                "tagCount": len(_json_list(row["tags"])),
                "annotationCount": len(_json_list(row["annotations"])),
            }
        )
    return items
