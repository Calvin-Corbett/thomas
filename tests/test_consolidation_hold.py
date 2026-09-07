"""Tests for the consolidation circuit breaker.

Two properties matter most:

* while a hold is active, a new branch is genuinely refused -- otherwise the
  breaker is decoration;
* a hold can never wedge the repository -- trunk stays usable, and releasing is
  unconditional even from a corrupt state.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from thomas.forge.consolidation_hold import (
    HOLD_ENV,
    Hold,
    active_hold,
    audit,
    guard_new_branch,
    hold_path,
    place_hold,
    release_hold,
)

TRUNK = "dev"
TODAY = 20_000


class FakeGit:
    """Minimal git: N branches, all old, none carrying unique content."""

    def __init__(self, branch_names: list[str], *, unique: dict[str, list[str]] | None = None) -> None:
        self.names = branch_names
        self.unique = unique or {}

    def __call__(self, args):  # noqa: ANN001
        args = list(args)
        if args[0] == "log":
            # survey() derives "today" from HEAD so it needs no wall clock.
            return f"{TODAY * 86400}\n"
        if args[0] == "for-each-ref":
            ts = (TODAY - 40) * 86400
            return "\n".join(f"{n}\tsha-{n}\t{ts}" for n in self.names) + "\n"
        if args[0] == "rev-list":
            b = args[-1].split("..")[-1]
            return "0\n" if b == TRUNK else "5\n"
        if args[0] == "diff":
            b = args[-1].split("...")[-1]
            return "\n".join(self.unique.get(b, [])) + "\n"
        return ""


@pytest.fixture
def repo(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv(HOLD_ENV, str(tmp_path / "hold.json"))
    return tmp_path


def _many(n: int) -> FakeGit:
    return FakeGit([TRUNK] + [f"wip/b{i}" for i in range(n)])


def test_no_hold_by_default(repo: Path) -> None:
    assert active_hold(repo) is None
    assert guard_new_branch("feature/x", repo).allowed is True


def test_audit_places_a_hold_when_over_ceiling(repo: Path) -> None:
    result = audit(_many(20), repo, trunk=TRUNK, ceiling=5, now=lambda: "2026-07-22T00:00:00Z")

    assert result.hold_placed is True
    assert result.action == "placed"
    assert active_hold(repo) is not None
    assert "over a ceiling of 5" in result.hold.reason


def test_hold_actually_blocks_a_new_branch(repo: Path) -> None:
    """If this passes trivially, the breaker is decoration."""
    audit(_many(20), repo, trunk=TRUNK, ceiling=5)

    decision = guard_new_branch("feature/brand-new", repo, trunk=TRUNK)
    assert decision.allowed is False
    assert bool(decision) is False
    assert "under consolidation" in decision.reason
    assert "thomas consolidate" in decision.reason  # names the remedy


def test_trunk_is_never_blocked_so_a_hold_cannot_wedge_the_repo(repo: Path) -> None:
    audit(_many(20), repo, trunk=TRUNK, ceiling=5)
    assert guard_new_branch(TRUNK, repo, trunk=TRUNK).allowed is True


def test_allowlisted_branch_passes_the_hold(repo: Path) -> None:
    place_hold(repo, reason="manual", branch_count=99, ceiling=5, allow=("rescue/consolidation",))
    assert guard_new_branch("rescue/consolidation", repo).allowed is True
    assert guard_new_branch("something/else", repo).allowed is False


def test_audit_lifts_the_hold_once_sprawl_is_back_under_the_ceiling(repo: Path) -> None:
    audit(_many(20), repo, trunk=TRUNK, ceiling=5)
    assert active_hold(repo) is not None

    result = audit(_many(1), repo, trunk=TRUNK, ceiling=5)

    assert result.hold_released is True
    assert result.action == "released"
    assert active_hold(repo) is None
    assert guard_new_branch("feature/x", repo).allowed is True


def test_audit_is_idempotent_while_still_over_ceiling(repo: Path) -> None:
    a = audit(_many(20), repo, trunk=TRUNK, ceiling=5)
    b = audit(_many(20), repo, trunk=TRUNK, ceiling=5)
    assert a.hold_placed and b.hold_placed
    assert active_hold(repo) is not None


def test_audit_does_nothing_when_tidy(repo: Path) -> None:
    result = audit(_many(1), repo, trunk=TRUNK, ceiling=5)
    assert result.action == "none"
    assert result.hold_placed is False
    assert result.hold_released is False
    assert active_hold(repo) is None


def test_hold_round_trips_through_disk(repo: Path) -> None:
    place_hold(repo, reason="r", branch_count=42, ceiling=7, needs_decision=3, now="T", allow=("a",))
    loaded = active_hold(repo)
    assert loaded == Hold(reason="r", branch_count=42, ceiling=7, needs_decision=3, placed_at="T", allow=("a",))


def test_release_is_unconditional_and_safe_to_repeat(repo: Path) -> None:
    place_hold(repo, reason="r", branch_count=1, ceiling=0)
    assert release_hold(repo) is True
    assert release_hold(repo) is False  # already gone, still no error
    assert active_hold(repo) is None


def test_corrupt_hold_file_degrades_to_no_hold_rather_than_blocking_everything(repo: Path) -> None:
    hold_path(repo).parent.mkdir(parents=True, exist_ok=True)
    hold_path(repo).write_text("{not json", encoding="utf-8")

    assert active_hold(repo) is None
    assert guard_new_branch("feature/x", repo).allowed is True  # fails open, never wedges
    assert release_hold(repo) is True


def test_hold_records_how_many_need_a_human_decision(repo: Path) -> None:
    git = FakeGit([TRUNK, "a", "b", "c"], unique={"a": ["thomas/x.py"], "b": ["thomas/y.py"]})
    result = audit(git, repo, trunk=TRUNK, ceiling=1)
    assert result.hold.needs_decision == 2
    assert "2 need a decision" in result.hold.message()


def test_hold_message_states_the_truth_not_a_fabricated_block(repo: Path) -> None:
    """Fix round 1 (adversarial review IMP-2, 2026-08-27): ``message()``
    used to say "To proceed, run `thomas consolidate`..." -- worded as if a
    new branch push was genuinely blocked pending that remedy. It never was:
    ``guard_new_branch`` (the only function that reads this hold to refuse a
    branch) has zero callers anywhere in this codebase. The message must now
    say that plainly, and name the mechanism that actually enforces at push
    time (``branch_claim_gate.py``) instead of implying this hold does."""
    audit(_many(20), repo, trunk=TRUNK, ceiling=5)
    message = active_hold(repo).message()

    assert "nothing" in message and "consults it at branch creation" in message
    assert "branch_claim_gate" in message
    # The old, false claim must be gone -- a reader must not come away
    # believing a push was actually refused by this hold.
    assert "new branches are blocked" not in message
    assert "does not, by itself, block" in message
    # Final-review fix wave (2026-08-27, IMP-3): naming branch_claim_gate.py
    # as bare fact was itself an unqualified enforcement claim -- at HEAD the
    # gate has no local pre-push hook, only a CI job. The message must say so.
    assert "CI today" in message
    assert "local pre-push wiring rides the prepared tap" in message


def test_audit_payload_is_json_shaped_for_a_scheduler(repo: Path) -> None:
    payload = audit(_many(20), repo, trunk=TRUNK, ceiling=5).as_dict()
    assert payload["action"] == "placed"
    assert payload["over_ceiling"] is True
    assert isinstance(payload["notes"], list)
    json.dumps(payload)  # must be serialisable for a background job to log it


def test_cli_hold_placed_line_states_the_truth_not_a_fabricated_block(repo: Path, capsys) -> None:
    """Fix round 1 (adversarial review IMP-2, 2026-08-27): ``thomas
    consolidate --audit`` used to print "Consolidation hold PLACED --
    new branches are blocked until this clears." on every hold-placed run
    -- nothing was ever blocked, because guard_new_branch has zero
    callers. The CLI must now say what is true."""
    from thomas.cli.consolidate_cmd import _run_audit

    _run_audit(_many(20), repo=str(repo), trunk=TRUNK, ceiling=5, namespace="refs/heads", as_json=False)
    out = capsys.readouterr().out

    assert "Consolidation hold PLACED" in out
    assert "new branches are blocked" not in out
    assert "does not by itself block a new branch" in out
    assert "branch_claim_gate" in out
    # Final-review fix wave (2026-08-27, IMP-3): same qualifier as the
    # library message -- naming branch_claim_gate.py bare was itself an
    # unqualified enforcement claim.
    assert "CI today" in out
    assert "local pre-push wiring rides the prepared tap" in out
