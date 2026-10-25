"""Command line helpers: ``uv run python -m app.cli import``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import DATA_DIR, PDF_ROOT, ensure_dirs
from .db import init_db
from .importer import backfill_colors, import_readpaper


def cmd_import(args: argparse.Namespace) -> int:
    ensure_dirs()
    init_db()
    data_path = Path(args.data or (PDF_ROOT / "data.json")).resolve()
    if not data_path.exists():
        print(f"data.json not found: {data_path}", file=sys.stderr)
        return 1
    print(f"importing {data_path}")
    print(f"  pdf root : {PDF_ROOT}")
    print(f"  data dir : {DATA_DIR}")
    stats = import_readpaper(data_path, reset=args.reset)
    print(
        f"done: {stats['papers']} papers, {stats['folders']} folders, {stats['tags']} tags, "
        f"{stats['annotations']} annotations"
        + (f" ({stats['skipped']} skipped, already imported)" if stats["skipped"] else "")
        + (f" ({stats['no_file']} without a file, not imported)" if stats.get("no_file") else "")
        + (f" ({stats['empty_tags']} empty tags dropped)" if stats.get("empty_tags") else "")
    )
    return 0


def cmd_backfill_colors(args: argparse.Namespace) -> int:
    """Give the imported highlights the colour they have in readpaper."""
    ensure_dirs()
    init_db()
    data_path = Path(args.data or (PDF_ROOT / "data.json")).resolve()
    if not data_path.exists():
        print(f"data.json not found: {data_path}", file=sys.stderr)
        return 1
    dry_run = not args.apply
    stats = backfill_colors(data_path, dry_run=dry_run)
    print(f"{'would change' if dry_run else 'changed'} {stats['changed']} highlights")
    print(
        f"  papers      : {stats['papers']}\n"
        f"  annotations : {stats['annotations']}\n"
        f"  same colour: {stats['same']}\n"
        f"  left alone  : {stats['kept']} (colour picked by hand)\n"
        f"  no mark     : {stats['unmatched']} (no mark in the export)"
    )
    if dry_run:
        print("(nothing was written - add --apply to write it)")
    return 0


def cmd_stats(_args: argparse.Namespace) -> int:
    init_db()
    from .db import get_conn

    with get_conn() as conn:
        for table in ("papers", "folders", "tags", "paper_tags", "paper_folders", "annotations"):
            count = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
            print(f"{table:>14}: {count}")
    return 0


def cmd_index_hashes(_args: argparse.Namespace) -> int:
    """Give every paper the hash of its file, so duplicates can be found."""
    ensure_dirs()
    init_db()
    from .db import get_conn, resolve_pdf_path
    from .hashes import sha256_file

    hashed = missing = unchanged = 0
    by_hash: dict[str, list[str]] = {}
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, title, file_path, content_hash FROM papers "
            "WHERE file_path IS NOT NULL AND file_path != ''"
        ).fetchall()
        for row in rows:
            path = resolve_pdf_path(row["file_path"])
            if path is None or not path.exists():
                missing += 1
                continue
            digest = sha256_file(path)
            by_hash.setdefault(digest, []).append(row["title"])
            if row["content_hash"] == digest:
                unchanged += 1
                continue
            conn.execute(
                "UPDATE papers SET content_hash = ? WHERE id = ?", (digest, row["id"])
            )
            hashed += 1
        conn.commit()

    print(f"hashed {hashed} papers, {unchanged} already up to date, {missing} without a file")
    duplicates = {digest: titles for digest, titles in by_hash.items() if len(titles) > 1}
    if duplicates:
        print(f"\n{len(duplicates)} groups of papers with the same file:")
        for titles in duplicates.values():
            print("  - " + "  |  ".join(titles))
        print("(nothing was deleted - these are only reported)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="paper-reader")
    sub = parser.add_subparsers(dest="command", required=True)

    imp = sub.add_parser("import", help="import a readpaper export (data.json)")
    imp.add_argument("data", nargs="?", help="path to data.json (default: $PDF_ROOT/data.json)")
    imp.add_argument("--reset", action="store_true", help="wipe existing data first")
    imp.set_defaults(func=cmd_import)

    st = sub.add_parser("stats", help="show row counts")
    st.set_defaults(func=cmd_stats)

    ih = sub.add_parser(
        "index-hashes", help="hash every PDF so duplicates can be found"
    )
    ih.set_defaults(func=cmd_index_hashes)

    bc = sub.add_parser(
        "backfill-colors",
        help="give the imported highlights the colour they have in readpaper",
    )
    bc.add_argument("data", nargs="?", help="path to data.json (default: $PDF_ROOT/data.json)")
    bc.add_argument(
        "--apply", action="store_true", help="write the colours (without it nothing is written)"
    )
    bc.set_defaults(func=cmd_backfill_colors)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
