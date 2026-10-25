"""The browser tests.

They drive a real Chrome over the DevTools protocol, against a server of
their own, on a library of their own: the library in ``local_data/`` is
never touched.

    make test-e2e                 # every case
    make test-e2e CASE=duplicate  # one case

Chrome has to listen on the debug port first:

    /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome \\
      --remote-debugging-port=9333
"""

from __future__ import annotations

import asyncio
import importlib
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "cases"))

from harness import (
    Checker,
    Server,
    chrome_available,
    drop_root,
    free_port,
    make_root,
    seed,
)

#: The cases, in the order they run. Each one gets a library of its own.
CASES = [
    "columns",
    "list_layout",
    "delete_menu",
    "duplicate",
    "add_paper",
    "tags",
    "reader",
]


class Context:
    """What a case gets to work with."""

    def __init__(self, url: str, root: Path, seeded: dict, checker: Checker):
        self.url = url
        self.root = root
        self.seeded = seeded
        self.checker = checker

    def check(self, name: str, ok: bool, extra: object = "") -> bool:
        return self.checker.check(name, ok, extra)


async def run_case(name: str) -> Checker:
    checker = Checker(name)
    root = make_root()
    print(f"  library: {root}  (a throw-away one, never local_data/)")
    server = Server(root, free_port())
    try:
        server.start()
        seeded = seed(server.url, root)
        module = importlib.import_module(name)
        await module.run(Context(server.url, root, seeded, checker))
    finally:
        server.stop()
        drop_root(root)
    return checker


async def main(names: list[str]) -> int:
    if not chrome_available():
        print("No Chrome on the debug port 9333.")
        print("Start it with:")
        print("  /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome \\")
        print("    --remote-debugging-port=9333")
        return 2

    checkers = []
    for name in names:
        print(f"\n== {name} ==")
        try:
            checkers.append(await run_case(name))
        except Exception:  # noqa: BLE001 - a broken case must not stop the others
            traceback.print_exc()
            checker = Checker(name)
            checker.check("用例没有跑完", False, "see the traceback above")
            checkers.append(checker)

    passed = sum(len(c.results) - len(c.failed) for c in checkers)
    total = sum(len(c.results) for c in checkers)
    print("\n" + "=" * 60)
    for checker in checkers:
        for row in checker.failed:
            print(f"FAILED  {checker.name}: {row[0]}")
    print(f"{passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    wanted = sys.argv[1:] or CASES
    unknown = [name for name in wanted if name not in CASES]
    if unknown:
        print(f"Unknown case(s): {', '.join(unknown)}")
        print(f"The cases are: {', '.join(CASES)}")
        sys.exit(2)
    sys.exit(asyncio.run(main(wanted)))
