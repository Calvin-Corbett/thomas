"""The canary notices dev moving, measures only when the check machinery changed, and raises or clears its alarm.

A guard that watched only one lane would not have seen 10-27's operator landings, so the canary reads dev itself.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from scripts.pipeline_canary import canary, measure

STUB = """
import time
from pathlib import Path


class Selection:
    def __init__(self, files):
        self.files = tuple(files)
        self.left_out = ()


def select(root, changed, cap=360):
    delay, count = (Path(root) / "thomas/server/proof/stub.txt").read_text().split()
    time.sleep(float(delay))
    return Selection([f"tests/test_{i}.py" for i in range(int(count))])
"""


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    proof = root / "thomas" / "server" / "proof"
    proof.mkdir(parents=True)
    for package in (root / "thomas", root / "thomas" / "server", proof):
        (package / "__init__.py").write_text("", encoding="utf-8")
    (proof / "selection.py").write_text(STUB, encoding="utf-8")
    (proof / "stub.txt").write_text("0 40", encoding="utf-8")
    _git(tmp_path, "init", "-q", "-b", "dev", str(root))
    for key, value in (("user.email", "canary@test"), ("user.name", "canary"), ("commit.gpgsign", "false")):
        _git(root, "config", key, value)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "start")
    return root


def land(repo: Path, rel: str, text: str) -> str:
    (repo / rel).write_text(text, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", f"change {rel}")
    return _git(repo, "rev-parse", "HEAD")


class Actions:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def alarm(self, alarm: dict) -> dict:
        self.calls.append(("alarm", alarm))
        return {"window": True, "claim": True}

    def clear(self, holds: dict) -> None:
        self.calls.append(("clear", holds))

    def tell(self, title: str, body: str) -> None:
        self.calls.append(("tell", title))


def quick(repo: Path, commit: str, root: Path) -> measure.Measurement:
    return measure.measure(repo, commit, root, timeout_s=3, python=sys.executable)


def once(repo: Path, tmp_path: Path, act: Actions, measure_fn=quick) -> str:
    return canary.run_once(repo, tmp_path / "data", tmp_path / "trees", act, measure_fn=measure_fn)


def test_the_first_run_sets_the_baseline_and_an_unrelated_landing_is_not_measured(repo, tmp_path) -> None:
    act = Actions()
    assert once(repo, tmp_path, act).startswith("baseline ")
    start = canary.load_state(tmp_path / "data")
    assert start["last_good"] == start["last_checked"] == _git(repo, "rev-parse", "HEAD")
    assert once(repo, tmp_path, act) == "dev has not moved"
    other = land(repo, "README.md", "hello")
    assert once(repo, tmp_path, act) == "dev moved without a change to the check machinery"
    state = canary.load_state(tmp_path / "data")
    assert state["last_good"] == state["last_checked"] == other and act.calls == []
    assert len((tmp_path / "data" / "history.jsonl").read_text("utf-8").splitlines()) == 1


def test_a_slow_selection_raises_the_alarm_once_and_a_fast_one_clears_it(repo, tmp_path) -> None:
    act = Actions()
    once(repo, tmp_path, act)
    good = canary.load_state(tmp_path / "data")["last_good"]
    bad = land(repo, "thomas/server/proof/stub.txt", "30 40")
    said = once(repo, tmp_path, act)
    assert said.startswith("ALARM") and "did not finish" in said
    (kind, alarm), *rest = act.calls
    assert kind == "alarm" and not rest
    assert alarm["suspects"] == [bad] and alarm["good"]["commit"] == good and alarm["head"] == bad
    state = canary.load_state(tmp_path / "data")
    assert state["alarm"]["suspects"] == [bad] and state["holds"] == {"window": True, "claim": True}
    assert state["last_good"] == good
    land(repo, "README.md", "still bad underneath")
    assert "alarm still stands" in once(repo, tmp_path, act) and len(act.calls) == 1
    fixed = land(repo, "thomas/server/proof/stub.txt", "0 41")
    assert once(repo, tmp_path, act).startswith("fine")
    assert act.calls[-1] == ("clear", {"window": True, "claim": True})
    state = canary.load_state(tmp_path / "data")
    assert state["alarm"] is None and state["holds"] == {} and state["last_good"] == fixed


def test_a_ratio_alarm_is_measured_once_more_before_it_counts(repo, tmp_path) -> None:
    act = Actions()
    once(repo, tmp_path, act)
    land(repo, "thomas/server/proof/stub.txt", "0 42")
    answers = iter([10.0, 60.0, 10.0, 12.0])  # good, new, then again: the first new was noise

    def noisy(repo: Path, commit: str, root: Path) -> measure.Measurement:
        return measure.Measurement(commit, next(answers), 40)

    assert once(repo, tmp_path, act, noisy).startswith("fine") and act.calls == []
    lines = [json.loads(line) for line in (tmp_path / "data" / "history.jsonl").read_text("utf-8").splitlines()]
    assert [line["seconds"] for line in lines[-4:]] == [10.0, 60.0, 10.0, 12.0]
