"""Small, deterministic file tools used by the Day 2 invoice task."""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Iterable

from .base import ToolError


def export_csv(rows: Iterable[dict[str, Any]], path: str | Path, *, fieldnames: list[str] | None = None) -> str:
    """Write dictionaries to CSV and return the absolute path."""
    records = list(rows)
    if not records and not fieldnames:
        raise ToolError("invalid_request", "Cannot export an empty result without field names")
    fields = fieldnames or list(records[0].keys())
    if not fields or any(not isinstance(field, str) or not field for field in fields):
        raise ToolError("invalid_request", "CSV field names must be non-empty strings")
    destination = Path(path).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows({field: row.get(field, "") for field in fields} for row in records)
    return str(destination.resolve())
