"""install.sh picks a supported Python, and keeps an editable install editable.

install.sh looked only at ``python3`` and ``python``, so a machine whose default python3
is newer than Thomas supports (Homebrew ships 3.14) was told no suitable Python exists
although python3.12 sat beside it. And a venv that already held an editable install
(run-ui makes one) had it replaced by a snapshot copy. The script is never run whole;
each test cuts the one step out of it and runs only that, in a temporary folder, with
stand-in interpreters that just print a version.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
CANDIDATES = ("python3.13", "python3.12", "python3.11", "python3.10", "python3", "python")
UNSUPPORTED = "3.14"


def _install_sh() -> str:
    return (ROOT / "install.sh").read_text(encoding="utf-8")


def _working_bash() -> str | None:
    bash = shutil.which("bash")
    if not bash:
        return None
    try:
        probe = subprocess.run(
            [bash, "-c", "echo ok"], capture_output=True, text=True, timeout=45, creationflags=_NO_WINDOW
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return bash if probe.stdout.strip() == "ok" else None


def _run(lines: list[str], cwd: Path) -> subprocess.CompletedProcess:
    script = "set -euo pipefail\n" + "\n".join(lines) + "\n"
    bash = _working_bash()
    if bash is None:
        pytest.skip("no working bash on this machine")
    try:
        return subprocess.run(
            [bash, "-s"],
            input=script.encode("utf-8"),
            cwd=cwd,
            capture_output=True,
            timeout=90,
            creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired):
        pytest.skip("bash could not run the script here")


def _out(done: subprocess.CompletedProcess) -> str:
    return (done.stdout + done.stderr).decode("utf-8", "replace")


def _python_step() -> str:
    text = _install_sh()
    start = text.index('PYTHON=""\n')
    return text[start : text.index('ok "Found $PYTHON')]


def _fake_pythons(folder: Path, versions: dict[str, str]) -> None:
    """One stand-in for every name install.sh tries, so no real interpreter is ever found."""
    folder.mkdir()
    for name in CANDIDATES:
        version = versions.get(name, UNSUPPORTED)
        shim = f'#!/bin/sh\ncase "$*" in\n*version_info*) echo "{version}";;\n*) echo "Python {version}.0";;\nesac\n'
        (folder / name).write_bytes(shim.encode("ascii"))


@pytest.mark.parametrize(
    ("versions", "picked"),
    [
        ({"python3.12": "3.12"}, "python3.12"),  # default python3 is too new; 3.12 sits beside it
        ({"python3.13": "3.13", "python3.12": "3.12", "python3": "3.12"}, "python3.13"),  # newest first
        ({"python3": "3.11"}, "python3"),  # an older system with only the plain names
        ({"python": "3.10"}, "python"),
    ],
)
def test_the_install_picks_the_newest_supported_python(tmp_path: Path, versions: dict[str, str], picked: str) -> None:
    _fake_pythons(tmp_path / "bin", versions)
    done = _run(_with_fake_pythons_first(), tmp_path)
    assert f"PICKED={picked}\n" in _out(done).replace("\r", ""), _out(done)


def _with_fake_pythons_first() -> list[str]:
    return ['fail() { echo "FAILED: $*"; exit 1; }', 'PATH="$PWD/bin:$PATH"', _python_step(), 'echo "PICKED=$PYTHON"']


def test_a_machine_with_only_a_too_new_python_gets_the_reason(tmp_path: Path) -> None:
    _fake_pythons(tmp_path / "bin", {})
    done = _run(_with_fake_pythons_first(), tmp_path)
    assert done.returncode != 0
    assert "Python 3.10 to 3.13 is required" in _out(done), _out(done)
    assert "PICKED=" not in _out(done)


def _editable_step() -> str:
    match = re.search(r'^    if \[ "\$\{THOMAS_DEV:-\}" != "1" \]; then\n.*?\n    fi\n', _install_sh(), re.M | re.S)
    assert match, "install.sh no longer checks the venv for an editable install; update this test with it"
    return match.group(0)


def _venv_holding(root: Path, *names: str) -> None:
    site = root / "venv" / "lib" / "python3.12" / "site-packages"
    site.mkdir(parents=True)
    for name in names:
        target = site / name
        if name.endswith(".dist-info"):
            target.mkdir()
        else:
            target.write_text("", encoding="utf-8")


@pytest.mark.parametrize(
    ("names", "wanted"),
    [
        (("__editable__.thomas_ai-0.19.41.pth", "__editable___thomas_ai_0_19_41_finder.py"), "1"),
        (("thomas_ai-0.19.41.dist-info",), ""),  # a copy install: nothing to keep
        ((), ""),
    ],
)
def test_a_venv_that_holds_an_editable_install_keeps_it(tmp_path: Path, names: tuple[str, ...], wanted: str) -> None:
    _venv_holding(tmp_path, *names)
    lines = ['info() { echo "INFO $*"; }', "unset THOMAS_DEV", 'VENV_DIR="$PWD/venv"', _editable_step()]
    done = _run(lines + ['echo "DEV=${THOMAS_DEV:-}"'], tmp_path)
    assert done.returncode == 0, _out(done)
    assert f"DEV={wanted}\n" in _out(done).replace("\r", ""), _out(done)
