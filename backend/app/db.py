"""SQLite access layer: schema, connection handling and query helpers."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .config import DB_PATH, ensure_dirs

SCHEMA = """
CREATE TABLE IF NOT EXISTS folders (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    legacy_id   TEXT UNIQUE,
    parent_id   INTEGER REFERENCES folders(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    color       TEXT NOT NULL DEFAULT '#3b71ca',
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tags (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    legacy_id   TEXT UNIQUE,
    name        TEXT NOT NULL UNIQUE,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS papers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    legacy_id       TEXT UNIQUE,
    title           TEXT NOT NULL,
    authors         TEXT NOT NULL DEFAULT '',
    year            INTEGER,
    source          TEXT NOT NULL DEFAULT 'pdf',
    file_path       TEXT,
    url             TEXT,
    abstract        TEXT NOT NULL DEFAULT '',
    remark          TEXT NOT NULL DEFAULT '',
    notes           TEXT NOT NULL DEFAULT '',
    importance      INTEGER NOT NULL DEFAULT 0,
    reading_status  TEXT,
    is_read         INTEGER NOT NULL DEFAULT 0,
    progress        INTEGER NOT NULL DEFAULT 0,
    read_count      INTEGER NOT NULL DEFAULT 0,
    last_read_at    TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    content_hash    TEXT
);

CREATE TABLE IF NOT EXISTS paper_folders (
    paper_id  INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    folder_id INTEGER NOT NULL REFERENCES folders(id) ON DELETE CASCADE,
    PRIMARY KEY (paper_id, folder_id)
);

CREATE TABLE IF NOT EXISTS paper_tags (
    paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    tag_id   INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (paper_id, tag_id)
);

CREATE TABLE IF NOT EXISTS annotations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id    INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    page_number INTEGER,
    text        TEXT NOT NULL DEFAULT '',
    idea        TEXT NOT NULL DEFAULT '',
    rects       TEXT NOT NULL DEFAULT '[]',
    color       TEXT NOT NULL DEFAULT 'yellow',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- The trash bin. A deleted paper leaves the library completely (its row and
-- everything pointing at it is gone), but its PDF file stays on disk: the
-- trash remembers where the file is, so the paper can be restored or the
-- file purged for good.
CREATE TABLE IF NOT EXISTS trash (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id       INTEGER NOT NULL,
    legacy_id      TEXT,
    title          TEXT NOT NULL,
    authors        TEXT NOT NULL DEFAULT '',
    year           INTEGER,
    source         TEXT NOT NULL DEFAULT 'pdf',
    file_path      TEXT,
    url            TEXT,
    abstract       TEXT NOT NULL DEFAULT '',
    remark         TEXT NOT NULL DEFAULT '',
    notes          TEXT NOT NULL DEFAULT '',
    importance     INTEGER NOT NULL DEFAULT 0,
    reading_status TEXT,
    is_read        INTEGER NOT NULL DEFAULT 0,
    progress       INTEGER NOT NULL DEFAULT 0,
    read_count     INTEGER NOT NULL DEFAULT 0,
    last_read_at   TEXT,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    deleted_at     TEXT NOT NULL DEFAULT (datetime('now')),
    size_bytes     INTEGER NOT NULL DEFAULT 0,
    tags           TEXT NOT NULL DEFAULT '[]',
    annotations    TEXT NOT NULL DEFAULT '[]',
    content_hash   TEXT
);

CREATE INDEX IF NOT EXISTS idx_papers_updated ON papers(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_annot_paper ON annotations(paper_id);
CREATE INDEX IF NOT EXISTS idx_pf_folder ON paper_folders(folder_id);
CREATE INDEX IF NOT EXISTS idx_pt_tag ON paper_tags(tag_id);
"""


#: The reading status readpaper uses for a paper that was read.
READ_STATUS = "READ"


def is_read_status(status: str | None) -> bool:
    """Whether a readpaper reading status means "read".

    readpaper has three states: READ, UNREAD and READING (still in
    progress). Only READ counts as read - the local field is a plain
    boolean, so READING comes in as "not read yet".
    """
    return (status or "").strip().upper() == READ_STATUS


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    # Wait instead of failing with "database is locked" when another
    # connection is writing (the server and the CLI can run side by side).
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    ensure_dirs()
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        _ensure_column(conn, "annotations", "rects", "TEXT NOT NULL DEFAULT '[]'")
        # The colour of a highlight. The column is only added: the rows that
        # are already there keep their meaning - they were drawn yellow.
        _ensure_column(conn, "annotations", "color", "TEXT NOT NULL DEFAULT 'yellow'")
        if _ensure_column(conn, "papers", "is_read", "INTEGER NOT NULL DEFAULT 0"):
            # One-time initialisation: seed 已读 from readpaper's own
            # reading status. Only the papers that were read there come
            # in as read; from then on the field and the importance are
            # completely independent. This only runs on a database that
            # predates the column - an existing one is never touched.
            conn.execute("UPDATE papers SET is_read = 1 WHERE reading_status = 'READ'")
        # Created after the column exists so old databases migrate cleanly.
        conn.execute("CREATE INDEX IF NOT EXISTS idx_papers_is_read ON papers(is_read)")
        # The hash of the file, so the same PDF cannot be uploaded twice.
        # The column only holds extra information - no row value changes.
        _ensure_column(conn, "papers", "content_hash", "TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_papers_hash ON papers(content_hash)")
        # The trash keeps the hash too, so a restored paper is found by the
        # duplicate check right away.
        _ensure_column(conn, "trash", "content_hash", "TEXT")
        conn.commit()


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> bool:
    """Add a column to an existing table when it is missing.

    Returns True when the column was actually added.
    """
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column in columns:
        return False
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    return True


def dict_rows(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


# --------------------------------------------------------------------------- #
# helpers shared by the routers
# --------------------------------------------------------------------------- #


def prune_empty_tags(conn: sqlite3.Connection, only: set[str] | None = None) -> list[str]:
    """Delete tags that no paper carries any more.

    A tag is derived data: without a paper it carries no information, so
    it goes away as soon as it loses its last paper. Returns the names
    that were removed.

    ``only`` limits the sweep to the given names - used by the importer,
    which only knows about the tags the export mentions. Tags the user
    made by hand are left alone even when nothing carries them yet.
    """
    wanted: list[str] | None = None
    if only is not None:
        wanted = sorted(name for name in only if name)
        if not wanted:
            return []

    def scope(alias: str) -> tuple[str, list[Any]]:
        if wanted is None:
            return "", []
        placeholders = ",".join("?" * len(wanted))
        return f" AND {alias}.name IN ({placeholders})", list(wanted)

    where, params = scope("t")
    names = [
        row["name"]
        for row in conn.execute(
            """SELECT t.name FROM tags t
               WHERE NOT EXISTS (SELECT 1 FROM paper_tags pt WHERE pt.tag_id = t.id)"""
            + where,
            params,
        )
    ]
    if names:
        # The same scope as the SELECT above: only the tags that were
        # picked are deleted.
        where, params = scope("tags")
        conn.execute(
            """DELETE FROM tags WHERE NOT EXISTS
               (SELECT 1 FROM paper_tags pt WHERE pt.tag_id = tags.id)"""
            + where,
            params,
        )
    return names


def tag_ids_for(conn: sqlite3.Connection, names: list[str]) -> list[int]:
    """The id of every named tag; a tag that does not exist yet is created."""
    result: list[int] = []
    for raw in names:
        name = str(raw).strip()
        if not name:
            continue
        row = conn.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()
        if row is None:
            cur = conn.execute("INSERT INTO tags (name) VALUES (?)", (name,))
            result.append(int(cur.lastrowid))
        else:
            result.append(int(row["id"]))
    return result


def set_tags(conn: sqlite3.Connection, paper_id: int, names: list[str]) -> None:
    """Replace the tags of a paper.

    A tag that just lost its last paper goes away with it. A tag that
    never had a paper (one that was only just created) stays: it is
    waiting to be used.
    """
    old_ids = [
        row["tag_id"]
        for row in conn.execute(
            "SELECT tag_id FROM paper_tags WHERE paper_id = ?", (paper_id,)
        ).fetchall()
    ]
    conn.execute("DELETE FROM paper_tags WHERE paper_id = ?", (paper_id,))
    new_ids = tag_ids_for(conn, names)
    for tag_id in new_ids:
        conn.execute(
            "INSERT OR IGNORE INTO paper_tags (paper_id, tag_id) VALUES (?, ?)", (paper_id, tag_id)
        )
    drop_orphan_tags(conn, [tag_id for tag_id in old_ids if tag_id not in new_ids])


def drop_orphan_tags(conn: sqlite3.Connection, tag_ids: list[int]) -> list[str]:
    """Delete the given tags when no paper carries them any more."""
    names: list[str] = []
    for tag_id in tag_ids:
        row = conn.execute(
            """SELECT t.name FROM tags t WHERE t.id = ?
               AND NOT EXISTS (SELECT 1 FROM paper_tags pt WHERE pt.tag_id = t.id)""",
            (tag_id,),
        ).fetchone()
        if row is None:
            continue
        names.append(row["name"])
        conn.execute("DELETE FROM tags WHERE id = ?", (tag_id,))
    return names


def folder_descendants(conn: sqlite3.Connection, folder_id: int) -> list[int]:
    """A folder plus all of its descendants."""
    result = [folder_id]
    queue = [folder_id]
    while queue:
        current = queue.pop()
        children = conn.execute(
            "SELECT id FROM folders WHERE parent_id = ?", (current,)
        ).fetchall()
        for child in children:
            if child["id"] not in result:
                result.append(child["id"])
                queue.append(child["id"])
    return result


def folder_tree(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM folders ORDER BY sort_order, name").fetchall()
    direct_counts = {
        row["folder_id"]: row["n"]
        for row in conn.execute(
            "SELECT folder_id, COUNT(*) AS n FROM paper_folders GROUP BY folder_id"
        ).fetchall()
    }
    nodes: dict[int, dict[str, Any]] = {
        row["id"]: {
            "id": row["id"],
            "name": row["name"],
            "color": row["color"],
            "parentId": row["parent_id"],
            "count": direct_counts.get(row["id"], 0),
            "ownCount": direct_counts.get(row["id"], 0),
            "children": [],
        }
        for row in rows
    }
    roots: list[dict[str, Any]] = []
    for node in nodes.values():
        parent = nodes.get(node["parentId"])
        if parent is not None:
            parent["children"].append(node)
        else:
            roots.append(node)

    # roll up descendant counts so a parent shows everything filed below it
    def rollup(node: dict[str, Any]) -> int:
        total = node["ownCount"]
        for child in node["children"]:
            total += rollup(child)
        node["count"] = total
        return total

    for root in roots:
        rollup(root)
    return roots


def resolve_pdf_path(file_path: str | None) -> Path | None:
    """Map a stored relative path to an absolute one on disk.

    Every PDF lives in the single store under ``PDF_ROOT/pdfs`` (see
    config), so the stored path is relative to that root. Only files
    inside the PDF store are reachable - the database next to it is not.
    """
    if not file_path:
        return None
    from .config import PDF_DIR, PDF_ROOT

    candidate = (PDF_ROOT / file_path).resolve()
    if PDF_DIR not in candidate.parents:
        return None
    return candidate
