"""The public-repo leak guard says what a PASS covered, and can insist on its blocklist.

The substring rules live in a local, git-ignored blocklist. A fresh clone (CI included) has none, so there the
gate enforces only its path rules -- yet it printed the same "PASS (no internal artifacts detected)" as a full
run. A PASS that covered less than it claimed is how drift gets through, so the message now names its scope,
and ``--require-blocklist`` fails a run that would check paths only.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

leak_guard = importlib.import_module("forge.gates.public_repo_leak_guard")


def _run(monkeypatch: pytest.MonkeyPatch, blocklist: Path, *flags: str) -> int:
    monkeypatch.setattr(leak_guard, "LOCAL_BLOCKLIST_PATH", blocklist)
    monkeypatch.setattr(leak_guard, "_tracked_files", lambda: ["README.md"])
    monkeypatch.setattr(leak_guard, "_scan_paths", lambda paths: ([], []))
    monkeypatch.setattr(sys, "argv", ["public_repo_leak_guard.py", *flags])
    return leak_guard.main()


def test_without_a_blocklist_the_pass_says_only_path_rules_ran(monkeypatch, tmp_path, capsys) -> None:
    assert _run(monkeypatch, tmp_path / "missing.json") == 0

    out = capsys.readouterr().out
    assert "substring rules NOT loaded" in out
    assert "PASS (path rules only)" in out


def test_require_blocklist_fails_when_the_blocklist_is_absent(monkeypatch, tmp_path, capsys) -> None:
    assert _run(monkeypatch, tmp_path / "missing.json", "--require-blocklist") == 1

    assert "FAIL: --require-blocklist" in capsys.readouterr().out


def test_with_the_blocklist_present_the_pass_is_full(monkeypatch, tmp_path, capsys) -> None:
    blocklist = tmp_path / "leak_blocklist.local.json"
    blocklist.write_text(json.dumps({"forbidden_substrings": ["acmecorp"]}), encoding="utf-8")

    assert _run(monkeypatch, blocklist, "--require-blocklist") == 0

    out = capsys.readouterr().out
    assert "PASS (full)" in out
    assert "NOT loaded" not in out
