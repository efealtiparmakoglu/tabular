"""Reading CSV/TSV text into header + string rows."""

from __future__ import annotations

import csv
import io
from typing import List, Optional, Tuple

SNIFF_SAMPLE_LINES = 10


class TableError(Exception):
    """Fatal input problem — the CLI turns this into exit code 1."""


def detect_delimiter(text: str, path_hint: str, override: Optional[str]) -> str:
    if override is not None:
        if len(override) != 1:
            raise TableError(
                f"--delimiter must be a single character, got {override!r}"
            )
        return override
    stem = path_hint.lower()
    if stem.endswith((".tsv", ".tab")):
        return "\t"
    if stem.endswith(".csv"):
        return ","
    # unknown extension: sniff a semicolon vs comma vs tab from the sample
    sample = "".join(text.splitlines(keepends=True)[:SNIFF_SAMPLE_LINES])
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        return ","


def split_header(
    rows: List[List[str]], has_header: bool
) -> Tuple[List[str], List[List[str]]]:
    """Return (header, data_rows), generating names when there is none and
    de-duplicating repeated column names deterministically."""
    if not rows:
        raise TableError("input has no rows")
    width = max(len(r) for r in rows)
    if has_header:
        raw = list(rows[0])
        rows = rows[1:]
    else:
        raw = [f"col{i + 1}" for i in range(width)]
    raw += [""] * (width - len(raw))
    header: List[str] = []
    seen: dict = {}
    for name in raw:
        name = name.strip()
        if not name:
            n = len(header) + 1
            name = f"col{n}"
        if name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 1
        header.append(name)
    return header, rows


def read_text(text: str, path_hint: str, delimiter: Optional[str], header: bool) -> Tuple[List[str], List[List[str]]]:
    delim = detect_delimiter(text, path_hint, delimiter)
    rows = list(csv.reader(io.StringIO(text), delimiter=delim))
    if not rows:
        raise TableError("input is empty")
    rows = [r for r in rows if r != []]
    if not rows:
        raise TableError("input has no rows")
    return split_header(rows, header)
