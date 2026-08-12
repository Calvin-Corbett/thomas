"""IDE-integrated agent bridge for JetBrains IDEs (CAP-102, Level 2).

This module implements a thin, deterministic protocol core that lets a Thomas
agent participate inside a JetBrains editor: it receives the live editor
**context** (open file, selection range/text, caret offset, and a lightweight
PSI-derived structural hint -- the enclosing symbol's name, kind, and text
range), runs a **scoped action** that produces an in-editor **patch** confined
to the enclosing symbol (or the active selection within it), and confirms the
edit by round-tripping the patch back through the IDE.

Design (the injectable-adapter pattern)
---------------------------------------
The IDE edge lives behind the :class:`IdeTransport` protocol -- a single
``roundtrip(request) -> response`` method exchanging JSON-serializable dicts.

* The **real** default, :class:`StdioIdeTransport`, speaks newline-delimited
  JSON (one compact JSON object per line) over a pair of text streams. This is
  the protocol a JetBrains plugin backend would drive over its process stdio
  (the same newline-delimited-JSON shape LSP-style plugin hosts use), and it is
  built entirely on :mod:`json` from the stdlib -- no new pip dependency and no
  network.
* A hermetic :class:`FakeIde` holds an in-memory document plus a PSI symbol
  model and answers the same protocol offline. Every request it sees is
  recorded, so the whole bridge is provable without a running IDE. The exact
  acceptance line is proven against the fake in
  ``tests/test_jetbrains_bridge.py``.

Live lane (documented honestly)
-------------------------------
The real JetBrains plugin host is a GUI/plugin-gated live lane: an installed
plugin would own the editor process and drive :class:`StdioIdeTransport`. That
lane cannot run headless in CI. This module + its tests prove the **protocol**,
the **PSI-context** ingestion, and the **localized-patch** core against the
fake IDE; no live IDE run is claimed here.

Determinism
-----------
Given the same context and the same action, the produced patch is byte-for-byte
identical, including a stable ``patch_id`` derived from a canonical JSON hash of
the edit. No wall-clock, randomness, or ambient state is consulted.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "TextRange",
    "PsiHint",
    "IdeContext",
    "ActionRequest",
    "Patch",
    "ApplyResult",
    "IdeTransport",
    "StdioIdeTransport",
    "FakeIde",
    "JetBrainsBridge",
    "JetBrainsBridgeError",
    "IdeProtocolError",
    "PatchScopeError",
    "PatchApplyError",
    "ScopedAction",
]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class JetBrainsBridgeError(RuntimeError):
    """Base class for all bridge errors."""


class IdeProtocolError(JetBrainsBridgeError):
    """Raised when the IDE transport returns a malformed/incomplete response."""


class PatchScopeError(JetBrainsBridgeError):
    """Raised when an edit would fall outside the enclosing symbol's range."""


class PatchApplyError(JetBrainsBridgeError):
    """Raised when the IDE fails to apply a patch or reports a mismatch."""


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TextRange:
    """A half-open character-offset span ``[start, end)`` into a document.

    Offsets are 0-based character indices, matching JetBrains' ``TextRange``
    (``startOffset``/``endOffset``) convention.
    """

    start: int
    end: int

    def __post_init__(self) -> None:
        if self.start < 0 or self.end < 0:
            raise ValueError("TextRange offsets must be non-negative")
        if self.end < self.start:
            raise ValueError("TextRange end must be >= start")

    @property
    def length(self) -> int:
        return self.end - self.start

    @property
    def is_empty(self) -> bool:
        return self.end == self.start

    def contains(self, other: TextRange) -> bool:
        """True when ``other`` is fully enclosed by this range."""
        return self.start <= other.start and other.end <= self.end

    def slice_of(self, text: str) -> str:
        return text[self.start : self.end]

    def to_json(self) -> dict[str, int]:
        return {"start": self.start, "end": self.end}

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> TextRange:
        try:
            return cls(int(data["start"]), int(data["end"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise IdeProtocolError(f"invalid TextRange payload: {data!r}") from exc


@dataclass(frozen=True)
class PsiHint:
    """Lightweight structural hint distilled from the IDE's PSI tree.

    ``kind`` is a coarse symbol kind (e.g. ``"function"``, ``"method"``,
    ``"class"``). ``range`` is the enclosing symbol's full text range -- the
    hard boundary any scoped edit must stay within.
    """

    symbol_name: str
    symbol_kind: str
    range: TextRange

    def to_json(self) -> dict[str, Any]:
        return {
            "symbol_name": self.symbol_name,
            "symbol_kind": self.symbol_kind,
            "range": self.range.to_json(),
        }

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> PsiHint:
        try:
            return cls(
                symbol_name=str(data["symbol_name"]),
                symbol_kind=str(data["symbol_kind"]),
                range=TextRange.from_json(data["range"]),
            )
        except (KeyError, TypeError) as exc:
            raise IdeProtocolError(f"invalid PsiHint payload: {data!r}") from exc


@dataclass(frozen=True)
class IdeContext:
    """The editor context received from the IDE for a single interaction."""

    file_path: str
    text: str
    caret: int
    selection: TextRange | None
    psi_hint: PsiHint

    @property
    def selected_text(self) -> str:
        return "" if self.selection is None else self.selection.slice_of(self.text)

    @property
    def enclosing_symbol_text(self) -> str:
        return self.psi_hint.range.slice_of(self.text)

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> IdeContext:
        try:
            selection_raw = data.get("selection")
            selection = TextRange.from_json(selection_raw) if selection_raw else None
            return cls(
                file_path=str(data["file_path"]),
                text=str(data["text"]),
                caret=int(data["caret"]),
                selection=selection,
                psi_hint=PsiHint.from_json(data["psi_hint"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise IdeProtocolError(f"invalid IdeContext payload: {data!r}") from exc


@dataclass(frozen=True)
class ActionRequest:
    """What a scoped action sees: only the scope it is allowed to rewrite.

    The action is handed the text of its scope (the active selection if one is
    present within the enclosing symbol, otherwise the whole symbol) plus the
    PSI identity. It never sees -- and therefore cannot edit -- anything outside
    the scope, which is what keeps the resulting patch localized by
    construction.
    """

    file_path: str
    symbol_name: str
    symbol_kind: str
    scope_text: str
    scope_range: TextRange
    is_selection_scoped: bool


@dataclass(frozen=True)
class Patch:
    """A single localized replacement edit, ready to apply in the editor."""

    file_path: str
    range: TextRange
    original_text: str
    replacement_text: str
    patch_id: str = field(default="", compare=False)

    def to_json(self) -> dict[str, Any]:
        return {
            "file_path": self.file_path,
            "range": self.range.to_json(),
            "original_text": self.original_text,
            "replacement_text": self.replacement_text,
            "patch_id": self.patch_id,
        }

    def preview(self, text: str) -> str:
        """Return what ``text`` becomes once this patch is applied."""
        return text[: self.range.start] + self.replacement_text + text[self.range.end :]


@dataclass(frozen=True)
class ApplyResult:
    """Outcome of round-tripping a patch through the IDE."""

    ok: bool
    patch_id: str
    new_text: str
    applied_range: TextRange


# ---------------------------------------------------------------------------
# Transport seam
# ---------------------------------------------------------------------------


@runtime_checkable
class IdeTransport(Protocol):
    """The injectable IDE edge: exchange one JSON request for one JSON reply."""

    def roundtrip(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        """Send a JSON-serializable request, return the JSON-serializable reply."""
        ...


def _canonical(payload: Mapping[str, Any]) -> str:
    """Deterministic compact JSON encoding (sorted keys, no incidental spaces)."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class StdioIdeTransport:
    """Real default transport: newline-delimited JSON over two text streams.

    ``writer`` receives one compact JSON object per line (terminated by ``\\n``
    and flushed); ``reader.readline()`` yields the reply line. This is the shape
    a JetBrains plugin backend drives over its process stdio. It is deliberately
    dependency-free (stdlib :mod:`json` only) and does no network I/O.
    """

    def __init__(self, reader: Any, writer: Any) -> None:
        self._reader = reader
        self._writer = writer

    def roundtrip(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        self._writer.write(_canonical(request) + "\n")
        flush = getattr(self._writer, "flush", None)
        if callable(flush):
            flush()
        line = self._reader.readline()
        if not line:
            raise IdeProtocolError("IDE transport closed before replying")
        try:
            reply = json.loads(line)
        except json.JSONDecodeError as exc:
            raise IdeProtocolError(f"IDE reply was not valid JSON: {line!r}") from exc
        if not isinstance(reply, dict):
            raise IdeProtocolError(f"IDE reply was not a JSON object: {reply!r}")
        return reply


# ---------------------------------------------------------------------------
# Hermetic fake IDE
# ---------------------------------------------------------------------------


class FakeIde:
    """In-memory JetBrains-style editor for hermetic tests.

    Holds a document plus a PSI symbol model (symbols carry a name, kind, and
    text range). Answers the same protocol :class:`StdioIdeTransport` would,
    resolving the enclosing symbol for the current caret and applying patches to
    its buffer. Every request is recorded in :attr:`requests`.
    """

    def __init__(
        self,
        *,
        file_path: str,
        text: str,
        caret: int,
        symbols: list[PsiHint],
        selection: TextRange | None = None,
    ) -> None:
        self.file_path = file_path
        self.text = text
        self.caret = caret
        self.selection = selection
        self._symbols = list(symbols)
        self.requests: list[dict[str, Any]] = []

    # -- PSI resolution ----------------------------------------------------

    def _enclosing_symbol(self, offset: int) -> PsiHint:
        """Innermost symbol whose range contains ``offset`` (smallest wins)."""
        candidates = [s for s in self._symbols if s.range.start <= offset <= s.range.end]
        if not candidates:
            raise IdeProtocolError(f"no enclosing symbol at offset {offset}")
        return min(candidates, key=lambda s: s.range.length)

    # -- protocol ----------------------------------------------------------

    def roundtrip(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        # Round-trip through JSON so the fake exercises the same serialization
        # boundary the real stdio transport does (no live object smuggling).
        request = json.loads(_canonical(request))
        self.requests.append(request)
        method = request.get("method")
        if method == "context":
            return self._handle_context()
        if method == "apply":
            return self._handle_apply(request)
        raise IdeProtocolError(f"unknown IDE method: {method!r}")

    def _handle_context(self) -> dict[str, Any]:
        hint = self._enclosing_symbol(self.caret)
        payload: dict[str, Any] = {
            "file_path": self.file_path,
            "text": self.text,
            "caret": self.caret,
            "selection": self.selection.to_json() if self.selection else None,
            "psi_hint": hint.to_json(),
        }
        return {"ok": True, "context": payload}

    def _handle_apply(self, request: Mapping[str, Any]) -> dict[str, Any]:
        patch_raw = request.get("patch")
        if not isinstance(patch_raw, Mapping):
            raise IdeProtocolError("apply request missing patch object")
        rng = TextRange.from_json(patch_raw["range"])
        original = str(patch_raw.get("original_text", ""))
        replacement = str(patch_raw.get("replacement_text", ""))
        if rng.end > len(self.text):
            raise PatchApplyError(f"patch range {rng} exceeds document length {len(self.text)}")
        if rng.slice_of(self.text) != original:
            raise PatchApplyError("patch original_text does not match current document (stale patch)")
        self.text = self.text[: rng.start] + replacement + self.text[rng.end :]
        applied = TextRange(rng.start, rng.start + len(replacement))
        return {
            "ok": True,
            "text": self.text,
            "applied_range": applied.to_json(),
            "patch_id": patch_raw.get("patch_id", ""),
        }


# ---------------------------------------------------------------------------
# Scoped action + bridge core
# ---------------------------------------------------------------------------


ScopedAction = Callable[[ActionRequest], str]
"""A pure edit: given the in-scope text + PSI identity, return replacement text."""


class JetBrainsBridge:
    """Protocol core wiring an agent's scoped edits to a JetBrains editor."""

    def __init__(self, transport: IdeTransport) -> None:
        self._transport = transport

    # -- context ingestion -------------------------------------------------

    def fetch_context(self) -> IdeContext:
        """Ask the IDE for the current editor context (incl. the PSI hint)."""
        reply = self._transport.roundtrip({"method": "context"})
        if not reply.get("ok"):
            raise IdeProtocolError(f"IDE refused context request: {reply!r}")
        context_raw = reply.get("context")
        if not isinstance(context_raw, Mapping):
            raise IdeProtocolError("context reply missing 'context' object")
        return IdeContext.from_json(context_raw)

    # -- scoping -----------------------------------------------------------

    @staticmethod
    def resolve_scope(context: IdeContext) -> ActionRequest:
        """Compute the editable scope, enforcing the PSI symbol boundary.

        Prefers an active selection when present, but a selection that escapes
        the enclosing symbol is rejected -- the enclosing symbol range is the
        hard localization boundary.
        """
        symbol_range = context.psi_hint.range
        selection = context.selection
        if selection is not None and not selection.is_empty:
            if not symbol_range.contains(selection):
                raise PatchScopeError(
                    f"selection {selection} escapes enclosing symbol {context.psi_hint.symbol_name} {symbol_range}"
                )
            scope_range = selection
            is_selection_scoped = True
        else:
            scope_range = symbol_range
            is_selection_scoped = False
        return ActionRequest(
            file_path=context.file_path,
            symbol_name=context.psi_hint.symbol_name,
            symbol_kind=context.psi_hint.symbol_kind,
            scope_text=scope_range.slice_of(context.text),
            scope_range=scope_range,
            is_selection_scoped=is_selection_scoped,
        )

    # -- patch production --------------------------------------------------

    def build_patch(self, context: IdeContext, action: ScopedAction) -> Patch:
        """Run ``action`` over the resolved scope and build a localized patch.

        The patch replaces exactly the scope range, so it is localized to the
        enclosing symbol by construction; a defensive check re-asserts the
        edit does not exceed the symbol range.
        """
        request = self.resolve_scope(context)
        replacement = action(request)
        if not isinstance(replacement, str):
            raise PatchScopeError(f"scoped action must return str, got {type(replacement).__name__}")

        symbol_range = context.psi_hint.range
        if not symbol_range.contains(request.scope_range):
            raise PatchScopeError(
                f"patch range {request.scope_range} exceeds enclosing symbol "
                f"{context.psi_hint.symbol_name} {symbol_range}"
            )

        original = request.scope_range.slice_of(context.text)
        patch = Patch(
            file_path=context.file_path,
            range=request.scope_range,
            original_text=original,
            replacement_text=replacement,
        )
        patch_id = self._patch_id(patch)
        return Patch(
            file_path=patch.file_path,
            range=patch.range,
            original_text=patch.original_text,
            replacement_text=patch.replacement_text,
            patch_id=patch_id,
        )

    @staticmethod
    def _patch_id(patch: Patch) -> str:
        canonical = _canonical(
            {
                "file_path": patch.file_path,
                "range": patch.range.to_json(),
                "original_text": patch.original_text,
                "replacement_text": patch.replacement_text,
            }
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    # -- apply round-trip --------------------------------------------------

    def apply_patch(self, patch: Patch) -> ApplyResult:
        """Send the patch to the IDE and confirm the applied round-trip."""
        reply = self._transport.roundtrip({"method": "apply", "patch": patch.to_json()})
        if not reply.get("ok"):
            raise PatchApplyError(f"IDE refused to apply patch {patch.patch_id}: {reply!r}")
        new_text = reply.get("text")
        if not isinstance(new_text, str):
            raise PatchApplyError("apply reply missing updated document text")
        applied_range = TextRange.from_json(reply["applied_range"])
        # Confirm the IDE spliced exactly what we asked for at the right place.
        if applied_range.slice_of(new_text) != patch.replacement_text:
            raise PatchApplyError("applied region does not match patch replacement (round-trip mismatch)")
        return ApplyResult(
            ok=True,
            patch_id=patch.patch_id,
            new_text=new_text,
            applied_range=applied_range,
        )

    # -- convenience -------------------------------------------------------

    def scoped_edit(self, action: ScopedAction) -> tuple[Patch, ApplyResult]:
        """Fetch context, build the localized patch, and apply it end-to-end."""
        context = self.fetch_context()
        patch = self.build_patch(context, action)
        result = self.apply_patch(patch)
        return patch, result
