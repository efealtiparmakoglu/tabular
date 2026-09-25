"""Column type inference for tabular data.

Each column is classified as INTEGER, REAL or TEXT. The classifier is
deliberately conservative: values that only *look* numeric but would change
on conversion (leading zeros like ``007``, integers beyond SQLite's 64-bit
range, ``nan``/``inf``) keep the column TEXT so nothing is silently mangled.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

INT_RE = re.compile(r"^[+-]?\d+$")
FLOAT_RE = re.compile(r"^[+-]?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?$")
INT64_MIN = -(2**63)
INT64_MAX = 2**63 - 1


@dataclass
class ColumnProfile:
    name: str
    type: str  # "INTEGER" | "REAL" | "TEXT"
    rows: int = 0
    nulls: int = 0  # empty cells under the active policy
    distinct: int = 0
    min_text: Optional[str] = None
    max_text: Optional[str] = None
    samples: List[str] = field(default_factory=list)


def _padded_zero(s: str) -> bool:
    """True when the integer part has padding zeros (``007``, ``00.5``)."""
    s = s.lstrip("+-")
    mantissa = re.split("[eE]", s)[0]
    int_part = mantissa.split(".")[0]
    return len(int_part) > 1 and int_part[0] == "0"


def _plain_int(raw: str) -> bool:
    """Integer whose round-trip through int() is value-preserving."""
    s = raw.strip()
    if not INT_RE.match(s):
        return False
    if _padded_zero(s):
        return False  # 007, +003 — leading zeros are identifiers, not numbers
    v = int(s)
    return INT64_MIN <= v <= INT64_MAX


def _plain_float(raw: str) -> bool:
    s = raw.strip()
    if not FLOAT_RE.match(s):
        return False
    if _padded_zero(s):
        return False
    try:
        v = float(s)
    except ValueError:  # pragma: no cover - regex already guarantees form
        return False
    if v != v or v in (float("inf"), float("-inf")):
        return False
    return INT64_MIN <= v <= INT64_MAX


def classify(values: List[str]) -> str:
    """Infer one column type from raw (non-empty) cell strings."""
    if not values:
        return "TEXT"
    if all(_plain_int(v) for v in values):
        return "INTEGER"
    if all(_plain_float(v) for v in values):
        return "REAL"
    return "TEXT"


def convert(raw: str, col_type: str) -> Optional[object]:
    """Convert one raw cell to its Python/SQLite value (or None)."""
    if raw == "":
        return None
    s = raw.strip()
    if col_type == "INTEGER":
        return int(s)
    if col_type == "REAL":
        return float(s)
    return raw


def profile_columns(
    header: List[str], rows: List[List[str]], empty_policy: str = "null"
) -> List[ColumnProfile]:
    """Build per-column profiles from raw (string) rows."""
    profiles: List[ColumnProfile] = []
    for i, name in enumerate(header):
        raws = [(r[i] if i < len(r) else "") for r in rows]
        non_empty = [v for v in raws if v != ""]
        col_type = classify(non_empty)
        converted = [convert(v, col_type) for v in raws]
        nulls = sum(1 for v in raws if v == "")
        if empty_policy != "null":
            nulls = 0
        numeric = [v for v in converted if isinstance(v, (int, float))]
        distinct = len({repr(v) for v in converted if v is not None})
        profiles.append(
            ColumnProfile(
                name=name,
                type=col_type,
                rows=len(rows),
                nulls=nulls,
                distinct=distinct,
                min_text=_fmt(min(numeric)) if numeric else None,
                max_text=_fmt(max(numeric)) if numeric else None,
                samples=non_empty[:3],
            )
        )
    return profiles


def _fmt(v: object) -> str:
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)
