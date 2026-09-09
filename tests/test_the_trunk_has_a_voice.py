"""The trunk's syncability gets a voice at session start (branch-equilibrium
plan, phase 2 Task 1, the internal design record.

Before this module, ``dev`` sat 746 commits unpushed because the pre-push
gate battery had been failing silently for weeks -- nothing at session start
ever said "the trunk cannot sync" or "the last push attempt was blocked".
These tests pin the honesty contracts ``scripts/crew/brief/trunk_health.py``
exists to satisfy, every one of them against real, hermetic git fixture
repos (never the live Thomas repo, never a fetch, never the network):

* an honest zero (nothing unpushed, an empty cache) reads as exactly that,
  not as "unknown";
* a missing remote-tracking ref degrades to ``unknown (<reason>)``, never a
  fabricated zero or a raised exception;
* an absent push-gate cache reads ``unchecked (never)``;
* a stale cache (older than the freshness window) reads ``unchecked (Nd)``,
  the same bucket as absent -- a stale "it passed" is not trustworthy
  evidence about code that has since changed;
* a blocked cache names the blocking gates;
* a corrupted cache file (garbage bytes, non-UTF-8, wrong JSON shape) never
  raises -- ``summarize()``/``render_text()`` degrade to ``unchecked`` with a
  reason instead of crashing session start.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import scripts.crew.brief.trunk_health as trunk_health

TRUNK_BRANCH = "dev"
TRUNK_REMOTE = "dev-origin"


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _commit(repo: Path, rel_path: str, content: str, message: str) -> str:
    path = repo / rel_path
    path.write_text(content, encoding="utf-8")
    _git(repo, "add", rel_path)
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _init_repo(repo: Path, *, branch: str) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-b", branch)
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "tag.gpgsign", "false")


@pytest.fixture
def bare_remote(tmp_path: Path) -> Path:
    remote = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", "-b", TRUNK_BRANCH, str(remote)], check=True, capture_output=True)
    return remote


@pytest.fixture
def synced_repo(tmp_path: Path, bare_remote: Path) -> Path:
    """A working checkout with ``dev`` pushed to ``dev-origin`` and nothing
    unpushed -- the honest-zero baseline every other fixture branches from."""
    work = tmp_path / "work"
    _init_repo(work, branch=TRUNK_BRANCH)
    _commit(work, "a.txt", "a\n", "seed")
    _git(work, "remote", "add", TRUNK_REMOTE, str(bare_remote))
    _git(work, "push", TRUNK_REMOTE, TRUNK_BRANCH)
    return work


@pytest.fixture
def unsynced_repo(tmp_path: Path) -> Path:
    """A working checkout with no remote configured at all -- the repo is
    real and has commits, but has never heard of ``dev-origin``."""
    work = tmp_path / "work"
    _init_repo(work, branch=TRUNK_BRANCH)
    _commit(work, "a.txt", "a\n", "seed")
    return work


# ---------------------------------------------------------------------------
# Honest zero
# ---------------------------------------------------------------------------


def test_a_freshly_synced_trunk_reports_an_honest_zero(synced_repo: Path) -> None:
    result = trunk_health.count_unpushed(synced_repo, trunk_branch=TRUNK_BRANCH, trunk_remote=TRUNK_REMOTE)
    assert result == {"ok": True, "count": 0, "reason": ""}


def test_unpushed_commits_are_counted_live(synced_repo: Path) -> None:
    _commit(synced_repo, "b.txt", "b\n", "local work 1")
    _commit(synced_repo, "c.txt", "c\n", "local work 2")

    result = trunk_health.count_unpushed(synced_repo, trunk_branch=TRUNK_BRANCH, trunk_remote=TRUNK_REMOTE)

    assert result["ok"] is True
    assert result["count"] == 2


def test_zero_stashes_is_an_honest_zero_not_a_failure(synced_repo: Path) -> None:
    result = trunk_health.count_stashes(synced_repo)
    assert result == {"ok": True, "count": 0, "reason": ""}


def test_real_stashes_are_counted_live(synced_repo: Path) -> None:
    (synced_repo / "a.txt").write_text("changed\n", encoding="utf-8")
    _git(synced_repo, "stash", "push", "-m", "wip 1")
    (synced_repo / "a.txt").write_text("changed again\n", encoding="utf-8")
    _git(synced_repo, "stash", "push", "-m", "wip 2")

    result = trunk_health.count_stashes(synced_repo)

    assert result == {"ok": True, "count": 2, "reason": ""}


def test_local_and_remote_branch_counts_are_live_reads(synced_repo: Path) -> None:
    _git(synced_repo, "branch", "topic-a")
    _git(synced_repo, "branch", "topic-b")

    result = trunk_health.count_branches(synced_repo, trunk_remote=TRUNK_REMOTE)

    assert result["local"] == 3  # dev + topic-a + topic-b
    assert result["remote_ok"] is True
    assert result["remote"] == 1  # only dev has been pushed


def test_render_text_labels_the_remote_count_as_a_mirror(synced_repo: Path) -> None:
    """I1 (adversarial review, fix round 1): the remote count is the
    on-disk ``refs/remotes/<remote>`` mirror, not a live read -- it can run
    stale relative to the real remote (deleted-but-unpruned branches), so
    the line must say so rather than print a bare number that reads as
    as-of-now."""
    line = trunk_health.render_text(trunk_health.summarize(synced_repo, trunk_remote=TRUNK_REMOTE))

    assert "branches 1/1(mirror)" in line


def test_the_mirror_suffix_is_never_appended_to_an_unknown_remote(unsynced_repo: Path) -> None:
    line = trunk_health.render_text(trunk_health.summarize(unsynced_repo, trunk_remote=TRUNK_REMOTE))

    assert "(mirror)" not in line


# ---------------------------------------------------------------------------
# Unknown-not-fake on a missing remote
# ---------------------------------------------------------------------------


def test_a_repo_with_no_such_remote_reports_unknown_not_zero(unsynced_repo: Path) -> None:
    unpushed = trunk_health.count_unpushed(unsynced_repo, trunk_branch=TRUNK_BRANCH, trunk_remote=TRUNK_REMOTE)
    branches = trunk_health.count_branches(unsynced_repo, trunk_remote=TRUNK_REMOTE)

    assert unpushed["ok"] is False
    assert "no remote-tracking ref" in unpushed["reason"]
    assert branches["remote_ok"] is False
    assert "no such remote" in branches["remote_reason"]
    # Local counts stay live and honest even when the remote is unknown.
    assert branches["local"] == 1


def test_a_configured_remote_with_no_trunk_ref_yet_is_also_unknown(tmp_path: Path, bare_remote: Path) -> None:
    """The remote exists and is configured, but ``dev`` was never pushed to
    it (e.g. a brand-new branch) -- still unknown, not a fabricated zero."""
    work = tmp_path / "work"
    _init_repo(work, branch=TRUNK_BRANCH)
    _commit(work, "a.txt", "a\n", "seed")
    _git(work, "remote", "add", TRUNK_REMOTE, str(bare_remote))
    # Deliberately never pushed -- refs/remotes/dev-origin/dev must not exist.

    result = trunk_health.count_unpushed(work, trunk_branch=TRUNK_BRANCH, trunk_remote=TRUNK_REMOTE)

    assert result["ok"] is False
    assert f"{TRUNK_REMOTE}/{TRUNK_BRANCH}" in result["reason"]


def test_render_text_shows_unknown_reason_inline_not_a_raise(unsynced_repo: Path) -> None:
    summary = trunk_health.summarize(unsynced_repo, trunk_branch=TRUNK_BRANCH, trunk_remote=TRUNK_REMOTE)
    line = trunk_health.render_text(summary)

    assert line.startswith("TRUNK: ")
    assert "unpushed unknown (" in line
    assert "branches 1/unknown (" in line


# ---------------------------------------------------------------------------
# Push-gate cache: absent, stale, blocked
# ---------------------------------------------------------------------------


def test_an_absent_cache_reads_unchecked_never(synced_repo: Path) -> None:
    result = trunk_health.read_push_gate_cache(synced_repo)

    assert result["state"] == "unchecked"
    assert result["age_days"] is None

    line = trunk_health.render_text(trunk_health.summarize(synced_repo, trunk_remote=TRUNK_REMOTE))
    assert "push-gate unchecked (never)" in line


def test_a_fresh_ok_cache_reads_ok(synced_repo: Path) -> None:
    trunk_health.write_push_gate_cache(synced_repo, ok=True, blocked_gates=[])

    result = trunk_health.read_push_gate_cache(synced_repo)
    assert result["state"] == "ok"

    line = trunk_health.render_text(trunk_health.summarize(synced_repo, trunk_remote=TRUNK_REMOTE))
    assert "push-gate ok" in line


def test_a_fresh_blocked_cache_names_the_blocking_gates(synced_repo: Path) -> None:
    trunk_health.write_push_gate_cache(
        synced_repo, ok=False, blocked_gates=["thomas-merge-readiness", "thomas-publish-preflight"]
    )

    result = trunk_health.read_push_gate_cache(synced_repo)
    assert result["state"] == "blocked"
    assert result["blocked_gates"] == ["thomas-merge-readiness", "thomas-publish-preflight"]

    line = trunk_health.render_text(trunk_health.summarize(synced_repo, trunk_remote=TRUNK_REMOTE))
    assert "push-gate blocked: thomas-merge-readiness,thomas-publish-preflight" in line


def test_a_stale_ok_cache_reads_unchecked_with_its_age_not_a_fake_ok(synced_repo: Path) -> None:
    two_days_ago = datetime.now(timezone.utc) - timedelta(days=2)
    trunk_health.write_push_gate_cache(synced_repo, ok=True, blocked_gates=[], now=two_days_ago)

    result = trunk_health.read_push_gate_cache(synced_repo)
    assert result["state"] == "unchecked"
    assert result["age_days"] == 2
    assert "stale" in result["reason"]

    line = trunk_health.render_text(trunk_health.summarize(synced_repo, trunk_remote=TRUNK_REMOTE))
    assert "push-gate unchecked (2d)" in line
    assert "push-gate ok" not in line


def test_a_stale_blocked_cache_still_degrades_to_unchecked_not_blocked(synced_repo: Path) -> None:
    """Staleness wins over the recorded verdict either way: an old FAIL is
    exactly as untrustworthy as an old PASS -- the code has moved on."""
    three_days_ago = datetime.now(timezone.utc) - timedelta(days=3)
    trunk_health.write_push_gate_cache(
        synced_repo, ok=False, blocked_gates=["thomas-merge-readiness"], now=three_days_ago
    )

    result = trunk_health.read_push_gate_cache(synced_repo)

    assert result["state"] == "unchecked"
    assert result["age_days"] == 3


def test_the_stale_threshold_boundary_is_still_fresh_at_exactly_the_edge(synced_repo: Path) -> None:
    just_inside = datetime.now(timezone.utc) - timedelta(seconds=trunk_health.STALE_AFTER_SECONDS - 5)
    trunk_health.write_push_gate_cache(synced_repo, ok=True, blocked_gates=[], now=just_inside)

    assert trunk_health.read_push_gate_cache(synced_repo)["state"] == "ok"


def test_a_far_future_dated_cache_does_not_read_as_fresh_forever(synced_repo: Path) -> None:
    """M1 (adversarial review, fix round 1). Repro: before this fix,
    ``max(0.0, (now - ts).total_seconds())`` clamped the negative age from a
    future ``ts`` to zero, so a year-in-the-future timestamp read
    ``age_days: 0, state: ok`` -- an ``ok`` verdict staleness could never
    expire, since real time would need over a year to catch up to it."""
    a_year_from_now = datetime.now(timezone.utc) + timedelta(days=365)
    trunk_health.write_push_gate_cache(synced_repo, ok=True, blocked_gates=[], now=a_year_from_now)

    result = trunk_health.read_push_gate_cache(synced_repo)

    assert result["state"] == "unchecked"
    assert result["age_days"] is None
    assert "future" in result["reason"]

    line = trunk_health.render_text(trunk_health.summarize(synced_repo, trunk_remote=TRUNK_REMOTE))
    assert "push-gate unchecked (cache unreadable)" in line
    assert "push-gate ok" not in line


def test_benign_clock_skew_within_tolerance_still_reads_fresh(synced_repo: Path) -> None:
    """Not every future timestamp is corruption -- a machine's clock a few
    minutes ahead of the writer's must not be punished the same way a
    year-future value is."""
    thirty_minutes_ahead = datetime.now(timezone.utc) + timedelta(minutes=30)
    trunk_health.write_push_gate_cache(synced_repo, ok=True, blocked_gates=[], now=thirty_minutes_ahead)

    assert trunk_health.read_push_gate_cache(synced_repo)["state"] == "ok"


def test_the_future_tolerance_boundary_is_still_unreadable_just_past_it(synced_repo: Path) -> None:
    just_past = datetime.now(timezone.utc) + timedelta(seconds=trunk_health.FUTURE_TOLERANCE_SECONDS + 5)
    trunk_health.write_push_gate_cache(synced_repo, ok=True, blocked_gates=[], now=just_past)

    result = trunk_health.read_push_gate_cache(synced_repo)
    assert result["state"] == "unchecked"
    assert "future" in result["reason"]


# ---------------------------------------------------------------------------
# Never raises, even under a corrupted cache file
# ---------------------------------------------------------------------------


def test_a_corrupted_cache_file_degrades_to_unchecked_never_raises(synced_repo: Path) -> None:
    cache_path = synced_repo / trunk_health.CACHE_RELATIVE
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text("{not valid json at all", encoding="utf-8")

    result = trunk_health.read_push_gate_cache(synced_repo)
    assert result["state"] == "unchecked"
    assert "unreadable" in result["reason"]

    # And the full session-start path survives it too, distinguished from
    # an absent cache (M1's "cache unreadable" label, not "never").
    line = trunk_health.render_text(trunk_health.summarize(synced_repo, trunk_remote=TRUNK_REMOTE))
    assert line.startswith("TRUNK: ")
    assert "push-gate unchecked (cache unreadable)" in line


def test_a_cache_file_with_invalid_utf8_bytes_never_raises(synced_repo: Path) -> None:
    cache_path = synced_repo / trunk_health.CACHE_RELATIVE
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(b"\xff\xfe\x00garbage-not-utf8")

    result = trunk_health.read_push_gate_cache(synced_repo)

    assert result["state"] == "unchecked"


def test_a_cache_file_with_the_wrong_json_shape_never_raises(synced_repo: Path) -> None:
    cache_path = synced_repo / trunk_health.CACHE_RELATIVE
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")

    result = trunk_health.read_push_gate_cache(synced_repo)

    assert result["state"] == "unchecked"


def test_a_cache_with_no_timestamp_never_raises(synced_repo: Path) -> None:
    cache_path = synced_repo / trunk_health.CACHE_RELATIVE
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({"ok": True}), encoding="utf-8")

    result = trunk_health.read_push_gate_cache(synced_repo)

    assert result["state"] == "unchecked"


def test_summarize_never_raises_when_the_directory_is_not_a_git_repo_at_all(tmp_path: Path) -> None:
    not_a_repo = tmp_path / "not_a_repo"
    not_a_repo.mkdir()

    summary = trunk_health.summarize(not_a_repo, trunk_branch=TRUNK_BRANCH, trunk_remote=TRUNK_REMOTE)
    line = trunk_health.render_text(summary)

    assert isinstance(line, str)
    assert line.startswith("TRUNK:")


def test_render_text_never_raises_on_a_malformed_summary_dict() -> None:
    """A summary dict that does not match the expected shape at all (e.g. a
    caller-side bug) still must not crash the one line session start prints."""
    line = trunk_health.render_text({"ok": True})
    assert line.startswith("TRUNK: ")


def test_render_text_degrades_cleanly_when_summarize_itself_failed() -> None:
    line = trunk_health.render_text({"ok": False, "error": "simulated top-level failure"})
    assert line == "TRUNK: unavailable (simulated top-level failure)"


# ---------------------------------------------------------------------------
# Never fetches -- a cheap, local-only read
# ---------------------------------------------------------------------------


def test_summarize_never_invokes_fetch(monkeypatch: pytest.MonkeyPatch, synced_repo: Path) -> None:
    real_run = subprocess.run

    def _guarded_run(args, *pos_args, **kwargs):  # noqa: ANN001
        if isinstance(args, list) and "fetch" in args:
            raise AssertionError(f"session-start trunk health must never fetch: {args}")
        return real_run(args, *pos_args, **kwargs)

    monkeypatch.setattr(subprocess, "run", _guarded_run)

    trunk_health.summarize(synced_repo, trunk_branch=TRUNK_BRANCH, trunk_remote=TRUNK_REMOTE)


# ---------------------------------------------------------------------------
# The startup_signals.py wiring
# ---------------------------------------------------------------------------


def test_the_startup_signals_wrapper_never_raises_and_delegates(synced_repo: Path) -> None:
    import scripts.crew.brief.startup_signals as startup_signals

    result = startup_signals._startup_trunk_health(synced_repo)

    assert result["ok"] is True
    assert result["unpushed"]["ok"] is True


def test_the_startup_signals_wrapper_degrades_when_the_module_is_unavailable(
    monkeypatch: pytest.MonkeyPatch, synced_repo: Path
) -> None:
    import scripts.crew.brief.startup_signals as startup_signals

    monkeypatch.setattr(startup_signals, "trunk_health", None)

    result = startup_signals._startup_trunk_health(synced_repo)

    assert result == {"ok": False, "error": "trunk_health unavailable"}


def test_the_full_startup_payload_carries_a_trunk_line(synced_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end: the same seam ``incident_surfacing`` already uses --
    ``build_startup_payload`` carries the key, and ``render_startup_text``
    (exercised indirectly through the router's own render path) turns it
    into the printed line."""
    import scripts.crew.brief.startup_router as startup_router

    monkeypatch.setattr(startup_router, "ROOT", synced_repo)

    payload = {"trunk_health": startup_router._startup_trunk_health(synced_repo)}
    line = startup_router.trunk_health.render_text(payload["trunk_health"])

    assert line.startswith("TRUNK: ")
    assert "unpushed" in line
    assert "push-gate" in line
