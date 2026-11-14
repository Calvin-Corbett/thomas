"""A change that only deletes lines from a file adds no broad handler to it.

On 2026-11-09 a commit that removed eight lines from ``thomas/server/app_routes_init.py`` and added none was refused
with "Found 1 new broad exception handler(s)", naming a handler written long before. With no added lines the gate took
"nothing was added" for "the change could not be read" and flagged every handler in the file that does not log and
raise again. Any deletion from such a file was refused.

What must still be caught: a handler that stops meeting the rule because a line inside it was deleted, and a change
that really could not be read.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[1]


def _load() -> Any:
    spec = importlib.util.spec_from_file_location(
        "exception_handler_gate", _REPO / "scripts/forge/gates/exception_handler_gate.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


gate = _load()

BEFORE = """
def cleanup(task):
    try:
        task.cancel()
    except Exception:
        log.exception("a background task failed during cleanup")


def cancel_route(request):
    return answer(request)
"""

# The second function is gone and nothing else changed: the handler moved up, and is the one it always was.
AFTER_A_DELETION = """
def cleanup(task):
    try:
        task.cancel()
    except Exception:
        log.exception("a background task failed during cleanup")
"""

MET_THE_RULE = """
def save(thing):
    try:
        write(thing)
    except Exception:
        log.exception("could not save")
        raise
"""

# Only the ``raise`` was deleted: the same handler no longer meets the rule.
RAISE_DELETED = """
def save(thing):
    try:
        write(thing)
    except Exception:
        log.exception("could not save")
"""


def _flagged(before: str | None, after: str) -> set[int]:
    return gate._new_without_added_lines(before, after, set(gate._find_broad_handlers(after)))


def test_a_handler_that_was_already_there_is_not_new_after_a_deletion() -> None:
    assert gate._find_broad_handlers(AFTER_A_DELETION)  # it does break the rule, and did before
    assert _flagged(BEFORE, AFTER_A_DELETION) == set()


def test_a_handler_that_lost_its_raise_is_flagged() -> None:
    assert gate._find_broad_handlers(MET_THE_RULE) == []
    assert len(_flagged(MET_THE_RULE, RAISE_DELETED)) == 1


def test_an_earlier_version_that_cannot_be_read_flags_everything() -> None:
    assert len(_flagged(None, AFTER_A_DELETION)) == 1
    assert len(_flagged("def broken(:", AFTER_A_DELETION)) == 1


def test_one_old_handler_forgives_only_one() -> None:
    twice = AFTER_A_DELETION + AFTER_A_DELETION.replace("def cleanup", "def cleanup_again")
    assert len(_flagged(BEFORE, twice)) == 1


def _run(monkeypatch, capsys, *, hunks: dict[str, set[int]]) -> int:
    path = "thomas/server/some_file.py"
    monkeypatch.setattr(gate, "_staged_files", lambda: [path])
    monkeypatch.setattr(gate, "_staged_content", lambda rel: AFTER_A_DELETION)
    monkeypatch.setattr(gate, "_git_show_head", lambda rel: BEFORE)
    monkeypatch.setattr(gate, "_added_lines_per_file", lambda base=None, head=None: hunks)
    monkeypatch.setattr(gate, "_is_pure_rename", lambda rel, base=None, head=None: False)
    monkeypatch.setattr(gate, "_signatures_removed_elsewhere", lambda files, base, head: gate.Counter())
    monkeypatch.setattr(gate, "_exception_ratchet", lambda: True)
    code = gate.run([])
    capsys.readouterr()
    return code


def test_the_gate_passes_a_file_whose_change_only_deletes(monkeypatch, capsys) -> None:
    assert _run(monkeypatch, capsys, hunks={"thomas/server/some_file.py": set()}) == 0


def test_the_gate_still_refuses_when_the_change_could_not_be_read(monkeypatch, capsys) -> None:
    assert _run(monkeypatch, capsys, hunks={}) == 1
