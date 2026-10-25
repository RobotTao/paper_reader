"""Take the screenshots that go into the README.

The pictures are made of a library that is invented for the occasion: a
throw-away directory, a server of its own, a browser of its own. The real
library in ``local_data/`` is never touched, and none of the titles below
belong to a real paper.

    make screenshots

The pictures land in ``docs/screenshots/``.
"""

from __future__ import annotations

import asyncio
import base64
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "tests" / "e2e"))

from harness import (  # the path above has to be set first
    Browser,
    Server,
    api_json,
    chrome_available,
    drop_root,
    free_port,
    make_root,
    upload_pdf,
)

SHOTS = ROOT / "docs" / "screenshots"


# --------------------------------------------------------------------------- #
# the library of the pictures
# --------------------------------------------------------------------------- #

#: The folders of the demo library: name, parent (None for a top folder).
FOLDERS = [
    ("计算机视觉", None),
    ("目标检测", "计算机视觉"),
    ("深度估计", "计算机视觉"),
    ("SLAM", None),
    ("点云配准", "SLAM"),
    ("机器人", None),
]

#: The papers of the demo library: title, authors, year, folder, tags,
#: remark, importance, read.
PAPERS = [
    (
        "Iterative Closest Point Revisited: A Practical Review",
        "A. Researcher, B. Scholar",
        2021,
        "点云配准",
        ["综述", "SLAM"],
        "第三章的实验可以直接复用",
        3,
        True,
    ),
    (
        "Deep Multi-View Stereo with Learned Cost Volumes",
        "C. Writer, D. Author",
        2022,
        "深度估计",
        ["深度学习", "MVS"],
        "",
        2,
        False,
    ),
    (
        "Tightly-Coupled Lidar-Inertial Odometry on the Move",
        "E. Engineer, F. Scientist",
        2020,
        "SLAM",
        ["里程计", "开源"],
        "开源代码很干净，值得跑一遍",
        4,
        True,
    ),
    (
        "Neural Radiance Fields for Scene Reconstruction",
        "G. Fellow, H. Researcher",
        2023,
        "计算机视觉",
        ["渲染", "深度学习"],
        "",
        3,
        False,
    ),
    (
        "Robust Dense Metric-Semantic SLAM in Urban Scenes",
        "I. Author, J. Scholar, K. Scientist",
        2022,
        "SLAM",
        ["SLAM"],
        "",
        2,
        False,
    ),
    (
        "A Survey of 3D Object Detection for Autonomous Driving",
        "L. Writer, M. Author",
        2021,
        "目标检测",
        ["综述", "点云"],
        "综述，用来补背景",
        3,
        True,
    ),
    (
        "Fast Direct LiDAR-Inertial Odometry with Incremental Kernels",
        "N. Researcher, O. Engineer",
        2023,
        "SLAM",
        ["里程计"],
        "",
        1,
        False,
    ),
    (
        "Shape from Shading: A Survey",
        "P. Scholar, Q. Author",
        2019,
        "深度估计",
        ["综述"],
        "",
        2,
        False,
    ),
    (
        "Bundle Adjustment: Modern Extensions and Practice",
        "R. Scientist, S. Writer",
        2020,
        "机器人",
        ["优化"],
        "重定位的底层就是它",
        4,
        True,
    ),
    (
        "End-to-End Point Cloud Detection for Autonomous Driving",
        "T. Author, U. Researcher, V. Fellow",
        2022,
        "目标检测",
        ["点云", "深度学习"],
        "",
        2,
        False,
    ),
]

#: The body of the paper that is read in the pictures.
PAPER_LINES = [
    "Abstract",
    "Accurate and robust odometry is a prerequisite for autonomous navigation.",
    "We present a tightly-coupled framework that fuses lidar measurements",
    "and inertial readings in a single optimization problem, so that the",
    "motion of the sensor can be recovered even when the scan is degraded.",
    "",
    "1. Introduction",
    "Mapping and localization have been studied for decades, and the",
    "classic approaches still form the backbone of most systems in use.",
    "However, the assumption of a static environment breaks down as soon",
    "as the robot moves through a crowd of people or a narrow corridor.",
    "",
    "2. Method",
    "Our system keeps the states of all previous frames in a sliding",
    "window and re-linearizes them whenever a new scan arrives. The",
    "residual of every point is expressed in the frame of the sensor at",
    "the moment it was measured, which keeps the Jacobians small and",
    "the optimization well behaved even over long trajectories.",
    "",
    "3. Experiments",
    "We evaluate the method on a public benchmark of urban sequences and",
    "compare it against a set of well known systems. The results show a",
    "consistent improvement in accuracy, in particular in the segments",
    "where the lidar sees very little of the environment.",
]


def paper_pdf(title: str, lines: list[str]) -> bytes:
    """A page of text - enough for the reader to show and to select."""
    parts = [b"BT /F1 16 Tf 72 706 Td (" + _pdf_text(title) + b") Tj ET"]
    y = 660
    for line in lines:
        if line:
            parts.append(
                b"BT /F1 11 Tf 72 " + str(y).encode() + b" Td (" + _pdf_text(line) + b") Tj ET"
            )
        y -= 19
    content = b"\n".join(parts)
    return (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]"
        b"/Resources<</Font<</F1 4 0 R>>>>/Contents 5 0 R>>endobj\n"
        b"4 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
        b"5 0 obj<</Length "
        + str(len(content)).encode()
        + b">>stream\n"
        + content
        + b"\nendstream\nendobj\n"
        b"trailer<</Root 1 0 R/Size 6>>\n"
        b"%%EOF\n"
    )


def _pdf_text(text: str) -> bytes:
    """Text as the simple font of a PDF wants it."""
    out = text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
    return out.encode("latin-1", "replace")


# --------------------------------------------------------------------------- #
# the pictures
# --------------------------------------------------------------------------- #


async def shoot(tab, name: str, height: int | None = None) -> None:
    """Save what is on the screen as a PNG.

    ``height`` cuts the picture off at that height, so a page that is
    mostly empty does not leave a big blank area in the README.
    """
    params: dict = {"format": "png"}
    if height:
        params["clip"] = {"x": 0, "y": 0, "width": 1440, "height": height, "scale": 1}
    result = await tab.send("Page.captureScreenshot", params)
    path = SHOTS / f"{name}.png"
    path.write_bytes(base64.b64decode(result["result"]["data"]))
    print(f"  -> {path.relative_to(ROOT)}")


async def drag_over(tab, x1: float, y1: float, x2: float, y2: float) -> None:
    """Drag the mouse over the page - the real thing, not a fake event."""
    await tab.send(
        "Input.dispatchMouseEvent",
        {
            "type": "mousePressed",
            "x": x1,
            "y": y1,
            "button": "left",
            "buttons": 1,
            "clickCount": 1,
        },
    )
    for step in range(1, 9):
        await tab.send(
            "Input.dispatchMouseEvent",
            {
                "type": "mouseMoved",
                "x": x1 + (x2 - x1) * step / 8,
                "y": y1 + (y2 - y1) * step / 8,
                "button": "left",
                "buttons": 1,
            },
        )
        await asyncio.sleep(0.04)
    await tab.send(
        "Input.dispatchMouseEvent",
        {
            "type": "mouseReleased",
            "x": x2,
            "y": y2,
            "button": "left",
            "buttons": 0,
            "clickCount": 1,
        },
    )
    await asyncio.sleep(0.9)


async def click_at(tab, x: float, y: float) -> None:
    """A click with the mouse."""
    for kind, buttons in (("mousePressed", 1), ("mouseReleased", 0)):
        await tab.send(
            "Input.dispatchMouseEvent",
            {
                "type": kind,
                "x": x,
                "y": y,
                "button": "left",
                "buttons": buttons,
                "clickCount": 1,
            },
        )


async def line_box(tab, index: int) -> dict:
    """Where a line of the text sits on the screen."""
    return await tab.js(
        "(() => { const spans = [...document.querySelectorAll('.pdf-page .textLayer span')];"
        f" const s = spans[{index}].getBoundingClientRect();"
        " return {x1: s.left + 2, y: s.top + s.height / 2, x2: s.right - 2}; })()"
    )


async def build_library(url: str, root: Path) -> dict:
    """The demo library: folders, tags and papers."""
    ids: dict[str, int] = {}
    for name, parent in FOLDERS:
        body = {"name": name}
        if parent:
            body["parentId"] = ids[parent]
        ids[name] = api_json(url, "/api/folders", body)["id"]
    for tag in ["综述", "深度学习", "SLAM", "里程计", "点云", "渲染", "开源", "优化"]:
        api_json(url, "/api/tags", {"name": tag})

    papers = []
    for index, (title, authors, year, folder, tags, remark, importance, read) in enumerate(PAPERS):
        # Every paper gets its own file, so the duplicate check does not
        # get in the way.
        data = paper_pdf(title, PAPER_LINES if index == 2 else [f"Page one of {title}."])
        created = upload_pdf(
            url,
            root,
            f"demo{index}.pdf",
            f"demo{index}",
            data=data,
            title=title,
            authors=authors,
            year=str(year),
            tags=json.dumps(tags, ensure_ascii=False),
            remark=remark,
            importance=str(importance),
            folderIds=json.dumps([ids[folder]]),
        )
        if read:
            api_json(url, f"/api/papers/{created['id']}", {"isRead": True}, "PATCH")
        papers.append(created)
    return {"folders": ids, "papers": papers}


async def take_pictures(url: str, root: Path) -> None:
    library = await build_library(url, root)
    paper_id = library["papers"][2]["id"]  # the one with the body text

    async with Browser(url) as tab:
        # ---------------------------------------------------- the library
        await tab.js("location.reload()")
        await asyncio.sleep(2.5)
        await shoot(tab, "library", height=672)

        # ------------------------------------------- the delete window
        await tab.js(
            "document.querySelector('.paper-row .paper-title-cell .title')"
            ".dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,clientX:300,clientY:200}))"
        )
        await asyncio.sleep(0.6)
        await tab.js(
            "[...document.querySelectorAll('#context-menu [data-menu-index]')]"
            ".find(el=>el.textContent.includes('删除文献')).click()"
        )
        await asyncio.sleep(1.2)
        await shoot(tab, "delete-dialog", height=700)
        await tab.js("document.querySelector('#modal-root [data-close]').click()")
        await asyncio.sleep(0.6)

        # ------------------------------------------------- the reading page
        await tab.send("Page.navigate", {"url": f"{url}/paper/{paper_id}"})
        await asyncio.sleep(3.5)

        # Drag over a line of the text: the bar with the colours shows up.
        spot = await line_box(tab, 3)
        await drag_over(tab, spot["x1"], spot["y"], spot["x2"], spot["y"])
        await shoot(tab, "selection-bar")

        # The first highlight: yellow.
        await tab.js("document.querySelector('#sel-bar .sel-dot.yellow').click()")
        await asyncio.sleep(2.5)

        # A thought is written in the small window on the highlight.
        await tab.js("getSelection().removeAllRanges()")
        await asyncio.sleep(0.4)
        middle = await tab.js(
            "(() => { const h = document.querySelector('.pdf-highlight.yellow');"
            " const r = h.getBoundingClientRect();"
            " return {x: r.left + r.width / 2, y: r.top + r.height / 2}; })()"
        )
        await click_at(tab, middle["x"], middle["y"])
        await asyncio.sleep(1.0)
        await tab.js("document.querySelector('#annot-popup-idea').click()")
        await asyncio.sleep(0.5)
        await tab.js(
            "(() => { const i = document.querySelector('#annot-popup-note-input');"
            " i.value = '重定位的思路和这篇很像，可以对照着看';"
            " i.dispatchEvent(new Event('blur')); })()"
        )
        await asyncio.sleep(2.0)

        # The second highlight: green.
        await tab.js("getSelection().removeAllRanges()")
        await tab.js("document.body.click()")
        await asyncio.sleep(0.6)
        spot = await line_box(tab, 13)
        await drag_over(tab, spot["x1"], spot["y"], spot["x2"], spot["y"])
        await tab.js("document.querySelector('#sel-bar .sel-dot.green').click()")
        await asyncio.sleep(2.5)

        # Close the small window, open the panel with the notes.
        await tab.js("getSelection().removeAllRanges()")
        await tab.js("document.body.click()")
        await asyncio.sleep(0.6)
        await tab.js("document.querySelector('#toggle-side').click()")
        await asyncio.sleep(1.2)
        await shoot(tab, "reader")


async def main() -> int:
    if not chrome_available():
        print("No Chrome on the debug port 9333.")
        print("Start it with:")
        print("  /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome \\")
        print("    --remote-debugging-port=9333")
        return 2

    SHOTS.mkdir(parents=True, exist_ok=True)
    root = make_root()
    print(f"  library: {root}  (a throw-away one, never local_data/)")
    server = Server(root, free_port())
    try:
        server.start()
        await take_pictures(server.url, root)
    finally:
        server.stop()
        drop_root(root)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
