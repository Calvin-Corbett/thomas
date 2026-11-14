"""A shell script in the release bundle runs on macOS and Linux, whichever OS built it.

A Windows checkout holds install.sh with CRLF line endings (git's autocrlf, and the repo
has no .gitattributes rule), and the packager copied the bytes as they were. The source
zip then carried ``set -euo pipefail\\r``, which bash rejects as an invalid option name,
and ``./install.sh`` failed with a bad interpreter error.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = b"#!/usr/bin/env bash\nset -euo pipefail\necho hello\n"


def _packager():
    spec = importlib.util.spec_from_file_location("_pkg_release_eol", ROOT / "scripts" / "package_release.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _stage(tmp_path: Path, monkeypatch, files: dict[str, bytes]) -> Path:
    module = _packager()
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    for name, data in files.items():
        (checkout / name).parent.mkdir(parents=True, exist_ok=True)
        (checkout / name).write_bytes(data)
    monkeypatch.setattr(module, "ROOT", checkout)
    stage = tmp_path / "stage"
    stage.mkdir()
    copied, skipped = module._copy_to_stage(sorted(files), stage)
    assert copied == len(files) and not skipped
    return stage


def test_a_crlf_shell_script_is_staged_with_lf(tmp_path: Path, monkeypatch) -> None:
    stage = _stage(tmp_path, monkeypatch, {"install.sh": SCRIPT.replace(b"\n", b"\r\n")})
    staged = (stage / "install.sh").read_bytes()
    assert b"\r" not in staged, "bash reads the carriage return as part of each line"
    assert staged == SCRIPT


def test_an_lf_shell_script_is_staged_unchanged(tmp_path: Path, monkeypatch) -> None:
    stage = _stage(tmp_path, monkeypatch, {"install.sh": SCRIPT})
    assert (stage / "install.sh").read_bytes() == SCRIPT


def test_windows_scripts_keep_the_line_endings_they_were_written_with(tmp_path: Path, monkeypatch) -> None:
    cmd = b"@echo off\r\necho hello\r\n"
    stage = _stage(tmp_path, monkeypatch, {"install.cmd": cmd, "scripts/run-ui.ps1": cmd})
    assert (stage / "install.cmd").read_bytes() == cmd
    assert (stage / "scripts" / "run-ui.ps1").read_bytes() == cmd
