"""Read an archive file and put its rows back into a board, byte for byte.

Pure functions, like board_archive.py. A block is only trusted when its manifest
line is present and its rows hash to the manifest's sha256; a half-written block
(a crash mid-append) is ignored rather than guessed at.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from scripts.praxis.board_archive import EOL_BYTES, find_section, parse_fields, parse_time, row_key, rows_digest

logger = logging.getLogger(__name__)

BATCH = "<!-- batch "
END = "<!-- end-batch "
CLOSED = ("<!-- restored ", "<!-- abandoned ")


@dataclass
class Block:
    ident: str
    eol: str
    runs: list[tuple[int, str]]
    rows: list[str]
    manifest: dict[str, object]
    active: bool = True

    @property
    def keys(self) -> list[str]:
        return [row_key(r.encode("utf-8")) for r in self.rows]


@dataclass
class ArchiveState:
    blocks: list[Block] = field(default_factory=list)
    invalid: int = 0
    torn_bytes: int = 0  # bytes of lines that were not valid UTF-8 (a run killed mid-character), skipped

    def active_blocks(self) -> list[Block]:
        return [b for b in self.blocks if b.active]

    def is_active(self, ident: str) -> bool:
        return any(b.ident == ident for b in self.active_blocks())

    def close(self, ident: str) -> None:
        """A restored/abandoned note closes the latest still-active block with that id."""
        for block in reversed(self.blocks):
            if block.ident == ident and block.active:
                block.active = False
                return


def _json_tail(line: str, prefix: str) -> dict | None:
    try:
        value = json.loads(line[len(prefix) :].rsplit(" -->", 1)[0])
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _lines(data: bytes, state: ArchiveState) -> list[str]:
    """Decode line by line, so one torn multi-byte character costs only its own line.

    A kill mid-append can leave a half character at the end of the file, and the next append then
    starts on a fresh line after it. A strict whole-file decode would raise on every later run and
    wedge the archiver for good. A line that is not valid UTF-8 can never be part of a hash-verified
    block (rows are written whole), so it is dropped, counted and logged, and nothing else is touched.
    """
    out: list[str] = []
    for number, raw in enumerate(data.split(b"\n"), start=1):
        try:
            out.append(raw.removesuffix(b"\r").decode("utf-8"))
        except UnicodeDecodeError:
            state.torn_bytes += len(raw)
            logger.warning("archive line %d is not valid UTF-8 (%d bytes, a torn write); skipped", number, len(raw))
            out.append("")
    return out


def parse_archive(data: bytes) -> ArchiveState:
    """Complete, hash-verified blocks in file order, plus which are still active."""
    state = ArchiveState()
    head: dict | None = None
    rows: list[str] = []
    for line in _lines(data, state):
        if line.startswith(BATCH):
            state.invalid += 1 if head is not None else 0
            head, rows = _json_tail(line, BATCH), []
        elif line.startswith(END) and head is not None:
            tail = _json_tail(line, END) or {}
            good = tail.get("id") == head.get("id") and tail.get("sha256") == rows_digest(rows)
            if good and tail.get("rows") == len(rows):
                runs = [(int(a), str(b)) for a, b in head["runs"]]
                state.blocks.append(Block(str(head["id"]), str(head["eol"]), runs, rows, tail))
            else:
                state.invalid += 1
            head = None
        elif line.startswith(CLOSED):
            prefix = next(p for p in CLOSED if line.startswith(p))
            state.close(str((_json_tail(line, prefix) or {}).get("id")))
        elif head is not None:
            rows.append(line)
    state.invalid += 1 if head is not None else 0
    return state


def _is_bullet(raw: bytes) -> bool:
    return raw.strip().startswith(b"- ")


def _by_time(lines: list[bytes], raw: bytes) -> None:
    """Fallback: slot a row among the board's bullets by created_at."""
    start, end = find_section(lines) or (len(lines), len(lines))
    wanted = parse_time((parse_fields(raw.decode("utf-8")) or {}).get("created_at", ""))
    pos = max([i for i in range(start, end) if _is_bullet(lines[i])] or [start - 1]) + 1
    for i in range(start, end):
        fields = parse_fields(lines[i].decode("utf-8", "replace")) if _is_bullet(lines[i]) else None
        stamp = parse_time((fields or {}).get("created_at", ""))
        if wanted and stamp and stamp > wanted:
            pos = i
            break
    lines.insert(pos, raw)


def restore_blocks(lines: list[bytes], blocks: list[Block]) -> tuple[list[bytes], int, int]:
    """Put a batch's blocks back together, so cross-month anchors resolve exactly.

    Returns (new lines, rows put back, rows placed by timestamp instead of position).
    """
    start, end = find_section(lines) or (len(lines), len(lines))
    present = {row_key(r) for r in lines[start:end] if _is_bullet(r)}
    after: dict[str, list[tuple[str, bytes]]] = {}
    order: dict[str, int] = {}
    for block in blocks:
        starts, keys = dict(block.runs), block.keys
        for i, text in enumerate(block.rows):
            if keys[i] in present:
                continue
            anchor = starts[i] if i in starts else keys[i - 1]
            after.setdefault(anchor, []).append((keys[i], text.encode("utf-8") + EOL_BYTES[block.eol]))
            order[keys[i]] = len(order)
    restored = len(order)
    out: list[bytes] = []

    def emit(key: str) -> None:
        stack = [iter(after.pop(key, []))]
        while stack:
            for child, raw in stack[-1]:
                out.append(raw)
                stack.append(iter(after.pop(child, [])))
                break
            else:
                stack.pop()

    first = next((i for i in range(start, end) if _is_bullet(lines[i])), end)
    for idx in range(start, end):
        if idx == first:
            emit("^")
        out.append(lines[idx])
        if _is_bullet(lines[idx]):
            emit(row_key(lines[idx]))
    if first == end:
        emit("^")
    merged = lines[:start] + out + lines[end:]
    leftovers = sorted((order[k], raw) for rest in after.values() for k, raw in rest)
    for _, raw in leftovers:
        _by_time(merged, raw)
    return merged, restored, len(leftovers)
