"""The canary's command line: one pass, its status, a replay of two commits, and never two passes at once."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
from scripts.pipeline_canary import __main__ as cli

from tests.test_pipeline_canary_run import land, repo  # noqa: F401


def run(repo: Path, tmp_path: Path, *args: str) -> int:
    return cli.main(["--repo", str(repo), "--data", str(tmp_path / "data"), "--scratch", str(tmp_path / "t"), *args])


def test_once_sets_a_baseline_then_finds_dev_unmoved_and_status_says_so(repo, tmp_path, capsys) -> None:
    assert run(repo, tmp_path, "once") == 0
    assert capsys.readouterr().out.startswith("baseline ")
    assert run(repo, tmp_path, "once") == 0
    assert capsys.readouterr().out.strip() == "dev has not moved"
    log = (tmp_path / "data" / "canary.log").read_text("utf-8").splitlines()
    assert len(log) == 2 and log[-1].endswith("dev has not moved")
    assert run(repo, tmp_path, "status") == 0
    status = json.loads(capsys.readouterr().out)
    assert status["state"]["last_good"] and status["state"]["alarm"] is None and len(status["recent"]) == 1


def test_a_pass_already_running_is_not_joined(repo, tmp_path, capsys) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "run.lock").write_text(str(os.getpid()), encoding="utf-8")
    assert run(repo, tmp_path, "once") == 0
    assert "already running" in capsys.readouterr().out
    assert not (tmp_path / "data" / "state.json").exists()


def test_a_lock_left_by_a_pass_long_gone_is_taken_over(repo, tmp_path, capsys) -> None:
    (tmp_path / "data").mkdir()
    lock = tmp_path / "data" / "run.lock"
    lock.write_text("1", encoding="utf-8")
    old = time.time() - cli.STALE_LOCK_S - 60
    os.utime(lock, (old, old))
    assert run(repo, tmp_path, "once") == 0
    assert capsys.readouterr().out.startswith("baseline ") and not lock.exists()


@pytest.mark.parametrize(("second", "verdict"), [("0 41", "fine"), ("30 41", "ALARM")])
def test_replay_judges_two_commits_measured_back_to_back(repo, tmp_path, capsys, monkeypatch, second, verdict) -> None:
    monkeypatch.setattr(cli.measure, "BACKSTOP_S", 3)
    good = land(repo, "thomas/server/proof/stub.txt", "0 39")
    new = land(repo, "thomas/server/proof/stub.txt", second)
    assert run(repo, tmp_path, "replay", good, new) == 0
    assert capsys.readouterr().out.splitlines()[-1].startswith(verdict)
