"""Removals and renames count toward the commit-scope limit, and so do added files.

An earlier draft of the scope gate exempted removed and renamed files, on the argument that a deletion is one visible line.
The owner-facing review of the gate-parity batch asked for the opposite: every changed code file counts, so a commit that touches
more than 50 files is split whatever the files are. The price is real and is recorded here so nobody finds it by surprise:
a cleanup like 93415742 (1,584 dead listings removed in one commit) cannot go through commit.py in one piece; it has to be split
or landed some other way.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

_REPO = Path(__file__).resolve().parents[1]


def _load() -> Any:
    spec = importlib.util.spec_from_file_location(
        "commit_scope_gate", _REPO / "scripts/forge/gates/commit_scope_gate.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


gate = _load()


class _Proc:
    def __init__(self, stdout: str) -> None:
        self.stdout = stdout
        self.stderr = ""
        self.returncode = 0


def _staged(monkeypatch: pytest.MonkeyPatch, lines: list[str]) -> None:
    """Make the gate see exactly this staged name-status listing."""

    def _fake_run(argv: list[str], **kwargs: Any) -> _Proc:
        return _Proc("\n".join(line.split("\t")[-1] for line in lines) + "\n")

    monkeypatch.setattr(gate.subprocess, "run", _fake_run)


def test_sixty_removals_are_over_the_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    _staged(monkeypatch, [f"D\textensions/listing_{i}.py" for i in range(60)])

    assert gate.run(["--json"]) == 1


def test_sixty_renames_are_over_the_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    _staged(monkeypatch, [f"R100\tolds/a_{i}.py\tnews/a_{i}.py" for i in range(60)])

    assert gate.run(["--json"]) == 1


def test_a_removal_mixed_with_new_code_counts_everything(monkeypatch: pytest.MonkeyPatch) -> None:
    _staged(monkeypatch, [f"D\tdead/old_{i}.py" for i in range(30)] + [f"A\tthomas/added_{i}.py" for i in range(30)])

    assert gate.run(["--json"]) == 1


def test_fifty_removals_stay_under_the_hard_limit_but_still_need_a_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    _staged(monkeypatch, [f"D\tdead/old_{i}.py" for i in range(40)])
    monkeypatch.setattr(gate, "_load_verification_record", lambda: None)

    assert gate.run(["--json"]) == 1, "more than 20 files needs a scope justification, whatever the files are"


def test_twenty_files_are_fine(monkeypatch: pytest.MonkeyPatch) -> None:
    _staged(monkeypatch, [f"D\tdead/old_{i}.py" for i in range(20)])

    assert gate.run(["--json"]) == 0
