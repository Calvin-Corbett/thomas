"""The sprawl curve never guesses (branch-equilibrium plan, phase 2 Task 3,
docs/superpowers/plans/2026-08-27-branch-equilibrium.md).

``scripts/forge/sprawl_history.py`` reads five sources -- remote-tracking
reflogs, the graveyard, archive refs, hardcoded milestone shas, and two
cited historical anchors -- and reports a weekly series. Every field is
MEASURED, CITED, or explicitly UNKNOWN; nothing is interpolated or
estimated. These tests pin that contract against real, hermetic fixture
repos (never the live Thomas repo, never a network call):

* a week outside every anchor's date reports ``"unknown"``, not a guess;
* an anchor week reports its value with the correct provenance
  (``"measured"``/``"cited"``);
* the graveyard is grouped by kind and recorded date, and an all-seeded
  kind is flagged honestly (a recording date is not a death date);
* a missing graveyard is an honest zero, not an error;
* remote-tracking reflog absence is reported as ``available: False`` with a
  reason, never a fabricated zero branch count;
* real reflog file parsing extracts the correct first/last timestamps;
* the JSON schema's top-level shape and row shape are stable across runs.
"""

from __future__ import annotations

import json
import subprocess
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
import scripts.forge.sprawl_history as sprawl_history

TRUNK_BRANCH = "dev"
TRUNK_REMOTE = "dev-origin"

# A date range that deliberately does NOT overlap 2026-08-27 -- the real date
# every hardcoded CITED_ANCHORS entry and every "measured, this run" anchor
# carries. Using it isolates "does the bucketing/unknown-marking logic work"
# from "do the real anchors happen to land in my fixture's window", which
# would conflate two different things this suite tests separately.
NON_ANCHOR_SINCE = date(2020, 1, 1)
NON_ANCHOR_UNTIL = date(2020, 3, 1)


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _commit(repo: Path, rel_path: str, content: str, message: str, *, when: str | None = None) -> str:
    path = repo / rel_path
    path.write_text(content, encoding="utf-8")
    _git(repo, "add", rel_path)
    env = None
    if when is not None:
        import os

        env = {**os.environ, "GIT_COMMITTER_DATE": when, "GIT_AUTHOR_DATE": when}
    subprocess.run(["git", "commit", "-m", message], cwd=repo, check=True, capture_output=True, text=True, env=env)
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


# A fixed, early root-commit date every fixture repo seeds at -- deliberately
# before any synthetic reflog timestamp this suite writes (2026-06 onward),
# so the plausibility floor (_repo_root_commit_iso) never rejects a
# legitimate test fixture entry as "before the repo existed."
_ROOT_COMMIT_DATE = "2026-01-01T00:00:00-05:00"


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
def bare_repo(tmp_path: Path) -> Path:
    """A real, minimal repo with no remote configured at all -- the honest
    baseline for testing 'no remote reflogs exist' behavior. Rooted at
    ``_ROOT_COMMIT_DATE`` so this suite's synthetic reflog timestamps
    (2026-06 onward) sit safely after the plausibility floor."""
    work = tmp_path / "work"
    _init_repo(work, branch=TRUNK_BRANCH)
    _commit(work, "a.txt", "a\n", "seed", when=_ROOT_COMMIT_DATE)
    return work


@pytest.fixture
def synced_repo(tmp_path: Path, bare_remote: Path) -> Path:
    work = tmp_path / "work"
    _init_repo(work, branch=TRUNK_BRANCH)
    _commit(work, "a.txt", "a\n", "seed", when=_ROOT_COMMIT_DATE)
    _git(work, "remote", "add", TRUNK_REMOTE, str(bare_remote))
    _git(work, "push", TRUNK_REMOTE, TRUNK_BRANCH)
    return work


def _write_synthetic_reflog(repo: Path, ref_relative: str, entries: list[tuple[str, str, int, str]]) -> None:
    """Write a raw reflog file at ``.git/logs/<ref_relative>`` from
    ``entries`` of ``(old_sha, new_sha, epoch, tz)`` -- full control over
    timestamps, since real ``git push`` reflog entries always use the
    system clock at call time (verified empirically: GIT_COMMITTER_DATE
    does not affect them), which real git operations cannot give a
    deterministic test."""
    common = Path(_git(repo, "rev-parse", "--git-common-dir").stdout.strip())
    if not common.is_absolute():
        common = repo / common
    log_path = common / "logs" / ref_relative
    log_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"{old} {new} Test User <test@example.com> {epoch} {tz}\tupdate by push" for old, new, epoch, tz in entries
    ]
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Unknown-marking: no anchor, no guess
# ---------------------------------------------------------------------------


def test_every_week_outside_an_anchor_date_reports_unknown(bare_repo: Path) -> None:
    rows = sprawl_history.build_weekly_series(bare_repo, since=NON_ANCHOR_SINCE, until=NON_ANCHOR_UNTIL)
    assert rows, "expected at least one week row"
    for row in rows:
        assert row["live_branch_local"] == "unknown"
        assert row["live_branch_local_provenance"] == "unknown"
        assert row["unpushed_estimate"] == "unknown"
        assert row["unpushed_provenance"] == "unknown"


def test_signal_counts_are_honest_zeros_not_unknown_when_no_events_exist(bare_repo: Path) -> None:
    """Unlike the live-branch/unpushed fields (which have no fallback and
    must say 'unknown'), the per-week signal counts (reflog first-seen,
    graveyard deaths, archive creations) are always derivable -- zero
    really means zero events, not 'nobody knows'."""
    rows = sprawl_history.build_weekly_series(bare_repo, since=NON_ANCHOR_SINCE, until=NON_ANCHOR_UNTIL)
    for row in rows:
        assert row["remote_branch_first_seen_count"] == 0
        assert row["graveyard_branch_deaths_recorded"] == 0
        assert row["graveyard_file_deaths_recorded"] == 0
        assert row["stash_original_created_count"] == 0
        assert row["worktree_archive_original_created_count"] == 0


def test_only_the_real_anchor_week_carries_a_known_live_branch_count(bare_repo: Path) -> None:
    """The hardcoded CITED_ANCHORS and the 'measured, this run' anchor both
    carry the real date 2026-08-27. A series that spans that date should
    show a known value in EXACTLY that one week; every other week in the
    same span stays unknown -- no interpolation leaks it sideways."""
    since = date(2026, 8, 1)
    until = date(2026, 9, 1)
    rows = sprawl_history.build_weekly_series(bare_repo, since=since, until=until)
    known_weeks = [r for r in rows if r["live_branch_local"] != "unknown"]
    assert len(known_weeks) == 1
    assert known_weeks[0]["live_branch_local_provenance"] == "measured"  # live_today applied last, wins the week
    other_weeks = [r for r in rows if r is not known_weeks[0]]
    assert all(r["live_branch_local"] == "unknown" for r in other_weeks)


# ---------------------------------------------------------------------------
# Graveyard-record ingestion
# ---------------------------------------------------------------------------


def _write_graveyard(repo: Path, records: list[dict]) -> None:
    path = repo / "docs" / "ops" / "graveyard.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "records": records}, indent=2), encoding="utf-8")


def test_a_missing_graveyard_reports_an_honest_zero_not_an_error(bare_repo: Path) -> None:
    summary = sprawl_history.graveyard_summary(bare_repo)
    assert summary["branch"]["total"] == 0
    assert summary["file"]["total"] == 0
    assert "honest zero" in summary["branch"]["note"]


def test_all_seeded_branch_records_are_flagged_as_a_recording_date_not_a_death_date(bare_repo: Path) -> None:
    _write_graveyard(
        bare_repo,
        [
            {
                "id": "x-1",
                "kind": "branch",
                "name": "foo",
                "dead_sha": "a" * 40,
                "deleted_on": "2026-08-25",
                "reason": "seeded: archived by custodian/salvage",
                "by": "graveyard-seed",
                "refs": None,
            },
            {
                "id": "x-2",
                "kind": "branch",
                "name": "bar",
                "dead_sha": "b" * 40,
                "deleted_on": "2026-08-25",
                "reason": "seeded: archived by custodian/salvage",
                "by": "graveyard-seed",
                "refs": None,
            },
        ],
    )
    summary = sprawl_history.graveyard_summary(bare_repo)
    assert summary["branch"]["total"] == 2
    assert summary["branch"]["by_deleted_on"] == {"2026-08-25": 2}
    assert summary["branch"]["all_records_seeded"] is True
    assert "RECORDING date" in summary["branch"]["note"]


def test_an_organic_death_record_is_not_misreported_as_seeded(bare_repo: Path) -> None:
    _write_graveyard(
        bare_repo,
        [
            {
                "id": "x-1",
                "kind": "branch",
                "name": "foo",
                "dead_sha": "a" * 40,
                "deleted_on": "2026-08-27",
                "reason": "swept: claim expired after 7-day grace",
                "by": "branch_sweep",
                "refs": None,
            }
        ],
    )
    summary = sprawl_history.graveyard_summary(bare_repo)
    assert summary["branch"]["all_records_seeded"] is False
    assert "mixed provenance" in summary["branch"]["note"]


def test_graveyard_deaths_are_bucketed_into_the_week_they_were_recorded(bare_repo: Path) -> None:
    _write_graveyard(
        bare_repo,
        [
            {
                "id": "x-1",
                "kind": "branch",
                "name": "foo",
                "dead_sha": "a" * 40,
                "deleted_on": "2020-01-08",
                "reason": "seeded: test fixture",
                "by": "graveyard-seed",
                "refs": None,
            }
        ],
    )
    rows = sprawl_history.build_weekly_series(bare_repo, since=NON_ANCHOR_SINCE, until=NON_ANCHOR_UNTIL)
    matching = [r for r in rows if r["week_start"] == "2020-01-08"]
    assert len(matching) == 1
    assert matching[0]["graveyard_branch_deaths_recorded"] == 1


# ---------------------------------------------------------------------------
# Reflog-horizon honesty
# ---------------------------------------------------------------------------


def test_remote_reflogs_are_honestly_unavailable_with_no_remote_configured(bare_repo: Path) -> None:
    result = sprawl_history.remote_branch_first_seen(bare_repo, remote=TRUNK_REMOTE)
    assert result["available"] is False
    assert result["reason"]
    assert result["branches"] == {}


def test_remote_reflogs_are_available_once_a_remote_has_pushed(synced_repo: Path) -> None:
    result = sprawl_history.remote_branch_first_seen(synced_repo, remote=TRUNK_REMOTE)
    assert result["available"] is True
    assert TRUNK_BRANCH in result["branches"]
    assert result["branches"][TRUNK_BRANCH]["first_seen"] is not None


def test_a_synthetic_reflog_is_parsed_into_the_correct_first_and_last_timestamps(bare_repo: Path) -> None:
    zero = "0" * 40
    sha_a, sha_b = "a" * 40, "b" * 40
    _write_synthetic_reflog(
        bare_repo,
        f"refs/remotes/{TRUNK_REMOTE}/some/nested/branch",
        [
            (zero, sha_a, 1780326000, "-0500"),  # 2026-06-01T10:00:00-05:00
            (sha_a, sha_b, 1782918000, "-0500"),  # 2026-07-01T10:00:00-05:00, later
        ],
    )
    result = sprawl_history.remote_branch_first_seen(bare_repo, remote=TRUNK_REMOTE)
    assert result["available"] is True
    entry = result["branches"]["some/nested/branch"]
    assert entry["first_seen"].startswith("2026-06-01T10:00:00")
    assert entry["last_seen"] > entry["first_seen"]


def test_an_implausible_reflog_entry_is_treated_as_unparseable_not_measured(bare_repo: Path) -> None:
    """MINOR-2 (adversarial review, fix round 1, 2026-08-27): a reviewer's
    fixture reflog with a first entry seven years before the repo's own
    root commit was previously passed through verbatim as measured
    'first_seen' data -- no plausibility check at all. This reproduces that
    shape directly: one entry ~7 years before the repo's own root commit
    (2019 vs the fixture's 2026-01-01 root), one entry ~2 years in the
    future, and a garbage middle line. Only the one plausible entry
    (2026-06-01) may set first_seen/last_seen; the implausible ones must be
    excluded exactly like a parse failure, not reported as data."""
    zero = "0" * 40
    sha_a, sha_b, sha_c = "a" * 40, "b" * 40, "c" * 40
    tz5 = timezone(timedelta(hours=-5))
    too_early_epoch = int(datetime(2019, 1, 1, tzinfo=tz5).timestamp())  # years before the 2026-01-01 root
    plausible_epoch = 1780326000  # 2026-06-01T10:00:00-05:00
    too_late_epoch = int(datetime(2029, 1, 1, tzinfo=tz5).timestamp())  # years in the future
    common = Path(_git(bare_repo, "rev-parse", "--git-common-dir").stdout.strip())
    if not common.is_absolute():
        common = bare_repo / common
    log_path = common / "logs" / "refs" / "remotes" / TRUNK_REMOTE / "liar"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"{zero} {sha_a} Test User <test@example.com> {too_early_epoch} -0500\tupdate by push",
        "this line is not a reflog entry at all -- corruption, not data",
        f"{sha_a} {sha_b} Test User <test@example.com> {plausible_epoch} -0500\tupdate by push",
        f"{sha_b} {sha_c} Test User <test@example.com> {too_late_epoch} -0500\tupdate by push",
    ]
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = sprawl_history.remote_branch_first_seen(bare_repo, remote=TRUNK_REMOTE)
    assert result["available"] is True
    entry = result["branches"]["liar"]
    # The garbage line and both implausible entries are excluded -- only the
    # one real, plausible entry survives, as both first_seen and last_seen.
    assert entry["first_seen"] == entry["last_seen"]
    assert entry["first_seen"].startswith("2026-06-01T10:00:00")


def test_head_reflog_span_is_available_for_a_real_checkout(bare_repo: Path) -> None:
    span = sprawl_history.head_reflog_span(bare_repo)
    assert span["available"] is True
    assert span["earliest"] is not None
    assert span["latest"] is not None
    assert span["earliest"] <= span["latest"]


def test_head_reflog_span_is_honestly_unavailable_when_the_log_is_missing(tmp_path: Path) -> None:
    not_a_repo = tmp_path / "not_a_repo"
    not_a_repo.mkdir()
    span = sprawl_history.head_reflog_span(not_a_repo)
    assert span["available"] is False
    assert span["earliest"] is None


# ---------------------------------------------------------------------------
# JSON schema stability
# ---------------------------------------------------------------------------

_EXPECTED_TOP_LEVEL_KEYS = {
    "version",
    "generated_at",
    "repo_root",
    "since",
    "until",
    "blind_spots",
    "reflog_horizons",
    "milestones",
    "graveyard_summary",
    "anchors",
    "weekly_series",
    "regenerate_command",
}

_EXPECTED_WEEK_ROW_KEYS = {
    "week_start",
    "week_end",
    "live_branch_local",
    "live_branch_local_provenance",
    "unpushed_estimate",
    "unpushed_provenance",
    "remote_branch_first_seen_count",
    "graveyard_branch_deaths_recorded",
    "graveyard_file_deaths_recorded",
    "stash_original_created_count",
    "worktree_archive_original_created_count",
    "milestones",
}


def test_the_top_level_json_shape_is_stable(bare_repo: Path) -> None:
    summary = sprawl_history.summarize(bare_repo, since=NON_ANCHOR_SINCE)
    assert set(summary.keys()) == _EXPECTED_TOP_LEVEL_KEYS


def test_every_week_row_has_the_same_keys(bare_repo: Path) -> None:
    summary = sprawl_history.summarize(bare_repo, since=NON_ANCHOR_SINCE)
    assert summary["weekly_series"], "expected at least one week row"
    for row in summary["weekly_series"]:
        assert set(row.keys()) == _EXPECTED_WEEK_ROW_KEYS


def test_the_output_is_json_serializable(bare_repo: Path) -> None:
    summary = sprawl_history.summarize(bare_repo, since=NON_ANCHOR_SINCE)
    # Round-trips without raising -- every value is a JSON-native type.
    json.loads(json.dumps(summary))


def test_two_runs_against_the_same_fixture_agree_on_everything_but_the_clock(bare_repo: Path) -> None:
    first = sprawl_history.summarize(bare_repo, since=NON_ANCHOR_SINCE)
    second = sprawl_history.summarize(bare_repo, since=NON_ANCHOR_SINCE)
    first.pop("generated_at")
    second.pop("generated_at")
    assert first == second


def test_render_table_never_raises_on_a_minimal_fixture(bare_repo: Path) -> None:
    summary = sprawl_history.summarize(bare_repo, since=NON_ANCHOR_SINCE)
    text = sprawl_history.render_table(summary)
    assert "SPRAWL HISTORY" in text
    assert "BLIND SPOTS" in text
