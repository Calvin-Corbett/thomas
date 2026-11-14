"""Follow-ups 1 and 2: a refusal keeps its whole output and shows 2,000 characters; the pre-check runs in the waiting
process, near the head of the line, only in a free slot, and never before the ticket exists or in the way of a turn."""

from __future__ import annotations

import dataclasses
import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts.crew.brief import land, land_commit, land_precheck, land_worker
from scripts.crew.brief.landing_queue import Config, Lane, Outcome
from scripts.crew.brief.landing_store import FileTicketStore

from tests._landing_fakes import World

GATE = "".join(f"F{i:04d} a long ruff finding\n" for i in range(300))  # about 7,800 characters, like the review's s25
ARGS = SimpleNamespace(
    message="feat b",
    include=["b.txt"],
    no_detach=False,
    agent="",
    allow_scope_fallback=False,
    fallback_reason="",
    max_hold=900.0,
    wait_timeout=2700.0,
    no_precheck=False,
)


def refusing_tool(tmp_path: Path) -> list[str]:
    row = {"ok": False, "blocker_class": "local_gate_failed", "gate_name": "ruff", "message": "ruff failed"}
    path = tmp_path / "refuse.py"
    path.write_text(f"import json\nprint('warming up')\nprint(json.dumps({dict(row, gate_output=GATE)!r}))\n")
    return [sys.executable, str(path)]


# ---- 1. gate reasons
def test_the_agent_sees_2000_characters_of_a_refused_gate_and_a_file_has_all_of_it(tmp_path):
    lane = Lane(FileTicketStore(tmp_path / "queue"), agent="a", cfg=Config())
    num = lane.enqueue("key", "s")
    lane.wait_turn(num)
    tool = refusing_tool(tmp_path)
    verdict, out = lane.hold(num, lambda: land_commit.run_commit(tool, lane, num, Config(), "key", root=tmp_path))
    assert verdict == "refused" and out.output_file == str(tmp_path / "queue" / "output" / f"T{num:06d}-refused.txt")
    saved = Path(out.output_file).read_text(encoding="utf-8")
    assert "warming up" in saved and "F0299" in saved  # the whole output, not only the verdict line
    code, status, text, extra = land_worker.report(lane, num)
    assert code == 1 and status == "refused" and extra["output_file"] == out.output_file
    assert "F0070" in text and out.output_file in text  # was: 306 characters, cut mid-line, and no file


def test_a_verdict_keeps_2000_characters_of_the_gate_and_of_an_unparsed_answer():
    row = '{"ok": false, "gate_name": "ruff", "message": "m", "gate_output": "' + "x" * 5889 + '"}'
    assert land_commit.parse_outcome(1, row).message.count("x") >= 2000
    assert land_commit.parse_outcome(1, "y" * 5000).message.count("y") >= 2000


def test_a_refused_dry_run_keeps_its_whole_output_through_save(tmp_path):
    kept = tmp_path / "kept.txt"

    def save(text: str) -> str:
        kept.write_text(text, encoding="utf-8")
        return str(kept)

    out, _paths, stopped = land_commit.dry_run(refusing_tool(tmp_path), tmp_path, 60.0, save=save)
    assert not out.ok and not stopped and out.output_file == str(kept) and "F0299" in kept.read_text(encoding="utf-8")


# ---- 2. the pre-check, in the waiting process
def waiting_world(tmp_path: Path, behind: int):  # noqa: ANN201
    """A holder in the slot and ``behind`` tickets after it."""
    w = World(tmp_path)
    h = w.lane("h", 100)
    h.wait_turn(h.enqueue("kh", "s"))
    lanes = [w.lane(f"a{i}", 101 + i) for i in range(behind)]
    return w, lanes, [lane.enqueue(f"k{i}", "s") for i, lane in enumerate(lanes)]


def fake_dry(monkeypatch, outcome: Outcome, calls: list) -> None:  # noqa: ANN001
    def dry_run(cmd, root, timeout, tick=None, save=None):  # noqa: ANN001, ANN202
        calls.append(cmd)
        if tick is not None:
            tick(5.0)
        out = outcome
        if not out.ok and save is not None and out.blocker != "precheck_timeout":
            out = dataclasses.replace(out, output_file=save("the whole output\n" + out.message))
        return out, None, out.blocker == "precheck_timeout"

    monkeypatch.setattr(land_commit, "dry_run", dry_run)


def test_taking_a_ticket_runs_no_dry_run_even_with_others_queued(tmp_path, monkeypatch):
    w, lanes, nums = waiting_world(tmp_path, 1)
    monkeypatch.setattr(land_commit, "dry_run", lambda *a, **k: pytest.fail("a dry run before the ticket exists"))
    num, code, text, _ = land.start_ticket(ARGS, w.lane("b", 300), "kb")
    assert (code, text) == (0, "queued") and w.store.tickets()[num]["request"]["precheck"] is True


def test_the_precheck_runs_only_with_at_most_two_ahead_and_only_once(tmp_path, monkeypatch):
    calls: list = []
    fake_dry(monkeypatch, Outcome(True), calls)
    w, lanes, nums = waiting_world(tmp_path, 3)
    far = land_precheck.Precheck(lanes[2], nums[2], ["dry-far"], tmp_path, pause=0)
    far(nums[2], 3)
    assert calls == [] and not far.done  # three ahead: no dry run yet, and it will try again later
    near = land_precheck.Precheck(lanes[1], nums[1], ["dry-near"], tmp_path, pause=0)
    near(nums[1], 2)
    near(nums[1], 2)
    assert calls == [["dry-near"]]


def test_with_no_free_slot_there_is_no_dry_run_and_a_later_poll_tries_again(tmp_path, monkeypatch):
    calls: list = []
    fake_dry(monkeypatch, Outcome(True), calls)
    w, lanes, nums = waiting_world(tmp_path, 1)
    folder = w.store.root / "prechecks"
    folder.mkdir(parents=True, exist_ok=True)
    for i in range(land_precheck.MAX_PRECHECKS):
        (folder / f"S{i}.lock").write_text("")
    check = land_precheck.Precheck(lanes[0], nums[0], ["dry"], tmp_path, pause=0)
    check(nums[0], 1)
    assert calls == [] and not check.done  # was: it waited up to 120 s, then ran anyway beside the holder
    (folder / "S1.lock").unlink()
    check(nums[0], 1)
    assert calls == [["dry"]] and not (folder / "S1.lock").exists()  # ran in the free slot and gave it back


def test_a_precheck_refusal_finishes_the_ticket_before_the_slot_and_never_counts_toward_a_cap(tmp_path, monkeypatch):
    long = "gate x failed: " + "y" * 3000
    fake_dry(monkeypatch, Outcome(False, blocker="local_gate_failed", message=long, gate="x"), [])
    w, lanes, nums = waiting_world(tmp_path, 1)
    lane, num = lanes[0], nums[0]
    lane.on_wait = land_precheck.Precheck(lane, num, ["dry"], tmp_path, pause=0)
    assert lane.wait_turn(num) == "lost"
    s = lane.states()[num]
    assert s["state"] == "refused" and "granted" not in [e["kind"] for e in s["events"]]
    assert lane.recent_ends(w.clock()) == ([], [])  # it never used the slot
    code, status, text, extra = land_worker.report(lane, num)
    assert code == 1 and extra["stage"] == "precheck" and "before your turn, no slot used" in text
    assert text.count("y") >= 2000 and Path(extra["output_file"]).read_text().startswith("the whole output")


@pytest.mark.parametrize(
    "out",
    [
        Outcome(False, blocker="branch_race", message="moved"),
        Outcome(False, blocker="local_gate_failed", gate="workboard_changed_files", message="moved"),
        Outcome(False, blocker="precheck_timeout", message="slow"),
    ],
)
def test_a_race_class_refusal_or_a_timeout_is_advisory_and_the_ticket_stays(tmp_path, monkeypatch, out):
    calls: list = []
    fake_dry(monkeypatch, out, calls)
    w, lanes, nums = waiting_world(tmp_path, 1)
    land_precheck.Precheck(lanes[0], nums[0], ["dry"], tmp_path, pause=0)(nums[0], 1)
    assert lanes[0].states()[nums[0]]["state"] == "waiting"
    assert any("queueing anyway" in line for line in w.said)
    assert len(calls) == (1 if out.blocker == "precheck_timeout" else 2)  # a race-class refusal is retried once


def test_no_detach_answers_a_precheck_refusal_with_its_stage_blocker_and_output_file(tmp_path, monkeypatch, capsys):
    fake_dry(monkeypatch, Outcome(False, blocker="local_gate_failed", message="gate x failed", gate="x"), [])
    w, lanes, nums = waiting_world(tmp_path, 1)
    w.alive.add(os.getppid())  # the caller of this in-process wait is alive
    args = SimpleNamespace(**vars(ARGS), json=True)
    assert land.land_in_process(args, lanes[0], tmp_path, nums[0], Config(), "k0") == 1
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["stage"] == "precheck" and out["blocker_class"] == "local_gate_failed"  # was: only the ticket number
    assert Path(out["output_file"]).is_file()


def test_an_error_inside_the_precheck_is_advisory_and_never_costs_the_ticket(tmp_path, monkeypatch):
    def broken(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(land_commit, "dry_run", broken)
    w, lanes, nums = waiting_world(tmp_path, 1)
    land_precheck.Precheck(lanes[0], nums[0], ["dry"], tmp_path, pause=0)(nums[0], 1)  # was: raised, the worker died
    assert lanes[0].states()[nums[0]]["state"] == "waiting"
    assert any("pre-check could not run" in line for line in w.said)
    assert not list((w.store.root / "prechecks").glob("S*.lock"))  # the slot is given back


def test_a_dry_run_keeps_the_ticket_beating(tmp_path, monkeypatch):
    fake_dry(monkeypatch, Outcome(True), [])
    w, lanes, nums = waiting_world(tmp_path, 1)
    w.clock.advance(80.0)  # close to the 90 s a silent waiter is allowed
    land_precheck.Precheck(lanes[0], nums[0], ["dry"], tmp_path, pause=0)(nums[0], 1)
    assert w.store.beats([nums[0]])[nums[0]]["t"] == w.clock()


def test_a_dry_run_is_stopped_when_the_turn_comes_so_it_never_delays_the_turn(tmp_path):
    lane = Lane(FileTicketStore(tmp_path / "queue"), agent="a", cfg=Config(precheck_timeout=60.0))
    num = lane.enqueue("key", "s")  # nobody ahead: the turn has come
    slow = tmp_path / "slow.py"
    slow.write_text("import time\ntime.sleep(60)\n")
    t0 = time.monotonic()
    out = land_precheck.Precheck(lane, num, [sys.executable, str(slow)], tmp_path).run()
    assert out.blocker == "precheck_stopped" and time.monotonic() - t0 < 20  # was: the whole dry run, past the grace


def test_alone_there_is_no_precheck_at_all_even_while_a_git_lock_holds_the_turn_back(tmp_path):
    w = World(tmp_path)
    w.locks = ([], [".git/index.lock"])  # git is running: the head waits a few polls before it may take the slot
    a = w.lane("a", 100)
    seen: list[int] = []
    a.on_wait = lambda num, ahead: seen.append(ahead)
    assert a.wait_turn(a.enqueue("ka", "s")) == "granted" and seen == []  # one agent alone pays one gate ladder
