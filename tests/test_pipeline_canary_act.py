"""On an alarm the canary tells you, holds the window and the watched folders, and puts the revert on your card.

It lifts only what it set, and it prepares a revert only when one landing changed the watched paths and reverting it
applies cleanly on dev's head (2026-10-27).
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

import pytest
from scripts import active_folders
from scripts.pipeline_canary import act, canary


def _git(repo: Path, *args: str, stdin: str | None = None) -> str:
    done = subprocess.run(["git", "-C", str(repo), *args], input=stdin, capture_output=True, text=True, check=True)
    return done.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "thomas" / "server" / "proof").mkdir(parents=True)
    _git(tmp_path, "init", "-q", "-b", "dev", str(root))
    for key, value in (("user.email", "canary@test"), ("user.name", "canary"), ("commit.gpgsign", "false")):
        _git(root, "config", key, value)
    land(root, "thomas/server/proof/selection.py", "def select():\n    return 1\n")
    return root


def land(repo: Path, rel: str, text: str) -> str:
    (repo / rel).write_text(text, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", f"change {rel}")
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def actions(repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    state_dir = tmp_path / "coordination"
    state_dir.mkdir()
    monkeypatch.setattr(active_folders, "STATE_DIR", state_dir)
    monkeypatch.setattr(active_folders, "STATE_FILE", state_dir / "active_folders.json")
    monkeypatch.setattr(active_folders, "LOCK_FILE", state_dir / "active_folders.lock")
    told: list[tuple[str, str]] = []
    real = act.RealActions(repo, tmp_path / "cage", notify=lambda title, body: told.append((title, body)))
    return real, told, tmp_path / "cage"


def alarm_for(repo: Path, suspects: list[str]) -> dict:
    return {
        "head": _git(repo, "rev-parse", "HEAD"),
        "good": {"commit": "g", "seconds": 28.5, "files": 35, "left_out": 0, "error": ""},
        "new": {"commit": "n", "seconds": None, "files": 0, "left_out": 0, "error": "it did not finish: over 600 s"},
        "reasons": ["it did not finish: over 600 s"],
        "suspects": suspects,
    }


def claims() -> list[dict]:
    try:
        return json.loads(active_folders.STATE_FILE.read_text("utf-8")).get("claims") or []
    except OSError:
        return []


def test_the_window_is_held_and_lifted_only_when_the_canary_set_it(repo, actions) -> None:
    real, told, cage = actions
    bad = land(repo, "thomas/server/proof/selection.py", "def select():\n    return 2\n")
    holds = real.alarm(alarm_for(repo, [bad]))
    off = cage / "promoter" / "window" / "off"
    assert holds["window"] is True and off.read_text("utf-8").startswith(act.OFF_TEXT)
    assert told and "alarm" in told[0][0].lower()
    real.clear(holds)
    assert not off.exists() and len(told) == 2


def test_a_window_you_turned_off_is_left_alone_both_ways(repo, actions) -> None:
    real, _told, cage = actions
    off = cage / "promoter" / "window" / "off"
    off.parent.mkdir(parents=True)
    off.write_text("off", encoding="utf-8")
    holds = real.alarm(alarm_for(repo, []))
    assert holds["window"] is False
    real.clear(holds)
    assert off.read_text("utf-8") == "off"


def test_the_watched_folders_are_claimed_and_released(repo, actions) -> None:
    real, _told, _cage = actions
    holds = real.alarm(alarm_for(repo, []))
    mine = [claim for claim in claims() if claim["agent_id"] == act.AGENT]
    assert holds["claim"] is True and len(mine) == 1
    assert sorted(mine[0]["paths"]) == sorted(f"{path}/" for path in canary.WATCHED)
    real.clear(holds)
    assert not [claim for claim in claims() if claim["agent_id"] == act.AGENT]


def test_one_clean_suspect_puts_its_revert_on_your_card(repo, actions) -> None:
    real, _told, cage = actions
    bad = land(repo, "thomas/server/proof/selection.py", "def select():\n    return 2\n")
    holds = real.alarm(alarm_for(repo, [bad]))
    sid = holds["revert"]
    folder = cage / "inbox" / sid
    assert re.match(r"^self-[A-Za-z0-9_-]{1,80}$", sid) and folder.is_dir()
    manifest = json.loads((folder / "submission.json").read_text("utf-8"))
    patch = (folder / "change.patch").read_bytes()
    assert manifest["kind"] == "self_change" and manifest["id"] == sid and manifest["base"] == bad
    assert manifest["patch_sha256"] == hashlib.sha256(patch).hexdigest() and manifest["agent"] == act.AGENT
    assert manifest["files"] == ["thomas/server/proof/selection.py"] and bad[:8] in manifest["message"]
    # It applies on dev's head, as bytes: text mode would write CRLF into git's input on Windows.
    subprocess.run(["git", "-C", str(repo), "apply", "--check", "-"], input=patch, capture_output=True, check=True)


def test_no_revert_for_two_suspects_or_one_that_no_longer_applies(repo, actions) -> None:
    real, _told, cage = actions
    first = land(repo, "thomas/server/proof/selection.py", "def select():\n    return 2\n")
    second = land(repo, "thomas/server/proof/selection.py", "def select():\n    return 3\n")
    assert real.alarm(alarm_for(repo, [first, second]))["revert"] == ""
    assert real.alarm(alarm_for(repo, [first]))["revert"] == ""  # second rewrote the same lines
    assert not (cage / "inbox").exists() or not list((cage / "inbox").iterdir())


def test_a_notification_that_fails_never_stops_the_canary(repo, tmp_path) -> None:
    def broken(title: str, body: str) -> None:
        raise OSError("no notifications here")

    real = act.RealActions(repo, tmp_path / "cage", notify=broken)
    real.tell("title", "body")
