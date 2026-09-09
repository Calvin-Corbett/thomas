"""Tests for the landing heartbeat (`thomas.core.landing_health`).

Two things are being defended here:

1. **The thresholds mean what they say.** Every boundary is tested from both
   sides -- one below and exactly on -- so a silently loosened constant or a
   ``>`` that should be ``>=`` fails a test instead of quietly reclassifying a
   pile of work as fine.
2. **It cannot crash the thing it is checking.** No git, no repo, no remote, a
   detached head, git that hangs -- each must come back as ``unknown`` with an
   honest sentence. A health check that raises inside a server's startup task
   is worse than no health check at all.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest

from aiohttp.test_utils import AioHTTPTestCase

from thomas.core import landing_health as lh
from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.server.app import create_app


def describe(
    *,
    commits_ahead: int = 0,
    files_diverged: int = 0,
    days_default: float | None = 0.0,
    days_branch: float | None = 0.0,
    uncommitted: int = 0,
    branch: str = "dev",
    default_branch: str = "origin/main",
) -> tuple[str, list[str]]:
    """Call the verdict builder with everything quiet unless a test says otherwise."""
    return lh._describe(
        branch=branch,
        default_branch=default_branch,
        commits_ahead=commits_ahead,
        files_diverged=files_diverged,
        days_default=days_default,
        days_branch=days_branch,
        uncommitted=uncommitted,
    )


def severity_of(**kwargs) -> str:
    return describe(**kwargs)[0]


def _git_available() -> bool:
    return shutil.which("git") is not None


def _init_repo(path: str, *, remote: str | None = None) -> None:
    """A real one-commit git repo on disk, optionally with a remote."""
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    run = lambda *args: subprocess.run(  # noqa: E731
        ["git", *args], cwd=path, capture_output=True, text=True, check=True, env=env, timeout=30
    )
    run("init", "--initial-branch=main")
    run("-c", "user.name=T", "-c", "user.email=t@example.com", "commit", "--allow-empty", "-m", "first")
    if remote:
        run("remote", "add", "origin", remote)


class TestThresholdValuesArePinned(unittest.TestCase):
    """The agreed numbers, written out in full.

    Every other threshold test compares against the constants, so it measures
    the comparison logic but moves with the constant -- raise
    ``COMMITS_AHEAD_ACT`` to 5000 and those tests all still pass while the
    alarm silently stops working. (Confirmed by mutation: that exact change
    was missed until this test existed.) These literals are the promise. If
    someone wants a different number they have to change it here too, which
    makes it a visible decision in review rather than a quiet one.
    """

    def test_size_thresholds(self):
        self.assertEqual(lh.COMMITS_AHEAD_WATCH, 25)
        self.assertEqual(lh.COMMITS_AHEAD_ACT, 50)
        self.assertEqual(lh.FILES_DIVERGED_WATCH, 100)
        self.assertEqual(lh.FILES_DIVERGED_ACT, 200)

    def test_time_thresholds(self):
        self.assertEqual(lh.DAYS_DEFAULT_STALE_WATCH, 7)
        self.assertEqual(lh.DAYS_DEFAULT_STALE_ACT, 21)
        self.assertEqual(lh.DAYS_BRANCH_IDLE_WATCH, 7)
        self.assertEqual(lh.DAYS_BRANCH_IDLE_ACT, 21)

    def test_safety_threshold(self):
        self.assertEqual(lh.UNCOMMITTED_FILES_WATCH, 20)

    def test_the_pile_that_caused_this_module_reads_as_act(self):
        """576 changes / 1,890 files / main stale 64 days. Literal numbers on purpose."""
        self.assertEqual(severity_of(commits_ahead=576, files_diverged=1890, days_default=64.0), lh.SEVERITY_ACT)
        # And each of the three on its own would have been enough.
        self.assertEqual(severity_of(commits_ahead=576), lh.SEVERITY_ACT)
        self.assertEqual(severity_of(commits_ahead=1, files_diverged=1890), lh.SEVERITY_ACT)
        self.assertEqual(severity_of(commits_ahead=1, days_default=64.0), lh.SEVERITY_ACT)

    def test_a_normal_days_work_is_not_an_alarm(self):
        """Literal numbers: 4 changes, 12 files, everything fresh."""
        self.assertEqual(
            severity_of(commits_ahead=4, files_diverged=12, days_default=1.0, days_branch=0.2),
            lh.SEVERITY_OK,
        )


class TestThresholdBoundaries(unittest.TestCase):
    """Each threshold, from just below and from exactly on."""

    def test_commits_ahead_boundaries(self):
        self.assertEqual(severity_of(commits_ahead=lh.COMMITS_AHEAD_WATCH - 1), lh.SEVERITY_OK)
        self.assertEqual(severity_of(commits_ahead=lh.COMMITS_AHEAD_WATCH), lh.SEVERITY_WATCH)
        self.assertEqual(severity_of(commits_ahead=lh.COMMITS_AHEAD_ACT - 1), lh.SEVERITY_WATCH)
        self.assertEqual(severity_of(commits_ahead=lh.COMMITS_AHEAD_ACT), lh.SEVERITY_ACT)

    def test_files_diverged_boundaries(self):
        # commits_ahead=1 so there is unlanded work for the files to belong to.
        self.assertEqual(severity_of(commits_ahead=1, files_diverged=lh.FILES_DIVERGED_WATCH - 1), lh.SEVERITY_OK)
        self.assertEqual(severity_of(commits_ahead=1, files_diverged=lh.FILES_DIVERGED_WATCH), lh.SEVERITY_WATCH)
        self.assertEqual(severity_of(commits_ahead=1, files_diverged=lh.FILES_DIVERGED_ACT - 1), lh.SEVERITY_WATCH)
        self.assertEqual(severity_of(commits_ahead=1, files_diverged=lh.FILES_DIVERGED_ACT), lh.SEVERITY_ACT)

    def test_days_since_default_moved_boundaries(self):
        low = lh.DAYS_DEFAULT_STALE_WATCH
        high = lh.DAYS_DEFAULT_STALE_ACT
        self.assertEqual(severity_of(commits_ahead=1, days_default=low - 0.1), lh.SEVERITY_OK)
        self.assertEqual(severity_of(commits_ahead=1, days_default=float(low)), lh.SEVERITY_WATCH)
        self.assertEqual(severity_of(commits_ahead=1, days_default=high - 0.1), lh.SEVERITY_WATCH)
        self.assertEqual(severity_of(commits_ahead=1, days_default=float(high)), lh.SEVERITY_ACT)

    def test_branch_idle_boundaries_catch_abandonment(self):
        """Three saved changes untouched for three weeks. No size rule sees this."""
        low = lh.DAYS_BRANCH_IDLE_WATCH
        high = lh.DAYS_BRANCH_IDLE_ACT
        self.assertEqual(severity_of(commits_ahead=3, days_branch=low - 0.1), lh.SEVERITY_OK)
        self.assertEqual(severity_of(commits_ahead=3, days_branch=float(low)), lh.SEVERITY_WATCH)
        self.assertEqual(severity_of(commits_ahead=3, days_branch=float(high)), lh.SEVERITY_ACT)

    def test_uncommitted_files_boundary_watches_but_never_acts(self):
        self.assertEqual(severity_of(uncommitted=lh.UNCOMMITTED_FILES_WATCH - 1), lh.SEVERITY_OK)
        self.assertEqual(severity_of(uncommitted=lh.UNCOMMITTED_FILES_WATCH), lh.SEVERITY_WATCH)
        # Unsaved work is a different risk from an unlanded pile: it warns, it
        # never escalates on its own.
        self.assertEqual(severity_of(uncommitted=10_000), lh.SEVERITY_WATCH)

    def test_time_signals_stay_quiet_when_nothing_is_waiting(self):
        """An empty pile plus a quiet month is a holiday, not a problem."""
        verdict, sentences = describe(commits_ahead=0, days_default=400.0, days_branch=400.0)
        self.assertEqual(verdict, lh.SEVERITY_OK)
        self.assertIn("Nothing is waiting to land", " ".join(sentences))

    def test_worst_signal_decides_the_verdict(self):
        """A quiet size reading must not talk a loud time reading down."""
        self.assertEqual(severity_of(commits_ahead=2, files_diverged=3, days_default=90.0), lh.SEVERITY_ACT)


class TestSentencesAreReadable(unittest.TestCase):
    def test_sentences_quote_the_actual_numbers(self):
        verdict, sentences = describe(commits_ahead=576, files_diverged=1890, days_default=64.2, uncommitted=31)
        text = " ".join(sentences)
        self.assertEqual(verdict, lh.SEVERITY_ACT)
        self.assertIn("576", text)
        self.assertIn("1890", text)
        self.assertIn("64 days ago", text)
        self.assertIn("31", text)

    def test_every_sentence_is_non_empty_and_plain_ascii(self):
        for kwargs in (
            {},
            {"commits_ahead": 30},
            {"commits_ahead": 576, "files_diverged": 1890, "days_default": 64.0},
            {"uncommitted": 40},
        ):
            _verdict, sentences = describe(**kwargs)
            self.assertTrue(sentences, f"no sentences for {kwargs}")
            for sentence in sentences:
                self.assertTrue(sentence.strip(), f"empty sentence for {kwargs}")
                # A cp1252 Windows console has to be able to print this.
                sentence.encode("ascii")

    def test_ok_reading_says_you_are_ready_to_work(self):
        _verdict, sentences = describe()
        self.assertIn("ready to work", sentences[0])

    def test_headline_is_the_first_sentence(self):
        for kwargs in ({}, {"commits_ahead": 30}, {"commits_ahead": 600, "days_default": 64.0}):
            _verdict, sentences = describe(**kwargs)
            self.assertEqual(sentences[0], lh._headline(_verdict, "main"))

    def test_counts_of_one_are_not_pluralised(self):
        _verdict, sentences = describe(commits_ahead=1)
        self.assertIn("1 saved change ", " ".join(sentences) + " ")


class TestDegradesInsteadOfRaising(unittest.TestCase):
    """Every hostile environment produces 'unknown', never a traceback."""

    def _assert_honest_unknown(self, health: lh.LandingHealth) -> None:
        self.assertEqual(health.severity, lh.SEVERITY_UNKNOWN)
        self.assertTrue(health.sentences)
        self.assertTrue(all(s.strip() for s in health.sentences))
        # An unknown reading must never invent numbers.
        self.assertIsNone(health.commits_ahead)
        self.assertIsNone(health.files_diverged)
        self.assertIsNone(health.uncommitted_files)
        json.dumps(health.as_dict())

    def test_directory_that_is_not_a_git_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._assert_honest_unknown(lh.collect_landing_health(tmp))

    def test_path_that_does_not_exist_at_all(self):
        missing = os.path.join(tempfile.gettempdir(), "landing-health-no-such-dir-8977")
        self._assert_honest_unknown(lh.collect_landing_health(missing))

    def test_git_missing_from_path(self):
        original = lh.shutil.which
        lh.shutil.which = lambda _name: None
        try:
            health = lh.collect_landing_health()
        finally:
            lh.shutil.which = original
        self._assert_honest_unknown(health)
        self.assertIn("Git is not installed", " ".join(health.sentences))

    def test_every_git_command_timing_out(self):
        original = lh.subprocess.run

        def always_times_out(*_args, **_kwargs):
            raise subprocess.TimeoutExpired(cmd="git", timeout=1.0)

        lh.subprocess.run = always_times_out
        try:
            health = lh.collect_landing_health()
        finally:
            lh.subprocess.run = original
        self._assert_honest_unknown(health)

    def test_git_binary_that_cannot_be_executed(self):
        original = lh.subprocess.run

        def always_oserror(*_args, **_kwargs):
            raise OSError("git exploded")

        lh.subprocess.run = always_oserror
        try:
            health = lh.collect_landing_health()
        finally:
            lh.subprocess.run = original
        self._assert_honest_unknown(health)

    @unittest.skipUnless(_git_available(), "git is not installed")
    def test_real_repo_with_no_remote(self):
        with tempfile.TemporaryDirectory() as tmp:
            _init_repo(tmp)
            health = lh.collect_landing_health(tmp)
        self._assert_honest_unknown(health)
        self.assertIn("no shared copy", " ".join(health.sentences))

    @unittest.skipUnless(_git_available(), "git is not installed")
    def test_real_repo_with_a_remote_that_was_never_fetched(self):
        """A remote is configured but no origin/main ref exists locally."""
        with tempfile.TemporaryDirectory() as tmp:
            _init_repo(tmp, remote="https://example.invalid/nope.git")
            health = lh.collect_landing_health(tmp)
        self._assert_honest_unknown(health)

    @unittest.skipUnless(_git_available(), "git is not installed")
    def test_detached_head(self):
        with tempfile.TemporaryDirectory() as tmp:
            _init_repo(tmp)
            sha = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=tmp, capture_output=True, text=True, check=True
            ).stdout.strip()
            subprocess.run(
                ["git", "checkout", "--detach", sha],
                cwd=tmp,
                capture_output=True,
                text=True,
                check=True,
            )
            health = lh.collect_landing_health(tmp)
        self._assert_honest_unknown(health)


class TestAgainstTheLiveRepo(unittest.TestCase):
    @unittest.skipUnless(_git_available(), "git is not installed")
    def test_reading_this_repo_is_well_formed(self):
        health = lh.collect_landing_health()
        self.assertIn(
            health.severity,
            {lh.SEVERITY_OK, lh.SEVERITY_WATCH, lh.SEVERITY_ACT, lh.SEVERITY_UNKNOWN},
        )
        self.assertTrue(health.sentences)
        self.assertEqual(health.headline, health.sentences[0])
        json.dumps(health.as_dict())

    @unittest.skipUnless(_git_available(), "git is not installed")
    def test_reading_this_repo_is_fast_enough_for_a_background_task(self):
        import time

        started = time.monotonic()
        lh.collect_landing_health()
        self.assertLess(time.monotonic() - started, lh.GIT_TOTAL_BUDGET_SECONDS)


class TestLandingHealthEndpoint(AioHTTPTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._prev_db_path = os.environ.get("THOMAS_DB_PATH")
        os.environ["THOMAS_DB_PATH"] = os.path.join(self._tmpdir.name, "prefs_landing.sqlite")

    def tearDown(self) -> None:
        if self._prev_db_path is None:
            os.environ.pop("THOMAS_DB_PATH", None)
        else:
            os.environ["THOMAS_DB_PATH"] = self._prev_db_path
        try:
            self._tmpdir.cleanup()
        finally:
            super().tearDown()

    async def get_application(self):
        cfg = AppConfig(
            models={"local": ModelConfig(name="local", model="dummy")},
            default_model="local",
            memory=MemoryConfig(root=self._tmpdir.name),
            server=ServerConfig(access_mode="local"),
        )
        return create_app(cfg)

    async def test_endpoint_returns_the_reading(self):
        resp = await self.client.get("/api/landing-health")
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        for key in (
            "severity",
            "headline",
            "sentences",
            "branch",
            "default_branch",
            "commits_ahead",
            "files_diverged",
            "days_since_default_moved",
            "days_since_branch_commit",
            "uncommitted_files",
            "checked_at",
            "thresholds",
        ):
            self.assertIn(key, body)
        self.assertIn(body["severity"], {"ok", "watch", "act", "unknown"})
        self.assertTrue(body["sentences"])
        self.assertEqual(body["headline"], body["sentences"][0])
        self.assertEqual(body["thresholds"]["commits_ahead_act"], lh.COMMITS_AHEAD_ACT)


if __name__ == "__main__":
    unittest.main()
