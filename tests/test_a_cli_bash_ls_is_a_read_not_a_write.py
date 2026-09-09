"""A claude-CLI Bash call that only reads is not evidence of a failed edit.

Measured (2026-08-06): the claude-CLI dispatch path classified tools by NAME
only (``_is_read_only_cli_tool``), so a CLI ``Bash`` call running a read-only
``ls`` still counted as write-capable, and CLI transcripts carried no
``access``/``access_basis`` stamps or command excerpts — while the GPT loop
path (``dispatch_agent_loop``) had both. The shared rule already exists
(``thomas.agent.loop_tool_protocol.tool_call_access``); the CLI translator
just never consulted it.

These tests drive the REAL stream translator with the REAL claude
``stream-json`` shapes (assistant ``tool_use`` blocks carry the input args,
user ``tool_result`` blocks carry only ``tool_use_id``), and the REAL
dispatcher verdict via an injected runner.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from thomas.forge.anvil.dispatch_claude_cli import dispatch_via_claude_cli
from thomas.forge.anvil.forge_event_stream import (
    FORGE_EVENT_KEY,
    ClaudeStreamTranslator,
)

ANSWER = "It is a small Python project that keeps one value in app.py."


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    for args in (["init", "--initial-branch=main"], ["add", "-A"]):
        subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=False)
    subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=T", "-c", "user.email=t@x", "commit", "-m", "base"],
        capture_output=True,
        check=False,
    )
    return root


def _tool_use(tool_id: str, name: str, inp: dict | None) -> str:
    block: dict = {"type": "tool_use", "id": tool_id, "name": name}
    if inp is not None:
        block["input"] = inp
    return json.dumps({"type": "assistant", "message": {"content": [block]}})


def _tool_result(tool_id: str, content: str = "output", *, is_error: bool = False) -> str:
    return json.dumps(
        {
            "type": "user",
            "message": {
                "content": [
                    {"type": "tool_result", "tool_use_id": tool_id, "content": content, "is_error": is_error}
                ]
            },
        }
    )


def _final(text: str = ANSWER) -> str:
    return json.dumps({"type": "result", "is_error": False, "result": text})


def _bash_call(tool_id: str, command: str, result: str = "output", *, is_error: bool = False) -> list[str]:
    return [
        _tool_use(tool_id, "Bash", {"command": command}),
        _tool_result(tool_id, result, is_error=is_error),
    ]


def _translate(lines: list[str]) -> list[dict]:
    translate = ClaudeStreamTranslator()
    out: list[dict] = []
    for line in lines:
        out.extend(translate(line))
    return out


def _dispatch(repo: Path, lines: list[str]):
    def runner(_cmd, _cwd, _timeout):
        return 0, "\n".join(lines)

    return dispatch_via_claude_cli(
        "look at this project and tell me what it does",
        cwd=repo,
        dry_run=False,
        runner=runner,
        claude_bin="claude",
        verify=False,
    )


# ── the translator stamps how each call was classified ──


def test_a_bash_ls_tool_event_is_stamped_read_by_its_command() -> None:
    out = _translate(_bash_call("t1", "ls"))
    tools = [e for e in out if e.get(FORGE_EVENT_KEY) == "tool"]

    assert tools, "the Bash call must reach the forge stream"
    assert tools[0].get("access") == "read"
    assert tools[0].get("access_basis") == "command"
    assert tools[0].get("command") == "ls"


def test_a_bash_rm_tool_event_is_stamped_write_by_its_command() -> None:
    out = _translate(_bash_call("t1", "rm x"))
    tools = [e for e in out if e.get(FORGE_EVENT_KEY) == "tool"]

    assert tools[0].get("access") == "write"
    assert tools[0].get("access_basis") == "command"
    assert tools[0].get("command") == "rm x"


def test_a_bash_call_with_no_visible_command_fails_toward_write() -> None:
    out = _translate([_tool_use("t1", "Bash", {})])
    tools = [e for e in out if e.get(FORGE_EVENT_KEY) == "tool"]

    assert tools[0].get("access") == "write"
    assert tools[0].get("access_basis") == "command-unseen"


def test_fixed_name_tools_are_stamped_by_name() -> None:
    out = _translate(
        [
            _tool_use("t1", "Read", {"file_path": "app.py"}),
            _tool_use("t2", "Edit", {"file_path": "app.py"}),
            _tool_use("t3", "SomeNewTool", {}),
        ]
    )
    tools = [e for e in out if e.get(FORGE_EVENT_KEY) == "tool"]

    assert (tools[0]["access"], tools[0]["access_basis"]) == ("read", "name")
    assert (tools[1]["access"], tools[1]["access_basis"]) == ("write", "name")
    assert (tools[2]["access"], tools[2]["access_basis"]) == ("write", "unknown-tool")


def test_the_tool_result_carries_the_name_access_and_command_of_its_call() -> None:
    """CLI ``tool_result`` blocks carry only ``tool_use_id``; the translator
    correlates them to the call so the durable record says WHAT ran and how it
    was judged — the same auditability dispatch_agent_loop already has."""
    out = _translate(_bash_call("t1", "ls", result="app.py"))
    results = [e for e in out if e.get(FORGE_EVENT_KEY) == "tool_result"]

    assert results, "the result must reach the forge stream"
    assert results[0].get("name") == "Bash"
    assert results[0].get("access") == "read"
    assert results[0].get("access_basis") == "command"
    assert results[0].get("command") == "ls"


# ── the dispatch verdict honors the stamps (stamp wins, name fallback) ──


def test_a_bash_ls_run_with_an_answer_classifies_read_only(repo: Path) -> None:
    result = _dispatch(repo, [*_bash_call("t1", "ls", result="app.py"), _final()])

    assert result.ok is True, result.reason
    assert "replied without changing files" in result.reason


def test_a_bash_ls_whose_result_errored_is_still_a_read_not_a_failed_edit(repo: Path) -> None:
    """The measured demotion: a read-only command whose RESULT carried an error
    (a grep with no match, an ls of a missing dir) plus a real answer was filed
    as a no-op failure, because Bash counted as write-capable BY NAME."""
    result = _dispatch(
        repo,
        [
            *_bash_call("t1", "ls missing/", result="ls: cannot access 'missing/'", is_error=True),
            _final(),
        ],
    )

    assert result.ok is True, result.reason


def test_a_failed_bash_rm_still_disqualifies_the_run(repo: Path) -> None:
    """The control the relaxation must not remove: a mutating command that
    reported failure while git truth says nothing changed is a failed edit."""
    result = _dispatch(
        repo,
        [
            *_bash_call("t1", "rm x", result="rm: cannot remove 'x'", is_error=True),
            _final("Removed the file."),
        ],
    )

    assert result.ok is False, result.reason


def test_unnamed_tool_activity_stays_strict(repo: Path) -> None:
    """A tool_result with no correlated call is unnamed and unstamped —
    nothing is known about what it did, so the run is not relaxed."""
    result = _dispatch(repo, [_tool_result("orphan", "boom", is_error=True), _final()])

    assert result.ok is False, result.reason
