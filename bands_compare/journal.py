"""Append-only research journal for comparator decisions."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Iterable, List, Mapping, Optional, Union

from .schemas import JOURNAL_FIELDS, JournalRow

# Re-export for tests.
__all__ = ["JOURNAL_FIELDS", "validate_row", "append_row", "read_rows", "default_journal_path"]


def default_journal_path() -> str:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, "reports", "bands_journal.jsonl")


def validate_row(payload: Mapping[str, Any]) -> Dict[str, Any]:
    missing = [k for k in JOURNAL_FIELDS if k not in payload]
    if missing:
        raise ValueError(f"journal row missing fields: {missing}")
    action = payload.get("actual_action")
    if action not in {"HOLD", "OPEN", "MOVE", "CLAIM", "CLOSE"}:
        raise ValueError(f"invalid actual_action: {action}")
    rec = payload.get("recommended_action")
    if rec not in {"HOLD", "OPEN", "MOVE", "CLAIM", "CLOSE"}:
        raise ValueError(f"invalid recommended_action: {rec}")
    return dict(payload)


def append_row(row: Union[JournalRow, Mapping[str, Any]], path: Optional[str] = None) -> None:
    payload = row.to_dict() if isinstance(row, JournalRow) else dict(row)
    validate_row(payload)
    dest = path or default_journal_path()
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    with open(dest, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, sort_keys=True) + "\n")


def append_rows(rows: Iterable[Union[JournalRow, Mapping[str, Any]]], path: Optional[str] = None) -> None:
    for row in rows:
        append_row(row, path=path)


def read_rows(path: str) -> List[Dict[str, Any]]:
    if not os.path.exists(path):
        return []
    out: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            out.append(json.loads(line))
    return out
