"""Direct shell exposure matches the selected Forge guardrail.

Thomas's builder got Read/Edit/Write/Glob/Grep and nothing else. The comment above
that list names the assumption it was built on: *"The human watcher reviews the
resulting diff and runs the tests."* Thomas is used unsupervised, by people who
cannot read a diff, so nobody was running those tests.

The Claude CLI's Bash tool is an unsandboxed host shell on native Windows. It is
therefore exposed only when the request explicitly selects ``open``. Guarded and
fortress edit without direct shell and use Thomas's bounded verifier afterward.

Measured cost, 2026-08-05: Thomas built a three-file expense tracker whose app.js
referenced an undeclared `refreshButton` on its last line. It reported it was
"doing a quick source review" — a READ — and nothing ever executed the page.
Raising the pass budget from 10 to 25 produced more edits and the same bug, because
once a file is written no new information can reach a model that cannot run things.

Read-only and low-autonomy runs never get a shell in any mode.
"""

from __future__ import annotations

import json
from itertools import product
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from thomas.forge.anvil import forge_code_git, forge_code_runner
from thomas.forge.anvil.bridge_prompts import compose_headless_prompt
from thomas.forge.anvil.dispatch_claude_cli import SAFE_CLI_TOOLS, dispatch_via_claude_cli
from thomas.forge.anvil.forge_code_settings import ForgeCodeSettings, direct_shell_allowed


def _allow_shell(guardrails: str, *, autonomy: int = 3, file_access: str = "project") -> bool:
    return direct_shell_allowed(
        autonomy_level=autonomy,
        file_access=file_access,
        guardrails=guardrails,
    )


def test_only_open_builder_has_a_direct_shell() -> None:
    guardrails = "open"
    assert _allow_shell(guardrails), (
        f"at guardrails={guardrails!r} the builder cannot run anything, so it cannot "
        "check its own work and a one-line runtime bug ships"
    )


def test_the_default_guardrail_denies_direct_shell() -> None:
    source = Path(forge_code_runner.__file__).read_text(encoding="utf-8")
    assert 'default="guarded"' in source, "the default guardrail moved; re-check this gate"
    assert not _allow_shell("guarded")


def test_fortress_still_means_no_shell() -> None:
    """Widening the default must not delete the setting that exists to say no."""

    assert not _allow_shell("fortress")


@pytest.mark.parametrize("guardrails", ["open", "guarded", "fortress"])
def test_read_only_never_gets_a_shell(guardrails: str) -> None:
    assert not _allow_shell(guardrails, file_access="read_only")


@pytest.mark.parametrize("guardrails", ["open", "guarded", "fortress"])
def test_low_autonomy_never_gets_a_shell(guardrails: str) -> None:
    assert not _allow_shell(guardrails, autonomy=2)


def test_guarded_prompt_tells_the_truth_about_verification() -> None:
    prompt = compose_headless_prompt(
        "build a small page", guardrails="guarded", file_access="project", autonomy_level=3
    )
    assert "Direct shell is unavailable" in prompt
    assert "bounded verifier runs after the edit pass" in prompt
    assert "RUN WHAT YOU BUILT" not in prompt


def test_open_prompt_names_the_unsandboxed_host_boundary() -> None:
    prompt = compose_headless_prompt("build a small page", guardrails="open", file_access="project", autonomy_level=3)
    assert "RUN WHAT YOU BUILT" in prompt
    assert "unsandboxed host process" in prompt
    assert "explicitly selected Open" in prompt
    assert "commands can leave that project" in prompt


@pytest.mark.parametrize(
    ("autonomy", "file_access"),
    [(2, "project"), (3, "read_only")],
)
def test_open_prompt_does_not_claim_shell_when_policy_denies_it(autonomy: int, file_access: str) -> None:
    prompt = compose_headless_prompt(
        "build a small page",
        guardrails="open",
        file_access=file_access,
        autonomy_level=autonomy,
    )

    assert "Direct shell is unavailable under this execution policy" in prompt
    assert "RUN WHAT YOU BUILT" not in prompt
    assert "unsandboxed host process" not in prompt


_POLICY_CASES = list(
    product(("open", "guarded", "fortress"), range(1, 5), ("read_only", "workspace", "project", "pc", "full"))
)


@pytest.mark.parametrize(("guardrails", "autonomy", "file_access"), _POLICY_CASES)
def test_all_policy_rows_match_both_engine_dispatches(
    guardrails: str,
    autonomy: int,
    file_access: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = guardrails == "open" and autonomy >= 3 and file_access != "read_only"
    captured: dict[str, dict[str, Any]] = {}
    result = SimpleNamespace(ok=True, reason="ok", returncode=0)

    def _gpt(*_args: Any, **kwargs: Any) -> Any:
        captured["gpt"] = kwargs
        return result

    def _claude(*_args: Any, **kwargs: Any) -> Any:
        captured["claude"] = kwargs
        return result

    monkeypatch.setattr(forge_code_runner, "dispatch_via_agent_loop", _gpt)
    monkeypatch.setattr(forge_code_runner, "dispatch_via_claude_cli", _claude)
    monkeypatch.setattr(forge_code_runner, "_default_emit", lambda _event: None)

    for family, model in (("gpt", "gpt-5.6"), ("claude", "sonnet")):
        args = forge_code_runner.build_parser().parse_args(
            [
                "build it",
                "--project-root",
                str(tmp_path),
                "--family",
                family,
                "--model",
                model,
                "--autonomy",
                str(autonomy),
                "--file-access",
                file_access,
                "--guardrails",
                guardrails,
                "--memory",
                "off",
            ]
        )
        assert forge_code_runner.run_configured_turn(args) == 0

    assert captured["gpt"]["allow_shell"] is expected
    assert ("Bash" in captured["claude"]["allowed_tools"]) is expected


@pytest.mark.parametrize(
    ("guardrails", "autonomy", "file_access", "has_shell"),
    [
        ("guarded", 3, "project", False),
        ("fortress", 3, "project", False),
        ("open", 3, "project", True),
        ("open", 2, "project", False),
        ("open", 3, "read_only", False),
    ],
)
def test_claude_argv_has_an_exact_guardrail_tool_surface(
    guardrails: str,
    autonomy: int,
    file_access: str,
    has_shell: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    raw_result = json.dumps({"type": "result", "is_error": False, "result": "Done."})

    def _runner(cmd: list[str], _cwd: str, _timeout: int) -> tuple[int, str]:
        captured["cmd"] = cmd
        return 0, raw_result

    monkeypatch.setattr(forge_code_git, "snapshot", lambda _root: {})
    monkeypatch.setattr(forge_code_git, "project_delta_since", lambda _root, _snap: ["index.html"])

    result = dispatch_via_claude_cli(
        "build it",
        cwd=tmp_path,
        model="sonnet",
        dry_run=False,
        verify=False,
        allowed_tools=("Read", "Bash", "Bash(rm:*)", "WebFetch"),
        guardrails=guardrails,
        autonomy_level=autonomy,
        file_access=file_access,
        runner=_runner,
        claude_bin="claude",
    )

    assert result.ok is True
    cmd = captured["cmd"]
    assert cmd[cmd.index("--permission-mode") + 1] == "dontAsk"
    tools = tuple(cmd[cmd.index("--tools") + 1 : cmd.index("--allowedTools")])
    allowed_end = cmd.index("--disallowedTools") if "--disallowedTools" in cmd else cmd.index("--output-format")
    allowed = tuple(cmd[cmd.index("--allowedTools") + 1 : allowed_end])
    expected = SAFE_CLI_TOOLS + (("Bash",) if has_shell else ())
    assert tools == expected
    assert allowed == expected
    assert "Bash(rm:*)" not in cmd
    assert "WebFetch" not in cmd
    if has_shell:
        assert "--disallowedTools" not in cmd
    else:
        assert cmd[cmd.index("--disallowedTools") + 1] == "Bash"


@pytest.mark.parametrize("guardrails", ["guarded", "fortress", "open"])
def test_capability_report_names_the_real_terminal_boundary(guardrails: str) -> None:
    settings = ForgeCodeSettings.from_payload(
        {
            "model": "claude:sonnet",
            "autonomy_level": 3,
            "file_access": "project",
            "guardrails": guardrails,
        }
    )
    report = settings.capability_report()["support"]["guardrails"]

    if guardrails == "open":
        assert report["terminal"] == "enabled_in_selected_project"
        assert "unsandboxed host shell" in report["terminal_boundary"]
        assert "Open was selected" in report["terminal_boundary"]
    else:
        assert report["terminal"] == "engine_verification_only"
        assert report["terminal_boundary"] == (
            "no direct shell; the engine runs bounded verification after the edit pass"
        )
