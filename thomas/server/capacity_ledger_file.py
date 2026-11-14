"""What the reservation ledger's file may hold, and how it is written (see :mod:`thomas.server.capacity_ledger`).

Every row the ledger reads must have its text fields (``key``, ``id``, ``kind``, ``owner``, ``state``) and any number it
carries of the right type. A row missing its ``state``, or with a ``pool_size`` of ``"twelve"``, would be a KeyError or
a ValueError in the middle of whichever job read it, which a check read as the change breaking the run. :func:`problem`
names what is wrong with a row, and :func:`~thomas.server.capacity_ledger_locks.read_rows` treats a file with such a row
as one it cannot read.

:func:`write` flushes the new rows to the disk before the rename that puts them in place. NTFS keeps a rename whose data
it had not yet written, so a power cut left ``reservations.json`` empty, and an empty file is the one thing every server
then refuses to move aside while another lives.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any

from thomas.core import atomic_json

TEXT = ("key", "id", "kind", "owner", "state")  # fields every row has
NUMBERS = ("files", "disk_bytes", "memory_bytes", "pool_size", "since", "admitted_at", "computed_at")  # when present


def _number(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:  # an integer too large to be a float overflows the arithmetic that reads it
        return False


def problem(row: object) -> str:
    """What is wrong with *row*, or "" when it has every field the ledger reads and each is of its type."""
    if not isinstance(row, dict):
        return "a row is not an object"
    for field in TEXT:
        if not isinstance(row.get(field), str) or not row[field]:
            return f"a row has no {field}, or its {field} is not text"
    for field in NUMBERS:
        if row.get(field) is not None and not _number(row[field]):
            return f"a row's {field} is not a finite number"
    return ""


def write(place: Path, name: str, rows: list[dict[str, Any]]) -> None:
    """Replace the JSON list *name* in *place* with *rows*, flushed to the disk before it takes the old file's place.

    A temporary file of its own is written and ``fsync``-ed, then renamed over the ledger: a power cut leaves the old
    file or the new one. The rename is tried again while a reader has the file open, which Windows will not replace
    (:mod:`thomas.core.atomic_json`'s retry). A write that fails leaves the old file and no temporary file behind.
    """
    target = place / name
    place.mkdir(parents=True, exist_ok=True)
    scratch = atomic_json.temp_path_for(target)
    try:
        with open(scratch, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(rows, indent=2, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        atomic_json._replace_with_retry(scratch, target)
    finally:
        scratch.unlink(missing_ok=True)


__all__ = ["NUMBERS", "TEXT", "problem", "write"]
