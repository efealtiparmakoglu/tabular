"""tabular CLI — import CSV/TSV into SQLite, or report the inferred schema."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import List, Optional, Tuple

from . import __version__
from .importer import (
    EMPTY_POLICIES,
    IF_EXISTS_MODES,
    ImportError_,
    import_rows,
    sanitize_table_name,
)
from .infer import profile_columns
from .reader import TableError, read_text
from .report import render_json as report_json
from .report import render_text as report_text


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tabular",
        description="Import CSV/TSV into SQLite with inferred column types.",
    )
    parser.add_argument("--version", action="version", version=f"tabular {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("file", help="CSV/TSV file to read ('-' for stdin)")
        p.add_argument(
            "--delimiter", help="field delimiter (default: by extension, then sniff)"
        )
        p.add_argument(
            "--no-header", action="store_true", help="file has no header row"
        )

    imp = sub.add_parser("import", help="load a file into a SQLite table")
    common(imp)
    imp.add_argument("--db", required=True, help="SQLite database file")
    imp.add_argument("--table", help="table name (default: file stem, sanitized)")
    imp.add_argument(
        "--empty",
        choices=EMPTY_POLICIES,
        default="null",
        help="what empty cells become (default: null)",
    )
    imp.add_argument("--pk", help="single-column primary key")
    imp.add_argument(
        "--if-exists",
        choices=IF_EXISTS_MODES,
        default="fail",
        help="when the table already exists (default: fail)",
    )

    sch = sub.add_parser("schema", help="print the inferred schema")
    common(sch)
    sch.add_argument("--json", action="store_true", help="emit JSON")
    return parser


def _load(path: str, delimiter: Optional[str], has_header: bool) -> Tuple[List[str], List[List[str]], str]:
    if path == "-":
        text = sys.stdin.read()
        hint = "stdin"
    else:
        p = Path(path)
        if not p.is_file():
            raise TableError(f"no such file: {path}")
        text = p.read_text(encoding="utf-8-sig")
        hint = p.name
    delim = delimiter if delimiter else None
    header, rows = read_text(text, hint, delim, has_header)
    return header, rows, hint


def _table_name(explicit: Optional[str], path: str) -> str:
    if explicit:
        return explicit
    return sanitize_table_name(Path(path).stem) if path != "-" else "stdin"


def cmd_import(args: argparse.Namespace) -> int:
    header, rows, path = _load(args.file, args.delimiter, not args.no_header)
    table = _table_name(args.table, path)
    profiles = profile_columns(header, rows, args.empty)
    conn = sqlite3.connect(args.db)
    try:
        count = import_rows(
            conn,
            table,
            profiles,
            rows,
            empty_policy=args.empty,
            pk=args.pk,
            if_exists=args.if_exists,
        )
        conn.commit()
    except (ImportError_, sqlite3.Error) as exc:
        print(f"tabular: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()
    print(f"imported {count} rows into {table} ({args.db})")
    return 0


def cmd_schema(args: argparse.Namespace) -> int:
    header, rows, path = _load(args.file, args.delimiter, not args.no_header)
    table = _table_name(None, path)
    profiles = profile_columns(header, rows, "null")
    if args.json:
        print(report_json(table, profiles, len(rows)))
    else:
        print(report_text(table, profiles, len(rows)))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "import":
            return cmd_import(args)
        return cmd_schema(args)
    except (TableError, ImportError_) as exc:
        print(f"tabular: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
