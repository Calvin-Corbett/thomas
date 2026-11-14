"""``--restore``: put archived rows back on the board, byte for byte. stdlib only."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from scripts.praxis import archive_io, board_restore


def restore_archive(board: Path, archive_dir: Path, which: str, now: datetime) -> dict[str, object]:
    months = sorted(
        p.stem.removeprefix("messages-") for p in archive_dir.glob(f"messages-*{archive_io.ARCHIVE_SUFFIX}")
    )
    if which != "all":
        months = [m for m in months if m == which]
    data = board.read_bytes()
    states = {m: archive_io.read_state(archive_io.archive_path(archive_dir, m)) for m in months}
    batches: dict[str, list[tuple[str, board_restore.Block]]] = {}
    for month, state in states.items():
        for block in state.active_blocks():
            batches.setdefault(str(block.manifest.get("at")), []).append((month, block))
    lines, rows, reordered = data.splitlines(keepends=True), 0, 0
    for at in sorted(batches, reverse=True):
        lines, n, late = board_restore.restore_blocks(lines, [b for _, b in sorted(batches[at], key=lambda x: x[0])])
        rows, reordered = rows + n, reordered + late
    if b"".join(lines) != data:
        archive_io.atomic_replace(board, b"".join(lines))
    for at in batches:
        for month, block in batches[at]:
            note = {"id": block.ident, "rows": len(block.rows), "at": archive_io.iso(now)}
            archive_io.append_bytes(
                archive_io.archive_path(archive_dir, month), f"<!-- restored {json.dumps(note)} -->\n".encode()
            )
    return {"months": months, "blocks": sum(len(v) for v in batches.values()), "rows_restored": rows,
            "rows_placed_by_time": reordered, "board_bytes_after": board.stat().st_size}  # fmt: skip
