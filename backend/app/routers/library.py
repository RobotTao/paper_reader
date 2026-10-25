"""Folder (category tree) and tag management."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..db import folder_descendants, folder_tree, get_conn
from ..trash import move_to_trash
from .papers import decorate

router = APIRouter(prefix="/api", tags=["library"])


class FolderIn(BaseModel):
    name: str
    parentId: int | None = None
    color: str = "#3b71ca"
    sortOrder: int | None = None


class FolderPatch(BaseModel):
    name: str | None = None
    parentId: int | None = None
    color: str | None = None


class TagIn(BaseModel):
    name: str


@router.get("/folders")
def list_folders() -> list[dict]:
    with get_conn() as conn:
        return folder_tree(conn)


@router.get("/folders/{folder_id}/papers")
def folder_papers(folder_id: int, limit: int = 200) -> dict[str, Any]:
    """Papers filed *directly* in this folder.

    The tree shows each paper under the folder it actually belongs to, so
    sub-folders are not walked here (unlike the `folder=` filter on /papers).
    """
    limit = max(1, min(500, int(limit or 200)))
    with get_conn() as conn:
        if not conn.execute("SELECT 1 FROM folders WHERE id = ?", (folder_id,)).fetchone():
            raise HTTPException(status_code=404, detail="folder not found")
        total = conn.execute(
            "SELECT COUNT(*) AS n FROM paper_folders WHERE folder_id = ?", (folder_id,)
        ).fetchone()["n"]
        # Papers that no folder outside this sub-tree points at: they would
        # go away together with the folder.
        subtree = folder_descendants(conn, folder_id)
        placeholders = ",".join("?" * len(subtree))
        exclusive = conn.execute(
            f"""SELECT COUNT(*) AS n FROM papers p JOIN paper_folders pf ON pf.paper_id = p.id
                WHERE pf.folder_id IN ({placeholders})
                  AND NOT EXISTS (SELECT 1 FROM paper_folders pf2
                                  WHERE pf2.paper_id = p.id
                                    AND pf2.folder_id NOT IN ({placeholders}))""",
            [*subtree, *subtree],
        ).fetchone()["n"]
        rows = conn.execute(
            """SELECT p.* FROM papers p JOIN paper_folders pf ON pf.paper_id = p.id
               WHERE pf.folder_id = ? ORDER BY p.title COLLATE NOCASE LIMIT ?""",
            (folder_id, limit),
        ).fetchall()
        items = decorate(conn, rows)
    return {"items": items, "total": total, "limit": limit, "exclusive": exclusive}


@router.post("/folders", status_code=201)
def create_folder(payload: FolderIn) -> dict:
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    with get_conn() as conn:
        parent_id = payload.parentId
        if parent_id is not None and not conn.execute(
            "SELECT id FROM folders WHERE id = ?", (parent_id,)
        ).fetchone():
            parent_id = None
        sort_order = payload.sortOrder
        if sort_order is None:
            row = conn.execute(
                "SELECT COALESCE(MAX(sort_order), -1) + 1 AS n FROM folders "
                "WHERE parent_id IS ?",
                (parent_id,),
            ).fetchone()
            sort_order = int(row["n"])
        cur = conn.execute(
            "INSERT INTO folders (name, parent_id, color, sort_order) VALUES (?, ?, ?, ?)",
            (name, parent_id, payload.color, sort_order),
        )
        conn.commit()
        return {
            "id": int(cur.lastrowid),
            "name": name,
            "parentId": parent_id,
            "color": payload.color,
        }


@router.patch("/folders/{folder_id}")
def update_folder(folder_id: int, payload: FolderPatch) -> dict:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM folders WHERE id = ?", (folder_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="folder not found")
        name = payload.name.strip() if payload.name is not None else row["name"]
        if not name:
            raise HTTPException(status_code=400, detail="name is required")
        color = payload.color or row["color"]
        if "parentId" in payload.model_fields_set:
            parent_id = payload.parentId
        else:
            parent_id = row["parent_id"]
        if parent_id == folder_id:
            parent_id = None
        if parent_id is not None:
            if not conn.execute("SELECT id FROM folders WHERE id = ?", (parent_id,)).fetchone():
                raise HTTPException(status_code=404, detail="parent folder not found")
            # A folder cannot live inside itself.
            if parent_id in folder_descendants(conn, folder_id):
                raise HTTPException(status_code=400, detail="cannot move a folder into itself")
        conn.execute(
            "UPDATE folders SET name = ?, color = ?, parent_id = ? WHERE id = ?",
            (name, color, parent_id, folder_id),
        )
        conn.commit()
        return {"id": folder_id, "name": name, "color": color, "parentId": parent_id}


@router.delete("/folders/{folder_id}")
def delete_folder(folder_id: int) -> dict[str, Any]:
    """Delete a folder (and its sub-folders).

    Folders are virtual: a paper that another folder still points at stays.
    A paper that no folder points at any more goes to the trash - its
    metadata leaves the library, its PDF file stays on disk.
    """
    with get_conn() as conn:
        if not conn.execute("SELECT id FROM folders WHERE id = ?", (folder_id,)).fetchone():
            raise HTTPException(status_code=404, detail="folder not found")
        # Sub-folders are removed together with their parent.
        subtree = folder_descendants(conn, folder_id)
        placeholders = ",".join("?" * len(subtree))
        orphans = conn.execute(
            f"""SELECT p.id FROM papers p
                JOIN paper_folders pf ON pf.paper_id = p.id
                WHERE pf.folder_id IN ({placeholders})
                  AND NOT EXISTS (SELECT 1 FROM paper_folders pf2
                                  WHERE pf2.paper_id = p.id
                                    AND pf2.folder_id NOT IN ({placeholders}))
                GROUP BY p.id""",
            [*subtree, *subtree],
        ).fetchall()
        conn.execute("DELETE FROM folders WHERE id = ?", (folder_id,))
        trashed = []
        for row in orphans:
            entry = move_to_trash(conn, row["id"])
            if entry:
                trashed.append({"id": entry["id"], "title": entry["title"]})
        # A tag that just lost its last paper goes away with it - the
        # papers that went to the trash took their tags with them. Tags
        # nobody has used yet (a tag the user just made) stay.
        conn.commit()
    return {
        "ok": True,
        "trashedPapers": trashed,
    }


@router.get("/tags")
def list_tags() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT t.id, t.name, COUNT(pt.paper_id) AS count FROM tags t
               LEFT JOIN paper_tags pt ON pt.tag_id = t.id
               GROUP BY t.id ORDER BY count DESC, t.name"""
        ).fetchall()
        return [dict(row) for row in rows]


@router.post("/tags", status_code=201)
def create_tag(payload: TagIn) -> dict:
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    with get_conn() as conn:
        row = conn.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()
        if row is None:
            cur = conn.execute("INSERT INTO tags (name) VALUES (?)", (name,))
            tag_id = int(cur.lastrowid)
        else:
            tag_id = int(row["id"])
        conn.commit()
        return {"id": tag_id, "name": name}


@router.delete("/tags/{tag_id}")
def delete_tag(tag_id: int) -> dict[str, bool]:
    with get_conn() as conn:
        conn.execute("DELETE FROM tags WHERE id = ?", (tag_id,))
        conn.commit()
    return {"ok": True}
