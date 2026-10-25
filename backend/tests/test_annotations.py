"""The highlights of a paper: making them, changing them, throwing them away."""

from __future__ import annotations


def test_a_highlight_keeps_its_colour_and_its_rectangles(client, upload):
    paper = upload(marker="one", title="第一篇").json()
    rects = [{"x": 10, "y": 20, "w": 100, "h": 12, "page": 1}]

    created = client.post(
        f"/api/papers/{paper['id']}/annotations",
        json={
            "pageNumber": 1,
            "text": "选中的那句",
            "idea": "值得一看",
            "rects": rects,
            "color": "red",
        },
    )
    assert created.status_code == 201
    assert created.json()["color"] == "red"

    body = client.get(f"/api/papers/{paper['id']}").json()
    assert len(body["annotations"]) == 1
    note = body["annotations"][0]
    assert note["color"] == "red"
    assert note["text"] == "选中的那句"
    assert note["idea"] == "值得一看"
    assert note["rects"] == rects


def test_a_highlight_is_yellow_when_nothing_else_is_said(client, upload):
    paper = upload(marker="one", title="第一篇").json()

    client.post(f"/api/papers/{paper['id']}/annotations", json={"text": "一句话"})

    note = client.get(f"/api/papers/{paper['id']}").json()["annotations"][0]
    assert note["color"] == "yellow"


def test_an_unknown_colour_is_refused(client, upload):
    paper = upload(marker="one", title="第一篇").json()

    answer = client.post(
        f"/api/papers/{paper['id']}/annotations", json={"text": "一句话", "color": "rainbow"}
    )

    assert answer.status_code == 400


def test_the_thought_next_to_a_highlight_can_be_changed(client, upload):
    paper = upload(marker="one", title="第一篇").json()
    note = client.post(
        f"/api/papers/{paper['id']}/annotations", json={"text": "一句话", "color": "green"}
    ).json()

    answer = client.patch(f"/api/annotations/{note['id']}", json={"idea": "后来想到的"})

    assert answer.status_code == 200
    assert answer.json()["idea"] == "后来想到的"
    # The colour is not touched when only the thought changes.
    assert answer.json()["color"] == "green"

    stored = client.get(f"/api/papers/{paper['id']}").json()["annotations"][0]
    assert stored["idea"] == "后来想到的"
    assert stored["color"] == "green"


def test_the_colour_of_a_highlight_can_be_changed(client, upload):
    paper = upload(marker="one", title="第一篇").json()
    note = client.post(
        f"/api/papers/{paper['id']}/annotations", json={"text": "一句话", "color": "yellow"}
    ).json()

    answer = client.patch(f"/api/annotations/{note['id']}", json={"color": "blue"})

    assert answer.status_code == 200
    stored = client.get(f"/api/papers/{paper['id']}").json()["annotations"][0]
    assert stored["color"] == "blue"


def test_a_changed_highlight_comes_back_whole(client, upload):
    """The answer holds the rectangles as a list, not as the text of JSON."""
    paper = upload(marker="one", title="第一篇").json()
    rects = [{"x": 10, "y": 20, "w": 100, "h": 12, "page": 1}]
    note = client.post(
        f"/api/papers/{paper['id']}/annotations",
        json={"text": "一句话", "color": "yellow", "rects": rects},
    ).json()

    answer = client.patch(f"/api/annotations/{note['id']}", json={"color": "orange"})

    assert answer.status_code == 200
    assert answer.json()["rects"] == rects
    assert answer.json()["color"] == "orange"


def test_a_highlight_can_be_thrown_away(client, upload):
    paper = upload(marker="one", title="第一篇").json()
    note = client.post(
        f"/api/papers/{paper['id']}/annotations", json={"text": "一句话"}
    ).json()

    assert client.delete(f"/api/annotations/{note['id']}").status_code == 200
    assert client.get(f"/api/papers/{paper['id']}").json()["annotations"] == []
