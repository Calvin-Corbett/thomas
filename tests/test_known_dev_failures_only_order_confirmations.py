"""What dev is known to fail orders a check's re-runs and never excuses a failure (spec 2026-10-12 Part 1 item 2).

The record is kept by dev tree, interpreter and environment. Build teams run as the account that can write it, so a
false entry may only delay or block a change: the re-run on dev, alone, is still the only excuse. A record no one can
read (too deep or too large) is no record at all, never a check that cannot run.

``precard.known`` is imported inside the tests that need it, and the two guards patch it only where it exists, so the
guards also run, and pass, on a dev without it.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tests.test_the_change_runs_once_and_dev_only_when_needed import TEST, Copies, copies  # noqa: F401 -- fixture
from thomas.server import green_checkout
from thomas.server.precard import check
from thomas.server.proof import ProofRun, runner

FOLDER = "precard-known"


def test_the_known_on_dev_record_only_orders_and_never_excuses(copies: Copies, monkeypatch: pytest.MonkeyPatch) -> None:
    if hasattr(check, "known"):
        monkeypatch.setattr(check.known, "key", lambda *_a, **_k: "k1")
        monkeypatch.setattr(check.known, "read", lambda _key: frozenset({TEST}))
    copies.change_run = ProofRun(True, "", (TEST,), 5, 1)
    copies.alone_change[TEST], copies.alone_dev[TEST] = runner.FAILED, runner.PASSED

    checked = copies.check()

    assert checked.state == check.FAILED and TEST in checked.findings


def test_dev_failures_confirmed_alone_are_remembered_for_the_next_check(
    copies: Copies, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from thomas.server.precard import known

    monkeypatch.setattr(green_checkout, "green_root", lambda: tmp_path / "greens")
    monkeypatch.setattr(check.known, "key", lambda *_a, **_k: "k1")
    copies.change_run = ProofRun(True, "", (TEST,), 5, 1)
    copies.alone_change[TEST] = copies.alone_dev[TEST] = runner.FAILED
    assert copies.check().state == check.PASSED
    assert known.read("k1") == frozenset({TEST})

    real, given = check.proofs.confirm, {}
    monkeypatch.setattr(check.proofs, "confirm", lambda *a, **k: given.update(k) or real(*a, **k))
    copies.check()
    assert TEST in given["known_on_dev"]


def test_a_record_that_cannot_be_read_or_written_never_changes_a_check(
    copies: Copies, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "greens"
    root.mkdir()
    (root / FOLDER).write_text("a file where the folder should be", encoding="utf-8")
    monkeypatch.setattr(green_checkout, "green_root", lambda: root)
    if hasattr(check, "known"):
        monkeypatch.setattr(check.known, "key", lambda *_a, **_k: "k1")
    copies.change_run = ProofRun(True, "", (TEST,), 5, 1)
    copies.alone_change[TEST], copies.alone_dev[TEST] = runner.FAILED, runner.PASSED

    assert copies.check().state == check.FAILED
    assert not (root / FOLDER).is_dir(), "nothing was written in its place"


def test_a_record_too_deep_or_too_large_to_read_is_no_record_and_never_stops_a_check(
    copies: Copies, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Whole review I2: a nested record raised RecursionError, an unexpected strike on every check on that dev."""
    from thomas.server.precard import known

    (tmp_path / FOLDER).mkdir()
    (tmp_path / FOLDER / "deep.json").write_text("[" * 100_000 + "]" * 100_000, encoding="utf-8")
    large = [f"tests/test_x.py::test_{n:07d}" for n in range(60_000)]  # over 1 MB; the record keeps at most 400
    (tmp_path / FOLDER / "large.json").write_text(json.dumps(large), encoding="utf-8")
    monkeypatch.setattr(green_checkout, "green_root", lambda: tmp_path)

    assert known.read("deep") == frozenset() and known.read("large") == frozenset()

    monkeypatch.setattr(check.known, "key", lambda *_a, **_k: "deep")
    copies.change_run = ProofRun(True, "", (TEST,), 5, 1)
    copies.alone_change[TEST], copies.alone_dev[TEST] = runner.FAILED, runner.PASSED

    assert copies.check().state == check.FAILED


def test_the_key_names_the_dev_tree_the_interpreter_and_the_environment(tmp_path: Path) -> None:
    from thomas.server.precard import known

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    for args in (
        ("init", "-q"),
        ("add", "-A"),
        ("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "a"),
    ):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
    copy = green_checkout.Green("copy", repo, repo / ".git", "base", repo)

    first = known.key(copy, "python-a")

    assert first and first == known.key(copy, "python-a")
    assert first != known.key(copy, "python-b")
    assert first != known.key(copy, "python-a", {"EXTRA": "1"})
    assert known.key(object(), "python-a") == ""
