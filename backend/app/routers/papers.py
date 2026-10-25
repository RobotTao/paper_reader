"""Paper CRUD, search, bulk actions and file streaming."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import urllib.parse
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from ..config import MAX_UPLOAD_MB, PDF_DIR
from ..db import (
    folder_descendants,
    get_conn,
    resolve_pdf_path,
    set_tags,
)
from ..hashes import find_duplicate
from ..trash import move_to_trash

router = APIRouter(prefix="/api", tags=["papers"])

SORT_FIELDS = {
    "lastRead": "p.last_read_at",
    "created": "p.created_at",
    "updated": "p.updated_at",
    "title": "p.title COLLATE NOCASE",
    "importance": "p.importance",
    "isRead": "p.is_read",
}

#: Older aliases kept so existing clients keep working.
SORT_ALIASES = {
    "recent": "lastRead",
    "created": "created",
    "updated": "updated",
    "title": "title",
    "importance": "importance",
    "isRead": "isRead",
}

ORDERS = ("asc", "desc", "none")


def order_clause(sort: str, order: str) -> str:
    """Build the ORDER BY clause; an empty string means "no sorting"."""
    if order not in ORDERS or order == "none":
        return ""
    field = SORT_ALIASES.get(sort, sort)
    if field not in SORT_FIELDS:
        field = "lastRead"
    direction = "ASC" if order == "asc" else "DESC"

    if field == "title":
        return f"p.title COLLATE NOCASE {direction}, p.id {direction}"
    if field == "lastRead":
        # papers that were never read always come last
        return f"p.last_read_at IS NULL, p.last_read_at {direction}, p.id {direction}"
    return f"{SORT_FIELDS[field]} {direction}, p.id {direction}"


class PaperUpdate(BaseModel):
    title: str | None = None
    authors: str | None = None
    year: int | None = None
    abstract: str | None = None
    remark: str | None = None
    notes: str | None = None
    importance: int | None = Field(default=None, ge=0, le=5)
    readingStatus: str | None = None
    isRead: bool | None = None
    progress: int | None = None
    tags: list[str] | None = None
    folderIds: list[int] | None = None
    addFolderIds: list[int] | None = None
    removeFolderIds: list[int] | None = None
    clearFolders: bool | None = None
    markRead: bool | None = None


class BulkAction(BaseModel):
    ids: list[int]
    action: str
    folderIds: list[int] | None = None
    tag: str | None = None
    importance: int | None = None
    isRead: bool | None = None


def serialize(row: sqlite3.Row, folders: list[dict], tags: list[dict]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "authors": row["authors"],
        "year": row["year"],
        "source": row["source"],
        "url": row["url"],
        "abstract": row["abstract"],
        "remark": row["remark"],
        "notes": row["notes"],
        "importance": row["importance"],
        "readingStatus": row["reading_status"],
        "isRead": bool(row["is_read"]),
        "progress": row["progress"],
        "readCount": row["read_count"],
        "lastReadAt": row["last_read_at"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "hasFile": bool(row["file_path"]),
        "folders": folders,
        "tags": tags,
    }


def decorate(conn: sqlite3.Connection, rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    if not rows:
        return []
    ids = [row["id"] for row in rows]
    placeholders = ",".join("?" * len(ids))

    folders_by_paper: dict[int, list[dict]] = {}
    for row in conn.execute(
        f"""SELECT pf.paper_id AS pid, f.id, f.name FROM paper_folders pf
            JOIN folders f ON f.id = pf.folder_id WHERE pf.paper_id IN ({placeholders})""",
        ids,
    ).fetchall():
        folders_by_paper.setdefault(row["pid"], []).append({"id": row["id"], "name": row["name"]})

    tags_by_paper: dict[int, list[dict]] = {}
    for row in conn.execute(
        f"""SELECT pt.paper_id AS pid, t.id, t.name FROM paper_tags pt
            JOIN tags t ON t.id = pt.tag_id WHERE pt.paper_id IN ({placeholders})""",
        ids,
    ).fetchall():
        tags_by_paper.setdefault(row["pid"], []).append({"id": row["id"], "name": row["name"]})

    return [
        serialize(row, folders_by_paper.get(row["id"], []), tags_by_paper.get(row["id"], []))
        for row in rows
    ]


def set_folders(conn: sqlite3.Connection, paper_id: int, folder_ids: list[int]) -> None:
    conn.execute("DELETE FROM paper_folders WHERE paper_id = ?", (paper_id,))
    for folder_id in folder_ids:
        if conn.execute("SELECT id FROM folders WHERE id = ?", (folder_id,)).fetchone():
            conn.execute(
                "INSERT OR IGNORE INTO paper_folders (paper_id, folder_id) VALUES (?, ?)",
                (paper_id, folder_id),
            )


@router.get("/papers")
def list_papers(
    q: str = "",
    folder: str = "all",
    tag: str = "",
    importance: int = 0,
    read: str = "all",
    sort: str = "lastRead",
    order: str = "desc",
    limit: int = 40,
    offset: int = 0,
) -> dict[str, Any]:
    where: list[str] = []
    params: list[Any] = []

    q = q.strip()
    if q:
        where.append(
            "(p.title LIKE ? OR p.remark LIKE ? OR p.notes LIKE ? OR p.authors LIKE ? OR p.abstract LIKE ?)"
        )
        params.extend([f"%{q}%"] * 5)

    if folder == "unfiled":
        where.append("NOT EXISTS (SELECT 1 FROM paper_folders pf WHERE pf.paper_id = p.id)")
    elif folder and folder != "all":
        with get_conn() as conn:
            ids = folder_descendants(conn, int(folder))
        where.append(
            "p.id IN (SELECT paper_id FROM paper_folders WHERE folder_id IN ("
            + ",".join("?" * len(ids))
            + "))"
        )
        params.extend(ids)

    tag = tag.strip()
    if tag:
        where.append(
            "p.id IN (SELECT paper_id FROM paper_tags WHERE tag_id = (SELECT id FROM tags WHERE name = ?))"
        )
        params.append(tag)

    if importance > 0:
        where.append("p.importance >= ?")
        params.append(importance)

    # The read filter narrows the list; the counts of read / unread papers in
    # this view are what the filter dropdown shows, so they are counted
    # without it.
    base_where = list(where)
    base_params = list(params)

    if read == "read":
        where.append("p.is_read = 1")
    elif read == "unread":
        where.append("p.is_read = 0")

    clause = f"WHERE {' AND '.join(where)}" if where else ""
    order_sql = order_clause(sort, order)
    ordering = f"ORDER BY {order_sql}" if order_sql else ""

    limit = max(1, min(500, int(limit or 40)))
    offset = max(0, int(offset or 0))

    with get_conn() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) AS n FROM papers p {clause}", params
        ).fetchone()["n"]
        rows = conn.execute(
            f"SELECT * FROM papers p {clause} {ordering} LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()

        def count_with(extra: str) -> int:
            conds = [*base_where, extra]
            sql = f"WHERE {' AND '.join(conds)}" if conds else ""
            return conn.execute(
                f"SELECT COUNT(*) AS n FROM papers p {sql}", base_params
            ).fetchone()["n"]

        read_count = count_with("p.is_read = 1")
        unread_count = count_with("p.is_read = 0")

        return {
            "items": decorate(conn, rows),
            "total": total,
            "limit": limit,
            "offset": offset,
            "readCount": read_count,
            "unreadCount": unread_count,
        }


@router.get("/papers/{paper_id}")
def get_paper(paper_id: int) -> dict[str, Any]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM papers WHERE id = ?", (paper_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="paper not found")
        paper = decorate(conn, [row])[0]
        paper["annotations"] = []
        for note in conn.execute(
            "SELECT id, page_number AS pageNumber, text, idea, rects, color FROM annotations "
            "WHERE paper_id = ? ORDER BY page_number, id",
            (paper_id,),
        ).fetchall():
            item = dict(note)
            try:
                item["rects"] = json.loads(item.get("rects") or "[]")
            except json.JSONDecodeError:
                item["rects"] = []
            paper["annotations"].append(item)
        return paper


@router.get("/papers/{paper_id}/file")
def stream_file(paper_id: int, download: bool = False) -> FileResponse:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM papers WHERE id = ?", (paper_id,)).fetchone()
    if row is None or not row["file_path"]:
        raise HTTPException(status_code=404, detail="file not found")
    path = resolve_pdf_path(row["file_path"])
    if path is None or not path.exists():
        raise HTTPException(status_code=410, detail="file missing on disk")
    return FileResponse(
        path,
        media_type="application/pdf",
        headers={"Content-Disposition": content_disposition(row["title"], paper_id, download)},
    )


@router.post("/papers", status_code=201)
async def create_paper(
    file: UploadFile | None = File(default=None),
    title: str = Form(default=""),
    authors: str = Form(default=""),
    year: int | None = Form(default=None),
    url: str = Form(default=""),
    abstract: str = Form(default=""),
    remark: str = Form(default=""),
    notes: str = Form(default=""),
    importance: int = Form(default=0),
    tags: str = Form(default="[]"),
    folderIds: str = Form(default="[]"),
) -> dict[str, Any]:
    def parse_list(raw: str) -> list:
        try:
            value = json.loads(raw or "[]")
            return value if isinstance(value, list) else []
        except json.JSONDecodeError:
            return []

    file_path: str | None = None
    stored_name: str | None = None
    content_hash: str | None = None
    size = 0
    if file is not None and file.filename:
        suffix = Path(file.filename).suffix.lower() or ".pdf"
        stored_name = f"{uuid.uuid4().hex}{suffix}"
        PDF_DIR.mkdir(parents=True, exist_ok=True)
        # Stream the file to disk instead of holding it in memory: a large
        # PDF would otherwise be read into RAM before the size check.
        # The hash of the file is computed on the way, so the file is never
        # read a second time.
        digest = hashlib.sha256()
        limit = MAX_UPLOAD_MB * 1024 * 1024
        target = PDF_DIR / stored_name
        handle = await run_in_threadpool(open, target, "wb")
        try:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(status_code=413, detail="file too large")
                digest.update(chunk)
                await run_in_threadpool(handle.write, chunk)
        except HTTPException:
            await run_in_threadpool(handle.close)
            target.unlink(missing_ok=True)
            raise
        except OSError as error:
            await run_in_threadpool(handle.close)
            target.unlink(missing_ok=True)
            raise HTTPException(status_code=500, detail=f"cannot store the file: {error}")
        else:
            await run_in_threadpool(handle.close)
        content_hash = digest.hexdigest()
        # Uploaded PDFs live in the same store as the imported ones, so a
        # paper's file is never duplicated.
        file_path = f"pdfs/{stored_name}"
        if not title:
            title = Path(file.filename).stem.replace("_", " ").strip()
    else:
        # Every paper has a file, so every paper has a hash. A paper without
        # a file could not be found by the duplicate check later.
        raise HTTPException(status_code=400, detail="a file is required")

    with get_conn() as conn:
        # The same file must not end up in the library twice. The paper that
        # is already there is reported back, so the user can be told which
        # one it is.
        duplicate = find_duplicate(conn, content_hash, size)
        if duplicate is not None:
            # The file that was just written is not kept - the paper is
            # already in the library.
            if stored_name:
                (PDF_DIR / stored_name).unlink(missing_ok=True)
            row = conn.execute(
                "SELECT * FROM papers WHERE id = ?", (duplicate["id"],)
            ).fetchone()
            existing = decorate(conn, [row])[0]
            return JSONResponse(
                status_code=409,
                content={
                    "detail": f"这篇已经在库里了：《{existing['title']}》",
                    "code": "duplicate",
                    "paper": existing,
                },
            )

        cur = conn.execute(
            """INSERT INTO papers (title, authors, year, source, file_path, url, abstract,
                                  remark, notes, importance, created_at, updated_at,
                                  content_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'), ?)""",
            (
                (title or url or "Untitled").strip(),
                authors,
                year,
                "pdf" if file_path else "url",
                file_path,
                url or None,
                abstract,
                remark,
                notes,
                max(0, min(5, importance or 0)),
                content_hash,
            ),
        )
        paper_id = int(cur.lastrowid)
        set_tags(conn, paper_id, [str(t) for t in parse_list(tags)])
        set_folders(conn, paper_id, [int(f) for f in parse_list(folderIds)])
        conn.commit()
        row = conn.execute("SELECT * FROM papers WHERE id = ?", (paper_id,)).fetchone()
        return decorate(conn, [row])[0]


@router.patch("/papers/{paper_id}")
def update_paper(paper_id: int, payload: PaperUpdate) -> dict[str, Any]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM papers WHERE id = ?", (paper_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="paper not found")

        updates: list[str] = []
        params: dict[str, Any] = {}
        # Only the fields the client actually sent are touched, so a field
        # can be cleared by sending null (an empty year, say) without the
        # others being overwritten.
        sent = payload.model_dump(exclude_unset=True)
        simple = {
            "title": "title",
            "authors": "authors",
            "year": "year",
            "abstract": "abstract",
            "remark": "remark",
            "notes": "notes",
            "reading_status": "readingStatus",
            "progress": "progress",
        }
        nullable = {"year", "reading_status"}
        for column, field in simple.items():
            if field not in sent:
                continue
            value = sent[field]
            if value is None and column not in nullable:
                continue
            updates.append(f"{column} = :{column}")
            params[column] = value
        if payload.importance is not None:
            updates.append("importance = :importance")
            params["importance"] = max(0, min(5, payload.importance))
        if payload.isRead is not None:
            updates.append("is_read = :is_read")
            params["is_read"] = 1 if payload.isRead else 0
        if payload.markRead:
            updates.append("read_count = read_count + 1")
            updates.append("last_read_at = datetime('now')")

        if updates:
            updates.append("updated_at = datetime('now')")
            params["id"] = paper_id
            conn.execute(f"UPDATE papers SET {', '.join(updates)} WHERE id = :id", params)

        if payload.tags is not None:
            set_tags(conn, paper_id, payload.tags)
        if payload.folderIds is not None:
            set_folders(conn, paper_id, payload.folderIds)
        if payload.addFolderIds:
            for folder_id in payload.addFolderIds:
                if conn.execute("SELECT id FROM folders WHERE id = ?", (folder_id,)).fetchone():
                    conn.execute(
                        "INSERT OR IGNORE INTO paper_folders (paper_id, folder_id) VALUES (?, ?)",
                        (paper_id, folder_id),
                    )
        if payload.removeFolderIds:
            for folder_id in payload.removeFolderIds:
                conn.execute(
                    "DELETE FROM paper_folders WHERE paper_id = ? AND folder_id = ?",
                    (paper_id, folder_id),
                )
        if payload.clearFolders:
            conn.execute("DELETE FROM paper_folders WHERE paper_id = ?", (paper_id,))

        conn.commit()
        row = conn.execute("SELECT * FROM papers WHERE id = ?", (paper_id,)).fetchone()
        return decorate(conn, [row])[0]


def remove_pdf(file_path: str | None) -> None:
    """Delete a paper's file from the single PDF store.

    The store is writable and holds one copy per paper, so removing the
    paper removes its file as well.
    """
    target = resolve_pdf_path(file_path)
    if target and target.exists() and PDF_DIR in target.parents:
        os.remove(target)


def content_disposition(title: str, paper_id: int, attachment: bool) -> str:
    """Build the Content-Disposition header for a paper's PDF.

    Titles are often non-ASCII, so the readable name goes into the
    RFC 5987 ``filename*`` part and a generic name is the fallback.
    """
    mode = "attachment" if attachment else "inline"
    safe = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", title or "").strip()[:120]
    quoted = urllib.parse.quote(f"{safe or f'paper-{paper_id}'}.pdf")
    return f'{mode}; filename="paper-{paper_id}.pdf"; filename*=UTF-8\'\'{quoted}'


@router.delete("/papers/{paper_id}")
def delete_paper(paper_id: int) -> dict[str, Any]:
    """Move a paper to the trash. Its file stays on disk."""
    with get_conn() as conn:
        trashed = move_to_trash(conn, paper_id)
        if trashed is None:
            raise HTTPException(status_code=404, detail="paper not found")
        conn.commit()
    return {"ok": True, "trashed": True, "paper": trashed}


@router.post("/papers/bulk")
def bulk_action(payload: BulkAction) -> dict[str, Any]:
    if not payload.ids:
        raise HTTPException(status_code=400, detail="ids is required")

    with get_conn() as conn:
        trashed: list[dict[str, Any]] = []
        if payload.action == "move":
            folder_ids = payload.folderIds or []
            for paper_id in payload.ids:
                set_folders(conn, paper_id, folder_ids)
        elif payload.action in ("tag", "untag"):
            if not payload.tag:
                raise HTTPException(status_code=400, detail="tag is required")
            for paper_id in payload.ids:
                rows = conn.execute(
                    """SELECT t.name FROM paper_tags pt JOIN tags t ON t.id = pt.tag_id
                       WHERE pt.paper_id = ?""",
                    (paper_id,),
                ).fetchall()
                names = [r["name"] for r in rows]
                if payload.action == "tag":
                    names.append(payload.tag)
                else:
                    names = [n for n in names if n != payload.tag]
                set_tags(conn, paper_id, names)
        elif payload.action == "importance":
            value = max(0, min(5, payload.importance or 0))
            for paper_id in payload.ids:
                conn.execute(
                    "UPDATE papers SET importance = ?, updated_at = datetime('now') WHERE id = ?",
                    (value, paper_id),
                )
        elif payload.action == "read":
            value = 1 if payload.isRead is not False else 0
            for paper_id in payload.ids:
                conn.execute(
                    "UPDATE papers SET is_read = ?, updated_at = datetime('now') WHERE id = ?",
                    (value, paper_id),
                )
        elif payload.action == "delete":
            # The papers go to the trash, their files stay on disk.
            for paper_id in payload.ids:
                entry = move_to_trash(conn, paper_id)
                if entry:
                    trashed.append(entry)
        else:
            raise HTTPException(status_code=400, detail=f"unknown action: {payload.action}")

        conn.commit()
        rows = conn.execute(
            f"SELECT * FROM papers WHERE id IN ({','.join('?' * len(payload.ids))})", payload.ids
        ).fetchall()
        return {"ok": True, "papers": decorate(conn, rows), "trashed": trashed}


#: The colours a highlight can have. They mean something, so they are a
#: fixed list and not a free text field.
ANNOTATION_COLORS = ("yellow", "green", "red", "blue", "orange")


def check_color(color: str) -> str:
    """The colour to store, or an error when it is not one of ours."""
    if color not in ANNOTATION_COLORS:
        raise HTTPException(status_code=400, detail=f"unknown colour: {color}")
    return color


class AnnotationIn(BaseModel):
    pageNumber: int | None = None
    text: str = ""
    idea: str = ""
    rects: list[dict[str, Any]] = Field(default_factory=list)
    color: str = "yellow"


class AnnotationUpdate(BaseModel):
    text: str | None = None
    idea: str | None = None
    color: str | None = None


@router.post("/papers/{paper_id}/annotations", status_code=201)
def create_annotation(paper_id: int, payload: AnnotationIn) -> dict[str, Any]:
    color = check_color(payload.color)
    with get_conn() as conn:
        if not conn.execute("SELECT id FROM papers WHERE id = ?", (paper_id,)).fetchone():
            raise HTTPException(status_code=404, detail="paper not found")
        cur = conn.execute(
            "INSERT INTO annotations (paper_id, page_number, text, idea, rects, color)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                paper_id,
                payload.pageNumber,
                payload.text,
                payload.idea,
                json.dumps(payload.rects, ensure_ascii=False),
                color,
            ),
        )
        conn.commit()
        return {
            "id": int(cur.lastrowid),
            "pageNumber": payload.pageNumber,
            "text": payload.text,
            "idea": payload.idea,
            "rects": payload.rects,
            "color": color,
        }


@router.patch("/annotations/{annotation_id}")
def update_annotation(annotation_id: int, payload: AnnotationUpdate) -> dict[str, Any]:
    """Change what a highlight says - the note next to it, mostly."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, page_number AS pageNumber, text, idea, rects, color"
            " FROM annotations WHERE id = ?",
            (annotation_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="annotation not found")
        text = payload.text if payload.text is not None else row["text"]
        idea = payload.idea if payload.idea is not None else row["idea"]
        color = check_color(payload.color) if payload.color is not None else row["color"]
        conn.execute(
            "UPDATE annotations SET text = ?, idea = ?, color = ? WHERE id = ?",
            (text, idea, color, annotation_id),
        )
        conn.commit()
        item = dict(row)
        item.update({"text": text, "idea": idea, "color": color})
        # The rectangles come back as a list, the way the reader expects
        # them - the same shape the paper carries them in.
        try:
            item["rects"] = json.loads(item.get("rects") or "[]")
        except json.JSONDecodeError:
            item["rects"] = []
        return item


@router.delete("/annotations/{annotation_id}")
def delete_annotation(annotation_id: int) -> dict[str, bool]:
    with get_conn() as conn:
        conn.execute("DELETE FROM annotations WHERE id = ?", (annotation_id,))
        conn.commit()
    return {"ok": True}


@router.get("/stats")
def stats() -> dict[str, int]:
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) AS n FROM papers").fetchone()["n"]
        unfiled = conn.execute(
            "SELECT COUNT(*) AS n FROM papers p WHERE NOT EXISTS "
            "(SELECT 1 FROM paper_folders pf WHERE pf.paper_id = p.id)"
        ).fetchone()["n"]
        with_file = conn.execute(
            "SELECT COUNT(*) AS n FROM papers WHERE file_path IS NOT NULL"
        ).fetchone()["n"]
        annotations = conn.execute("SELECT COUNT(*) AS n FROM annotations").fetchone()["n"]
        read_count = conn.execute("SELECT COUNT(*) AS n FROM papers WHERE is_read = 1").fetchone()["n"]
        trash = conn.execute("SELECT COUNT(*) AS n FROM trash").fetchone()["n"]
    return {
        "total": total,
        "unfiled": unfiled,
        "withFile": with_file,
        "annotations": annotations,
        "read": read_count,
        "unread": total - read_count,
        "trash": trash,
    }
