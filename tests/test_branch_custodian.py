"""Tests for the branch custodian.

The custodian deletes branches, so the tests that matter most are the ones
proving it *refuses* to: unique work must survive both a dry run and a real
apply, and any git failure must degrade to "assume unique work" rather than
"assume safe to delete".
"""

from __future__ import annotations

import pytest

from thomas.forge.branch_custodian import (
    Action,
    BranchCustodianError,
    BranchStatus,
    consolidate,
    survey,
)

TRUNK = "dev"
TODAY = 20_000  # days since epoch, injected


class FakeGit:
    """A hermetic git. Branches are (sha, age_days, unique_commits, unique_files)."""

    def __init__(self, branches: dict[str, tuple[str, int, int, list[str]]], *, fail_on: str = "") -> None:
        self.branches = dict(branches)
        self.fail_on = fail_on
        self.calls: list[list[str]] = []

    def __call__(self, args):  # noqa: ANN001 - matches GitRunner
        args = list(args)
        self.calls.append(args)
        joined = " ".join(args)
        if self.fail_on and self.fail_on in joined:
            raise BranchCustodianError(f"simulated git failure on: {joined}")

        if args[0] == "for-each-ref":
            rows = []
            for name, (sha, age, _uc, _uf) in self.branches.items():
                ts = (TODAY - age) * 86400
                rows.append(f"{name}\t{sha}\t{ts}")
            return "\n".join(rows) + "\n"

        if args[0] == "rev-list":
            branch = args[-1].split("..")[-1]
            return f"{self.branches[branch][2]}\n"

        if args[0] == "diff":
            branch = args[-1].split("...")[-1]
            return "\n".join(self.branches[branch][3]) + "\n"

        if args[0] == "branch" and "-D" in args:
            self.branches.pop(args[-1], None)
            return ""

        if args[0] == "update-ref":
            return ""

        return ""


def _survey(fake: FakeGit, **kw):
    return survey(fake, trunk=TRUNK, active_days=3, ceiling=kw.pop("ceiling", 10), now_days=lambda: TODAY, **kw)


def _row(report, name):
    return next(b for b in report.branches if b.name == name)


def _fixture() -> FakeGit:
    return FakeGit(
        {
            TRUNK: ("aaa", 0, 0, []),
            "merged/feature": ("bbb", 30, 0, []),  # contained
            "stale/superseded": ("ccc", 40, 12, []),  # diverged, nothing unique
            "wip/real-work": ("ddd", 40, 5, ["thomas/x.py", "tests/test_x.py"]),  # unique
            "hot/today": ("eee", 1, 9, ["thomas/y.py"]),  # active
        }
    )


def test_classifies_each_branch_correctly() -> None:
    report = _survey(_fixture())
    assert _row(report, TRUNK).status is BranchStatus.TRUNK
    assert _row(report, "merged/feature").status is BranchStatus.CONTAINED
    assert _row(report, "stale/superseded").status is BranchStatus.SUPERSEDED
    assert _row(report, "wip/real-work").status is BranchStatus.UNIQUE_WORK
    assert _row(report, "hot/today").status is BranchStatus.ACTIVE


def test_actions_follow_status() -> None:
    report = _survey(_fixture())
    assert _row(report, TRUNK).action is Action.KEEP
    assert _row(report, "hot/today").action is Action.KEEP
    assert _row(report, "merged/feature").action is Action.DELETE
    assert _row(report, "stale/superseded").action is Action.ARCHIVE_AND_DELETE
    assert _row(report, "wip/real-work").action is Action.FLAG_FOR_CONSOLIDATION


def test_unique_work_is_never_deleted_even_on_apply() -> None:
    """The single most important guarantee."""
    fake = _fixture()
    report = _survey(fake)
    result = consolidate(fake, report, apply=True)

    assert "wip/real-work" not in result.deleted
    assert "wip/real-work" in result.flagged
    assert "wip/real-work" in fake.branches  # still exists in the repo
    assert result.ok


def test_active_branch_survives_even_with_unique_commits() -> None:
    fake = _fixture()
    result = consolidate(fake, _survey(fake), apply=True)
    assert "hot/today" not in result.deleted
    assert "hot/today" in fake.branches


def test_dry_run_touches_nothing() -> None:
    fake = _fixture()
    before = dict(fake.branches)
    result = consolidate(fake, _survey(fake), apply=False)

    assert fake.branches == before
    assert not any(a[0] == "branch" and "-D" in a for a in fake.calls)
    # ...but it still reports what it *would* do
    assert "merged/feature" in result.deleted
    assert "stale/superseded" in result.archived


def test_apply_deletes_reclaimable_and_archives_superseded_first() -> None:
    fake = _fixture()
    result = consolidate(fake, _survey(fake), apply=True)

    assert set(result.deleted) == {"merged/feature", "stale/superseded"}
    assert result.archived == ["stale/superseded"]
    assert "merged/feature" not in fake.branches
    assert "stale/superseded" not in fake.branches

    archived = [a for a in fake.calls if a[0] == "update-ref"]
    assert archived and archived[0][1] == "refs/archive/stale/superseded"
    assert archived[0][2] == "ccc"  # archived at its real sha


def test_git_diff_failure_is_treated_as_unique_work_not_as_safe() -> None:
    """Fail-safe: an unreadable branch must never be classified deletable."""
    fake = FakeGit({TRUNK: ("aaa", 0, 0, []), "risky": ("bbb", 40, 3, [])}, fail_on="diff")
    report = _survey(fake)
    row = _row(report, "risky")

    assert row.status is BranchStatus.UNIQUE_WORK
    assert row.action is Action.FLAG_FOR_CONSOLIDATION

    result = consolidate(fake, report, apply=True)
    assert "risky" not in result.deleted
    assert "risky" in fake.branches


def test_rev_list_failure_is_treated_as_unique_work() -> None:
    fake = FakeGit({TRUNK: ("aaa", 0, 0, []), "risky": ("bbb", 40, 3, [])}, fail_on="rev-list")
    row = _row(_survey(fake), "risky")
    assert row.status is BranchStatus.UNIQUE_WORK


def test_delete_failure_is_reported_not_swallowed() -> None:
    fake = FakeGit({TRUNK: ("aaa", 0, 0, []), "merged/x": ("bbb", 30, 0, [])}, fail_on="branch -D")
    result = consolidate(fake, _survey(fake), apply=True)

    assert not result.ok
    assert any("merged/x" in e for e in result.errors)
    assert "merged/x" not in result.deleted


def test_unreadable_head_date_makes_everything_active_so_nothing_is_touched() -> None:
    """If 'today' cannot be determined, every branch reads as ACTIVE.

    Ages become unknowable, so the custodian must not guess: treating all
    branches as recently-touched means nothing is proposed for deletion. Found
    while building the hold audit, where a fake git that did not answer
    `log -1 --format=%ct` silently produced an all-ACTIVE survey.
    """
    fake = FakeGit({TRUNK: ("aaa", 0, 0, []), "ancient": ("bbb", 900, 7, [])})
    # No now_days injected -> survey asks git for HEAD's timestamp, which this
    # fake does not implement.
    report = survey(fake, trunk=TRUNK, active_days=3, ceiling=10)

    assert _row(report, "ancient").status is BranchStatus.ACTIVE
    assert report.reclaimable == ()

    result = consolidate(fake, report, apply=True)
    assert result.deleted == []
    assert "ancient" in fake.branches


def test_circuit_breaker_trips_over_ceiling() -> None:
    fake = _fixture()
    assert _survey(fake, ceiling=99).over_ceiling is False
    assert _survey(fake, ceiling=2).over_ceiling is True


def test_summary_is_plain_language_for_a_non_engineer() -> None:
    summary = _survey(_fixture()).summary()
    assert "branches" in summary
    assert "need your call" in summary  # surfaces the human decision explicitly

    tidy = FakeGit({TRUNK: ("aaa", 0, 0, [])})
    assert "tidy" in _survey(tidy).summary()


def test_report_partitions_are_consistent() -> None:
    report = _survey(_fixture())
    assert {b.name for b in report.reclaimable} == {"merged/feature", "stale/superseded"}
    assert {b.name for b in report.needs_decision} == {"wip/real-work"}
    assert report.total == 5


def test_as_dict_is_json_shaped_for_the_ledger_and_ui() -> None:
    payload = _survey(_fixture()).as_dict()
    assert payload["trunk"] == TRUNK
    assert payload["total"] == 5
    assert payload["needs_decision"] == 1
    assert isinstance(payload["branches"], list)
    assert {"name", "status", "action", "unique_files"} <= set(payload["branches"][0])


def test_unique_files_are_surfaced_so_a_human_sees_what_is_at_stake() -> None:
    row = _row(_survey(_fixture()), "wip/real-work")
    assert row.has_unique_content
    assert "thomas/x.py" in row.unique_files


@pytest.mark.parametrize(
    "age,expected", [(0, BranchStatus.ACTIVE), (3, BranchStatus.ACTIVE), (4, BranchStatus.CONTAINED)]
)
def test_active_window_boundary(age: int, expected: BranchStatus) -> None:
    fake = FakeGit({TRUNK: ("aaa", 0, 0, []), "b": ("bbb", age, 0, [])})
    assert _row(_survey(fake), "b").status is expected
