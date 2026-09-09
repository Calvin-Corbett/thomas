"""CAP-101: VS Code editor bridge -- selection/context-aware agent edits.

This module is a thin *editor-bridge protocol core*: it lets a Thomas agent
receive live editor context (the active file, the current selection, the cursor,
and the language-server diagnostics), run a scoped action against that context,
and hand the editor back an *in-editor diff* -- a set of range-scoped text edits
the editor can apply directly. It is the same shape a real VS Code extension
would speak, but nothing here talks to a real editor: the editor lives behind an
injectable :class:`EditorTransport`.

Three pieces make up the bridge:

1. :class:`EditorTransport` -- a small ``request(method, params) -> Mapping``
   protocol (JSON-RPC style). The production default,
   :class:`StdioJsonRpcTransport`, speaks real JSON-RPC 2.0 over stdio with
   LSP-style ``Content-Length`` framing against a peer process (the VS Code
   extension host). For tests, :class:`FakeEditor` implements the same
   ``request`` surface in-memory over a real text buffer -- no VS Code, no
   subprocess, fully hermetic.

2. :class:`VSCodeBridge` -- the protocol core. ``fetch_context()`` pulls the
   :class:`EditorContext`; ``run_action(action, ...)`` runs an *injectable*
   scoped action against that context and produces an :class:`EditorDiff` that
   is *localized to the selection* (a single range edit, never a whole-file
   replace); ``apply(diff)`` sends the edit back through the transport and
   returns an :class:`ApplyResult`.

3. The data model -- :class:`Position`, :class:`Range`, :class:`Diagnostic`,
   :class:`EditorContext`, :class:`TextEdit`, :class:`EditorDiff` -- with pure
   wire (de)serialization shared by both transports so the fake and the real
   default are byte-for-byte protocol-compatible.

The scoped-action contract is deliberately narrow: an action receives the full
:class:`EditorContext` (so it can *read* the whole file and the diagnostics) but
returns only replacement text for the *selected region*. That guarantees the
produced diff touches nothing outside the selection. An action that returns
``None`` -- or text identical to the current selection -- yields an empty diff
(a no-op), so a "nothing to do" action never dirties the buffer.

Live lane (documented, not exercised here): the real VS Code extension host is
GUI- and marketplace-gated. This module proves the protocol + context + diff
core against :class:`FakeEditor`; wiring :class:`StdioJsonRpcTransport` to a
published extension is the live integration and is out of scope for the
hermetic test suite.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, BinaryIO, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

# JSON-RPC method names the bridge speaks to the editor peer.
METHOD_CONTEXT = "editor/context"
METHOD_APPLY_EDIT = "editor/applyEdit"

# Severity vocabulary for diagnostics (LSP-aligned, lower-cased for readability).
SEVERITIES: frozenset[str] = frozenset({"error", "warning", "information", "hint"})


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class VSCodeBridgeError(Exception):
    """Base class for all editor-bridge failures."""


class TransportError(VSCodeBridgeError):
    """The transport could not deliver or decode a message."""


class ProtocolError(VSCodeBridgeError):
    """A message was delivered but did not honour the protocol shape."""


# ---------------------------------------------------------------------------
# Data model -- positions, ranges, diagnostics, context, edits, diffs
# ---------------------------------------------------------------------------
@dataclass(frozen=True, order=True)
class Position:
    """A zero-based ``(line, character)`` position, LSP semantics."""

    line: int
    character: int

    def to_wire(self) -> dict[str, int]:
        return {"line": self.line, "character": self.character}

    @classmethod
    def from_wire(cls, raw: Mapping[str, Any]) -> Position:
        try:
            return cls(line=int(raw["line"]), character=int(raw["character"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ProtocolError(f"malformed position: {raw!r}") from exc


@dataclass(frozen=True)
class Range:
    """A half-open ``[start, end)`` span, LSP semantics."""

    start: Position
    end: Position

    def is_empty(self) -> bool:
        """True when the range selects nothing (start == end)."""
        return self.start == self.end

    def to_wire(self) -> dict[str, Any]:
        return {"start": self.start.to_wire(), "end": self.end.to_wire()}

    @classmethod
    def from_wire(cls, raw: Mapping[str, Any]) -> Range:
        try:
            return cls(
                start=Position.from_wire(raw["start"]),
                end=Position.from_wire(raw["end"]),
            )
        except (KeyError, TypeError) as exc:
            raise ProtocolError(f"malformed range: {raw!r}") from exc


@dataclass(frozen=True)
class Diagnostic:
    """A language-server diagnostic scoped to a range."""

    range: Range
    message: str
    severity: str = "error"
    source: str | None = None

    def to_wire(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "range": self.range.to_wire(),
            "message": self.message,
            "severity": self.severity,
        }
        if self.source is not None:
            payload["source"] = self.source
        return payload

    @classmethod
    def from_wire(cls, raw: Mapping[str, Any]) -> Diagnostic:
        try:
            severity = str(raw.get("severity", "error")).lower()
            return cls(
                range=Range.from_wire(raw["range"]),
                message=str(raw["message"]),
                severity=severity if severity in SEVERITIES else "error",
                source=(str(raw["source"]) if raw.get("source") is not None else None),
            )
        except (KeyError, TypeError) as exc:
            raise ProtocolError(f"malformed diagnostic: {raw!r}") from exc


@dataclass(frozen=True)
class EditorContext:
    """A snapshot of what the editor is showing the agent.

    ``text`` is the *entire* document; ``selection`` is the highlighted range;
    ``selection_text`` is the substring the selection covers (derived from
    ``text`` and ``selection`` so it can never drift); ``cursor`` is the caret;
    ``diagnostics`` are the language-server findings for the file.
    """

    file_path: str
    text: str
    selection: Range
    cursor: Position
    diagnostics: tuple[Diagnostic, ...] = ()

    @property
    def selection_text(self) -> str:
        """The substring the selection covers within ``text``."""
        start = offset_at(self.text, self.selection.start)
        end = offset_at(self.text, self.selection.end)
        return self.text[start:end]

    def diagnostics_in_selection(self) -> tuple[Diagnostic, ...]:
        """Diagnostics whose range starts inside the current selection."""
        lo = self.selection.start
        hi = self.selection.end
        return tuple(d for d in self.diagnostics if lo <= d.range.start < hi or lo == d.range.start)

    def to_wire(self) -> dict[str, Any]:
        return {
            "path": self.file_path,
            "text": self.text,
            "selection": self.selection.to_wire(),
            "cursor": self.cursor.to_wire(),
            "diagnostics": [d.to_wire() for d in self.diagnostics],
        }

    @classmethod
    def from_wire(cls, raw: Mapping[str, Any]) -> EditorContext:
        try:
            diags_raw = raw.get("diagnostics") or ()
            return cls(
                file_path=str(raw["path"]),
                text=str(raw["text"]),
                selection=Range.from_wire(raw["selection"]),
                cursor=Position.from_wire(raw["cursor"]),
                diagnostics=tuple(Diagnostic.from_wire(d) for d in diags_raw),
            )
        except (KeyError, TypeError) as exc:
            raise ProtocolError(f"malformed editor context: {raw!r}") from exc


@dataclass(frozen=True)
class TextEdit:
    """A single range-scoped replacement the editor can apply."""

    range: Range
    new_text: str

    def to_wire(self) -> dict[str, Any]:
        return {"range": self.range.to_wire(), "newText": self.new_text}

    @classmethod
    def from_wire(cls, raw: Mapping[str, Any]) -> TextEdit:
        try:
            return cls(range=Range.from_wire(raw["range"]), new_text=str(raw["newText"]))
        except (KeyError, TypeError) as exc:
            raise ProtocolError(f"malformed text edit: {raw!r}") from exc


@dataclass(frozen=True)
class EditorDiff:
    """An in-editor diff: an ordered set of range-scoped text edits.

    An *empty* diff (no edits) is a well-formed no-op the editor can ignore.
    """

    file_path: str
    edits: tuple[TextEdit, ...] = ()

    def is_empty(self) -> bool:
        return len(self.edits) == 0

    def touches_only(self, region: Range) -> bool:
        """True when every edit is contained within ``region``.

        Used to prove a diff is localized to the selection rather than a
        whole-file replace.
        """
        for edit in self.edits:
            if edit.range.start < region.start or edit.range.end > region.end:
                return False
        return True

    def to_wire(self) -> dict[str, Any]:
        return {"path": self.file_path, "edits": [e.to_wire() for e in self.edits]}


@dataclass(frozen=True)
class ApplyResult:
    """The outcome of applying a diff through the transport."""

    applied: bool
    file_path: str
    text: str | None = None
    detail: str = ""

    @classmethod
    def from_wire(cls, raw: Mapping[str, Any]) -> ApplyResult:
        try:
            return cls(
                applied=bool(raw["applied"]),
                file_path=str(raw.get("path", "")),
                text=(str(raw["text"]) if raw.get("text") is not None else None),
                detail=str(raw.get("detail", "")),
            )
        except (KeyError, TypeError) as exc:
            raise ProtocolError(f"malformed apply result: {raw!r}") from exc


# The action an agent runs against the editor context. It receives the full
# context (so it can read the whole file + diagnostics) and returns replacement
# text for the *selected region only*, or ``None`` for "no change".
ScopedAction = Callable[[EditorContext], "str | None"]


# ---------------------------------------------------------------------------
# Offset helpers -- convert LSP (line, character) <-> string offset
# ---------------------------------------------------------------------------
def _line_start_offsets(text: str) -> list[int]:
    """Return the string offset at which each line begins."""
    offsets = [0]
    for i, ch in enumerate(text):
        if ch == "\n":
            offsets.append(i + 1)
    return offsets


def offset_at(text: str, pos: Position) -> int:
    """Convert an LSP ``(line, character)`` position to a string offset.

    Positions past the end of a line clamp to the line end; positions past the
    document clamp to ``len(text)`` -- mirroring how editors resolve them.
    """
    starts = _line_start_offsets(text)
    if pos.line < 0:
        return 0
    if pos.line >= len(starts):
        return len(text)
    line_start = starts[pos.line]
    line_end = starts[pos.line + 1] - 1 if pos.line + 1 < len(starts) else len(text)
    return min(line_start + max(pos.character, 0), line_end)


def apply_edits(text: str, edits: Sequence[TextEdit]) -> str:
    """Apply range-scoped edits to ``text`` and return the new document.

    Edits are applied from the *last* offset to the *first* so earlier offsets
    stay valid as the string mutates. Overlapping edits raise ``ProtocolError``.
    """
    resolved: list[tuple[int, int, str]] = []
    for edit in edits:
        start = offset_at(text, edit.range.start)
        end = offset_at(text, edit.range.end)
        if end < start:
            start, end = end, start
        resolved.append((start, end, edit.new_text))
    resolved.sort(key=lambda t: t[0])
    for i in range(1, len(resolved)):
        if resolved[i][0] < resolved[i - 1][1]:
            raise ProtocolError("overlapping text edits cannot be applied")
    out = text
    for start, end, new_text in reversed(resolved):
        out = out[:start] + new_text + out[end:]
    return out


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------
@runtime_checkable
class EditorTransport(Protocol):
    """A request/response channel to an editor peer.

    ``request`` sends a method + params and returns the peer's result mapping.
    Implementations must be synchronous and deterministic for a given peer
    state so the bridge core stays testable.
    """

    def request(self, method: str, params: Mapping[str, Any]) -> Mapping[str, Any]: ...


def _encode_message(obj: Mapping[str, Any]) -> bytes:
    """Encode a JSON-RPC message with LSP ``Content-Length`` framing."""
    body = json.dumps(obj, separators=(",", ":"), sort_keys=True).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    return header + body


def _read_message(stream: BinaryIO) -> dict[str, Any]:
    """Read one LSP-framed JSON-RPC message from ``stream``."""
    content_length: int | None = None
    while True:
        line = stream.readline()
        if not line:
            raise TransportError("stream closed before a full header was read")
        stripped = line.strip()
        if stripped == b"":
            break
        if b":" in line:
            name, _, value = line.partition(b":")
            if name.strip().lower() == b"content-length":
                try:
                    content_length = int(value.strip())
                except ValueError as exc:
                    raise TransportError(f"invalid Content-Length: {value!r}") from exc
    if content_length is None:
        raise TransportError("message header missing Content-Length")
    body = stream.read(content_length)
    if len(body) != content_length:
        raise TransportError("stream closed mid-body")
    try:
        return json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise TransportError(f"could not decode message body: {exc}") from exc


class StdioJsonRpcTransport:
    """Production default: JSON-RPC 2.0 over stdio, LSP ``Content-Length`` framing.

    Speaks the real wire protocol against a peer process's stdin/stdout (the VS
    Code extension host). No editor is embedded here -- this is the framing +
    request/response half of the protocol, exercised in the live lane against a
    published extension. Injectable streams keep it unit-testable without a
    subprocess.
    """

    def __init__(self, reader: BinaryIO, writer: BinaryIO) -> None:
        self._reader = reader
        self._writer = writer
        self._next_id = 0

    def request(self, method: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
        self._next_id += 1
        req_id = self._next_id
        message = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": dict(params),
        }
        self._writer.write(_encode_message(message))
        self._writer.flush()
        response = _read_message(self._reader)
        if response.get("id") != req_id:
            raise ProtocolError(f"response id {response.get('id')!r} != request id {req_id!r}")
        if "error" in response:
            raise ProtocolError(f"editor returned error: {response['error']!r}")
        result = response.get("result")
        if not isinstance(result, Mapping):
            raise ProtocolError(f"response result is not a mapping: {result!r}")
        return result


# ---------------------------------------------------------------------------
# Fake editor -- hermetic in-memory peer for tests
# ---------------------------------------------------------------------------
class FakeEditor:
    """A hermetic in-memory editor peer implementing :class:`EditorTransport`.

    Holds a real text buffer, a selection, a cursor, and diagnostics. It answers
    ``editor/context`` from that state and mutates the buffer on
    ``editor/applyEdit`` -- so an apply round-trip is genuinely reflected in the
    buffer. No VS Code, no subprocess, no network.
    """

    def __init__(
        self,
        *,
        file_path: str,
        text: str,
        selection: Range,
        cursor: Position | None = None,
        diagnostics: Sequence[Diagnostic] = (),
    ) -> None:
        self.file_path = file_path
        self.document = text
        self.selection = selection
        self.cursor = cursor if cursor is not None else selection.end
        self.diagnostics = tuple(diagnostics)
        self.applied_edits: list[EditorDiff] = []

    # -- context ---------------------------------------------------------
    def context(self) -> EditorContext:
        return EditorContext(
            file_path=self.file_path,
            text=self.document,
            selection=self.selection,
            cursor=self.cursor,
            diagnostics=self.diagnostics,
        )

    # -- EditorTransport surface ----------------------------------------
    def request(self, method: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
        if method == METHOD_CONTEXT:
            return self.context().to_wire()
        if method == METHOD_APPLY_EDIT:
            return self._apply(params)
        raise ProtocolError(f"fake editor received unknown method: {method!r}")

    def _apply(self, params: Mapping[str, Any]) -> dict[str, Any]:
        edits = tuple(TextEdit.from_wire(e) for e in params.get("edits", ()))
        if not edits:
            # Empty diff is a well-formed no-op: nothing changes, still "applied".
            return {"applied": True, "path": self.file_path, "text": self.document, "detail": "noop"}
        new_text = apply_edits(self.document, edits)
        self.document = new_text
        self.applied_edits.append(EditorDiff(self.file_path, edits))
        return {"applied": True, "path": self.file_path, "text": new_text, "detail": "ok"}


# ---------------------------------------------------------------------------
# Bridge core
# ---------------------------------------------------------------------------
@dataclass
class VSCodeBridge:
    """The editor-bridge protocol core over an injectable transport."""

    transport: EditorTransport
    diagnostics_seen: int = field(default=0, init=False)

    def fetch_context(self) -> EditorContext:
        """Pull the current editor context from the peer."""
        raw = self.transport.request(METHOD_CONTEXT, {})
        ctx = EditorContext.from_wire(raw)
        self.diagnostics_seen = len(ctx.diagnostics)
        logger.debug(
            "fetched editor context path=%s selection=%s diagnostics=%d",
            ctx.file_path,
            ctx.selection,
            len(ctx.diagnostics),
        )
        return ctx

    def run_action(self, action: ScopedAction, context: EditorContext | None = None) -> EditorDiff:
        """Run a scoped ``action`` and produce a selection-localized diff.

        The action reads the full context but may only replace the selected
        region. Returning ``None`` -- or text identical to the current
        selection -- yields an empty (no-op) diff.
        """
        ctx = context if context is not None else self.fetch_context()
        replacement = action(ctx)
        if replacement is None or replacement == ctx.selection_text:
            return EditorDiff(ctx.file_path, ())
        edit = TextEdit(range=ctx.selection, new_text=replacement)
        diff = EditorDiff(ctx.file_path, (edit,))
        if not diff.touches_only(ctx.selection):  # pragma: no cover - invariant guard
            raise ProtocolError("scoped action produced an edit outside the selection")
        return diff

    def apply(self, diff: EditorDiff) -> ApplyResult:
        """Send a diff back to the editor and report the outcome."""
        raw = self.transport.request(METHOD_APPLY_EDIT, diff.to_wire())
        result = ApplyResult.from_wire(raw)
        logger.debug("applied diff path=%s edits=%d applied=%s", diff.file_path, len(diff.edits), result.applied)
        return result

    def run_and_apply(
        self, action: ScopedAction, context: EditorContext | None = None
    ) -> tuple[EditorDiff, ApplyResult]:
        """Convenience: run a scoped action then apply the resulting diff."""
        diff = self.run_action(action, context=context)
        return diff, self.apply(diff)
