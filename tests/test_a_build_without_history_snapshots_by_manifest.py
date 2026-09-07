"""Both Build dispatchers accept the no-history choice and snapshot by manifest (2026-09-05).

Codex's first live no-history run passed the HTTP launch and then died in the
child: the dispatcher takes its own git snapshot before the pass and refused
the plain folder ("fatal: not a git repository"). The choice a person made at
open time has to reach the dispatcher as an explicit argument (never inferred
from the environment), and with it the pre-run snapshot is the content
manifest, so the run's changed files are attributed by hash. Without it a
plain folder is still refused, exactly as before.
"""

from __future__ import annotations

from pathlib import Path

from thomas.forge.anvil import dispatch_agent_loop as dal
from thomas.forge.anvil import dispatch_claude_cli as dcc


def _writes_a_file(cwd: Path):
    def run_pass(prompt: str, cwd_: str, timeout: int, emit, **kwargs):
        (cwd / "out.txt").write_text("built", encoding="utf-8")
        return 0, "done"

    return run_pass


def test_the_agent_loop_dispatcher_refuses_a_plain_folder_without_the_choice(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(dal, "_run_agent_loop_pass", _writes_a_file(tmp_path))
    result = dal.dispatch_via_agent_loop("build", cwd=tmp_path, dry_run=False, verify=False, token_check=lambda: True)
    assert result.ok is False and "not a git repository" in result.reason, result


def test_the_agent_loop_dispatcher_attributes_by_manifest_with_the_choice(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(dal, "_run_agent_loop_pass", _writes_a_file(tmp_path))
    result = dal.dispatch_via_agent_loop(
        "build", cwd=tmp_path, dry_run=False, verify=False, allow_without_history=True, token_check=lambda: True
    )
    assert result.ok, result.reason
    assert result.changed_files == ["out.txt"], result


def test_the_claude_cli_dispatcher_takes_the_same_choice(monkeypatch, tmp_path: Path) -> None:
    def runner(argv, cwd, timeout):
        (tmp_path / "out.txt").write_text("built", encoding="utf-8")
        return 0, ""

    refused = dcc.dispatch_via_claude_cli("build", cwd=tmp_path, dry_run=False, verify=False, runner=runner)
    assert refused.ok is False and "not a git repository" in refused.reason, refused
    result = dcc.dispatch_via_claude_cli(
        "build", cwd=tmp_path, dry_run=False, verify=False, runner=runner, allow_without_history=True
    )
    assert result.ok, result.reason
    assert result.changed_files == ["out.txt"], result
