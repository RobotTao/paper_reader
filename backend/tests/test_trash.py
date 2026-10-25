"""The trash bin: delete, restore, purge."""

from __future__ import annotations

import json

from app.config import PDF_DIR
from app.db import get_conn


def uploaded_files() -> list:
    return sorted(PDF_DIR.glob("*.pdf"))


def test_delete_moves_the_paper_into_the_trash(client, upload):
    paper = upload(marker="one", title="要删掉的那篇").json()

    response = client.delete(f"/api/papers/{paper['id']}")

    assert response.status_code == 200
    with get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM papers").fetchone()["n"] == 0
        entry = conn.execute("SELECT title FROM trash").fetchone()
    assert entry["title"] == "要删掉的那篇"


def test_deleting_keeps_the_file_on_disk(client, upload):
    paper = upload(marker="one", title="要删掉的那篇").json()
    before = uploaded_files()

    client.delete(f"/api/papers/{paper['id']}")

    assert uploaded_files() == before


def test_restore_brings_the_paper_back_with_its_hash(client, upload):
    paper = upload(marker="one", title="要删掉的那篇").json()
    with get_conn() as conn:
        digest = conn.execute(
            "SELECT content_hash FROM papers WHERE id = ?", (paper["id"],)
        ).fetchone()["content_hash"]
    client.delete(f"/api/papers/{paper['id']}")

    trash = client.get("/api/trash").json()["items"]
    response = client.post(f"/api/trash/{trash[0]['id']}/restore")

    assert response.status_code == 200
    with get_conn() as conn:
        row = conn.execute(
            "SELECT title, content_hash FROM papers WHERE id = ?", (paper["id"],)
        ).fetchone()
    assert row["title"] == "要删掉的那篇"
    # The hash survives the round trip, so the paper is found by the
    # duplicate check right away.
    assert row["content_hash"] == digest


def test_restore_brings_the_tags_and_the_annotations_back(client, upload):
    paper = upload(marker="one", title="要删掉的那篇", tags=json.dumps(["NLP"])).json()
    client.post(
        f"/api/papers/{paper['id']}/annotations",
        json={"pageNumber": 1, "text": "一段高亮", "idea": ""},
    )
    client.delete(f"/api/papers/{paper['id']}")
    trash = client.get("/api/trash").json()["items"]

    client.post(f"/api/trash/{trash[0]['id']}/restore")

    with get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM paper_tags").fetchone()["n"] == 1
        assert conn.execute("SELECT COUNT(*) AS n FROM annotations").fetchone()["n"] == 1


def test_a_restored_paper_comes_back_without_a_folder(client, upload):
    folder = client.post("/api/folders", json={"name": "点云"}).json()
    paper = upload(
        marker="one", title="要删掉的那篇", folderIds=json.dumps([folder["id"]])
    ).json()
    client.delete(f"/api/papers/{paper['id']}")
    trash = client.get("/api/trash").json()["items"]

    client.post(f"/api/trash/{trash[0]['id']}/restore")

    body = client.get(f"/api/papers/{paper['id']}").json()
    assert body["folders"] == []


def test_purge_removes_the_file_and_the_entry(client, upload):
    paper = upload(marker="one", title="要删掉的那篇").json()
    client.delete(f"/api/papers/{paper['id']}")
    trash = client.get("/api/trash").json()["items"]

    response = client.delete(f"/api/trash/{trash[0]['id']}")

    assert response.status_code == 200
    assert uploaded_files() == []
    assert client.get("/api/trash").json()["items"] == []


def test_purge_of_a_paper_without_a_file_works(client, upload):
    # A paper whose file is gone from the disk: it must still be removable.
    paper = upload(marker="one", title="文件不见了").json()
    for path in uploaded_files():
        path.unlink()
    client.delete(f"/api/papers/{paper['id']}")
    trash = client.get("/api/trash").json()["items"]

    response = client.delete(f"/api/trash/{trash[0]['id']}")

    assert response.status_code == 200
    assert client.get("/api/trash").json()["items"] == []


def test_emptying_the_trash_removes_everything(client, upload):
    upload(marker="one", title="第一篇")
    upload(marker="two", title="第二篇")
    for paper in client.get("/api/papers").json()["items"]:
        client.delete(f"/api/papers/{paper['id']}")

    response = client.post("/api/trash/empty")

    assert response.status_code == 200
    assert client.get("/api/trash").json()["items"] == []
    assert uploaded_files() == []


def test_restore_is_refused_when_the_file_was_uploaded_again(client, upload):
    paper = upload(marker="same", title="要删掉的那篇").json()
    client.delete(f"/api/papers/{paper['id']}")

    # The very same file was added again while the paper was in the trash:
    # it is back in the library under a new id. Restoring the old entry must
    # not create a second copy of the file, so it is refused as a duplicate.
    upload(marker="same", title="重新上传的那篇")
    trash = client.get("/api/trash").json()["items"]

    response = client.post(f"/api/trash/{trash[0]['id']}/restore")

    assert response.status_code == 409
    assert "已经在库里" in response.json()["detail"]
    with get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM papers").fetchone()["n"] == 1
        # The entry stays in the trash: it was not silently dropped.
        assert conn.execute("SELECT COUNT(*) AS n FROM trash").fetchone()["n"] == 1
