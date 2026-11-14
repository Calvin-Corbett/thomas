"""Two launcher scripts that broke only on Windows PowerShell, checked from their source.

run-ui.ps1 starts the Boot Doctor rescue in a hidden window. Without --no-interactive the rescue ends at "Press Enter
to close this window" and waits for good, with nobody able to see it. setup.ps1 asks Python whether ChatGPT is
connected with `python -c <probe>`. Windows PowerShell 5.1 strips embedded double quotes from native arguments, so a
probe with "..." strings dies with NameError and Easy Setup never sees a connected ChatGPT profile.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _rescue_arguments(run_ui: str) -> str:
    """The argument list of the Start-Process call that runs `bootdoctor.ps1 rescue`."""
    for block in re.findall(
        r"Start-Process\s+-FilePath\s+\S+\s+-ArgumentList\s+@\((.*?)\)\s+-WorkingDirectory", run_ui, re.S
    ):
        if re.search(r"""["']rescue["']""", block):
            return block
    raise AssertionError("run-ui.ps1 has no Start-Process call that runs the Boot Doctor rescue")


def _chatgpt_probe(setup: str) -> str:
    match = re.search(r'function Test-OpenAICodexTokenConfigured\b.*?\$probe = @"\r?\n(.*?)\r?\n"@', setup, re.S)
    assert match, "setup.ps1 has no Test-OpenAICodexTokenConfigured probe"
    return match.group(1)


def test_the_hidden_rescue_never_waits_for_typed_input() -> None:
    arguments = _rescue_arguments((ROOT / "scripts" / "run-ui.ps1").read_text(encoding="utf-8"))
    assert re.search(r"""["']--relaunch["']""", arguments)
    assert re.search(r"""["']--no-interactive["']""", arguments), (
        "the rescue runs in a hidden window, so it must be started with --no-interactive"
    )


def test_the_chatgpt_probe_survives_windows_powershell_quoting() -> None:
    probe = _chatgpt_probe((ROOT / "scripts" / "setup.ps1").read_text(encoding="utf-8-sig"))
    assert '"' not in probe, "Windows PowerShell 5.1 strips these quotes when it runs python -c"
    ast.parse(probe)
    profiles_line = next(line for line in probe.splitlines() if line.startswith("profiles = "))
    assert ast.literal_eval(profiles_line.split("=", 1)[1].strip()) == ("openai_codex", "chatgpt", None)


def test_the_checks_catch_the_old_scripts() -> None:
    old_rescue = 'Start-Process -FilePath "powershell.exe" -ArgumentList @(\n  "rescue",\n  "--relaunch"\n) -WorkingDirectory $Root'
    assert not re.search(r"""["']--no-interactive["']""", _rescue_arguments(old_rescue))
    old_probe = (
        'function Test-OpenAICodexTokenConfigured {\n  $probe = @"\nprofiles = ("openai_codex", "chatgpt", None)\n"@\n}'
    )
    assert '"' in _chatgpt_probe(old_probe)
