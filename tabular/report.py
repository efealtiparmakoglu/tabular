"""Schema report rendering (text and JSON)."""

from __future__ import annotations

import json
from typing import List

from .infer import ColumnProfile


def render_text(table: str, profiles: List[ColumnProfile], row_count: int) -> str:
    out = [f"table {table}: {len(profiles)} columns, {row_count} rows"]
    name_w = max([len("column")] + [len(p.name) for p in profiles])
    type_w = max([len("type")] + [len(p.type) for p in profiles])
    header = f"{'column':<{name_w}}  {'type':<{type_w}}  nulls  distinct  min  max"
    out.append(header)
    out.append("-" * len(header))
    for p in profiles:
        min_s = p.min_text if p.min_text is not None else "-"
        max_s = p.max_text if p.max_text is not None else "-"
        out.append(
            f"{p.name:<{name_w}}  {p.type:<{type_w}}  {p.nulls:>5}  "
            f"{p.distinct:>8}  {min_s:>3}  {max_s:>3}"
        )
    return "\n".join(out)


def render_json(table: str, profiles: List[ColumnProfile], row_count: int) -> str:
    doc = {
        "table": table,
        "rows": row_count,
        "columns": [
            {
                "name": p.name,
                "type": p.type,
                "nulls": p.nulls,
                "distinct": p.distinct,
                "min": p.min_text,
                "max": p.max_text,
                "samples": p.samples,
            }
            for p in profiles
        ],
    }
    return json.dumps(doc, ensure_ascii=False, indent=2)
