"""A candidate stacked on another is proven as its own commit above the one that landed, never whole.

On 2026-09-24 seven salvage snapshots sat one commit above fcb5f06. The lower
commit's refs stay after it lands (the archive only copies them), so the census
still sees it; the ledger says it landed, so it is not proven again and the
snapshot above it is proven as its own commit on top of that landing.
"""

from __future__ import annotations

import asyncio
import getpass
import json
from pathlib import Path

import pytest

from tests.ratchet_support import (
    FakeCage,
    candidate,
    dev_moves,
    extra_candidate,
    git,
    make_repo,
    on_ref,
    promote,
    submissions,
    verdict,
)
from thomas.server.ratchet.attempt import Hooks
from thomas.server.ratchet.gitrepo import Repo
from thomas.server.ratchet.ledger import DECLINED, Ledger
from thomas.server.ratchet.service import ACCOUNT_ENV, RatchetService
from thomas.server.ratchet.stacking import onto_for

LOWER_FILES = ["tests/test_extra.py", "thomas/core/extra.py"]


@pytest.fixture(autouse=True)
def _here(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ACCOUNT_ENV, getpass.getuser())


def _hooks(cage: FakeCage | None = None, **overrides: object) -> Hooks:
    return Hooks(run_caged=cage or FakeCage(), runner_alive=lambda: True, dirty_wait_s=0.0, **overrides)


def _land_the_lower(tmp_path: Path) -> tuple[Path, str, Path]:
    """fix/extra goes through a whole run and lands by your card; its ref is copied to the archive and kept."""
    repo = make_repo(tmp_path)
    lower = extra_candidate(repo)
    dev_moves(repo)

    async def the_promoter(_seconds: float) -> None:
        [sub] = submissions()
        verdict(sub, "landed", commit=promote(repo, sub), files=LOWER_FILES)

    root = tmp_path / "ratchet"
    first = RatchetService(repo=repo, root=root, hooks=_hooks(sleep=the_promoter, poll_s=0.0))
    assert asyncio.run(first.run_once(limit=1))["proven"][0]["state"] == "landed"
    assert git(repo, "for-each-ref", "--format=%(refname)", "refs/archive/ratchet/heads/fix").splitlines() == [
        "refs/archive/ratchet/heads/fix/extra"
    ]
    assert git(repo, "rev-parse", "refs/heads/fix/extra") == lower  # copied, never deleted
    return repo, lower, root


def test_a_snapshot_waits_on_the_work_under_it_and_says_so(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    lower = extra_candidate(repo)
    snap = on_ref(repo, "refs/salvage/run/snap", lower, {"thomas/core/snap.py": "S = 1\n"}, "snapshot")
    dev = dev_moves(repo)
    book = Ledger(tmp_path / "ledger.jsonl")
    upper = candidate(snap, "refs/salvage/run/snap", stacked_on=lower)

    waiting = ("", "queued", f"it waits on {lower[:12]}, which it is stacked on (not proven yet)")
    assert onto_for(Repo(repo), book, upper, dev) == waiting
    book.record(sha=lower, refs=["refs/heads/fix/extra"], dev_sha=dev, state="reported", reason=f"{DECLINED}: no")
    onto, state, why = onto_for(Repo(repo), book, upper, dev)
    assert (onto, state) == ("", "reported") and why.startswith(f"it is stacked on {lower[:12]}, which will not land")


def test_a_snapshot_above_landed_work_brings_only_its_own_commit(tmp_path: Path) -> None:
    repo, lower, root = _land_the_lower(tmp_path)
    files = {".praxis-salvage-expected-files": "thomas/core/snap.py\n", "thomas/core/snap.py": "S = 1\n"}
    snap = on_ref(repo, "refs/salvage/run/snap", lower, files, "snapshot")
    second = RatchetService(repo=repo, root=root, hooks=_hooks(verdict_timeout_s=0.0))

    outcome = asyncio.run(second.run_once())

    assert outcome["proven"] == [{"ref": "refs/salvage/run/snap", "sha": snap, "state": "awaiting_card"}]
    [sub] = [s for s in submissions() if f"-{snap[:7]}-" in s.name]
    meta = json.loads((sub / "submission.json").read_text(encoding="utf-8"))
    assert meta["files"] == ["thomas/core/snap.py"]  # not the snapshot list, not the lower commit's files
    events = [e for e in Ledger(root / "ledger.jsonl").events() if e["candidate_sha"] == snap]
    assert events[0]["reason"] == f"proving it on dev, on top of {lower[:12]}"


def test_a_snapshot_two_commits_above_landed_work_is_reported_once_and_never_proven(tmp_path: Path) -> None:
    repo, lower, root = _land_the_lower(tmp_path)
    middle = on_ref(repo, "refs/heads/scratch-middle", lower, {"thomas/core/m.py": "M = 1\n"}, "middle")
    git(repo, "update-ref", "-d", "refs/heads/scratch-middle")
    high = on_ref(repo, "refs/salvage/run/high", middle, {"thomas/core/h.py": "H = 1\n"}, "high")
    cage = FakeCage()
    service = RatchetService(repo=repo, root=root, hooks=_hooks(cage))

    asyncio.run(service.run_once())
    asyncio.run(service.run_once())

    events = [e for e in Ledger(root / "ledger.jsonl").events() if e["candidate_sha"] == high]
    assert [e["state"] for e in events] == ["reported"]
    assert f"sits 2 commits above {lower[:12]}" in events[0]["reason"]
    assert cage.labels == []
