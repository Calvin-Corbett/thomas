"""The question the Thomas.vbs launcher asks before a first start lists the installs and changes that start can make.

The first start runs scripts/run-ui.ps1, which runs scripts/setup.ps1: winget installs, pip and npm
installs, a write to the registry, a rewrite of thomas.toml, new shortcuts, and Boot Doctor if the
server does not come up. Saying Yes is the only consent the launcher collects, so the question is
worth what it lists. The list is in scripts/thomas_app.py; these tests check the message box really
shows it (the launcher runs with its shell, file system and message boxes replaced by fakes, see
tests/launcher_script_host_support.py) and check it against the two scripts. A winget install or npm
call made through the helpers the scripts use now, which no single line of the question names, fails a
test, and so does a change the question lists that the scripts no longer make. An install made some
other way, or a side effect of some other kind, is not found by reading the scripts; the table of them
below is what a new one gets added to.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from scripts import thomas_app

from tests.launcher_script_host_support import (
    CSCRIPT,
    ELECTRON,
    LAUNCH,
    RUN_UI,
    prompts,
    run_scenario_with_output,
)

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
needs_cscript = pytest.mark.skipif(CSCRIPT is None, reason="needs Windows Script Host")

# What each side effect is called in the question: the words that must be in it.
WINGET_PACKAGES = {
    "Python.Python.3.11": ("Python", "winget"),
    "Python.Python.3.12": ("Python", "winget"),
    "OpenJS.NodeJS.LTS": ("Node.js", "winget"),
    "Ollama.Ollama": ("Ollama", "winget"),
}
NPM_CALLS = {
    '"i", "-g", "@openai/codex"': ("Codex", "npm"),
    '"install", "--no-audit", "--no-fund"': ("npm install", "desktop folder", "Electron"),
}
OTHER_EFFECTS = {
    "HKCU:\\Software\\Classes\\thomas": ("thomas://", "Windows account"),
    "function Set-DefaultModelName": ("default_model", "thomas.toml"),
    "function Install-ThomasShortcut": ("shortcuts", "Desktop", "Start Menu", "Thomas.vbs", "thomas.ico"),
    'Join-Path $setupDir "last_setup.txt"': ("last_setup.txt",),
    "Remove-Item -Recurse -Force $VenvRoot": ("replacing an incomplete one",),
    '"install", "-e", ".[server]"': ("Python packages",),
    '@("serve")': ("start Ollama",),
    "bootdoctor.ps1": ("Boot Doctor", "stop a Thomas process", "pip install", "startup files", "model"),
}


def _script(name: str) -> str:
    return (SCRIPTS / name).read_text(encoding="utf-8").replace("\\\\", "\\")


def _both() -> str:
    return _script("run-ui.ps1") + "\n" + _script("setup.ps1")


def test_the_question_fits_a_message_box_and_defaults_to_no() -> None:
    text = thomas_app.render_launcher(thomas_app.DEFAULT_PORT)

    assert len(thomas_app.setup_question_text()) <= 1000, "a message box shows about 1000 characters"
    assert thomas_app.setup_question_text().isascii()
    assert 'answer = MsgBox(setupAsk, 292, "Thomas")' in text, "Yes/No with No as the default button"
    assert text.count("setupAsk = ") == len(thomas_app._SETUP_QUESTION)
    assert thomas_app.setup_question_text().endswith("Set Thomas up now?")


@needs_cscript
def test_the_message_box_shows_the_whole_list_in_order(tmp_path: Path) -> None:
    scenario = {"server": "refused", "exists": [ELECTRON, LAUNCH, RUN_UI], "fail": "electron"}

    kinds, stdout = run_scenario_with_output(tmp_path, "question", scenario)

    assert "msgbox:setup(default No)" in kinds
    assert prompts(stdout)["setup"] == thomas_app.setup_question_text()


def _not_named(scripts: str) -> list[str]:
    """The winget and npm installs in these script texts that the question's table does not know."""
    found = set(re.findall(r'-PackageId "([^"]+)"', scripts)) | set(
        re.findall(r"Invoke-Native \$npm @\(([^)]*)\)", scripts)
    )
    return sorted(found - set(WINGET_PACKAGES) - set(NPM_CALLS))


def test_a_new_winget_or_npm_install_in_the_scripts_is_not_passed_over() -> None:
    """The check below only means something if it notices an install nobody wrote a question line for."""
    added = (
        _both()
        + '\nInstall-WithWinget -PackageId "Foo.Bar" -DisplayName "Foo"\nInvoke-Native $npm @("i", "-g", "baz")\n'
    )

    assert _not_named(_both()) == []
    assert _not_named(added) == ['"i", "-g", "baz"', "Foo.Bar"]


def _unnamed(scripts: str, lines: tuple[str, ...]) -> list[str]:
    """Markers the scripts contain whose words are not all together on one line of the question.

    One line, not the question as a whole: 'Python' is also in 'Thomas's Python packages', 'winget'
    is in the Node.js and Ollama line and 'Ollama' in 'start Ollama', so words found anywhere would
    leave a dropped line unnoticed.
    """
    markers = {**WINGET_PACKAGES, **NPM_CALLS, **OTHER_EFFECTS}
    return [m for m, words in markers.items() if m in scripts and not any(all(w in ln for w in words) for ln in lines)]


def test_every_install_and_change_in_the_scripts_is_named_in_the_question() -> None:
    scripts = _both()

    assert not _not_named(scripts), f"the scripts install something the question does not name: {_not_named(scripts)}"
    for marker in {**WINGET_PACKAGES, **NPM_CALLS, **OTHER_EFFECTS}:
        assert marker in scripts, f"the question names something the scripts no longer do: {marker}"
    assert _unnamed(scripts, thomas_app._SETUP_QUESTION) == [], "a line of the question that names an install is gone"


def test_a_question_that_lost_a_line_is_noticed_even_when_its_words_appear_elsewhere() -> None:
    """Dropping one bullet must fail the check although its words are still in other bullets."""
    scripts = _both()
    question = thomas_app._SETUP_QUESTION

    def without(fragment: str) -> tuple[str, ...]:
        kept = tuple(line for line in question if fragment not in line)
        assert len(kept) == len(question) - 1, fragment
        return kept

    assert _unnamed(scripts, question) == []
    assert _unnamed(scripts, without("- install Python, with winget")) == ["Python.Python.3.11", "Python.Python.3.12"]
    assert _unnamed(scripts, without("- install Node.js and Ollama")) == [
        "OpenJS.NodeJS.LTS",
        "Ollama.Ollama",
        '"i", "-g", "@openai/codex"',
    ]
    assert _unnamed(scripts, without("- run npm install")) == ['"install", "--no-audit", "--no-fund"']
    assert _unnamed(scripts, without("Boot Doctor")) == ["bootdoctor.ps1"]


def test_the_pip_installs_are_the_ones_the_question_names_or_belong_to_the_tray() -> None:
    """pystray and its friends install only for a tray start, which the launcher never asks for."""
    run_ui = _script("run-ui.ps1")
    installs = re.findall(r'"-m", "pip", "install"((?:, "[^"]+")+)', run_ui)
    start = thomas_app.render_launcher(thomas_app.DEFAULT_PORT)

    assert {i for i in installs if "pystray" not in i} == {', "-e", ".[server]", "--disable-pip-version-check"'}
    assert any("pystray" in i for i in installs), "the tray install moved; look at this test again"
    assert "-Tray" not in start, "the launcher would ask for a tray start, which installs more than the question says"
    assert "$Tray" in run_ui and "if (-not $NoTray)" in run_ui
    # setup.ps1 installs Python packages itself unless it is told not to, and run-ui.ps1 tells it.
    assert "'-Easy', '-NoPrompt', '-SkipInstall', '-SkipDoctor'" in run_ui


def _pip_installs_outside_the_skip_block(setup: str) -> list[int]:
    """Where in setup.ps1 a pip install runs that run-ui.ps1's -SkipInstall would not stop."""
    guard = setup.index("if (-not $SkipInstall) {")
    end = setup.index("\n}\n", guard)
    return [m.start() for m in re.finditer(r'"-m", "pip", "install"', setup) if not guard < m.start() < end]


def test_setup_ps1_runs_pip_install_only_where_the_launcher_start_skips_it() -> None:
    """The question names 'Thomas's Python packages' once, for run-ui.ps1's own pip install."""
    setup = _script("setup.ps1")
    added = setup + '\n$code = Invoke-Native $VenvPy @("-m", "pip", "install", "something")\n'

    assert setup.count('"-m", "pip", "install"') >= 1
    assert _pip_installs_outside_the_skip_block(setup) == []
    assert len(_pip_installs_outside_the_skip_block(added)) == 1, "a new pip install outside the block goes unseen"


def test_the_launcher_starts_run_ui_with_no_switch_that_changes_what_it_installs() -> None:
    start = thomas_app.render_launcher(thomas_app.DEFAULT_PORT)

    assert '-File " & Chr(34) & runUiPs1 & Chr(34)' in start, "the launcher no longer runs run-ui.ps1 itself"
    for switch in ("-Tray", "-NoInstall", "-DeepLink", "-Port", "-AutoPort", "-StrictPort"):
        assert switch not in start, switch
