"""CAP-101: VS Code editor bridge -- context + scoped diff + apply round-trip.

Acceptance line: "Editor-integrated agent with selection/context awareness and
in-editor diff application."

These tests prove the protocol core end to end against a hermetic
:class:`FakeEditor` -- no real VS Code, no subprocess, no network:

* editor context (active file + selection + cursor + diagnostics) is received
  and the selection substring is derived faithfully from the buffer;
* a scoped action is *constrained to the selection*: the produced diff is a
  single minimal range edit that touches only the selected region, never the
  whole file;
* applying that diff reports success and the fake buffer reflects the edit,
  with everything outside the selection left byte-for-byte unchanged;
* a no-op action (returns ``None``, or returns the selection unchanged) yields
  an empty diff;
* the whole path is deterministic.

The real VS Code extension host is the GUI/marketplace-gated live lane; the
production :class:`StdioJsonRpcTransport` framing is exercised here over
in-memory pipes to prove it is protocol-compatible with the fake.
"""

from __future__ import annotations

import io

import pytest

from thomas.integrations.vscode_bridge import (
    ApplyResult,
    Diagnostic,
    EditorContext,
    EditorDiff,
    FakeEditor,
    Position,
    Range,
    StdioJsonRpcTransport,
    TextEdit,
    VSCodeBridge,
    _encode_message,
    _read_message,
    apply_edits,
    offset_at,
)

# ---------------------------------------------------------------------------
# A small, deterministic document. Line/character are zero-based (LSP).
#
#   line 0: def greet(name):
#   line 1: <TAB>return "hi " + naem      <- typo 'naem', selected below
#   line 2: <blank>
#   line 3: print(greet("world"))
# ---------------------------------------------------------------------------
DOC = 'def greet(name):\n    return "hi " + naem\n\nprint(greet("world"))\n'

# The selection covers exactly the identifier ``naem`` on line 1.
# line 1 is:  '    return "hi " + naem'  -> 'naem' starts at char 19, ends 23.
SELECTION = Range(start=Position(1, 19), end=Position(1, 23))
DIAG = Diagnostic(
    range=SELECTION,
    message="undefined name 'naem'",
    severity="error",
    source="pyflakes",
)


def make_editor() -> FakeEditor:
    return FakeEditor(
        file_path="/repo/greet.py",
        text=DOC,
        selection=SELECTION,
        cursor=Position(1, 23),
        diagnostics=[DIAG],
    )


# ---------------------------------------------------------------------------
# Scoped actions (the "agent")
# ---------------------------------------------------------------------------
def fix_typo(ctx: EditorContext) -> str:
    """Replace the selected identifier -- reads context, edits selection only."""
    assert ctx.selection_text == "naem"  # action sees the selection
    assert any(d.severity == "error" for d in ctx.diagnostics)  # ...and diagnostics
    return "name"


def noop_return_none(_ctx: EditorContext) -> None:
    return None


def noop_identity(ctx: EditorContext) -> str:
    return ctx.selection_text


# ---------------------------------------------------------------------------
# Context reception
# ---------------------------------------------------------------------------
def test_context_received_with_selection_and_diagnostics() -> None:
    bridge = VSCodeBridge(transport=make_editor())
    ctx = bridge.fetch_context()

    assert ctx.file_path == "/repo/greet.py"
    assert ctx.selection == SELECTION
    assert ctx.cursor == Position(1, 23)
    # Selection substring is derived from the buffer, never trusted blindly.
    assert ctx.selection_text == "naem"
    # Diagnostics travel with the context.
    assert len(ctx.diagnostics) == 1
    assert ctx.diagnostics[0].message == "undefined name 'naem'"
    assert ctx.diagnostics[0].severity == "error"
    assert ctx.diagnostics_in_selection() == (DIAG,)
    assert bridge.diagnostics_seen == 1


# ---------------------------------------------------------------------------
# Scoped action -> minimal range diff (touches only the selection)
# ---------------------------------------------------------------------------
def test_action_is_constrained_to_selection_and_diff_is_minimal() -> None:
    editor = make_editor()
    bridge = VSCodeBridge(transport=editor)
    ctx = bridge.fetch_context()

    diff = bridge.run_action(fix_typo, context=ctx)

    # Exactly one range edit...
    assert isinstance(diff, EditorDiff)
    assert len(diff.edits) == 1
    edit = diff.edits[0]
    # ...whose range is precisely the selection (not the whole file).
    assert edit.range == SELECTION
    assert edit.new_text == "name"
    # Prove localization: the edit is contained in the selection region.
    assert diff.touches_only(ctx.selection)
    # And it is NOT a whole-file replace: a whole-file edit would span 0..end.
    whole_file = Range(Position(0, 0), Position(3, len('print(greet("world"))')))
    assert not (edit.range.start == whole_file.start and edit.range.end == whole_file.end)


# ---------------------------------------------------------------------------
# Apply round-trip: buffer reflects the edit; rest of file unchanged
# ---------------------------------------------------------------------------
def test_apply_round_trip_updates_fake_buffer_only_in_selection() -> None:
    editor = make_editor()
    bridge = VSCodeBridge(transport=editor)

    diff, result = bridge.run_and_apply(fix_typo)

    assert isinstance(result, ApplyResult)
    assert result.applied is True
    assert result.file_path == "/repo/greet.py"

    # The fake buffer genuinely changed.
    expected = DOC.replace("naem", "name")
    assert editor.document == expected
    assert result.text == expected

    # Everything OUTSIDE the selection is byte-for-byte identical: only line 1
    # changed, and only the 'naem' -> 'name' span within it.
    original_lines = DOC.splitlines()
    new_lines = editor.document.splitlines()
    assert original_lines[0] == new_lines[0]
    assert original_lines[2] == new_lines[2]
    assert original_lines[3] == new_lines[3]
    assert new_lines[1] == '    return "hi " + name'

    # The apply was recorded as a single range diff, not a wholesale rewrite.
    assert len(editor.applied_edits) == 1
    assert len(editor.applied_edits[0].edits) == 1


# ---------------------------------------------------------------------------
# No-op action -> empty diff
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("action", [noop_return_none, noop_identity])
def test_noop_action_yields_empty_diff(action) -> None:
    editor = make_editor()
    bridge = VSCodeBridge(transport=editor)

    diff = bridge.run_action(action)
    assert diff.is_empty()
    assert diff.edits == ()

    # Applying an empty diff is a well-formed no-op: buffer is untouched.
    result = bridge.apply(diff)
    assert result.applied is True
    assert editor.document == DOC
    assert editor.applied_edits == []


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------
def test_determinism_same_context_same_diff() -> None:
    diffs = []
    for _ in range(5):
        bridge = VSCodeBridge(transport=make_editor())
        diffs.append(bridge.run_action(fix_typo))
    first = diffs[0]
    for d in diffs[1:]:
        assert d == first  # frozen dataclasses compare by value


def test_determinism_apply_is_repeatable() -> None:
    outcomes = []
    for _ in range(5):
        editor = make_editor()
        bridge = VSCodeBridge(transport=editor)
        _, result = bridge.run_and_apply(fix_typo)
        outcomes.append((result.applied, editor.document))
    assert len(set(outcomes)) == 1


# ---------------------------------------------------------------------------
# Offset / edit primitives
# ---------------------------------------------------------------------------
def test_offset_at_resolves_and_clamps() -> None:
    assert offset_at(DOC, Position(0, 0)) == 0
    # Start of 'naem' on line 1.
    assert DOC[offset_at(DOC, Position(1, 19)) : offset_at(DOC, Position(1, 23))] == "naem"
    # Character past line end clamps to the line end (before the newline).
    assert offset_at(DOC, Position(0, 999)) == len("def greet(name):")
    # Line past the document clamps to len(text).
    assert offset_at(DOC, Position(99, 0)) == len(DOC)


def test_apply_edits_rejects_overlaps() -> None:
    e1 = TextEdit(Range(Position(1, 19), Position(1, 23)), "name")
    e2 = TextEdit(Range(Position(1, 21), Position(1, 23)), "x")
    with pytest.raises(Exception):
        apply_edits(DOC, [e1, e2])


# ---------------------------------------------------------------------------
# The production stdio transport is protocol-compatible with the fake.
# We drive StdioJsonRpcTransport over in-memory pipes: a canned peer answers
# one request. This proves the LSP framing + request/response half is real,
# without a VS Code subprocess (that is the live lane).
# ---------------------------------------------------------------------------
def test_stdio_transport_frames_real_jsonrpc() -> None:
    # Peer's canned response to request id 1.
    peer_response = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"applied": True, "path": "/repo/greet.py", "text": "ok"},
    }
    reader = io.BytesIO(_encode_message(peer_response))
    writer = io.BytesIO()
    transport = StdioJsonRpcTransport(reader=reader, writer=writer)

    result = transport.request("editor/applyEdit", {"path": "/repo/greet.py", "edits": []})
    assert result == {"applied": True, "path": "/repo/greet.py", "text": "ok"}

    # What we wrote to the peer is a valid LSP-framed JSON-RPC request.
    writer.seek(0)
    sent = _read_message(writer)
    assert sent["jsonrpc"] == "2.0"
    assert sent["id"] == 1
    assert sent["method"] == "editor/applyEdit"
    assert sent["params"]["path"] == "/repo/greet.py"
