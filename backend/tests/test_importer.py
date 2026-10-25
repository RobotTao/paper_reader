"""Importing a readpaper export."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.config import PDF_ROOT
from app.db import get_conn
from app.importer import backfill_colors, import_readpaper
from tests.conftest import pdf_bytes


def write_export(tmp_path: Path, docs: list[dict]) -> Path:
    """A small export.

    The PDFs go into the library's own PDF store - that is how a readpaper
    export is laid out: the export's `pdfs/` directory *is* the library's
    store, so the import never copies a file.
    """
    for doc in docs:
        relative = doc.get("paperPdf", {}).get("attachment", {}).get("relativePath")
        if relative:
            target = PDF_ROOT / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(pdf_bytes(doc["id"]))
    path = tmp_path / "data.json"
    path.write_text(json.dumps({"docFolders": [], "classifys": [], "docs": docs}), encoding="utf-8")
    return path


def doc(doc_id: str, title: str, with_file: bool = True) -> dict:
    entry = {
        "id": doc_id,
        "docName": title,
        "paper": {"title": title},
        "displayAuthors": [{"literal": "Someone"}],
        "paperPdf": {"url": f"https://example.com/{doc_id}.pdf"},
    }
    if with_file:
        entry["paperPdf"]["attachment"] = {"relativePath": f"pdfs/42/{doc_id}.pdf"}
    return entry


def test_import_reads_the_documents(tmp_path):
    path = write_export(tmp_path, [doc("1", "第一篇"), doc("2", "第二篇")])

    stats = import_readpaper(path)

    assert stats["papers"] == 2
    with get_conn() as conn:
        titles = [row["title"] for row in conn.execute("SELECT title FROM papers")]
    assert sorted(titles) == ["第一篇", "第二篇"]


def test_import_skips_the_documents_without_a_file(tmp_path):
    path = write_export(
        tmp_path, [doc("1", "有文件"), doc("2", "只有链接", with_file=False)]
    )

    stats = import_readpaper(path)

    assert stats["papers"] == 1
    assert stats["no_file"] == 1
    with get_conn() as conn:
        rows = conn.execute("SELECT title FROM papers").fetchall()
    assert [row["title"] for row in rows] == ["有文件"]


def test_import_writes_the_hash_of_the_file(tmp_path):
    path = write_export(tmp_path, [doc("1", "第一篇")])

    import_readpaper(path)

    with get_conn() as conn:
        row = conn.execute("SELECT file_path, content_hash FROM papers").fetchone()
    assert row["content_hash"] == hashlib.sha256(pdf_bytes("1")).hexdigest()
    assert (PDF_ROOT / row["file_path"]).exists()


def test_import_twice_does_not_create_a_second_copy(tmp_path):
    path = write_export(tmp_path, [doc("1", "第一篇")])

    import_readpaper(path)
    stats = import_readpaper(path)

    assert stats["papers"] == 0
    assert stats["skipped"] == 1
    with get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM papers").fetchone()["n"] == 1


def test_the_read_state_comes_from_the_reading_status(tmp_path):
    docs = [
        {**doc("1", "读过的"), "readingStatus": "READ", "importanceScore": 0},
        {**doc("2", "没读的"), "readingStatus": "UNREAD", "importanceScore": 0},
        {**doc("3", "在读的"), "readingStatus": "READING", "importanceScore": 0},
        {**doc("4", "没写状态的")},
    ]
    path = write_export(tmp_path, docs)

    import_readpaper(path)

    with get_conn() as conn:
        rows = {
            row["title"]: row["is_read"]
            for row in conn.execute("SELECT title, is_read FROM papers")
        }
    assert rows == {"读过的": 1, "没读的": 0, "在读的": 0, "没写状态的": 0}


def test_the_importance_does_not_decide_the_read_state(tmp_path):
    # A 5-star paper that was never read in readpaper is not read here.
    path = write_export(
        tmp_path, [{**doc("1", "五星的"), "readingStatus": "UNREAD", "importanceScore": 5}]
    )

    import_readpaper(path)

    with get_conn() as conn:
        row = conn.execute("SELECT is_read, importance FROM papers").fetchone()
    assert row["importance"] == 5
    assert row["is_read"] == 0


def test_import_reads_the_folders_and_the_tags(tmp_path):
    path = tmp_path / "data.json"
    path.write_text(
        json.dumps(
            {
                "docFolders": [{"id": "f1", "name": "父分类"}, {"id": "f2", "name": "子分类", "parentId": "f1"}],
                "classifys": [{"id": "t1", "name": "Transformer"}],
                "docs": [
                    {
                        **doc("1", "第一篇"),
                        "folderRelations": [{"folderId": "f2"}],
                        "classifyRelations": [{"classifyId": "t1"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    pdfs = PDF_ROOT / "pdfs" / "42"
    pdfs.mkdir(parents=True, exist_ok=True)
    (pdfs / "1.pdf").write_bytes(pdf_bytes("1"))

    import_readpaper(path)

    with get_conn() as conn:
        folders = conn.execute("SELECT id, name, parent_id FROM folders ORDER BY id").fetchall()
        assert [f["name"] for f in folders] == ["父分类", "子分类"]
        assert folders[1]["parent_id"] == folders[0]["id"]
        assert conn.execute("SELECT COUNT(*) AS n FROM tags").fetchone()["n"] == 1
        assert conn.execute("SELECT COUNT(*) AS n FROM paper_folders").fetchone()["n"] == 1


def test_import_of_an_export_without_pdfs_imports_nothing(tmp_path):
    path = tmp_path / "data.json"
    path.write_text(json.dumps({"docs": [doc("1", "第一篇")]}), encoding="utf-8")

    stats = import_readpaper(path)

    assert stats["papers"] == 0
    assert stats["no_file"] == 1


def test_a_reset_wipes_the_library(tmp_path):
    path = write_export(tmp_path, [doc("1", "第一篇")])
    import_readpaper(path)

    import_readpaper(path, reset=True)

    with get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM papers").fetchone()["n"] == 1
        assert conn.execute("SELECT COUNT(*) AS n FROM folders").fetchone()["n"] == 0


def mark(text: str, style: int) -> dict:
    """A highlight in the export: a piece of text in a colour."""
    return {
        "styleId": style,
        "isHighlight": True,
        "select": {
            "rectStr": text,
            "rectangles": [{"pageNumber": 1, "x": 10, "y": 20, "width": 30, "height": 8}],
        },
    }


def test_the_highlights_keep_their_colour(tmp_path):
    path = write_export(
        tmp_path,
        [
            {
                **doc("1", "第一篇"),
                "note": {"marks": [mark("红的", 5), mark("绿的", 2), mark("黄的", 3)]},
            }
        ],
    )

    import_readpaper(path)

    with get_conn() as conn:
        rows = conn.execute("SELECT text, color FROM annotations ORDER BY id").fetchall()
    assert [(row["text"], row["color"]) for row in rows] == [
        ("红的", "red"),
        ("绿的", "green"),
        ("黄的", "yellow"),
    ]


def test_an_unknown_colour_becomes_yellow(tmp_path):
    path = write_export(
        tmp_path, [{**doc("1", "第一篇"), "note": {"marks": [mark("不知道", 99)]}}]
    )

    import_readpaper(path)

    with get_conn() as conn:
        row = conn.execute("SELECT color FROM annotations").fetchone()
    assert row["color"] == "yellow"


def test_the_colours_can_be_filled_in_afterwards(tmp_path):
    path = write_export(
        tmp_path, [{**doc("1", "第一篇"), "note": {"marks": [mark("红的", 5), mark("绿的", 2)]}}]
    )
    import_readpaper(path)
    # An import from before the colours were read leaves them all yellow.
    with get_conn() as conn:
        conn.execute("UPDATE annotations SET color = 'yellow'")
        conn.commit()

    stats = backfill_colors(path, dry_run=True)

    assert stats["changed"] == 2
    with get_conn() as conn:
        rows = conn.execute("SELECT color FROM annotations").fetchall()
    assert [row["color"] for row in rows] == ["yellow", "yellow"]

    stats = backfill_colors(path, dry_run=False)

    assert stats["changed"] == 2
    with get_conn() as conn:
        rows = conn.execute("SELECT color FROM annotations ORDER BY id").fetchall()
    assert [row["color"] for row in rows] == ["red", "green"]


def test_a_colour_picked_by_hand_is_left_alone(tmp_path):
    path = write_export(
        tmp_path, [{**doc("1", "第一篇"), "note": {"marks": [mark("红的", 5), mark("黄的", 3)]}}]
    )
    import_readpaper(path)
    with get_conn() as conn:
        # An import from before the colours were read leaves them all yellow;
        # the reader changed the second one to blue by hand.
        conn.execute("UPDATE annotations SET color = 'yellow'")
        conn.execute("UPDATE annotations SET color = 'blue' WHERE id = 2")
        conn.commit()

    stats = backfill_colors(path, dry_run=False)

    assert stats["changed"] == 1
    assert stats["kept"] == 1
    with get_conn() as conn:
        rows = conn.execute("SELECT color FROM annotations ORDER BY id").fetchall()
    assert [row["color"] for row in rows] == ["red", "blue"]


def test_a_reset_also_empties_the_trash(tmp_path):
    path = write_export(tmp_path, [doc("1", "第一篇")])
    import_readpaper(path)
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO trash (paper_id, title, created_at, updated_at) "
            "VALUES (?, ?, datetime('now'), datetime('now'))",
            (1, "旧垃圾"),
        )
        conn.commit()

    import_readpaper(path, reset=True)

    with get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM trash").fetchone()["n"] == 0
        assert conn.execute("SELECT COUNT(*) AS n FROM papers").fetchone()["n"] == 1

