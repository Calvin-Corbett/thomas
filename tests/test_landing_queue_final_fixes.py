"""Final fixes (expbuild24): unproven means not landed, commas, one commit tool at a time, the briefing's words."""

from __future__ import annotations

import json
import sys
import time
from types import SimpleNamespace

import pytest
from scripts.crew.brief import land, land_commit, land_env, land_git, landing_briefing, scoped_commit_cli
from scripts.crew.brief.landing_queue import Config, Outcome
from scripts.crew.brief.landing_store import ENV_ROOT

from tests._landing_fakes import World
from tests.test_land_git import land as land_files
from tests.test_land_git import repo  # noqa: F401 - a fixture

ARGS = SimpleNamespace(agent="", include=[], allow_scope_fallback=False, fallback_reason="")
KEY = land_git.intent_key("agent-c", "wip", [])


def dry_tool(tmp_path, monkeypatch, row: dict) -> None:
    """A stand-in commit tool whose dry run prints ``row`` as its JSON verdict."""
    path = tmp_path / "dry_tool.py"
    path.write_text(f"import json\nprint(json.dumps({row!r}))\n")
    monkeypatch.setenv("THOMAS_LAND_COMMIT", str(path))


def lane_for(repo, tmp_path, monkeypatch, agent="agent-c", **extra):  # noqa: ANN001, ANN201
    monkeypatch.setenv(ENV_ROOT, str(tmp_path / "queue"))
    return land_env.make_lane(repo, agent, "", Config(), lambda text: None, staged_args=ARGS, **extra)


# ---- s5: a dry run refused before it chose any path prints selected_paths [] and that is NOT "nothing pending"
@pytest.mark.parametrize(
    ("row", "expected"),
    [
        ({"ok": False, "blocker_class": "session_identity", "selected_paths": []}, None),
        ({"ok": False, "blocker_class": "claim_scope_mismatch", "selected_paths": []}, None),
        ({"ok": False, "blocker_class": "coordination_p0", "selected_paths": []}, None),
        ({"ok": False, "blocker_class": "local_gate_failed", "selected_paths": ["b.txt"]}, None),
        ({"ok": False, "blocker_class": "no_claimed_changes", "selected_paths": []}, []),
        ({"ok": True, "selected_paths": ["b.txt"]}, ["b.txt"]),
    ],
)
def test_the_staged_set_is_known_only_for_a_dry_run_that_passed_or_found_nothing_to_stage(
    tmp_path, monkeypatch, row, expected
):
    dry_tool(tmp_path, monkeypatch, row)
    assert land_env.staged_paths(tmp_path, ARGS) == expected


def test_a_refused_dry_run_never_reads_as_nothing_pending(repo, tmp_path, monkeypatch):  # noqa: F811
    land_files(repo, {"a.txt": "a\n"}, "wip", KEY)
    (repo / "b.txt").write_text("b, a different change with the same words\n")  # untracked, same words
    dry_tool(tmp_path, monkeypatch, {"ok": False, "blocker_class": "session_identity", "selected_paths": []})
    lane = lane_for(repo, tmp_path, monkeypatch)
    assert lane.find_landed(KEY, [], True) is None  # was: the old sha, exit 0 "already landed", b.txt never landed
    dry_tool(tmp_path, monkeypatch, {"ok": False, "blocker_class": "no_claimed_changes", "selected_paths": []})
    (repo / "b.txt").unlink()
    assert lane.find_landed(KEY, [], True) is not None  # the commit tool itself says nothing is left to stage: landed


# ---- s22: a dry run that timed out says nothing
def test_a_timed_out_dry_run_reads_as_not_landed(repo, tmp_path, monkeypatch):  # noqa: F811
    land_files(repo, {"a.txt": "a\n"}, "wip", KEY)
    (repo / "b.txt").write_text("b, pending\n")
    timed_out = (Outcome(False, blocker="precheck_timeout"), ["a.txt"], True)
    monkeypatch.setattr(land_commit, "dry_run", lambda cmd, root, timeout: timed_out)
    assert land_env.staged_paths(repo, ARGS) is None
    assert lane_for(repo, tmp_path, monkeypatch).find_landed(KEY, [], True) is None


# ---- s4: a holder that died is recovered only with proof, never with an old commit that has the same words
def test_a_dead_holder_is_not_recovered_with_an_old_commit_that_has_the_same_words(repo, tmp_path, monkeypatch):  # noqa: F811
    land_files(repo, {"a.txt": "a\n"}, "wip", KEY)
    (repo / "b.txt").write_text("b, a different change, same words\n")
    holder = lane_for(repo, tmp_path, monkeypatch, "agent-c", pid=2_000_000_000)  # a process that no longer exists
    n = holder.enqueue(KEY, "wip")
    holder.store.append("granted", n, by="agent-c", now=time.time(), max_hold=900)
    lane_for(repo, tmp_path, monkeypatch, "agent-d").reap()
    state = holder.states()[n]
    assert state["state"] == "skipped" and "already landed" not in state["notice"]  # was: "recovered", the old sha


def test_a_dead_holder_with_an_include_and_proof_is_still_recovered(repo, tmp_path, monkeypatch):  # noqa: F811
    key = land_git.intent_key("agent-c", "wip", ["a.txt"])
    sha = land_files(repo, {"a.txt": "a\n"}, "wip", key)
    holder = lane_for(repo, tmp_path, monkeypatch, "agent-c", pid=2_000_000_000)
    n = holder.enqueue(key, "wip", includes=["a.txt"])
    holder.store.append("granted", n, by="agent-c", now=time.time(), max_hold=900)
    lane_for(repo, tmp_path, monkeypatch, "agent-d").reap()
    assert holder.states()[n]["state"] == "recovered" and holder.states()[n]["sha"] == sha


# ---- s3 / VERIFY (h): a comma is a separator, the way commit.py reads it
@pytest.mark.parametrize("raw", [["a.txt,b.txt"], ["a.txt", "b.txt"], [" a.txt , ,b.txt "], ["", "c"], ["a,,b", "c,d"]])
def test_include_splitting_is_exactly_what_the_commit_tool_does(raw):
    seen: dict = {}

    def fake_commit(**kw):  # noqa: ANN003, ANN202
        seen.update(kw)
        names = "ok blocker_class message agent branch claim_scopes selected_paths commit_sha dry_run gate_name"
        names += " gate_output scope_source next_step suggested_command"
        return SimpleNamespace(ok=True, **dict.fromkeys(names.split()[1:]))

    core = SimpleNamespace(commit_scoped_changes=fake_commit, _result_payload=lambda r: {})
    flags = [part for item in raw for part in ("--include", item)]
    assert scoped_commit_cli.run(["--message", "m", "--json", *flags], core=core) == 0
    assert land.split_includes(raw) == seen["include_paths"]


def test_a_comma_include_is_one_list_for_the_key_the_request_and_the_dirty_check(repo, tmp_path, monkeypatch):  # noqa: F811
    includes = land.split_includes(["a.txt,b.txt"])
    key = land_git.intent_key("agent-c", "wip", includes)
    assert key == land_git.intent_key("agent-c", "wip", land.split_includes(["a.txt", "b.txt"]))
    land_files(repo, {"a.txt": "a\n"}, "wip", key)
    (repo / "b.txt").write_text("b, a second change\n")
    assert (
        land_git.find_landed(repo, key, includes) is None
    )  # was: the old sha: "a.txt,b.txt" matched no path, b never looked at


def test_run_splits_commas_before_it_asks_or_queues(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(land_env, "resolve_identity", lambda agent, root: ("agent-c", ""))
    monkeypatch.setattr(land, "show_status", lambda args, lane, root: seen.update(include=args.include) or 0)
    monkeypatch.setenv(ENV_ROOT, str(tmp_path / "queue"))
    monkeypatch.setenv("THOMAS_LAND_ROOT", str(tmp_path))
    assert land.run(["--status", "--include", "a.txt,b.txt", "--include", "c.txt"]) == 0
    assert seen["include"] == ["a.txt", "b.txt", "c.txt"]


# ---- sim4: a ticket that was skipped while its holder checked never starts a commit tool
def slow_holder(tmp_path, seconds):
    w = World(tmp_path)
    h = w.lane("h", 100)
    n1 = h.enqueue("k1", "s")
    h.wait_turn(n1)
    x, y = w.lane("x", 101), w.lane("y", 102)
    n2, n3 = x.enqueue("k2", "s"), y.enqueue("k3", "s")  # y keeps beating: the queue is awake while h checks
    asked = []

    def slow_find(key, includes=(), own=False):  # noqa: ANN001, ANN202
        asked.append(own)
        w.life(seconds, x, (y, n3, "waiting"), (x, n2, "waiting"))
        return None

    h.find_landed = slow_find
    return w, h, x, n1, n2, asked


def test_the_commit_tool_never_starts_on_a_ticket_skipped_during_the_check(tmp_path):
    w, h, x, n1, n2, asked = slow_holder(tmp_path, 130)  # the reviewer's 130 s probe
    started = []
    verdict, out = h.hold(n1, lambda: started.append(1) or Outcome(True, sha="abc"))
    assert verdict == "lost" and out.blocker == "ticket_skipped"
    assert started == []  # was: skipped "heartbeat_stale" and its commit tool started anyway, beside the next holder
    assert x.states()[n1]["state"] == "skipped" and x.wait_turn(n2, max_wait=10) == "granted"


def test_hold_asks_without_a_dry_run_inside_the_slot_and_still_commits_when_it_is_open(tmp_path):
    w, h, x, n1, n2, asked = slow_holder(tmp_path, 10)
    verdict, out = h.hold(n1, lambda: Outcome(True, sha="abc"))
    assert asked == [False]  # `own` is not passed: no dry run inside the slot
    assert verdict == "landed" and out.sha == "abc"


# ---- the briefing's words
def test_the_briefing_says_what_land_py_takes_and_what_submit_does_and_does_not_teach_forging():
    text = landing_briefing.FIRST + " " + landing_briefing.SECOND
    for needed in (
        "--message, --agent, --include, --allow-scope-fallback and --fallback-reason",
        "it has no --dry-run",
        "returns once your ticket exists",
        "the path of a file with all of it",
        "hitting the attempt cap (exit 2) is not a reason to use commit.py either: fix the refusal, or ask",
    ):
        assert needed in text, needed
    assert "forging" not in text and " by`" not in text and "returns at once" not in text


def test_the_public_text_does_not_name_the_person():
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    for name in (
        "scripts/crew/brief/landing_spawn.py",
        "tests/test_landing_no_window.py",
        "scripts/crew/brief/land_env.py",
        "scripts/crew/brief/landing_liveness.py",
        "scripts/crew/brief/landing_proc.py",
        "scripts/crew/brief/landing_reaper.py",
        "scripts/crew/brief/landing_types.py",
    ):
        assert "the owner" not in (root / name).read_text(encoding="utf-8"), name
    assert sys.version_info >= (3, 12) and json.dumps({}) == "{}"
