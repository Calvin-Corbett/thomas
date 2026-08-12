"""Hermetic tests for the JetBrains IDE bridge (CAP-102, Level 2).

Every test injects :class:`FakeIde` -- no real IDE, no GUI, no network. The
exact acceptance line is proven against the fake:

* IDE context including the PSI/enclosing-symbol hint is received and scopes
  the action to that symbol.
* The produced patch is localized (its range does not exceed the symbol range).
* Apply round-trips through the fake IDE (the buffer actually changes).
* The whole flow is deterministic (identical patch + patch_id across runs).
"""

from __future__ import annotations

import io

import pytest

from thomas.integrations.jetbrains_bridge import (
    ActionRequest,
    ApplyResult,
    FakeIde,
    IdeProtocolError,
    JetBrainsBridge,
    Patch,
    PatchApplyError,
    PatchScopeError,
    PsiHint,
    StdioIdeTransport,
    TextRange,
)

# A small source document with two functions. Offsets are character-based.
#            0         1         2         3         4         5         6
#            0123456789012345678901234567890123456789012345678901234567890
SOURCE = "def greet(name):\n    return 'hi'\n\ndef add(a, b):\n    return a - b\n"

# Enclosing-symbol ranges (verified below in a sanity test).
GREET_RANGE = TextRange(0, SOURCE.index("\n\n"))  # the whole `greet` def
ADD_START = SOURCE.index("def add")
ADD_RANGE = TextRange(ADD_START, len(SOURCE) - 1)  # the whole `add` def (drop trailing \n)


def _symbols() -> list[PsiHint]:
    return [
        PsiHint("greet", "function", GREET_RANGE),
        PsiHint("add", "function", ADD_RANGE),
    ]


def _fake_on_add(selection: TextRange | None = None) -> FakeIde:
    """A fake IDE with the caret parked inside the `add` function."""
    caret = SOURCE.index("a - b")
    return FakeIde(
        file_path="proj/calc.py",
        text=SOURCE,
        caret=caret,
        symbols=_symbols(),
        selection=selection,
    )


def test_sanity_symbol_ranges_are_well_formed() -> None:
    assert SOURCE[GREET_RANGE.start : GREET_RANGE.end].startswith("def greet")
    add_text = SOURCE[ADD_RANGE.start : ADD_RANGE.end]
    assert add_text.startswith("def add")
    assert add_text.endswith("a - b")


# ---------------------------------------------------------------------------
# (1) PSI context received + scopes the action to the enclosing symbol
# ---------------------------------------------------------------------------


def test_context_carries_psi_hint_and_scopes_to_enclosing_symbol() -> None:
    fake = _fake_on_add()
    bridge = JetBrainsBridge(fake)

    context = bridge.fetch_context()

    # PSI/enclosing-symbol hint is received and identifies `add`, not `greet`.
    assert context.psi_hint.symbol_name == "add"
    assert context.psi_hint.symbol_kind == "function"
    assert context.psi_hint.range == ADD_RANGE
    assert context.file_path == "proj/calc.py"

    # The resolved action scope is confined to the `add` symbol text.
    request = bridge.resolve_scope(context)
    assert request.symbol_name == "add"
    assert request.scope_range == ADD_RANGE
    assert request.scope_text == context.enclosing_symbol_text
    assert "greet" not in request.scope_text
    assert request.is_selection_scoped is False

    # The IDE was actually asked for context over the protocol.
    assert fake.requests == [{"method": "context"}]


# ---------------------------------------------------------------------------
# (2) Patch is localized -- never exceeds the enclosing symbol range
# ---------------------------------------------------------------------------


def test_patch_is_localized_to_symbol_range() -> None:
    fake = _fake_on_add()
    bridge = JetBrainsBridge(fake)
    context = bridge.fetch_context()

    # Action fixes the bug `a - b` -> `a + b` by rewriting the whole symbol.
    def fix(req: ActionRequest) -> str:
        return req.scope_text.replace("a - b", "a + b")

    patch = bridge.build_patch(context, fix)

    # Localization: the patch range must not exceed the enclosing symbol range.
    assert context.psi_hint.range.contains(patch.range)
    assert patch.range.start >= ADD_RANGE.start
    assert patch.range.end <= ADD_RANGE.end
    # The greet symbol is entirely outside the edit.
    assert patch.range.start >= GREET_RANGE.end
    # The replacement contains the fix and nothing from the other function.
    assert "a + b" in patch.replacement_text
    assert "greet" not in patch.replacement_text


def test_selection_within_symbol_narrows_scope() -> None:
    # Select exactly the `a - b` expression inside `add`.
    expr_start = SOURCE.index("a - b")
    selection = TextRange(expr_start, expr_start + len("a - b"))
    fake = _fake_on_add(selection=selection)
    bridge = JetBrainsBridge(fake)
    context = bridge.fetch_context()

    request = bridge.resolve_scope(context)
    assert request.is_selection_scoped is True
    assert request.scope_range == selection
    assert request.scope_text == "a - b"

    patch = bridge.build_patch(context, lambda req: "a + b")
    # Still localized -- and now even tighter than the whole symbol.
    assert ADD_RANGE.contains(patch.range)
    assert patch.range == selection
    assert patch.range.length < ADD_RANGE.length


def test_selection_escaping_symbol_is_rejected() -> None:
    # Selection spans from inside `add` past the end of its symbol range.
    bad_selection = TextRange(ADD_RANGE.start, ADD_RANGE.end + 1)
    fake = _fake_on_add(selection=bad_selection)
    bridge = JetBrainsBridge(fake)
    context = bridge.fetch_context()

    with pytest.raises(PatchScopeError):
        bridge.resolve_scope(context)


# ---------------------------------------------------------------------------
# (3) Apply round-trips through the fake IDE
# ---------------------------------------------------------------------------


def test_apply_round_trips_through_ide() -> None:
    fake = _fake_on_add()
    bridge = JetBrainsBridge(fake)

    patch, result = bridge.scoped_edit(lambda req: req.scope_text.replace("a - b", "a + b"))

    assert isinstance(result, ApplyResult)
    assert result.ok is True
    # The fake IDE's buffer actually changed and now contains the fixed code.
    assert fake.text.endswith("return a + b\n")
    assert "a - b" not in fake.text
    # greet is untouched.
    assert "def greet(name):\n    return 'hi'" in fake.text
    # The applied region in the returned document equals our replacement.
    assert result.applied_range.slice_of(result.new_text) == patch.replacement_text
    # Protocol trace: one context request, then one apply request.
    assert [r["method"] for r in fake.requests] == ["context", "apply"]


def test_apply_detects_stale_patch() -> None:
    fake = _fake_on_add()
    bridge = JetBrainsBridge(fake)
    context = bridge.fetch_context()
    patch = bridge.build_patch(context, lambda req: "a + b")

    # Someone else edits the buffer first, invalidating the patch's original.
    fake.text = fake.text.replace("a - b", "a * b")
    with pytest.raises(PatchApplyError):
        bridge.apply_patch(patch)


# ---------------------------------------------------------------------------
# (4) Determinism
# ---------------------------------------------------------------------------


def test_patch_is_deterministic_including_patch_id() -> None:
    def run() -> Patch:
        fake = _fake_on_add()
        bridge = JetBrainsBridge(fake)
        context = bridge.fetch_context()
        return bridge.build_patch(context, lambda req: req.scope_text.replace("a - b", "a + b"))

    first = run()
    second = run()

    assert first.patch_id == second.patch_id
    assert first.patch_id != ""
    assert len(first.patch_id) == 64  # sha256 hexdigest
    assert first.range == second.range
    assert first.replacement_text == second.replacement_text
    assert first.to_json() == second.to_json()


# ---------------------------------------------------------------------------
# Real transport: exercise the newline-delimited JSON protocol end-to-end
# ---------------------------------------------------------------------------


def test_stdio_transport_speaks_newline_delimited_json() -> None:
    # Reader supplies a canned context reply as one JSON line.
    reply_line = (
        '{"ok": true, "context": {"file_path": "x.py", "text": "def f():\\n    return 1\\n", '
        '"caret": 4, "selection": null, "psi_hint": {"symbol_name": "f", "symbol_kind": '
        '"function", "range": {"start": 0, "end": 20}}}}\n'
    )
    reader = io.StringIO(reply_line)
    writer = io.StringIO()
    transport = StdioIdeTransport(reader, writer)
    bridge = JetBrainsBridge(transport)

    context = bridge.fetch_context()
    assert context.psi_hint.symbol_name == "f"

    # The request was written as a single compact JSON line terminated by \n.
    written = writer.getvalue()
    assert written == '{"method":"context"}\n'


def test_stdio_transport_rejects_truncated_stream() -> None:
    transport = StdioIdeTransport(io.StringIO(""), io.StringIO())
    bridge = JetBrainsBridge(transport)
    with pytest.raises(IdeProtocolError):
        bridge.fetch_context()
