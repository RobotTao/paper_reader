"""Shared plumbing for the browser tests.

The tests drive a real Chrome over the DevTools protocol. They run against
a server of their own, on a library of their own: nothing here ever
touches ``local_data/``.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import websockets

#: Where Chrome listens when it is started with --remote-debugging-port.
DEBUG_PORT = int(os.environ.get("CHROME_DEBUG_PORT", "9333"))

#: The backend, relative to this file.
BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"

#: The real library - the one thing the tests must never touch.
REAL_LIBRARY = (Path(__file__).resolve().parents[2] / "local_data").resolve()

#: A small PDF; the frontend never looks inside it.
PDF_BYTES = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
    b"trailer<</Root 1 0 R>>\n"
    b"%%EOF\n"
)

#: A PDF with three tall pages, so the page counter has something to count
#: and the content is long enough to scroll. The pages are about as wide as
#: a sheet of paper.
MULTI_PAGE_PDF_BYTES = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R 4 0 R 5 0 R]/Count 3>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 600 700]>>endobj\n"
    b"4 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 600 700]>>endobj\n"
    b"5 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 600 700]>>endobj\n"
    b"trailer<</Root 1 0 R>>\n"
    b"%%EOF\n"
)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def make_root() -> Path:
    """A throw-away library directory - never the real one."""
    root = Path(tempfile.mkdtemp(prefix="paper_reader_e2e_")).resolve()
    if root == REAL_LIBRARY or REAL_LIBRARY in root.parents:
        raise RuntimeError(f"the tests would run against the real library: {root}")
    return root


def drop_root(root: Path) -> None:
    """Throw the throw-away library away."""
    shutil.rmtree(root, ignore_errors=True)


#: A PDF with a line of text on it, so the reader has something to select
#: and highlight. The other PDFs are blank on purpose.
_TEXT_STREAM = b"BT /F1 18 Tf 40 100 Td (Hello Paper Reader) Tj ET\n"

TEXT_PDF_BYTES = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 400 200]"
    b"/Resources<</Font<</F1 4 0 R>>>>/Contents 5 0 R>>endobj\n"
    b"4 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
    b"5 0 obj<</Length "
    + str(len(_TEXT_STREAM)).encode()
    + b">>stream\n"
    + _TEXT_STREAM
    + b"endstream\nendobj\n"
    b"trailer<</Root 1 0 R/Size 6>>\n"
    b"%%EOF\n"
)


#: A PDF with two pages and a table of contents that points at them, so the
#: catalog of the reader has something to show. The pages are tall, so the
#: document has to be scrolled to reach the second one.
_OUTLINE_PAGE1 = b"BT /F1 18 Tf 40 650 Td (Introduction Chapter) Tj ET\n"
_OUTLINE_PAGE2 = b"BT /F1 18 Tf 40 650 Td (Method Chapter) Tj ET\n"

OUTLINE_PDF_BYTES = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R/Outlines 8 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R 4 0 R]/Count 2>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 600 700]"
    b"/Resources<</Font<</F1 5 0 R>>>>/Contents 6 0 R>>endobj\n"
    b"4 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 600 700]"
    b"/Resources<</Font<</F1 5 0 R>>>>/Contents 7 0 R>>endobj\n"
    b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
    b"6 0 obj<</Length "
    + str(len(_OUTLINE_PAGE1)).encode()
    + b">>stream\n"
    + _OUTLINE_PAGE1
    + b"endstream\nendobj\n"
    b"7 0 obj<</Length "
    + str(len(_OUTLINE_PAGE2)).encode()
    + b">>stream\n"
    + _OUTLINE_PAGE2
    + b"endstream\nendobj\n"
    b"8 0 obj<</Type/Outlines/First 9 0 R/Last 10 0 R/Count 2>>endobj\n"
    b"9 0 obj<</Title (Introduction)/Parent 8 0 R/Dest[3 0 R/XYZ 0 650 0]/Next 10 0 R>>endobj\n"
    b"10 0 obj<</Title (Method)/Parent 8 0 R/Dest[4 0 R/XYZ 0 650 0]/Prev 9 0 R>>endobj\n"
    b"trailer<</Root 1 0 R/Size 11>>\n"
    b"%%EOF\n"
)


#: A PDF with three lines that stand close to each other, so the rectangles
#: of a selection over them cover one another - the case in which a
#: highlight used to come out in two shades.
_MULTILINE_STREAM = (
    b"BT /F1 18 Tf 40 120 Td (First line of the paragraph) Tj ET\n"
    b"BT /F1 18 Tf 40 105 Td (Second line of the paragraph) Tj ET\n"
    b"BT /F1 18 Tf 40 90 Td (Third line of the paragraph) Tj ET\n"
)

MULTILINE_PDF_BYTES = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 400 200]"
    b"/Resources<</Font<</F1 4 0 R>>>>/Contents 5 0 R>>endobj\n"
    b"4 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
    b"5 0 obj<</Length "
    + str(len(_MULTILINE_STREAM)).encode()
    + b">>stream\n"
    + _MULTILINE_STREAM
    + b"endstream\nendobj\n"
    b"trailer<</Root 1 0 R/Size 6>>\n"
    b"%%EOF\n"
)


# --------------------------------------------------------------------------- #
# the server
# --------------------------------------------------------------------------- #


class Server:
    """A uvicorn of its own, with a library of its own."""

    def __init__(self, root: Path, port: int):
        self.root = root
        self.port = port
        self.process: subprocess.Popen | None = None

    def start(self) -> None:
        env = dict(os.environ)
        env["PDF_ROOT"] = str(self.root)
        env["DATA_DIR"] = str(self.root / "db")
        env["PYTHONPATH"] = str(BACKEND_DIR)
        self.process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(self.port),
             "--log-level", "warning"],
            cwd=str(BACKEND_DIR),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._wait_for_health()

    def _wait_for_health(self) -> None:
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/healthz") as resp:
                    if resp.status == 200:
                        return
            except OSError:
                # The server is not up yet.
                time.sleep(0.2)
        raise RuntimeError(f"the server on port {self.port} did not come up")

    def stop(self) -> None:
        if self.process is not None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


# --------------------------------------------------------------------------- #
# the library the tests work on
# --------------------------------------------------------------------------- #


def api_json(url: str, path: str, payload: dict | None = None, method: str = "POST") -> dict:
    data = json.dumps(payload).encode() if payload is not None else b"{}"
    request = urllib.request.Request(
        f"{url}{path}", data=data, method=method, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request) as resp:
        return json.loads(resp.read().decode())


def source_file(root: Path, marker: str) -> Path:
    """The file a paper was uploaded from - the browser can pick it again."""
    return root / "src" / f"{marker}.pdf"


def upload_pdf(
    url: str, root: Path, name: str, marker: str, data: bytes | None = None, **fields
) -> dict:
    """Upload a PDF through the API, like the user would.

    The file is kept in ``root/src`` so a test can hand the very same bytes
    to the browser and watch the duplicate check fire.
    """
    path = source_file(root, marker)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = PDF_BYTES if data is None else data
    path.write_bytes(body + f"% {marker}\n".encode())
    boundary = "----paperreadere2e"
    body = b""
    for key, value in fields.items():
        body += f"--{boundary}\r\n".encode()
        body += f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode()
        body += f"{value}\r\n".encode()
    body += f"--{boundary}\r\n".encode()
    body += f'Content-Disposition: form-data; name="file"; filename="{name}"\r\n'.encode()
    body += b"Content-Type: application/pdf\r\n\r\n"
    body += path.read_bytes() + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    request = urllib.request.Request(
        f"{url}/api/papers",
        data=body,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(request) as resp:
        return json.loads(resp.read().decode())


#: The papers the seeded library holds: title, folder key, marker.
SEED_PAPERS = [
    ("Point-to-Point ICP", "lidar", "icp"),
    ("Deep Learning for MVS", "slam", "mvs"),
    ("A Paper Without a Folder", None, "loose"),
    ("KinectFusion", None, "kinect"),
]


def seed(url: str, root: Path) -> dict:
    """A small library: two folders, a few tags and a few papers."""
    slam = api_json(url, "/api/folders", {"name": "SLAM"})
    lidar = api_json(url, "/api/folders", {"name": "点云", "parentId": slam["id"]})
    cv = api_json(url, "/api/folders", {"name": "CV"})
    api_json(url, "/api/tags", {"name": "Transformer"})
    folders = {"slam": slam, "lidar": lidar, "cv": cv}

    papers = []
    for index, (title, folder, marker) in enumerate(SEED_PAPERS):
        fields = {"title": title, "tags": json.dumps(["Transformer"] if index == 0 else [])}
        if folder is not None:
            fields["folderIds"] = json.dumps([folders[folder]["id"]])
        papers.append(upload_pdf(url, root, f"{marker}.pdf", marker, **fields))
    return {
        "folders": folders,
        "papers": papers,
        "markers": {marker: title for _title, _folder, marker in SEED_PAPERS},
    }


# --------------------------------------------------------------------------- #
# the browser
# --------------------------------------------------------------------------- #


class Tab:
    """One tab of the browser, seen through the DevTools protocol."""

    def __init__(self, ws):
        self.ws = ws
        self.id = 0
        self.errors: list[str] = []
        self._pending: dict[int, asyncio.Future] = {}
        self._reader: asyncio.Task | None = None

    async def start(self) -> None:
        """Start reading the socket, so the events are never missed."""
        self._reader = asyncio.ensure_future(self._read())

    async def _read(self) -> None:
        try:
            async for raw in self.ws:
                message = json.loads(raw)
                ident = message.get("id")
                if ident is not None and ident in self._pending:
                    self._pending.pop(ident).set_result(message)
                else:
                    self._note(message)
        except Exception:  # noqa: BLE001, S110 - the tab was closed, that is all
            pass

    def _note(self, message: dict) -> None:
        """Remember the errors the page produces."""
        if message.get("method") == "Runtime.exceptionThrown":
            self.errors.append(str(message["params"])[:300])
        elif message.get("method") == "Log.entryAdded":
            entry = message["params"]["entry"]
            if entry.get("level") == "error":
                self.errors.append(entry.get("text", "")[:300])

    async def send(self, method: str, params: dict | None = None) -> dict:
        self.id += 1
        ident = self.id
        future = asyncio.get_running_loop().create_future()
        self._pending[ident] = future
        await self.ws.send(
            json.dumps({"id": ident, "method": method, "params": params or {}})
        )
        return await future

    async def js(self, expression: str):
        result = await self.send(
            "Runtime.evaluate",
            {"expression": expression, "awaitPromise": True, "returnByValue": True},
        )
        if result.get("exceptionDetails"):
            raise RuntimeError(json.dumps(result["exceptionDetails"])[:400])
        return result["result"]["result"].get("value")

    async def mouse(self, kind: str, x: float, y: float, clicks: int = 1) -> None:
        await self.send(
            "Input.dispatchMouseEvent",
            {
                "type": kind,
                "x": x,
                "y": y,
                "button": "left" if kind != "mouseMoved" else "none",
                "buttons": 1 if kind != "mouseReleased" else 0,
                "clickCount": clicks,
            },
        )

    async def open_file_input(self, selector: str, path: str) -> None:
        """Put a file into a file input, as if it had been picked."""
        document = await self.send("DOM.getDocument")
        node = await self.send(
            "DOM.querySelector",
            {"nodeId": document["result"]["root"]["nodeId"], "selector": selector},
        )
        await self.send(
            "DOM.setFileInputFiles", {"files": [path], "nodeId": node["result"]["nodeId"]}
        )

    async def reset_view(self) -> None:
        """Start from the default look: no column widths in the storage."""
        await self.js("localStorage.removeItem('paper-reader.column-widths')")
        await self.js("location.reload()")
        await asyncio.sleep(2.5)


def chrome_available() -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{DEBUG_PORT}/json/version", timeout=2):
            return True
    except OSError:
        return False


class Browser:
    """A tab, opened and ready to be driven."""

    def __init__(self, url: str):
        self.url = url

    async def __aenter__(self) -> Tab:
        request = urllib.request.Request(
            f"http://127.0.0.1:{DEBUG_PORT}/json/new?{self.url}", method="PUT"
        )
        # The DevTools endpoint is a blocking one: it stays out of the way
        # of the event loop.
        with await asyncio.to_thread(urllib.request.urlopen, request) as resp:
            target = json.loads(resp.read().decode())
        self.ws = await websockets.connect(
            target["webSocketDebuggerUrl"], max_size=80_000_000
        )
        tab = Tab(self.ws)
        await tab.start()
        await tab.send("Page.enable")
        await tab.send("Runtime.enable")
        await tab.send("Log.enable")
        await tab.send("DOM.enable")
        await tab.send("Network.enable")
        await tab.send("Network.setCacheDisabled", {"cacheDisabled": True})
        await tab.send(
            "Emulation.setDeviceMetricsOverride",
            {"width": 1440, "height": 900, "deviceScaleFactor": 1, "mobile": False},
        )
        window = await tab.send("Browser.getWindowForTarget", {"targetId": target["id"]})
        await tab.send(
            "Browser.setWindowBounds",
            {
                "windowId": window["result"]["windowId"],
                "bounds": {"width": 1600, "height": 1000},
            },
        )
        await tab.send("Page.navigate", {"url": self.url})
        await asyncio.sleep(2.5)
        self.tab = tab
        return tab

    async def __aexit__(self, *_exc) -> None:
        self.tab._reader.cancel()
        await self.ws.close()


# --------------------------------------------------------------------------- #
# the results
# --------------------------------------------------------------------------- #


class Checker:
    """Collects the checks of one test file."""

    def __init__(self, name: str):
        self.name = name
        self.results: list[tuple[str, bool, str]] = []

    def check(self, name: str, ok: bool, extra: object = "") -> bool:
        self.results.append((name, bool(ok), str(extra) if extra != "" else ""))
        print(("  PASS " if ok else "  FAIL ") + name + (f"  -> {extra}" if extra != "" else ""))
        return bool(ok)

    @property
    def failed(self) -> list[tuple[str, bool, str]]:
        return [row for row in self.results if not row[1]]
