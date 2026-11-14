"""A slim proof copy's miss detector logs reads of tracked files the copy left out.

Spec: docs/superpowers/specs/2026-10-29-kernel-plugins-fast-checks-design.md section 3 (Misses): a miss voids the
scoped run, it never becomes a failure that dev shares and that gets excused.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import os
import sys
from pathlib import Path

import pytest

from tests import slim_copy_audit as audit


def test_a_read_and_a_listing_of_absent_files_are_logged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    absent, log = tmp_path / "absent.txt", tmp_path / "misses.jsonl"
    gone = tmp_path / "pkg" / "gone.py"
    absent.write_text(str(gone) + "\n", encoding="utf-8")
    (tmp_path / "pkg").mkdir()
    monkeypatch.setenv(audit.ENV_ABSENT, str(absent))
    monkeypatch.setenv(audit.ENV_LOG, str(log))
    audit.install()
    try:
        with pytest.raises(FileNotFoundError):
            open(gone, encoding="utf-8")
        os.listdir(tmp_path / "pkg")
        os.listdir(tmp_path)  # holds no absent file directly: not a miss
    finally:
        audit.stop()
    got = audit.misses(log)
    assert [r[1] for r in got] == ["open", "os.listdir"]
    assert got[0][0].endswith("gone.py") and Path(got[1][0]) == tmp_path / "pkg"
    assert "test_a_read_and_a_listing_of_absent_files_are_logged" in got[0][2]


def test_pytest_listing_a_folder_on_the_way_to_named_tests_is_not_a_miss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # pytest 8 lists each folder above a named test file, then keeps only the files it was named: what it collects
    # is the same in a slim copy as in a full checkout. A test listing the folder itself still sees fewer files.
    from _pytest.pathlib import scandir as pytest_scandir

    absent, log = tmp_path / "absent.txt", tmp_path / "misses.jsonl"
    absent.write_text(str(tmp_path / "pkg" / "gone.py") + "\n", encoding="utf-8")
    (tmp_path / "pkg").mkdir()
    monkeypatch.setenv(audit.ENV_ABSENT, str(absent))
    monkeypatch.setenv(audit.ENV_LOG, str(log))
    audit.install()
    try:
        pytest_scandir(tmp_path / "pkg")
        with os.scandir(tmp_path / "pkg"):
            pass
    finally:
        audit.stop()
    assert [r[1] for r in audit.misses(log)] == ["os.scandir"]


def test_the_import_system_finding_a_module_is_not_a_miss(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Python lists a package's folder to find a module in it. A module the copy left out then fails its import, loudly.
    absent, log = tmp_path / "absent.txt", tmp_path / "misses.jsonl"
    folder = tmp_path / "pkg"
    folder.mkdir()
    (folder / "slim_audit_probe.py").write_text("X = 1\n", encoding="utf-8")
    absent.write_text(str(folder / "gone.py") + "\n", encoding="utf-8")
    monkeypatch.setenv(audit.ENV_ABSENT, str(absent))
    monkeypatch.setenv(audit.ENV_LOG, str(log))
    monkeypatch.syspath_prepend(str(folder))
    audit.install()
    try:
        importlib.import_module("slim_audit_probe")
        # pytest looks for installed plugins once each run.
        list(importlib.metadata.distributions(path=[str(folder)]))
        os.listdir(folder)  # a test listing it still sees fewer files than a full checkout has
    finally:
        audit.stop()
        sys.modules.pop("slim_audit_probe", None)
    assert [r[1] for r in audit.misses(log)] == ["os.listdir"]


def test_the_manifest_loader_seeing_one_manifest_is_not_a_miss(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A copy holds its own plugin's manifest by design, or every scoped run would void itself on the fence test.
    from thomas.core import plugin_manifest

    absent, log = tmp_path / "absent.txt", tmp_path / "misses.jsonl"
    folder = tmp_path / "plugins"
    folder.mkdir()
    absent.write_text(str(folder / "other.toml") + "\n", encoding="utf-8")
    monkeypatch.setenv(audit.ENV_ABSENT, str(absent))
    monkeypatch.setenv(audit.ENV_LOG, str(log))
    audit.install()
    try:
        assert plugin_manifest.load(tmp_path) == ()
        list(folder.glob("*.toml"))  # a test listing it through pathlib still sees fewer files
    finally:
        audit.stop()
    assert [r[1] for r in audit.misses(log)] == ["os.scandir"]


def test_nothing_is_watched_without_both_variables(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log = tmp_path / "misses.jsonl"
    monkeypatch.delenv(audit.ENV_ABSENT, raising=False)
    monkeypatch.setenv(audit.ENV_LOG, str(log))
    audit.install()
    try:
        with pytest.raises(FileNotFoundError):
            open(tmp_path / "nothing.py", encoding="utf-8")
    finally:
        audit.stop()
    assert audit.misses(log) == []


def test_each_process_logs_alone_and_the_reader_gets_them_all(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Workers sharing one log overwrote each other's lines on Windows, and the reader then failed on the wreck."""
    log = tmp_path / "misses.jsonl"
    monkeypatch.setitem(audit._state, "log", str(log))
    for pid in (101, 202):
        monkeypatch.setattr(audit.os, "getpid", lambda pid=pid: pid)
        audit._record(f"left-out-{pid}.py", "open")
    assert len(list(tmp_path.iterdir())) == 2
    assert sorted(record[0] for record in audit.misses(log)) == ["left-out-101.py", "left-out-202.py"]
