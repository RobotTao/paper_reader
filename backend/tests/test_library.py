"""The library: the folder tree, the tags and the list of papers."""

from __future__ import annotations

import json

from app.db import get_conn


def folder(client, name: str, parent: int | None = None) -> dict:
    return client.post("/api/folders", json={"name": name, "parentId": parent}).json()


def test_the_folder_tree_nests(client):
    parent = folder(client, "CV")
    child = folder(client, "点云", parent["id"])

    tree = client.get("/api/folders").json()

    assert len(tree) == 1
    assert tree[0]["name"] == "CV"
    assert tree[0]["children"][0]["name"] == "点云"
    assert tree[0]["children"][0]["id"] == child["id"]


def test_a_parent_counts_the_papers_of_its_children(client, upload):
    parent = folder(client, "CV")
    child = folder(client, "点云", parent["id"])
    upload(marker="one", title="在子分类里", folderIds=json.dumps([child["id"]]))

    tree = client.get("/api/folders").json()

    assert tree[0]["count"] == 1
    assert tree[0]["ownCount"] == 0
    assert tree[0]["children"][0]["count"] == 1


def test_a_paper_can_be_in_several_folders(client, upload):
    first = folder(client, "CV")
    second = folder(client, "SLAM")
    upload(marker="one", title="两处都有", folderIds=json.dumps([first["id"], second["id"]]))

    tree = client.get("/api/folders").json()

    assert tree[0]["count"] == 1
    assert tree[1]["count"] == 1


def test_deleting_a_folder_keeps_the_papers_that_another_folder_holds(client, upload):
    first = folder(client, "CV")
    second = folder(client, "SLAM")
    paper = upload(
        marker="one", title="两处都有", folderIds=json.dumps([first["id"], second["id"]])
    ).json()

    response = client.delete(f"/api/folders/{first['id']}")

    assert response.status_code == 200
    assert response.json()["trashedPapers"] == []
    assert client.get(f"/api/papers/{paper['id']}").status_code == 200


def test_deleting_a_folder_moves_its_own_papers_to_the_trash(client, upload):
    only = folder(client, "只有它")
    paper = upload(marker="one", title="只在这里", folderIds=json.dumps([only["id"]])).json()

    response = client.delete(f"/api/folders/{only['id']}")

    assert response.status_code == 200
    assert response.json()["trashedPapers"] == [
        {"id": paper["id"], "title": "只在这里"}
    ]
    assert client.get(f"/api/papers/{paper['id']}").status_code == 404
    assert client.get("/api/trash").json()["items"][0]["title"] == "只在这里"


def test_a_tag_that_loses_its_last_paper_goes_away(client, upload):
    paper = upload(marker="one", title="带标签", tags=json.dumps(["临时标签"])).json()

    client.patch(f"/api/papers/{paper['id']}", json={"tags": []})

    assert client.get("/api/tags").json() == []


def test_a_new_tag_without_a_paper_stays(client):
    client.post("/api/tags", json={"name": "刚建的"})

    tags = client.get("/api/tags").json()

    assert [tag["name"] for tag in tags] == ["刚建的"]
    assert tags[0]["count"] == 0


def test_creating_the_same_tag_twice_gives_the_same_tag(client):
    first = client.post("/api/tags", json={"name": "NLP"}).json()
    second = client.post("/api/tags", json={"name": "NLP"}).json()

    assert first["id"] == second["id"]
    assert len(client.get("/api/tags").json()) == 1


def test_the_list_can_be_searched(client, upload):
    upload(marker="one", title="Point-to-Point ICP")
    upload(marker="two", title="完全不同的标题")

    body = client.get("/api/papers", params={"q": "ICP"}).json()

    assert body["total"] == 1
    assert body["items"][0]["title"] == "Point-to-Point ICP"


def test_the_list_can_be_filtered_by_folder(client, upload):
    cv = folder(client, "CV")
    upload(marker="one", title="在 CV 里", folderIds=json.dumps([cv["id"]]))
    upload(marker="two", title="没有分类")

    body = client.get("/api/papers", params={"folder": cv["id"]}).json()
    assert [item["title"] for item in body["items"]] == ["在 CV 里"]

    body = client.get("/api/papers", params={"folder": "unfiled"}).json()
    assert [item["title"] for item in body["items"]] == ["没有分类"]


def test_a_folder_filter_includes_the_sub_folders(client, upload):
    parent = folder(client, "CV")
    child = folder(client, "点云", parent["id"])
    upload(marker="one", title="在子分类里", folderIds=json.dumps([child["id"]]))

    body = client.get("/api/papers", params={"folder": parent["id"]}).json()

    assert body["total"] == 1


def test_the_list_can_be_filtered_by_tag_and_by_importance(client, upload):
    upload(marker="one", title="重要且有标签", tags=json.dumps(["NLP"]), importance=5)
    upload(marker="two", title="不重要")

    assert client.get("/api/papers", params={"tag": "NLP"}).json()["total"] == 1
    assert client.get("/api/papers", params={"importance": 4}).json()["total"] == 1
    # "importance ≥ n" only shows the papers with at least n stars, so the
    # paper without a star is left out.
    assert client.get("/api/papers", params={"importance": 1}).json()["total"] == 1


def test_the_read_counts_follow_the_current_view(client, upload):
    paper = upload(marker="one", title="已读的那篇").json()
    upload(marker="two", title="没读的那篇")
    client.patch(f"/api/papers/{paper['id']}", json={"isRead": True})

    body = client.get("/api/papers").json()

    assert body["readCount"] == 1
    assert body["unreadCount"] == 1


def test_the_read_counts_ignore_the_read_filter_itself(client, upload):
    paper = upload(marker="one", title="已读的那篇").json()
    upload(marker="two", title="没读的那篇")
    client.patch(f"/api/papers/{paper['id']}", json={"isRead": True})

    body = client.get("/api/papers", params={"read": "unread"}).json()

    assert body["total"] == 1
    assert body["readCount"] == 1
    assert body["unreadCount"] == 1


def test_the_list_is_sorted(client, upload):
    upload(marker="one", title="B 论文")
    upload(marker="two", title="A 论文")

    body = client.get("/api/papers", params={"sort": "title", "order": "asc"}).json()

    assert [item["title"] for item in body["items"]] == ["A 论文", "B 论文"]


def test_the_list_is_paged(client, upload):
    for index in range(5):
        upload(marker=f"p{index}", title=f"论文 {index}")

    body = client.get("/api/papers", params={"limit": 2, "offset": 2}).json()

    assert body["total"] == 5
    assert len(body["items"]) == 2
    assert body["limit"] == 2
    assert body["offset"] == 2


def test_a_paper_can_be_renamed_and_annotated(client, upload):
    paper = upload(marker="one", title="原来的名字").json()

    client.patch(f"/api/papers/{paper['id']}", json={"title": "新的名字", "importance": 3})
    client.post(
        f"/api/papers/{paper['id']}/annotations",
        json={"pageNumber": 2, "text": "高亮", "idea": "想法"},
    )

    body = client.get(f"/api/papers/{paper['id']}").json()
    assert body["title"] == "新的名字"
    assert body["importance"] == 3
    assert len(body["annotations"]) == 1


def test_the_stats_count_everything(client, upload):
    folder(client, "CV")
    upload(marker="one", title="第一篇", tags=json.dumps(["NLP"]))

    body = client.get("/api/stats").json()

    assert body["total"] == 1
    assert body["unfiled"] == 1
    assert body["withFile"] == 1
    assert body["read"] == 0
    assert body["unread"] == 1


def test_a_paper_without_a_folder_is_counted_as_unfiled(client, upload):
    upload(marker="one", title="没有分类")

    with get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM paper_folders").fetchone()["n"] == 0
