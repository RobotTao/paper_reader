"""Uploading papers: the file, its hash and the duplicate check."""

from __future__ import annotations

from io import BytesIO

from app.config import PDF_DIR
from app.db import get_conn
from tests.conftest import pdf_bytes


def test_upload_stores_the_file_and_its_hash(client, upload):
    response = upload(marker="one", title="第一篇")

    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "第一篇"
    assert body["hasFile"] is True

    with get_conn() as conn:
        row = conn.execute("SELECT file_path, content_hash FROM papers WHERE id = ?", (body["id"],)).fetchone()
    assert row["file_path"].startswith("pdfs/")
    # The hash is the fingerprint of the file that was written.
    import hashlib

    assert row["content_hash"] == hashlib.sha256(pdf_bytes("one")).hexdigest()
    assert (PDF_DIR / row["file_path"].split("/")[-1]).exists()


def test_upload_without_a_file_is_rejected(client):
    response = client.post("/api/papers", data={"title": "只有标题"})

    assert response.status_code == 400
    assert "file" in response.json()["detail"]


def test_upload_of_a_link_without_a_file_is_rejected(client):
    response = client.post(
        "/api/papers", data={"title": "只有链接", "url": "https://arxiv.org/abs/1234"}
    )

    assert response.status_code == 400


def test_upload_twice_reports_the_paper_that_is_already_there(client, upload):
    first = upload(marker="same", title="重复的那篇")
    assert first.status_code == 201

    second = upload(marker="same", title="另一个名字")
    assert second.status_code == 409
    body = second.json()
    assert body["code"] == "duplicate"
    assert body["paper"]["id"] == first.json()["id"]
    assert body["paper"]["title"] == "重复的那篇"
    assert "重复的那篇" in body["detail"]


def test_a_duplicate_leaves_no_second_paper_and_no_second_file(client, upload):
    upload(marker="same", title="重复的那篇")

    upload(marker="same", title="再来一次")

    with get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM papers").fetchone()["n"] == 1
    assert len(list(PDF_DIR.glob("*.pdf"))) == 1


def test_the_duplicate_answer_carries_the_folders_of_the_existing_paper(client, upload):
    folder = client.post("/api/folders", json={"name": "点云"}).json()
    upload(marker="same", title="重复的那篇", folderIds=json_ids([folder["id"]]))

    body = upload(marker="same", title="再来一次").json()

    assert [f["name"] for f in body["paper"]["folders"]] == ["点云"]


def test_a_different_file_is_not_a_duplicate(client, upload):
    upload(marker="one", title="第一篇")

    assert upload(marker="two", title="第二篇").status_code == 201


def test_the_title_falls_back_to_the_file_name(client, upload):
    response = upload(marker="one", filename="Attention_Is_All_You_Need.pdf")

    assert response.json()["title"] == "Attention Is All You Need"


def test_the_file_keeps_its_extension(client, upload):
    response = upload(marker="one", filename="paper.PDF")

    with get_conn() as conn:
        row = conn.execute("SELECT file_path FROM papers WHERE id = ?", (response.json()["id"],)).fetchone()
    assert row["file_path"].endswith(".pdf")


def test_a_paper_can_be_uploaded_with_a_folder_and_tags(client, upload):
    folder = client.post("/api/folders", json={"name": "CV"}).json()

    response = upload(
        marker="one",
        title="带分类",
        folderIds=json_ids([folder["id"]]),
        tags=json_ids(["Transformer", "NLP"]),
    )

    body = response.json()
    assert [f["name"] for f in body["folders"]] == ["CV"]
    assert sorted(t["name"] for t in body["tags"]) == ["NLP", "Transformer"]


def test_the_upload_rejects_a_file_that_is_too_big(client, monkeypatch):
    monkeypatch.setattr("app.routers.papers.MAX_UPLOAD_MB", 0)

    response = client.post(
        "/api/papers",
        files={"file": ("big.pdf", BytesIO(pdf_bytes("big")), "application/pdf")},
    )

    assert response.status_code == 413
    # The file that was written on the way is gone again.
    assert not list(PDF_DIR.glob("*.pdf"))


def json_ids(values: list) -> str:
    import json

    return json.dumps(values)
