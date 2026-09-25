"""SQLite import: create the table from inferred types and load the rows."""

from __future__ import annotations

import re
import sqlite3
from typing import List, Optional

from .infer import ColumnProfile, convert, profile_columns

EMPTY_POLICIES = ("null", "text", "zero")
IF_EXISTS_MODES = ("fail", "replace", "append")


class ImportError_(Exception):
    """Fatal import problem — the CLI turns this into exit code 1."""


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def sanitize_table_name(stem: str) -> str:
    name = re.sub(r"[^0-9A-Za-z_]+", "_", stem).strip("_")
    if not name:
        name = "table"
    if name[0].isdigit():
        name = "_" + name
    return name


def create_sql(table: str, profiles: List[ColumnProfile], pk: Optional[str]) -> str:
    cols = [f"{quote_ident(p.name)} {p.type}" for p in profiles]
    if pk is not None:
        cols.append(f"PRIMARY KEY ({quote_ident(pk)})")
    return f"CREATE TABLE {quote_ident(table)} ({', '.join(cols)})"


def _empty_fill(col_type: str, policy: str) -> object:
    """Value substituted for empty cells under the non-null policies."""
    if policy == "text":
        return ""
    if policy == "zero":
        return 0 if col_type == "INTEGER" else (0.0 if col_type == "REAL" else "")
    return None


def import_rows(
    conn: sqlite3.Connection,
    table: str,
    profiles: List[ColumnProfile],
    rows: List[List[str]],
    empty_policy: str = "null",
    pk: Optional[str] = None,
    if_exists: str = "fail",
) -> int:
    """Create (or reuse) the table and insert raw string rows; returns count."""
    if empty_policy not in EMPTY_POLICIES:
        raise ImportError_(f"empty policy must be one of {EMPTY_POLICIES}")
    if if_exists not in IF_EXISTS_MODES:
        raise ImportError_(f"if-exists mode must be one of {IF_EXISTS_MODES}")
    if pk is not None and pk not in [p.name for p in profiles]:
        raise ImportError_(f"--pk column {pk!r} not found in input")

    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    if exists:
        if if_exists == "fail":
            raise ImportError_(f"table {table!r} already exists (use --if-exists)")
        if if_exists == "replace":
            conn.execute(f"DROP TABLE {quote_ident(table)}")
        elif if_exists == "append":
            existing = [
                r[1]
                for r in conn.execute(f"PRAGMA table_info({quote_ident(table)})")
            ]  # PRAGMA does not take parameters; name is quoted above
            if existing != [p.name for p in profiles]:
                raise ImportError_(
                    f"column mismatch: table has {existing}, input has "
                    f"{[p.name for p in profiles]}"
                )
    if not exists or if_exists == "replace":
        conn.execute(create_sql(table, profiles, pk))

    types = [p.type for p in profiles]
    col_list = ", ".join(quote_ident(p.name) for p in profiles)
    marks = ", ".join("?" for _ in profiles)
    sql = f"INSERT INTO {quote_ident(table)} ({col_list}) VALUES ({marks})"
    converted = []
    for row in rows:
        vals = []
        for i, p in enumerate(profiles):
            raw = row[i] if i < len(row) else ""
            if raw == "":
                vals.append(_empty_fill(p.type, empty_policy))
            else:
                vals.append(convert(raw, p.type))
        converted.append(vals)
    try:
        conn.executemany(sql, converted)
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise ImportError_(f"integrity error: {exc}") from exc
    return len(converted)
