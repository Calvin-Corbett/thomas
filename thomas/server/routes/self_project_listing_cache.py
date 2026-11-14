"""Bound a self-project listing request without blocking its project starter."""

from __future__ import annotations

import asyncio
import codecs
import copy
import json
import logging
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)
# A streamed conversation record is read in 64 KiB pieces and only its listing fields are kept, so its size does not
# decide how much memory the read takes. The first cap is a safety valve far above any real record (a long-running
# team writes tens of MB of transcripts); the second bounds what is kept, not what is read.
MAX_PROJECT_RECORD_BYTES = 1 << 30
MAX_PROJECT_SUMMARY_BYTES = 4 << 20
MAX_CONVERSATION_KEPT_BYTES = 128 << 20  # what read_conversation may keep: every field but each transcript's tail
TRANSCRIPT_TAIL_CHARS = 200_000  # autopilot_park._TAIL_CHARS: the most of one transcript any decision reads
# A file read whole (the registry, the queue, a verdict) stays small; a conversation never goes through read_record.
MAX_WHOLE_FILE_BYTES = 32_000_000
_MAX_SCALAR = 65_536
_READ_CHUNK = 65_536
try:  # possessive quantifiers (Python 3.11+) pass an escape-dense transcript about seven times faster
    _PLAIN_RUN = re.compile(r'(?:[^"\\\x00-\x1f]++|\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))*+')
except re.error:  # pragma: no cover - Python 3.10
    _PLAIN_RUN = re.compile(r'(?:[^"\\\x00-\x1f]+|\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))*')
_SKIP = object()
# A record read in full once is not read again until its file changes: path -> ((mtime_ns, size), listing fields).
# Reading every record whole is what lets a long-running team stay listed, so it must not be paid on every refresh.
_PARSED: dict[str, tuple[tuple[int, int], dict[str, Any]]] = {}
_NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?\Z")
_TURN_FIELDS = frozenset(
    {
        "role",
        "ts",
        "run_id",
        "text",
        "status",
        "error",
        "reason",
        "outcome",
        "ok",
        "changed_files",
        "success",
        "completed",
        "model",
        "usage",
        "metadata",
        "finish_reason",
        "stop_reason",
        "result",
        "duration",
        "duration_ms",
    }
)
_ROOT_FIELDS = frozenset({"id", "title", "created_at", "updated_at", "thomas_project", "settings", "turns"})


class RecordTooLarge(ValueError):
    """A record past a safety valve: it may be intact, but this read will not take it."""


def read_record(path: Path, limit: int = MAX_WHOLE_FILE_BYTES):
    """Read at most limit plus one bytes, even if the file grows during the read."""
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise RecordTooLarge("file is larger than the safety limit for a file read whole")
    return json.loads(raw)


class _ProjectJSON:
    """Validate a JSON document while projecting only listing data.

    The input buffer is at most 64 KiB; ignored strings are validated without
    storing them. Kept values and container entries share a 64 KiB budget.
    User text is kept only as a 256-character prefix for turn classification.
    """

    def __init__(self, stream, *, whole=False):
        self.stream = stream
        self.whole = whole  # keep every field, but only the tail of each transcript (read_conversation)
        self.decoder = codecs.getincrementaldecoder("utf-8-sig")("strict")
        self.buffer = ""
        self.pos = 0
        self.count = 0
        self.eof = False
        self.budget = 0

    def charge(self, amount):
        self.budget += amount
        if self.budget > (MAX_CONVERSATION_KEPT_BYTES if self.whole else MAX_PROJECT_SUMMARY_BYTES):
            raise RecordTooLarge("what is kept of it is larger than the safety limit")

    def escape(self):
        """The character an escape stands for; its backslash is already taken."""
        escape = self.take()
        if escape == "u":
            digits = "".join(self.take() for _ in range(4))
            if len(digits) != 4 or any(c not in "0123456789abcdefABCDEF" for c in digits):
                raise ValueError("invalid unicode escape")
            return chr(int(digits, 16))
        if escape and escape in '"\\/bfnrt':
            return {"b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}.get(escape, escape)
        raise ValueError("invalid escape")

    def bulk_string(self, tail):
        """A kept string taken a piece at a time: all of it, or only its last ``tail`` characters."""
        parts, held = [], 0
        while True:
            self.peek()
            start = self.pos
            self.pos = _PLAIN_RUN.match(self.buffer, self.pos).end()
            piece = json.loads('"' + self.buffer[start : self.pos] + '"') if self.pos > start else ""
            # The plain run reached the end of what is read so far: the string goes on in the next piece, and the
            # next character is not its terminator. (Taking it as one refused every string that crossed 64 KiB.)
            char = None if self.pos == len(self.buffer) and not self.eof else self.take()
            if char and char != '"' and char != "\\":
                raise ValueError("control character in string")
            if char == "\\":
                piece += self.escape()
            elif char == "":
                raise ValueError("unterminated string")
            if piece:
                parts.append(piece)
                held += len(piece)
                if tail is None:
                    self.charge(len(piece))
                while tail is not None and len(parts) > 1 and held - len(parts[0]) >= tail:
                    held -= len(parts.pop(0))
            if char == '"':
                break
        text = "".join(parts)
        if tail is not None:
            text = text[-tail:]
            self.charge(len(text))
        return text.encode("utf-16-le", "surrogatepass").decode("utf-16-le", "surrogatepass")

    def peek(self):
        while self.pos == len(self.buffer) and not self.eof:
            raw = self.stream.read(min(_READ_CHUNK, MAX_PROJECT_RECORD_BYTES + 1 - self.count))
            self.count += len(raw)
            if self.count > MAX_PROJECT_RECORD_BYTES:
                raise RecordTooLarge("record is larger than the safety limit")
            self.eof = not raw
            self.buffer = self.decoder.decode(raw, final=self.eof)
            self.pos = 0
        return self.buffer[self.pos] if self.pos < len(self.buffer) else ""

    def take(self):
        char = self.peek()
        if char:
            self.pos += 1
        return char

    def whitespace(self):
        while self.peek() in (" ", "\t", "\r", "\n"):
            self.pos += 1

    def string(self, mode):
        if self.take() != '"':
            raise ValueError("expected string")
        if mode == "tail" or (self.whole and mode in ("keep", "prefix")):
            return self.bulk_string(TRANSCRIPT_TAIL_CHARS if mode == "tail" else None)
        result = []
        length = 0
        while True:
            # Text that is ignored, or a prefix already full, is validated and never kept: its plain stretch is passed
            # in one step. Without this a multi-MB transcript was walked one character at a time (2 MB/s).
            if not mode or (mode == "prefix" and length >= 256):
                self.peek()
                self.pos = _PLAIN_RUN.match(self.buffer, self.pos).end()
            char = self.take()
            if not char:
                raise ValueError("unterminated string")
            if char == '"':
                if not mode:
                    return _SKIP
                return "".join(result).encode("utf-16-le", "surrogatepass").decode("utf-16-le", "surrogatepass")
            if ord(char) < 32:
                raise ValueError("control character in string")
            if char == "\\":
                char = self.escape()
            if mode and (mode != "prefix" or length < 256):
                if result and 0xD800 <= ord(result[-1]) <= 0xDBFF and 0xDC00 <= ord(char) <= 0xDFFF:
                    result[-1] = chr(0x10000 + ((ord(result[-1]) - 0xD800) << 10) + ord(char) - 0xDC00)
                else:
                    self.charge(4)
                    result.append(char)
                    length += 1

    def value(self, mode, depth=0):
        if depth > 150:
            raise ValueError("record is nested too deeply")
        self.whitespace()
        char = self.peek()
        if char == '"':
            return self.string(mode)
        if char == "{":
            self.take()
            result = {} if mode else _SKIP
            self.whitespace()
            if self.peek() == "}":
                self.take()
                return result
            while True:
                self.whitespace()
                # Keys must be bounded even in skipped objects, without retaining them.
                key = self.string("key" if mode else None)
                self.whitespace()
                if self.take() != ":":
                    raise ValueError("expected colon")
                if mode == "root":
                    child = ("turns" if key == "turns" else "keep") if self.whole or key in _ROOT_FIELDS else None
                elif mode == "turn" and self.whole and key == "transcript":
                    child = "tail"
                elif mode == "turn":
                    child = ("prefix" if key == "text" else "keep") if self.whole or key in _TURN_FIELDS else None
                else:
                    child = "keep" if mode else None
                val = self.value(child, depth + 1)
                if child:
                    self.charge(16)
                    result[key] = val
                self.whitespace()
                separator = self.take()
                if separator == "}":
                    return result
                if separator != ",":
                    raise ValueError("expected comma or object end")
        if char == "[":
            self.take()
            result = [] if mode else _SKIP
            self.whitespace()
            if self.peek() == "]":
                self.take()
                return result
            while True:
                child = "turn" if mode == "turns" else ("keep" if mode else None)
                val = self.value(child, depth + 1)
                if child:
                    self.charge(8)
                    result.append(val)
                self.whitespace()
                separator = self.take()
                if separator == "]":
                    return result
                if separator != ",":
                    raise ValueError("expected comma or array end")
        token = []
        while self.peek() and self.peek() not in " \t\r\n,]}:":
            token.append(self.take())
            if len(token) > _MAX_SCALAR:
                raise ValueError("JSON scalar is too large")
        literal = "".join(token)
        if literal in ("true", "false", "null", "NaN", "Infinity", "-Infinity") or _NUMBER.fullmatch(literal):
            val = json.loads(literal)
        else:
            raise ValueError("invalid JSON value")
        if mode:
            self.charge(len(literal) + 8)
            return val
        return _SKIP

    def read(self):
        result = self.value("root")
        self.whitespace()
        if self.peek():
            raise ValueError("extra data after JSON value")
        return result


def read_conversation(path: Path):
    """A conversation as the restart survey reads it: every field, but each run's transcript cut to its tail.

    Streamed in 64 KiB pieces, so the memory taken follows what is kept and not the size of the file: a team's
    record is tens of MB of transcripts, and a whole-file read took three times that at once.
    """
    with path.open("rb") as stream:
        return _ProjectJSON(stream, whole=True).read()


def read_project_records(folder: Path, *, strict=False, unread=None, warnings=None, failures=None):
    """Skip individual bad records; folder failures still mark a listing incomplete."""
    found = []
    try:
        paths = sorted(path for path in folder.iterdir() if path.name.endswith(".json"))
    except FileNotFoundError:
        return found
    except OSError:
        if strict:
            raise
        return found
    for path in paths:
        try:
            seen = path.stat()
            stamp = (seen.st_mtime_ns, seen.st_size)
            cached = _PARSED.get(str(path))
            if cached is not None and cached[0] == stamp:
                if cached[1].get("thomas_project", {}).get("execution_id"):
                    found.append(copy.deepcopy(cached[1]))  # unchanged since the last scan: nothing to read again
                continue
            with path.open("rb") as stream:
                conversation = _ProjectJSON(stream).read()
            if not isinstance(conversation, dict) or conversation.get("id") != path.stem:
                raise ValueError("conversation identity does not match its filename")
            project = conversation.get("thomas_project", {})
            if not isinstance(project, dict):
                raise ValueError("Thomas project must be an object")
            execution_id = project.get("execution_id")
            if "thomas_project" in conversation and (not isinstance(execution_id, str) or not execution_id.strip()):
                raise ValueError("Thomas project must identify its execution")
            for field in ("settings",):
                if field in conversation and not isinstance(conversation[field], dict):
                    raise ValueError(f"{field} must be an object")
            if "retirement" in project and not isinstance(project["retirement"], dict):
                raise ValueError("project retirement must be an object")
            repairs = project.get("repairs", [])
            if not isinstance(repairs, list) or any(not isinstance(row, dict) for row in repairs):
                raise ValueError("project repairs must be a list of objects")
            turns = conversation.get("turns", [])
            if not isinstance(turns, list) or any(not isinstance(turn, dict) for turn in turns):
                raise ValueError("project turns must be a list of objects")
            if any("metadata" in turn and not isinstance(turn["metadata"], dict) for turn in turns):
                raise ValueError("turn metadata must be an object")
        except FileNotFoundError:
            continue
        except (OSError, ValueError, RecursionError, MemoryError) as exc:
            # Only real corruption is "unreadable". A record this read would not take (past a safety valve, or out of
            # memory) may be intact: it is named in the report so you can see the project exists.
            refused = isinstance(exc, (RecordTooLarge, MemoryError, RecursionError))
            warning = f"Skipped project {path.stem} in {folder}: " + (
                f"not listed, {exc or type(exc).__name__}" if refused else f"unreadable ({exc})"
            )
            if failures is not None and (refused or isinstance(exc, PermissionError)):
                from thomas.server.routes.self_project_unreadable import unread as unread_record

                failures.append(unread_record(path, exc, warning))
            if warnings is not None:
                if warning not in warnings:
                    warnings.append(warning)
            else:
                log.warning("%s", warning)
            continue
        _PARSED[str(path)] = (stamp, conversation)
        if execution_id:
            found.append(copy.deepcopy(conversation))
    return found


def read_registry(catalog: Path, unreadable: list[str]) -> dict[str, Any]:
    from thomas.forge.anvil import forge_code_conversations

    path = forge_code_conversations._registry_path(catalog)
    try:
        payload = read_record(path)
        if not isinstance(payload, dict) or any(not isinstance(row, dict) for row in payload.values()):
            raise ValueError("malformed project registry")
        return payload
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, MemoryError) as exc:
        # A shared registry failure cannot be assigned to one skipped project.
        unreadable.append(f"{path}: {exc}")
        return {}


async def read_listing(
    slot: dict[str, Any],
    catalog: Path,
    running: frozenset[str] | set[str] | Callable[[], set[str]],
    reader: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    """Wait briefly for a fresh report; keep the last complete report during a long scan."""
    task = slot.get("task")
    snapshot = slot.get("snapshot")
    if task is None or (task.done() and (slot.get("dirty") or time.monotonic() - slot.get("updated", 0) > 2)):

        async def refresh() -> None:
            # A start during a scan must be included in a later scan before the list is complete.
            while True:
                # Consuming dirty must not make a pre-start snapshot eligible for capacity.
                slot["invalidated"] = bool(slot.get("invalidated") or slot.get("dirty"))
                slot["dirty"] = False
                try:
                    current_running = running() if callable(running) else running
                    captured_at = time.time()
                    result = await asyncio.to_thread(reader, catalog, current_running)
                except Exception:
                    slot["error"] = "The list of Thomas projects could not be read. Try again."
                    slot["updated"] = time.monotonic()
                    log.exception("Could not refresh self-project listing")
                    if not slot.get("dirty"):
                        slot["finished"] = True
                        return
                else:
                    if not slot.get("dirty"):
                        incomplete = result.get("ok") is False or bool(
                            result.get("incomplete") or result.get("unreadable")
                        )
                        previous = slot.get("snapshot")
                        previous_complete = previous is not None and not (
                            previous.get("ok") is False or previous.get("incomplete") or previous.get("unreadable")
                        )
                        if not incomplete or not previous_complete:
                            slot["snapshot"] = result
                            slot["captured_at"] = captured_at
                        slot["incomplete"] = incomplete
                        slot["preserved"] = incomplete and previous_complete
                        slot["unreadable"] = result.get("unreadable", [])
                        slot["invalidated"] = incomplete
                        slot["error"] = None
                        slot["updated"] = time.monotonic()
                        slot["finished"] = True
                        return
                # No cached or pre-start result may be marked complete after a start.

        # Keep invalidation visible while refresh() consumes the dirty flag.
        # Old cards may still be displayed, but cannot authorize another start.
        slot["invalidated"] = bool(slot.get("invalidated") or slot.get("dirty"))
        slot["finished"] = False
        task = asyncio.create_task(refresh())
        slot["task"] = task
    if snapshot is None and not task.done():
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=0.75)
        except TimeoutError:
            pass
    snapshot = slot.get("snapshot")
    if snapshot is None and slot.get("error") and slot.get("finished") and not slot.get("dirty"):
        return {"ok": False, "error": slot["error"], "refreshing": False}
    if snapshot is None:
        snapshot = {"ok": True, "projects": [], "unreadable": []}
    return {
        **snapshot,
        **({"incomplete": True, "unreadable": slot.get("unreadable", [])} if slot.get("incomplete") else {}),
        "refreshing": (
            not slot.get("finished", False)
            or bool(slot.get("error"))
            or bool(slot.get("dirty"))
            or bool(slot.get("preserved"))
        ),
    }
