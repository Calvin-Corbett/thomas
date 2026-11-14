"""The last push of dev to GitHub is saved and shown as one plain sentence where the app shows landing health.

Proves: thomas.core.github_push_status, scripts.crew.brief.push_after_land, scripts.crew.brief.push_dev,
thomas.server.app_routes_task_ledger.

Every remote is a bare repository in tmp_path, and the data folder is tmp_path's too.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
from pathlib import Path

import pytest
from aiohttp.test_utils import AioHTTPTestCase
from scripts.crew.brief import push_after_land

from thomas.core import github_push_status as gps
from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.preferences.store import PreferencesPatch, PreferencesStore
from thomas.server.app import create_app

NOW = time.mktime((2026, 11, 3, 15, 0, 0, 0, 0, -1))
TWO_41_PM = time.mktime((2026, 11, 3, 14, 41, 0, 0, 0, -1))


def git(cwd: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    return done.stdout.strip()


def hook(path: Path, body: str) -> None:
    path.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8", newline="\n")
    path.chmod(0o755)


@pytest.fixture(autouse=True)
def own_data_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))


@pytest.fixture
def pair(tmp_path):
    remote, work = tmp_path / "remote.git", tmp_path / "work"
    git(tmp_path, "init", "-q", "--bare", str(remote))
    git(tmp_path, "init", "-q", "-b", "dev", str(work))
    git(work, "config", "user.email", "t@example.com")
    git(work, "config", "user.name", "t")
    git(work, "remote", "add", "dev-origin", str(remote))
    (work / "a.txt").write_text("1\n")
    git(work, "add", "-A")
    git(work, "commit", "-qm", "first")
    return work, remote


def land_one_more(work: Path, name: str) -> None:
    (work / name).write_text(name)
    git(work, "add", "-A")
    git(work, "commit", "-qm", name)


def push(work: Path, **kw):
    return push_after_land.push_after_landing(work, agent="claude", db_path=work / "none.db", **kw)


def said(work: Path) -> dict:
    return gps.collect_github_push(work)


def test_a_push_is_said_with_the_time_it_happened(pair) -> None:
    work, _remote = pair
    assert push(work).status == "pushed"
    reading = said(work)
    assert reading["status"] == "pushed" and reading["level"] == "ok" and reading["behind"] == 0
    assert reading["sentence"].startswith("Last pushed to GitHub: ")
    assert reading["last_pushed_sha"] == git(work, "rev-parse", "dev")


def test_the_sentence_names_today_and_yesterday_in_plain_clock_words() -> None:
    state = {"status": "pushed", "at": TWO_41_PM, "last_pushed_at": TWO_41_PM}
    assert gps.describe(state, 0, NOW) == ("ok", "Last pushed to GitHub: today 2:41 pm.")
    assert gps.describe(state, 0, NOW + 86400)[1] == "Last pushed to GitHub: yesterday 2:41 pm."
    assert gps.describe(state, 3, NOW)[1].endswith("3 landings since then are not there yet.")
    assert gps.describe(state, 1, NOW)[1].endswith("1 landing since then is not there yet.")


def test_a_check_that_stopped_the_push_is_recorded_and_shown_with_its_reason(pair) -> None:
    work, remote = pair
    assert push(work).status == "pushed"
    for name in ("b.txt", "c.txt", "d.txt"):
        land_one_more(work, name)
    hook(work / ".git" / "hooks" / "pre-push", 'echo "core overhead guard: 4 lines over" >&2; exit 1')
    assert push(work).status == "blocked"
    reading = said(work)
    assert reading["level"] == "act" and reading["behind"] == 3
    assert reading["sentence"] == (
        "GitHub is behind by 3 landings: a check stopped the push: core overhead guard: 4 lines over"
    )
    assert git(remote, "rev-parse", "dev") != git(work, "rev-parse", "dev")


def test_a_refusal_from_github_is_shown_with_its_reason(pair) -> None:
    work, remote = pair
    assert push(work).status == "pushed"
    land_one_more(work, "b.txt")
    hook(remote / "hooks" / "pre-receive", 'echo "protected branch: dev needs a pull request" >&2; exit 1')
    assert push(work).status == "refused"
    sentence = said(work)["sentence"]
    assert sentence.startswith("GitHub is behind by 1 landing: GitHub refused the push: ")
    assert "protected branch: dev needs a pull request" in sentence


def test_a_turned_off_setting_is_shown_as_off(pair, tmp_path) -> None:
    work, _remote = pair
    db = tmp_path / "settings.db"
    PreferencesStore(db_path=str(db)).patch(PreferencesPatch(advanced={"runtime": {"push_dev_after_landing": False}}))
    assert push_after_land.push_after_landing(work, agent="claude", db_path=db).status == "off"
    assert said(work)["sentence"] == "Pushing to GitHub after a landing is turned off in your settings."


def test_a_push_put_off_and_one_that_waits_are_said(pair) -> None:
    work, _remote = pair
    assert push(work, others_waiting=True).status == "deferred"
    assert "when the landing still in line has finished" in said(work)["sentence"]
    gps.record("waiting", "a push is running")
    assert said(work)["sentence"].startswith("A push to GitHub is waiting for the one already running")


def test_a_push_that_says_it_is_running_for_hours_is_taken_as_dead(pair) -> None:
    work, _remote = pair
    gps.record("pushing", "pushing", now=time.time() - 3 * 3600)
    assert "never finished" in said(work)["sentence"]


def test_before_any_push_and_with_no_github_remote_it_says_so(pair, tmp_path) -> None:
    work, _remote = pair
    assert said(work)["sentence"] == "Nothing has been pushed to GitHub from this app yet."
    lone = tmp_path / "lone"
    git(tmp_path, "init", "-q", "-b", "dev", str(lone))
    assert "no dev-origin remote" in said(lone)["sentence"]


def test_an_unreadable_record_is_said_not_raised(pair) -> None:
    work, _remote = pair
    gps.state_path().parent.mkdir(parents=True, exist_ok=True)
    gps.state_path().write_text("{not json", encoding="utf-8")
    assert said(work)["sentence"] == "The record of the last push to GitHub could not be read just now."


def test_the_reason_is_the_hooks_line_not_gits_wrapper_text() -> None:
    out = "claim gate said no\nerror: failed to push some refs to 'x'\nhint: updates were rejected\n"
    assert gps.one_line_reason(out) == "claim gate said no"
    assert gps.one_line_reason("", "fallback words") == "fallback words"


class TestLandingHealthShowsTheLastPush(AioHTTPTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._saved = {k: os.environ.get(k) for k in ("THOMAS_DB_PATH", "THOMAS_DATA_DIR")}
        os.environ["THOMAS_DB_PATH"] = os.path.join(self._tmp.name, "prefs.sqlite")
        os.environ["THOMAS_DATA_DIR"] = os.path.join(self._tmp.name, "data")

    def tearDown(self) -> None:
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        try:
            self._tmp.cleanup()
        finally:
            super().tearDown()

    async def get_application(self):
        cfg = AppConfig(
            models={"local": ModelConfig(name="local", model="dummy")},
            default_model="local",
            memory=MemoryConfig(root=self._tmp.name),
            server=ServerConfig(access_mode="local"),
        )
        return create_app(cfg)

    async def test_the_sentence_is_in_the_landing_health_reading(self):
        gps.record("blocked", "not pushed", output="the claim gate said no\nerror: failed to push some refs\n")
        resp = await self.client.get("/api/landing-health")
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        sentence = body["github_push"]["sentence"]
        self.assertIn("a check stopped the push: the claim gate said no", sentence)
        self.assertEqual(body["github_push"]["level"], "act")
        self.assertEqual(body["sentences"][-1], sentence)
        self.assertEqual(body["headline"], body["sentences"][0])
