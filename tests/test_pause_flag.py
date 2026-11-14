"""The saved Pause flag: ``thomas.core.pause`` keeps ``paused.json`` in the data folder and never raises on a read."""

from __future__ import annotations

import json
import logging

import pytest

from thomas.core import pause as pause_mod


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("THOMAS_PROFILE", raising=False)
    monkeypatch.setattr(pause_mod, "_warned_for", None)
    return tmp_path


def test_a_missing_file_means_not_paused(data_dir):
    assert pause_mod.paused() is False
    assert pause_mod.state() == {"paused": False, "since": None, "reason": ""}


def test_pause_saves_the_flag_in_the_data_folder_and_resume_clears_it(data_dir):
    got = pause_mod.pause("going out")
    assert got["paused"] is True and got["reason"] == "going out" and got["since"]
    assert json.loads((data_dir / "paused.json").read_text(encoding="utf-8"))["paused"] is True
    assert pause_mod.paused() is True
    assert pause_mod.resume()["paused"] is False
    assert pause_mod.paused() is False


def test_pausing_twice_keeps_the_first_time_and_reason(data_dir):
    first = pause_mod.pause("one")
    again = pause_mod.pause("two")
    assert again == first


def test_the_flag_survives_a_new_process_reading_the_same_folder(data_dir):
    pause_mod.pause()
    assert pause_mod.state()["paused"] is True


def test_an_unreadable_file_means_not_paused_and_warns_once(data_dir, caplog):
    (data_dir / "paused.json").write_text("{not json", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger=pause_mod.log.name):
        assert pause_mod.paused() is False
        assert pause_mod.paused() is False
    warnings = [r for r in caplog.records if "paused.json" in r.getMessage()]
    assert len(warnings) == 1


def test_a_file_that_is_a_folder_does_not_raise(data_dir):
    (data_dir / "paused.json").mkdir()
    assert pause_mod.paused() is False


def test_the_write_leaves_no_temporary_file(data_dir):
    pause_mod.pause("x")
    assert sorted(p.name for p in data_dir.iterdir()) == ["paused.json"]


def test_a_replace_refused_for_a_moment_is_retried(data_dir, monkeypatch):
    import os

    from thomas.core import atomic_json

    real = os.replace
    calls = {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError("held")
        return real(src, dst)

    monkeypatch.setattr(atomic_json.os, "replace", flaky)
    assert pause_mod.pause("retry")["paused"] is True
    assert calls["n"] == 3


def test_core_does_not_import_the_server():
    import ast
    import pathlib

    tree = ast.parse(pathlib.Path(pause_mod.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        names = [a.name for a in node.names] if isinstance(node, ast.Import) else [getattr(node, "module", "") or ""]
        assert not any(n.startswith("thomas.server") for n in names)
