"""A candidate the ratchet proves is read by a second model before your card, like every other hand-in.

The second look (``precard.review``) came in for Thomas's own projects, and a ratchet repair settles through the
same ``settle_if_finished``, so it had one. A candidate that needed no repair did not: once its proof passed it went
straight to the promoter, and so did a repair carried to a newer dev. Now each is read against what its own commits
say it is for. SAFE reaches your card and says so; NOT SAFE is reported and never reaches it; a reader that cannot run
(a usage limit, a sign-in gone) holds the candidate for the next run, and the run stops there rather than spend a
proof on each candidate after it. A held repair keeps its team's work in its green for the next run to take up.
"""

from __future__ import annotations

import asyncio
import getpass
import json
import time
from pathlib import Path
from typing import Any

import pytest

from tests.ratchet_support import FakeCage, candidate, dev_moves, extra_candidate, git, make_repo, on_ref, submissions
from tests.test_ratchet_repair import Team, _conflicting
from tests.test_ratchet_repair import _ctx as _repair_ctx
from thomas.server import capacity_ledger, green_checkout
from thomas.server.precard import review, review_dial
from thomas.server.ratchet.attempt import HELD, Context, Hooks, prove_candidate
from thomas.server.ratchet.gitrepo import Repo
from thomas.server.ratchet.ledger import Ledger
from thomas.server.ratchet.repair import resumable
from thomas.server.ratchet.service import ACCOUNT_ENV, RatchetService

FINDING = "thomas/core/extra.py:1 X is set but nothing reads it, so the change does nothing its commit says"
LIMIT = (1, "Claude AI usage limit reached|1790600000")
EXTRA = {
    "thomas/core/extra.py": "X = 1\n",
    "tests/test_extra.py": "from thomas.core import extra\n\n\ndef test_extra():\n    assert extra.X\n",
}


def _reply(verdict: str, findings: list[str]) -> tuple[int, str]:
    text = f"I read the change.\n{json.dumps({'verdict': verdict, 'findings': findings})}"
    return 0, json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": text})


class Reader:
    """Stands in for the Claude CLI: records each run and answers from a list."""

    def __init__(self, *answers: tuple[int, str]) -> None:
        self.answers = list(answers)
        self.calls: list[dict[str, Any]] = []

    def __call__(self, argv: list[str], cwd: str, prompt: str, timeout: float) -> tuple[int, str]:
        self.calls.append({"cwd": cwd, "prompt": prompt})
        return self.answers.pop(0)


@pytest.fixture(autouse=True)
def _own_turns_and_pause(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Second looks take turns, and pause, in this test's own ledger folder: never the real catalog's. A pause made
    here records no issue."""
    monkeypatch.setenv(capacity_ledger.ROOT_ENV, str(tmp_path / "ledger"))
    monkeypatch.setattr(capacity_ledger, "POLL_S", 0.02)
    monkeypatch.setattr(review_dial, "notice", lambda *_a: None)


def _reader(monkeypatch: pytest.MonkeyPatch, *answers: tuple[int, str]) -> Reader:
    reader = Reader(*answers)
    monkeypatch.delenv(review.REVIEW_ENV, raising=False)  # the suite turns it off; these tests are about it
    monkeypatch.setattr(review, "run_reviewer", reader)
    return reader


def _ctx(repo: Path, tmp_path: Path) -> Context:
    hooks = Hooks(run_caged=FakeCage(), runner_alive=lambda: True, dirty_wait_s=0.0)
    return Context(repo=Repo(repo), ledger=Ledger(tmp_path / "ratchet" / "ledger.jsonl"), hooks=hooks)


def _last(ctx: Context, sha: str) -> dict[str, Any]:
    return ctx.ledger.latest()[sha]


def _asked(reader: Reader, n: int = 0) -> str:
    """The part of the reader's prompt before the change itself: the request."""
    return reader.calls[n]["prompt"].split("The change:")[0]


def test_a_candidate_the_second_look_finds_safe_reaches_your_card_saying_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reader = _reader(monkeypatch, _reply("SAFE", []))
    repo = make_repo(tmp_path)
    base = git(repo, "rev-parse", "dev")
    sha = on_ref(repo, "refs/heads/fix/extra", base, EXTRA, "extra: X counts the widgets it was given")
    dev_moves(repo)
    ctx = _ctx(repo, tmp_path)

    state = asyncio.run(prove_candidate(ctx, candidate(sha, "refs/heads/fix/extra")))

    assert state == "awaiting_card"
    [call] = reader.calls
    assert Path(call["cwd"]).is_relative_to(green_checkout.green_root()), "it reads the candidate's own green"
    assert "refs/heads/fix/extra" in _asked(reader) and "+X = 1" in call["prompt"], "what it is, and the change"
    assert "- extra: X counts the widgets it was given" in _asked(reader), "what its commits say it is for"
    [submission] = submissions()
    summary = json.loads((submission / "submission.json").read_text(encoding="utf-8"))["summary"]
    assert review.SAFE_LINE in summary
    assert [e["state"] for e in ctx.ledger.events()] == ["proving", "settling", "awaiting_card"]


def test_a_candidate_the_second_look_finds_not_safe_is_reported_and_never_reaches_your_card(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _reader(monkeypatch, _reply("NOT_SAFE", [FINDING]))
    repo = make_repo(tmp_path)
    sha = extra_candidate(repo)
    dev_moves(repo)
    ctx = _ctx(repo, tmp_path)

    state = asyncio.run(prove_candidate(ctx, candidate(sha, "refs/heads/fix/extra")))

    assert state == "reported"
    assert submissions() == []
    assert FINDING in _last(ctx, sha)["reason"]
    assert "settling" not in [e["state"] for e in ctx.ledger.events()], "nothing was handed over"


def test_a_second_look_that_cannot_run_holds_the_candidate_for_the_next_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _reader(monkeypatch, LIMIT)
    repo = make_repo(tmp_path)
    sha = extra_candidate(repo)
    dev_moves(repo)
    ctx = _ctx(repo, tmp_path)

    state = asyncio.run(prove_candidate(ctx, candidate(sha, "refs/heads/fix/extra")))

    assert state == HELD
    assert submissions() == [], "never handed in unchecked"
    last = _last(ctx, sha)
    assert last["state"] == "queued", "queued is what the next run proves again"
    assert last["reason"].startswith("held") and "usage limit" in last["reason"]


def test_a_held_candidate_ends_the_run_before_the_next_one_is_proven(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(ACCOUNT_ENV, getpass.getuser())
    reader = _reader(monkeypatch, LIMIT, LIMIT)
    repo = make_repo(tmp_path)
    extra_candidate(repo)
    base = git(repo, "rev-parse", "dev")
    on_ref(repo, "refs/heads/fix/other", base, {"thomas/core/other.py": "Y = 2\n"}, "other")
    dev_moves(repo)
    hooks = Hooks(run_caged=FakeCage(), runner_alive=lambda: True, dirty_wait_s=0.0, verdict_timeout_s=0.0)
    service = RatchetService(repo=repo, root=tmp_path / "ratchet", hooks=hooks)

    outcome = asyncio.run(service.run_once(limit=3))

    assert [entry["state"] for entry in outcome["proven"]] == [HELD]
    assert len(reader.calls) == 1, "the reader is not asked again the same run"
    assert submissions() == []


def test_a_stacked_candidate_is_read_against_its_own_commit_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reader = _reader(monkeypatch, _reply("SAFE", []))
    repo = make_repo(tmp_path)
    base = git(repo, "rev-parse", "dev")
    lower = on_ref(repo, "refs/heads/lower", base, {"thomas/core/lower.py": "L = 1\n"}, "lower: the half that landed")
    upper = on_ref(repo, "refs/heads/upper", lower, EXTRA, "upper: the half still to land")
    dev_moves(repo, "the lower half landed", {"thomas/core/lower.py": "L = 1\n"})
    ctx = _ctx(repo, tmp_path)

    state = asyncio.run(prove_candidate(ctx, candidate(upper, "refs/heads/upper", stacked_on=lower), onto=lower))

    assert state == "awaiting_card"
    assert "upper: the half still to land" in _asked(reader)
    assert "lower: the half that landed" not in _asked(reader), "that commit is not in this change"


def test_a_repair_carried_to_a_newer_dev_gets_the_second_look_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reader = _reader(monkeypatch, _reply("NOT_SAFE", [FINDING]))
    repo, sha = _conflicting(tmp_path)
    ctx = _repair_ctx(repo, tmp_path / "ratchet", Team(repo, dev_moves_meanwhile=True))

    assert asyncio.run(prove_candidate(ctx, candidate(sha, "refs/heads/clash"))) == "reported"

    assert len(reader.calls) == 1 and "refs/heads/clash" in _asked(reader)
    assert "+VALUE = 34" in reader.calls[0]["prompt"], "the team's repair is what is read"
    assert submissions() == [] and FINDING in _last(ctx, sha)["reason"]


def test_a_repair_whose_second_look_cannot_run_keeps_its_work_for_the_next_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reader = _reader(monkeypatch, LIMIT, _reply("SAFE", []))
    repo, sha = _conflicting(tmp_path)
    team = Team(repo, dev_moves_meanwhile=True)
    ctx = _repair_ctx(repo, tmp_path / "ratchet", team)

    assert asyncio.run(prove_candidate(ctx, candidate(sha, "refs/heads/clash"))) == HELD

    last = _last(ctx, sha)
    assert last["state"] == "repairing" and last["reason"].startswith("held"), last
    assert team.retired == [] and submissions() == []
    [row] = ctx.ledger.repairing()
    found = resumable(ctx, row)
    assert found is not None, "the team's work is still in its green"
    att, cid = found

    monkeypatch.setattr(review_dial, "clock", lambda: time.time() + 3 * 86400)  # the plan's reset has passed
    assert asyncio.run(ctx.repairs.resume(ctx, att, cid)) == "awaiting_card"

    assert len(team.started) == 1, "no second team: the held work is taken up"
    assert len(reader.calls) == 2
    [submission] = submissions()
    assert "+VALUE = 34" in (submission / "change.patch").read_text(encoding="utf-8")


def test_a_ratchet_candidate_met_by_the_pause_is_held_without_asking_the_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from thomas.core.provider_limits import when_words

    reader = _reader(monkeypatch)
    reset = time.time() + 3600
    review_dial.pause(reset)
    repo = make_repo(tmp_path)
    sha = extra_candidate(repo)
    dev_moves(repo)
    ctx = _ctx(repo, tmp_path)

    assert asyncio.run(prove_candidate(ctx, candidate(sha, "refs/heads/fix/extra"))) == HELD

    assert reader.calls == [] and when_words(reset) in _last(ctx, sha)["reason"]
