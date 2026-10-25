"""Import a readpaper export (data.json + pdfs/ directory) into the library."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .db import get_conn, is_read_status, prune_empty_tags, resolve_pdf_path
from .hashes import sha256_file

YEAR_RE = re.compile(r"(\d{4})")

# The colour readpaper gives a highlight. It numbers its five styles from
# 1 to 5 and the numbers mean the same things as our colour names.
STYLE_COLORS = {1: "blue", 2: "green", 3: "yellow", 4: "orange", 5: "red"}


def style_color(mark: dict[str, Any]) -> str:
    """The colour of a readpaper mark, in our own names."""
    try:
        style = int(mark.get("styleId") or 0)
    except (TypeError, ValueError):
        return "yellow"
    return STYLE_COLORS.get(style, "yellow")


def file_digest(file_path: str | None) -> str | None:
    """The hash of the imported file, so duplicates can be found later.

    The file is the one the export points at; it is read once here, while
    the import runs. None when there is no file or when it is not on disk:
    such a paper has no hash, so it does not come into the library.
    """
    if not file_path:
        return None
    path = resolve_pdf_path(file_path)
    if path is None or not path.exists():
        return None
    return sha256_file(path)


def to_sql_date(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def author_string(doc: dict[str, Any]) -> str:
    paper = doc.get("paper") or {}
    authors = doc.get("displayAuthors") or doc.get("metaAuthors") or paper.get("authors") or []
    names = []
    for author in authors:
        if isinstance(author, dict):
            name = author.get("literal") or " ".join(
                part for part in (author.get("given"), author.get("family")) if part
            )
        else:
            name = str(author)
        if name:
            names.append(name)
    return ", ".join(names)


def extract_year(doc: dict[str, Any]) -> int | None:
    paper = doc.get("paper") or {}
    candidates = [
        doc.get("userEditedPublishDate"),
        doc.get("metaPublishDate"),
        doc.get("displayPublishDate"),
        doc.get("publishDate"),
        paper.get("publishDate"),
    ]
    for value in candidates:
        if not value:
            continue
        match = YEAR_RE.search(str(value))
        if match:
            return int(match.group(1))
    return None


def import_readpaper(data_path: Path, reset: bool = False) -> dict[str, int]:
    """Populate the database from a readpaper export file."""
    data = json.loads(Path(data_path).read_text(encoding="utf-8"))

    stats = {"folders": 0, "tags": 0, "papers": 0, "annotations": 0, "skipped": 0, "no_file": 0}

    with get_conn() as conn:
        if reset:
            conn.executescript(
                "DELETE FROM annotations; DELETE FROM paper_tags; DELETE FROM paper_folders;"
                "DELETE FROM papers; DELETE FROM tags; DELETE FROM folders; DELETE FROM trash;"
                "DELETE FROM sqlite_sequence WHERE name IN ('papers','folders','tags','annotations','trash');"
            )

        folders = data.get("docFolders") or []
        legacy_to_id: dict[str, int] = {}
        for folder in folders:
            legacy_id = str(folder.get("id"))
            cur = conn.execute(
                "INSERT OR IGNORE INTO folders (legacy_id, parent_id, name, color, sort_order) "
                "VALUES (?, NULL, ?, ?, ?)",
                (
                    legacy_id,
                    folder.get("name") or "未命名",
                    folder.get("color") or "#3b71ca",
                    int(folder.get("sort") or 0),
                ),
            )
            if cur.rowcount:
                stats["folders"] += 1
            # Re-importing must not fail on the unique legacy_id, so resolve
            # the row by legacy_id instead of trusting lastrowid.
            row = conn.execute(
                "SELECT id FROM folders WHERE legacy_id = ?", (legacy_id,)
            ).fetchone()
            if row is None:
                continue
            legacy_to_id[legacy_id] = int(row["id"])

        for folder in folders:
            parent_id = folder.get("parentId")
            parent = legacy_to_id.get(str(parent_id)) if parent_id and parent_id != "0" else None
            if parent:
                conn.execute(
                    "UPDATE folders SET parent_id = ? WHERE id = ?",
                    (parent, legacy_to_id[str(folder.get("id"))]),
                )

        for classify in data.get("classifys") or []:
            conn.execute(
                "INSERT OR IGNORE INTO tags (legacy_id, name, sort_order) VALUES (?, ?, ?)",
                (
                    str(classify.get("id")),
                    classify.get("name") or "未命名",
                    int(classify.get("sort") or 0),
                ),
            )
        stats["tags"] = conn.execute("SELECT COUNT(*) AS n FROM tags").fetchone()["n"]

        classify_names = {
            str(c.get("id")): c.get("name") for c in (data.get("classifys") or [])
        }
        tag_id_by_name = {
            row["name"]: int(row["id"])
            for row in conn.execute("SELECT id, name FROM tags").fetchall()
        }

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        for doc in data.get("docs") or []:
            paper = doc.get("paper") or {}
            attachment = (doc.get("paperPdf") or {}).get("attachment") or {}
            title = (doc.get("docName") or doc.get("paperTitle") or paper.get("title") or "Untitled").strip()
            notes = ((doc.get("note") or {}).get("summary") or {}).get("content") or ""
            file_path = attachment.get("relativePath")
            # Every paper has a file, so every paper has a hash, and the
            # duplicate check works on hashes. A record without a file on
            # disk cannot be read either, so it does not come in.
            digest = file_digest(file_path)
            if digest is None:
                stats["no_file"] += 1
                continue

            cur = conn.execute(
                """INSERT OR IGNORE INTO papers
                   (legacy_id, title, authors, year, source, file_path, url, abstract, remark, notes,
                    importance, reading_status, is_read, progress, read_count, last_read_at,
                    created_at, updated_at, content_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(doc.get("id")),
                    title,
                    author_string(doc),
                    extract_year(doc),
                    "pdf",
                    file_path,
                    (doc.get("paperPdf") or {}).get("url"),
                    paper.get("abstract") or "",
                    doc.get("remark") or "",
                    notes,
                    int(doc.get("importanceScore") or 0),
                    doc.get("readingStatus"),
                    # The initial value comes from readpaper's own reading
                    # status: a paper that was read there comes in as read.
                    # "READING" (still in progress) is not read yet - the
                    # local field is a plain boolean. After this the field
                    # and the importance are completely independent.
                    1 if is_read_status(doc.get("readingStatus")) else 0,
                    int(doc.get("progress") or 0),
                    1 if doc.get("lastReadTime") else 0,
                    to_sql_date(doc.get("lastReadTime")),
                    to_sql_date(doc.get("createdAt")) or now,
                    to_sql_date(doc.get("updatedAt")) or now,
                    digest,
                ),
            )
            # `INSERT OR IGNORE` keeps the previous lastrowid when the row
            # already exists, so rowcount is the only reliable "was it
            # inserted" signal.
            if not cur.rowcount:
                stats["skipped"] += 1
                continue
            paper_id = int(cur.lastrowid)
            stats["papers"] += 1

            for relation in doc.get("folderRelations") or []:
                folder_id = legacy_to_id.get(str(relation.get("folderId")))
                if folder_id:
                    conn.execute(
                        "INSERT OR IGNORE INTO paper_folders (paper_id, folder_id) VALUES (?, ?)",
                        (paper_id, folder_id),
                    )

            for relation in doc.get("classifyRelations") or []:
                name = classify_names.get(str(relation.get("classifyId")))
                tag_id = tag_id_by_name.get(name) if name else None
                if tag_id:
                    conn.execute(
                        "INSERT OR IGNORE INTO paper_tags (paper_id, tag_id) VALUES (?, ?)",
                        (paper_id, tag_id),
                    )

            for mark in (doc.get("note") or {}).get("marks") or []:
                select = mark.get("select") or {}
                text = select.get("rectStr") or mark.get("text") or ""
                idea = mark.get("idea") or ""
                rectangles = select.get("rectangles") or []
                page = rectangles[0].get("pageNumber") if rectangles else mark.get("pageNumber")
                if not text and not idea:
                    continue
                rects = [
                    {
                        "x": rect.get("x"),
                        "y": rect.get("y"),
                        "w": rect.get("width"),
                        "h": rect.get("height"),
                        "page": rect.get("pageNumber"),
                    }
                    for rect in rectangles
                    if rect.get("x") is not None and rect.get("width")
                ]
                conn.execute(
                    "INSERT INTO annotations (paper_id, page_number, text, idea, rects, color) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (paper_id, page, text, idea, json.dumps(rects), style_color(mark)),
                )
                stats["annotations"] += 1

        # Tags nobody uses carry no information - the export contains a few
        # of those, so they don't come back into the library. Only the tags
        # the export mentions are swept: a tag the user made by hand is not
        # the export's business.
        removed = prune_empty_tags(conn, set(classify_names.values()))
        if removed:
            stats["empty_tags"] = len(removed)

        conn.commit()

    return stats


def _mark_key(mark: dict[str, Any]) -> tuple[Any, str]:
    """What a mark is recognised by: the page it sits on and its text."""
    select = mark.get("select") or {}
    rectangles = select.get("rectangles") or []
    page = rectangles[0].get("pageNumber") if rectangles else mark.get("pageNumber")
    text = select.get("rectStr") or mark.get("text") or ""
    return (page, text)


def _row_key(row: Any) -> tuple[Any, str]:
    return (row["page_number"], row["text"] or "")


def _match_marks(rows: list[Any], marks: list[dict[str, Any]]) -> list[tuple[Any, dict]]:
    """Put every annotation row next to the readpaper mark it came from.

    The mark is found by the page and the text it has; the text of a
    highlight is what the reader picked, so the pair is unique unless the
    same sentence was picked twice on the same page - then the marks are
    used up one by one.
    """
    by_key: dict[tuple[Any, str], list[int]] = {}
    for index, mark in enumerate(marks):
        by_key.setdefault(_mark_key(mark), []).append(index)

    used: set[int] = set()
    pairs: list[tuple[Any, dict]] = []
    left_over: list[Any] = []
    for row in rows:
        index = None
        for candidate in by_key.get(_row_key(row), []):
            if candidate not in used:
                index = candidate
                break
        if index is None:
            left_over.append(row)
        else:
            used.add(index)
            pairs.append((row, marks[index]))

    # Rows the text does not match (the reader edited one of them) are only
    # paired when exactly as many marks are left as there are rows - then
    # the order of both sides is the order they came in.
    rest = [i for i in range(len(marks)) if i not in used]
    if rest and len(rest) == len(left_over):
        for index, row in zip(rest, left_over):
            pairs.append((row, marks[index]))
    return pairs


def backfill_colors(data_path: Path, dry_run: bool = True) -> dict[str, Any]:
    """Give the imported highlights the colour they have in readpaper.

    The import took the text and the place of every mark but left its
    colour behind, so all of them came in yellow. The colour is in the
    export as `styleId`; this finds the mark behind every annotation and
    writes its colour down.

    A colour the reader picked by hand is left alone: only the yellow the
    import gave is written over.
    """
    data = json.loads(Path(data_path).read_text(encoding="utf-8"))

    marks_by_doc: dict[str, list[dict[str, Any]]] = {}
    for doc in data.get("docs") or []:
        marks = []
        for mark in (doc.get("note") or {}).get("marks") or []:
            select = mark.get("select") or {}
            text = select.get("rectStr") or mark.get("text") or ""
            idea = mark.get("idea") or ""
            if not text and not idea:
                continue
            marks.append(mark)
        marks_by_doc[str(doc.get("id"))] = marks

    stats = {
        "papers": 0,
        "annotations": 0,
        "changed": 0,
        "same": 0,
        "kept": 0,
        "unmatched": 0,
    }
    with get_conn() as conn:
        papers = conn.execute(
            "SELECT id, legacy_id FROM papers "
            "WHERE legacy_id IS NOT NULL AND legacy_id != ''"
        ).fetchall()
        for paper in papers:
            marks = marks_by_doc.get(paper["legacy_id"])
            if not marks:
                continue
            rows = conn.execute(
                "SELECT id, page_number, text, color FROM annotations "
                "WHERE paper_id = ? ORDER BY id",
                (paper["id"],),
            ).fetchall()
            if not rows:
                continue
            stats["papers"] += 1
            stats["annotations"] += len(rows)
            pairs = _match_marks(rows, marks)
            for row, mark in pairs:
                color = style_color(mark)
                current = row["color"] or "yellow"
                if color == current:
                    stats["same"] += 1
                    continue
                if current != "yellow":
                    # The reader chose this colour by hand - it is not the
                    # one the import gave, so it is not ours to change.
                    stats["kept"] += 1
                    continue
                if not dry_run:
                    conn.execute(
                        "UPDATE annotations SET color = ? WHERE id = ?", (color, row["id"])
                    )
                stats["changed"] += 1
            stats["unmatched"] += len(rows) - len(pairs)
        if not dry_run:
            conn.commit()

    return stats

