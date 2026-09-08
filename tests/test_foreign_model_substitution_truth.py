"""Foreign model requests are mapped to the Claude model that really runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from thomas.forge.anvil import forge_code_git
from thomas.forge.anvil.dispatch_claude_cli import dispatch_via_claude_cli
from thomas.forge.anvil.forge_code_settings import ForgeCodeSettings, ForgeCodeSettingsError


@pytest.mark.parametrize(
    "foreign",
    ["qwen2.5-coder:7b", "gemini-2.0-flash", "mistral-large", "llama3.1:70b"],
)
def test_a_model_build_cannot_run_is_refused_instead_of_swapped(foreign: str) -> None:
    with pytest.raises(ForgeCodeSettingsError) as excinfo:
        ForgeCodeSettings.from_payload({"model": foreign, "model_id": foreign})

    message = str(excinfo.value)
    assert foreign in message, "the refusal must name the model that was asked for"
    assert "Chat" in message, "it must say where the model can still be used"


def test_the_refusal_says_when_the_culprit_is_the_configured_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """A bad default is a different fix from a bad pick, so it reads differently."""
    monkeypatch.setattr(
        "thomas.forge.anvil.forge_code_settings._configured_default_model",
        lambda: "qwen2.5-coder:7b",
    )

    with pytest.raises(ForgeCodeSettingsError) as excinfo:
        ForgeCodeSettings.from_payload({})

    assert "configured default model" in str(excinfo.value)


@pytest.mark.parametrize(
    ("requested", "effective"),
    [
        ("claude", "claude:claude"),
        ("sonnet", "claude:sonnet"),
        ("claude:opus", "claude:opus"),
        ("haiku", "claude:haiku"),
        ("claude-opus-4-6", "claude:claude-opus-4-6"),
        ("claude-3-5-sonnet-20241022", "claude:claude-3-5-sonnet-20241022"),
        ("claude:claude-sonnet-4-20250514", "claude:claude-sonnet-4-20250514"),
    ],
)
def test_valid_claude_variants_are_preserved(requested: str, effective: str) -> None:
    settings = ForgeCodeSettings.from_payload({"model": requested})

    assert settings.dispatch_model == effective
    assert settings.recorded_model() == effective
    assert settings.runs_requested_model() is True


@pytest.mark.parametrize("requested", ["claudette-local", "claudeevil", "claude:qwen"])
def test_a_name_that_merely_looks_like_claude_is_refused(requested: str) -> None:
    """Looking Claude-shaped is not being a Claude model.

    These used to map to ``claude:sonnet`` so the CLI never received bad argv.
    Under "the selected model does the work" the argv problem is solved the
    other way: none of these names a model the Claude CLI can run, so the
    request stops here instead of quietly becoming Sonnet.

    ``claude:qwen`` is the sharpest case — the wire form literally asks the
    Claude CLI to run qwen. Substituting made that read as success.
    """
    with pytest.raises(ForgeCodeSettingsError) as excinfo:
        ForgeCodeSettings.from_payload({"model": requested, "model_id": requested})

    assert requested.split(":")[-1] in str(excinfo.value) or requested in str(excinfo.value)


def test_a_real_claude_variant_still_reaches_the_cli_argv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Guard the other direction: refusing must not swallow a valid Claude pick."""
    settings = ForgeCodeSettings.from_payload({"model": "claude-opus-4-6", "model_id": "claude-opus-4-6"})
    captured: dict[str, Any] = {}
    raw_result = json.dumps({"type": "result", "is_error": False, "result": "Done."})

    def _runner(cmd: list[str], cwd: str, timeout: int) -> tuple[int, str]:
        captured.update({"cmd": cmd, "cwd": cwd, "timeout": timeout})
        return 0, raw_result

    monkeypatch.setattr(forge_code_git, "snapshot", lambda _root: {})
    monkeypatch.setattr(forge_code_git, "project_delta_since", lambda _root, _snap: ["index.html"])

    assert settings.runs_requested_model() is True

    result = dispatch_via_claude_cli(
        "build it",
        cwd=tmp_path,
        model=settings.dispatch_model.split(":", 1)[-1],
        dry_run=False,
        verify=False,
        runner=_runner,
        claude_bin="claude",
    )

    cmd = captured["cmd"]
    assert cmd[cmd.index("--model") + 1] == "claude-opus-4-6"
    assert result.ok is True
