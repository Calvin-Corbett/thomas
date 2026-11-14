"""A candidate that needs a model is repaired by a Build team in its own green, then proven again by the ratchet.

No commit carries a Build or Thomas-project conversation id (measured 2026-09-24),
so there is no writing session to resume: a repair is a new Thomas project in the
candidate's green, with its settle held for the ratchet.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from tests.ratchet_support import FakeCage, candidate, dev_moves, git, make_repo, on_ref, submissions
from thomas.forge.anvil import forge_code_projects, forge_code_store
from thomas.server import green_checkout, green_handoff
from thomas.server.ratchet.attempt import Context, Hooks, prove_candidate
from thomas.server.ratchet.gitrepo import Repo
from thomas.server.ratchet.ledger import Ledger
from thomas.server.ratchet.repair import Repairer, RepairHooks, resumable
from thomas.server.thomas_project import ThomasProjectError


def _team_edits(work: Path) -> None:
    """What a team does in the green: resolves the conflict, and -- against its goal -- notes it on the board
    and in a task plan whose folder name has a space, which the promoter's header check refuses."""
    (work / "thomas" / "core" / "widget.py").write_text("VALUE = 34\n", encoding="utf-8")
    (work / "plans" / "thomas" / "WORKBOARD.md").write_text("the team claimed it\n", encoding="utf-8")
    spaced = work / "plans" / "thomas" / "tasks" / "branch dev" / "PLAN.md"
    spaced.parent.mkdir(parents=True, exist_ok=True)
    spaced.write_text("- a progress line\n", encoding="utf-8")


class Team:
    """Stands in for a Thomas project: records the start, resolves the conflict in the green, and ends."""

    def __init__(self, repo: Path, *, ok: bool = True, refuse: bool = False, dev_moves_meanwhile: bool = False) -> None:
        self.repo, self.ok, self.refuse, self.moves = repo, ok, refuse, dev_moves_meanwhile
        self.started: list[dict[str, Any]] = []
        self.retired: list[str] = []
        self.stopped: list[str] = []
        self.green: Any = None
        self.deletes = ""  # a path beyond the candidate's own change that the team removes
        self.adds = ""  # a path beyond the candidate's own change that the team writes

    async def start(self, app: Any, *, request: str, settings: dict, port: int, green: Any, meta: dict) -> dict:
        if self.refuse:
            raise ThomasProjectError("Build refused to start a Thomas project: status 409")
        self.started.append({"request": request, "port": port, "meta": meta, "green": green})
        self.green = green
        _team_edits(green.work)
        if self.deletes:
            (green.work / self.deletes).unlink()
        if self.adds:
            (green.work / self.adds).write_text("CARRIED = 1\n", encoding="utf-8")
        if self.moves:
            dev_moves(self.repo, "another agent landed something")
        return {"conversation_id": "conv-1", "execution_id": green.execution_id, "status": 200}

    def phase(self, root: Path, catalog: Path, cid: str) -> tuple[str, str]:
        return "ended", ""

    def outcome(self, root: Path, catalog: Path, cid: str) -> dict:
        return {"ok": self.ok, "reason": "1 file(s) changed" if self.ok else "the run crashed", "autonomy_level": 5}

    def settle_held(self, root: Path, catalog: Path, cid: str, *, summary: str) -> Path | None:
        return green_handoff.settle(self.green.execution_id, promote=True, summary=summary, chat="")

    def retire(self, root: Path, catalog: Path, cid: str) -> None:
        self.retired.append(cid)

    def stop(self, root: Path, cid: str) -> None:
        self.stopped.append(cid)

    def hooks(self, **overrides: float) -> RepairHooks:
        return RepairHooks(
            start=self.start,
            phase=self.phase,
            outcome=self.outcome,
            settle_held=self.settle_held,
            retire=self.retire,
            stop=self.stop,
            catalog_root=lambda: self.repo,
            settings=lambda: {"autonomy_level": 5},
            poll_s=0.0,
            **overrides,
        )


def _conflicting(tmp_path: Path) -> tuple[Path, str]:
    repo = make_repo(tmp_path)
    base = git(repo, "rev-parse", "dev")
    sha = on_ref(repo, "refs/heads/clash", base, {"thomas/core/widget.py": "VALUE = 3\n"}, "clash")
    dev_moves(repo, "dev changes it too", {"thomas/core/widget.py": "VALUE = 4\n"})
    return repo, sha


def _ctx(repo: Path, folder: Path, team: Team, **overrides: float) -> Context:
    hooks = Hooks(run_caged=FakeCage(), runner_alive=lambda: True, dirty_wait_s=0.0)
    ctx = Context(repo=Repo(repo), ledger=Ledger(folder / "ledger.jsonl"), hooks=hooks)
    ctx.repairs = Repairer({}, 8898, team.hooks(**overrides))
    return ctx


def test_a_conflict_is_repaired_in_its_green_then_proven_and_sent_to_your_card(tmp_path: Path) -> None:
    repo, sha = _conflicting(tmp_path)
    team = Team(repo)
    ctx = _ctx(repo, tmp_path / "ratchet", team)

    assert asyncio.run(prove_candidate(ctx, candidate(sha, "refs/heads/clash"))) == "awaiting_card"

    [start] = team.started
    assert start["meta"]["hold_settle"] is True and start["meta"]["ratchet"]["sha"] == sha
    assert "thomas/core/widget.py: both sides changed it" in start["request"]
    [sub] = submissions()
    patch = (sub / "change.patch").read_text(encoding="utf-8")
    assert "+VALUE = 34" in patch and "<<<<<<<" not in patch
    assert "WORKBOARD" not in patch and "branch dev" not in patch  # the team's board and plan edits stay out
    assert json.loads((sub / "submission.json").read_text(encoding="utf-8"))["files"] == ["thomas/core/widget.py"]
    states = [e["state"] for e in ctx.ledger.events() if e["candidate_sha"] == sha]
    assert states == ["proving", "repairing", "settling", "awaiting_card"]


def test_a_repair_that_could_not_start_or_did_not_finish_is_reported(tmp_path: Path) -> None:
    repo, sha = _conflicting(tmp_path)
    ctx = _ctx(repo, tmp_path / "first", Team(repo, refuse=True))
    assert asyncio.run(prove_candidate(ctx, candidate(sha))) == "reported"
    assert "could not start" in ctx.ledger.latest()[sha]["reason"]

    team = Team(repo, ok=False)
    ctx = _ctx(repo, tmp_path / "second", team)
    assert asyncio.run(prove_candidate(ctx, candidate(sha))) == "reported"
    assert ctx.ledger.latest()[sha]["reason"] == "the repair team did not finish: the run crashed"
    assert team.retired == ["conv-1"] and submissions() == []


def test_a_repair_that_runs_too_long_is_stopped(tmp_path: Path) -> None:
    repo, sha = _conflicting(tmp_path)
    team = Team(repo)
    ctx = _ctx(repo, tmp_path / "ratchet", team, timeout_s=0.0)

    assert asyncio.run(prove_candidate(ctx, candidate(sha))) == "reported"
    assert "did not end within" in ctx.ledger.latest()[sha]["reason"]
    assert team.stopped == ["conv-1"]


def test_a_repair_finished_on_an_old_dev_is_carried_to_the_new_one(tmp_path: Path) -> None:
    repo, sha = _conflicting(tmp_path)
    team = Team(repo, dev_moves_meanwhile=True)
    ctx = _ctx(repo, tmp_path / "ratchet", team)

    assert asyncio.run(prove_candidate(ctx, candidate(sha))) == "awaiting_card"
    event = ctx.ledger.latest()[sha]
    assert event["execution_id"].startswith("ratchet-fwd-")
    assert event["dev_sha"] == git(repo, "rev-parse", "dev")
    assert team.retired == ["conv-1"]
    assert event["files"] == ["thomas/core/widget.py"]  # the board edit was not carried either


def test_a_repair_that_deletes_a_file_the_candidate_keeps_is_not_handed_in(tmp_path: Path) -> None:
    repo, sha = _conflicting(tmp_path)
    team = Team(repo)
    team.deletes = "thomas/core/old.py"  # nothing the candidate changes, and nothing its goal asked for
    ctx = _ctx(repo, tmp_path / "ratchet", team)

    assert asyncio.run(prove_candidate(ctx, candidate(sha, "refs/heads/clash"))) == "reported"
    assert ctx.ledger.latest()[sha]["reason"] == (
        "what would be handed over is not the candidate's change: thomas/core/old.py is deleted, "
        "and the candidate does not delete it"
    )
    assert submissions() == []


def test_a_repairs_own_work_beyond_the_candidate_is_handed_over_and_named(tmp_path: Path) -> None:
    repo, sha = _conflicting(tmp_path)
    team = Team(repo)
    team.adds = "thomas/core/carried.py"  # a repair may need a file of dev's that the candidate never touched
    ctx = _ctx(repo, tmp_path / "ratchet", team)

    assert asyncio.run(prove_candidate(ctx, candidate(sha, "refs/heads/clash"))) == "awaiting_card"
    event = ctx.ledger.latest()[sha]
    assert event["beyond_the_candidate"] == ["thomas/core/carried.py"]
    assert event["files"] == ["thomas/core/carried.py", "thomas/core/widget.py"]
    [sub] = submissions()
    summary = json.loads((sub / "submission.json").read_text(encoding="utf-8"))["summary"]
    assert "Beyond the candidate's own files, its repair also changed: thomas/core/carried.py" in summary


def test_the_default_hooks_read_a_held_project_and_settle_it_with_the_ratchets_summary(tmp_path: Path) -> None:
    """Only the start is stood in for. The phase, the outcome, the held settle and the catalog copy are Task 8's
    own (thomas_project.project_phase and settle_if_finished, thomas_project_held.held_outcome), read from a real
    conversation."""
    repo, sha = _conflicting(tmp_path)
    catalog = tmp_path / "catalog"
    started: list[str] = []

    async def start(app: Any, *, request: str, settings: dict, port: int, green: Any, meta: dict) -> dict:
        conv = forge_code_store.new_conversation(
            green.work, title="repair", thomas_project={**meta, "execution_id": green.execution_id}
        )
        requested = {"requested": {"autonomy_level": 3}}  # below Autopilot, the level a run without your grant gets
        forge_code_projects.bind_conversation(
            catalog, conv["id"], green.work, settings=requested, allow_without_history=True
        )
        _team_edits(green.work)
        forge_code_store.append_agent_turn(
            green.work,
            conv["id"],
            model="claude-cli",
            transcript="resolved the conflict",
            changed_files=["thomas/core/widget.py"],
            returncode=0,
            ok=True,
            noop=False,
            reason="1 file(s) changed",
            outcome="completed",
        )
        started.append(str(conv["id"]))
        return {"conversation_id": conv["id"], "execution_id": green.execution_id, "status": 200}

    hooks = Hooks(run_caged=FakeCage(), runner_alive=lambda: True, dirty_wait_s=0.0)
    ctx = Context(repo=Repo(repo), ledger=Ledger(tmp_path / "ratchet" / "ledger.jsonl"), hooks=hooks)
    repair_hooks = RepairHooks(
        start=start, catalog_root=lambda: catalog, settings=lambda: {}, poll_s=0.0, timeout_s=30.0
    )
    ctx.repairs = Repairer({}, 8898, repair_hooks)

    assert asyncio.run(prove_candidate(ctx, candidate(sha, "refs/heads/clash"))) == "awaiting_card"
    [cid] = started
    kept = forge_code_store.load_conversation(catalog, cid)
    assert kept["thomas_project"]["settled_at"]
    assert kept["thomas_project"]["summary"].startswith("ratchet: land clash")
    assert ctx.ledger.latest()[sha]["autonomy"] == 3
    [sub] = submissions()
    assert json.loads((sub / "submission.json").read_text(encoding="utf-8"))["files"] == ["thomas/core/widget.py"]


def test_a_repair_a_restart_cut_short_is_taken_up_in_the_same_green(tmp_path: Path) -> None:
    """A restart leaves ``repairing`` in the ledger and the team's work in a kept green. Proving the candidate
    over instead would call fresh_green on that same execution id, which discards exactly that work."""
    repo, sha = _conflicting(tmp_path)
    team = Team(repo)
    ctx = _ctx(repo, tmp_path / "ratchet", team)
    dev_sha = git(repo, "rev-parse", "dev")
    execution = f"ratchet-cand-{sha[:7]}-{dev_sha[:7]}"
    green = green_checkout.create_green(repo, execution)
    green_checkout.apply_candidate(green, sha)
    _team_edits(green.work)  # what the team had already finished when the run ended
    team.green = green
    ctx.ledger.record(
        sha=sha,
        refs=["refs/heads/clash"],
        dev_sha=dev_sha,
        state="repairing",
        reason="a Build team is repairing it",
        conversation_id="conv-1",
        execution_id=execution,
    )

    [row] = ctx.ledger.repairing()
    found = resumable(ctx, row)
    assert found is not None
    att, cid = found
    assert (att.green.execution_id, cid, att.repaired) == (execution, "conv-1", True)
    assert asyncio.run(ctx.repairs.resume(ctx, att, cid)) == "awaiting_card"

    assert team.started == []  # no second team: the one that was running is taken up where it was
    [sub] = submissions()
    assert json.loads((sub / "submission.json").read_text(encoding="utf-8"))["files"] == ["thomas/core/widget.py"]
    assert [e["state"] for e in ctx.ledger.events()] == ["repairing", "repairing", "settling", "awaiting_card"]
    assert "taken up again" in ctx.ledger.events()[1]["reason"]


def test_a_candidate_being_repaired_is_never_proven_over(tmp_path: Path) -> None:
    repo, sha = _conflicting(tmp_path)
    ctx = _ctx(repo, tmp_path / "ratchet", Team(repo))
    dev_sha = git(repo, "rev-parse", "dev")
    ctx.ledger.record(sha=sha, refs=["refs/heads/clash"], dev_sha=dev_sha, state="repairing", execution_id="gone")

    prove, why = ctx.ledger.should_prove(sha, dev_sha)

    assert prove is False and "repairing it" in why
