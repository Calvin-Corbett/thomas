"""The LIVE Desktop-write failure must carry the file-access remedy to the chat reply.

Measured live (exec-c3adbfcfa341, chat session chat_2a75273d5941a6d5, 2026-08-07
08:50 local, GPT-5.6 Terra): "Make a file on my Desktop called thomas-works.txt"
was delegated to the chat worker, whose ``fs.write_file`` call died in the agent
loop's PATH SANITIZER with the recorded tool-failure text::

    Invalid file path argument for write tool fs.write_file: invalid path:
    absolute paths are not allowed

The file-access ladder (``thomas/core/file_access.py`` — the ONLY producer of
the remedy sentence commit 84d8dd93 threads to the user) never ran:
``loop_tool_paths._validate_filesystem_path`` rejects every absolute path
before ``fs.write_file`` executes, even though ``WriteFileTool._resolve_target``
documents "absolute paths are taken as-is (the ladder ... decides if they're
allowed)". So no text matching ``is_file_access_refusal`` ever existed in the
run, ``policy_refusals`` stayed ``[]``, and the stored reply improvised
"provide a permitted folder path" with no mention of the setting the user
controls. The failure card read only "No verifiable result: ...".

Two independent kills confirmed on the same live turn:
  1. detection — the sanitizer's wording is not the ladder's, so the remedy
     source never fires (this file's sanitizer tests);
  2. delivery — the user-facing announcement is model-authored from a
     300-char-truncated summary ("one or two short sentences"), so even a
     threaded remedy dies before the chat bubble (this file's note tests).

No gate anywhere: an allowed path stays allowed, a refusal only gains words.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from thomas.agent.loop_execution import _tool_result_with_recovery
from thomas.agent.loop_tool_exec import execute_tools
from thomas.agent.loop_tool_paths import _sanitize_write_tool_path
from thomas.core.events import EventType
from thomas.core.file_access import (
    FULL,
    WORKSPACE,
    file_access_refusal_remedy,
    is_file_access_refusal,
)
from thomas.server.chat_delegation_result_policy import result_with_policy_remedy

_OUTSIDE_SCOPE_REMEDY = "Raise the file-access level (e.g. to 'Your PC') to write here."

# The reply the user actually received on the live turn (chat_2a75273d5941a6d5,
# message 2) — improvised, remedy-free.
_LIVE_REPLY = (
    "I couldn't create the file because this environment blocks writing to your "
    "Desktop, and no file was produced. I can try again if you provide a permitted folder path."
)

# The stored failure-card text of the live turn (exec-c3adbfcfa341
# progress_summary), verbatim shape.
_LIVE_SUMMARY = (
    "No verifiable result: nothing was produced and no tool success was confirmed. "
    "The worker reported: Tool failures: fs.write_file. I couldn't create it on the "
    "Desktop because this workspace only permits relative paths within its task "
    "directory; absolute Desktop paths are blocked."
)


def _live_desktop_args(tmp: Path) -> dict[str, Any]:
    """The live tool call, shape-for-shape: an ABSOLUTE path outside the workspace.

    The live path was ``C:\\Users\\corbe\\Desktop\\thomas-works.txt``; a tmp-rooted
    Desktop keeps the exact shape portable (absolute on every OS, outside the
    sandbox root on every machine).
    """
    return {"path": str(tmp / "Desktop" / "thomas-works.txt"), "content": "it works now"}


def _workspace(tmp: Path) -> Path:
    ws = tmp / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    return ws


# ── 1. The sanitizer hands back the LADDER's refusal, not a path error ────────


def test_the_live_desktop_write_gets_the_ladder_refusal_with_its_remedy(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    validated, error = _sanitize_write_tool_path(
        _live_desktop_args(tmp_path),
        require_path=True,
        sandbox_root=ws,
        benchmark_root=None,
        file_access=WORKSPACE,
    )
    assert validated is None
    assert error is not None
    assert is_file_access_refusal(error), (
        f"the refusal the worker sees must be the file-access POLICY refusal; got {error!r}"
    )
    assert file_access_refusal_remedy(error) == _OUTSIDE_SCOPE_REMEDY


def test_the_policy_refusal_is_not_wrapped_into_an_invalid_path_error(tmp_path: Path) -> None:
    """The worker prompt says "a tool result starting with 'BLOCKED:'" — keep that true."""
    ws = _workspace(tmp_path)
    _validated, error = _sanitize_write_tool_path(
        _live_desktop_args(tmp_path),
        require_path=True,
        sandbox_root=ws,
        benchmark_root=None,
        file_access=WORKSPACE,
    )
    assert error is not None and error.startswith("BLOCKED:"), error


def test_an_absolute_path_inside_the_workspace_is_allowed_at_workspace_level(tmp_path: Path) -> None:
    """The ladder is an authority, not a wider ban: what it allows passes."""
    ws = _workspace(tmp_path)
    target = ws / "notes" / "thomas-works.txt"
    validated, error = _sanitize_write_tool_path(
        {"path": str(target), "content": "it works now"},
        require_path=True,
        sandbox_root=ws,
        benchmark_root=None,
        file_access=WORKSPACE,
    )
    assert error is None
    assert validated == str(target.resolve())


def test_full_access_lets_an_absolute_path_through(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    validated, error = _sanitize_write_tool_path(
        _live_desktop_args(tmp_path),
        require_path=True,
        sandbox_root=ws,
        benchmark_root=None,
        file_access=FULL,
    )
    assert error is None
    assert validated is not None


def test_without_file_access_context_absolute_paths_stay_rejected(tmp_path: Path) -> None:
    """Callers that thread no ladder context (benchmark lane, legacy) are unchanged."""
    ws = _workspace(tmp_path)
    validated, error = _sanitize_write_tool_path(
        _live_desktop_args(tmp_path),
        require_path=True,
        sandbox_root=ws,
        benchmark_root=None,
    )
    assert validated is None
    assert error == "invalid path: absolute paths are not allowed"


# ── 2. execute_tools emits that refusal as the tool result_text ───────────────


class _SpyRunner:
    async def run(self, *, executor, tool_call, **_kwargs: Any) -> dict:
        return await executor(tool_call)


class _LoopStub:
    def __init__(self, ws: Path, file_access: int) -> None:
        self._autonomy_level = 4
        self._run_id = "run-live"
        self._session_id = "chat_2a75273d5941a6d5"
        self._guarded_tool_runner = _SpyRunner()
        self._tool_timeout_s = None
        self._max_parallel_tools = None
        self._conversation: list[Any] = []
        self.tools = SimpleNamespace()
        self.config = SimpleNamespace(
            tools=SimpleNamespace(sandbox_path=str(ws), file_access=file_access),
            memory=SimpleNamespace(root_path=str(ws / "memory")),
        )

    async def _audit_action(self, **_kwargs: Any) -> None:
        return None


def test_the_emitted_tool_result_is_the_policy_refusal_for_the_live_call(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    loop = _LoopStub(ws, WORKSPACE)

    async def _drive() -> Any:
        return await execute_tools(
            loop,
            [{"id": "t1", "name": "fs.write_file", "arguments": _live_desktop_args(tmp_path)}],
            0,
            file_audit_module=None,
        ).__anext__()

    event = asyncio.run(_drive())
    assert event.type == EventType.TOOL_RESULT
    assert event.data["ok"] is False
    result_text = str(event.data["result_text"])
    assert is_file_access_refusal(result_text), (
        "the run's recorded tool failure must be recognisable as a policy refusal; "
        f"got {result_text!r}"
    )
    assert _OUTSIDE_SCOPE_REMEDY in result_text
    # This exact text is what chat_delegation_runner scans into policy_refusals
    # and what result_with_policy_remedy threads to the user.
    assert _OUTSIDE_SCOPE_REMEDY in result_with_policy_remedy("The write failed.", [result_text])


def test_the_worker_recovery_note_fires_on_the_sanitizer_refusal(tmp_path: Path) -> None:
    """The model-visible result gains the do-not-retry note plus the verbatim remedy."""
    ws = _workspace(tmp_path)
    _validated, refusal = _sanitize_write_tool_path(
        _live_desktop_args(tmp_path),
        require_path=True,
        sandbox_root=ws,
        benchmark_root=None,
        file_access=WORKSPACE,
    )
    assert refusal is not None
    recovered = _tool_result_with_recovery("fs.write_file", refusal)
    assert "do not" in recovered.lower() and "retry" in recovered.lower()
    assert _OUTSIDE_SCOPE_REMEDY in recovered


# ── 3. The chat bubble the user reads carries the remedy ──────────────────────


def test_a_failed_announcement_note_carries_the_remedy_the_model_omitted(tmp_path: Path) -> None:
    """LIVE shape: the model's sentence omitted the lever; the note must still name it."""
    from thomas.server.routes.chat_v2_announcements import _failed_note_with_policy_remedy

    ws = _workspace(tmp_path)
    _validated, refusal = _sanitize_write_tool_path(
        _live_desktop_args(tmp_path),
        require_path=True,
        sandbox_root=ws,
        benchmark_root=None,
        file_access=WORKSPACE,
    )
    assert refusal is not None
    # The stored summary as _finalize_worker_completion now composes it: the live
    # card text plus the threaded remedy note.
    stored_summary = result_with_policy_remedy(_LIVE_SUMMARY, [refusal])
    assert _OUTSIDE_SCOPE_REMEDY in stored_summary

    note = _failed_note_with_policy_remedy(_LIVE_REPLY, stored_summary)
    assert note.startswith(_LIVE_REPLY), "additive only — the model's own sentence is kept"
    assert _OUTSIDE_SCOPE_REMEDY in note


def test_a_note_that_already_says_the_remedy_is_left_alone() -> None:
    from thomas.server.routes.chat_v2_announcements import _failed_note_with_policy_remedy

    note = f"I couldn't write to your Desktop. {_OUTSIDE_SCOPE_REMEDY}"
    assert _failed_note_with_policy_remedy(note, f"failed. {_OUTSIDE_SCOPE_REMEDY}") == note


def test_a_summary_without_a_remedy_changes_nothing() -> None:
    from thomas.server.routes.chat_v2_announcements import _failed_note_with_policy_remedy

    assert _failed_note_with_policy_remedy(_LIVE_REPLY, _LIVE_SUMMARY) == _LIVE_REPLY


def test_the_handler_threads_the_remedy_before_the_note_is_saved() -> None:
    """Wiring, not just existence: the chokepoint runs on the failed path before
    the note is stripped/saved. (The recurring debt shape is finished code with
    no caller — pin the caller.)"""
    source = (
        Path(__file__).resolve().parents[1] / "thomas" / "server" / "routes" / "chat_v2_announcements.py"
    ).read_text(encoding="utf-8")
    assert "def _failed_note_with_policy_remedy(" in source
    call = "note = _failed_note_with_policy_remedy(note, summary)"
    assert call in source, "the remedy chokepoint is defined but never called"
    assert source.index(call) < source.index("note = strip_sandbox_links(note)"), (
        "the remedy must be threaded before the note is finalized and saved"
    )
