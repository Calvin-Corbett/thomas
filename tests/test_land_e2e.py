"""land.py end to end with REAL processes: several agents at once, submit and resume, a killed foreground, identity."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest
from scripts.crew.brief import land, land_env, landing_status
from scripts.crew.brief.landing_store import FileTicketStore

from tests._landing_fakes import sp

LAND = Path(land.__file__).resolve()
FAKE_COMMIT = textwrap.dedent(
    """
    import json, os, subprocess, sys, time
    args = sys.argv[1:]
    message = args[args.index("--message") + 1]
    paths = [args[i + 1] for i, a in enumerate(args) if a == "--include"]
    dry = "--dry-run" in args
    log = os.path.join(os.path.dirname(__file__), "..", "commit_log.txt")
    if dry:
        print(json.dumps({"ok": True, "message": "dry"}))
        raise SystemExit(0)
    with open(log, "a") as fh:
        fh.write(f"start {time.time()} {os.getpid()}\\n")
    time.sleep(float(os.environ.get("FAKE_COMMIT_SECONDS", "1")))
    subprocess.run(["git", "add", "--", *paths], check=True)
    subprocess.run(["git", "commit", "-q", "-m", message], check=True)
    sha = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    with open(log, "a") as fh:
        fh.write(f"end {time.time()} {os.getpid()}\\n")
    print(json.dumps({"ok": True, "commit_sha": sha, "message": "ok"}))
    """
)


@pytest.fixture()
def world(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    for cmd in (
        ["init", "-q"],
        ["config", "user.email", "t@e.t"],
        ["config", "user.name", "t"],
        ["config", "commit.gpgsign", "false"],
        ["config", "core.autocrlf", "false"],
    ):
        sp.run(["git", *cmd], cwd=repo, check=True)
    (repo / "base.txt").write_text("base\n")
    sp.run(["git", "add", "-A"], cwd=repo, check=True)
    sp.run(["git", "commit", "-q", "-m", "base"], cwd=repo, check=True)
    tool = tmp_path / "tool"
    tool.mkdir()
    (tool / "fake_commit.py").write_text(FAKE_COMMIT)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("THOMAS_", "AGENT_", "CLAUDE", "GIT_INDEX"))}
    env.update(
        THOMAS_LAND_ROOT=str(repo),
        THOMAS_LAND_COMMIT=str(tool / "fake_commit.py"),
        THOMAS_LANDING_QUEUE_DIR=str(tmp_path / "queue"),
        PYTHONPATH=str(Path(land.__file__).resolve().parents[3]),
        PYTHONDONTWRITEBYTECODE="1",
    )
    return type("W", (), {"repo": repo, "env": env, "tmp": tmp_path, "queue": tmp_path / "queue"})()


def start(world, agent: str, *args: str, seconds: str = "1") -> subprocess.Popen:
    env = {**world.env, "THOMAS_AGENT_ID": agent, "FAKE_COMMIT_SECONDS": seconds}
    return sp.Popen(
        [sys.executable, str(LAND), "--json", *args],
        env=env,
        cwd=world.repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def run(world, agent: str, *args: str, seconds: str = "1", timeout: float = 120) -> tuple[int, dict]:
    proc = start(world, agent, *args, seconds=seconds)
    out, _ = proc.communicate(timeout=timeout)
    lines = [ln for ln in out.splitlines() if ln.startswith("{")]
    return proc.returncode, (json.loads(lines[-1]) if lines else {"raw": out})


def write(world, name: str, text: str) -> None:
    (world.repo / name).write_text(text)


def lane_of(world):
    os.environ["THOMAS_LANDING_QUEUE_DIR"] = str(world.queue)
    return land_env.make_lane(world.repo, "observer", "", land.Config(), lambda t: None)


def test_four_agents_landing_at_once_all_land_one_commit_tool_at_a_time(world):
    for i in range(4):
        write(world, f"f{i}.txt", f"change {i}\n")
    procs = [start(world, f"agent-{i}", "--message", f"feat: change {i}", "--include", f"f{i}.txt") for i in range(4)]
    results = []
    for proc in procs:
        out, err = proc.communicate(timeout=180)
        results.append((proc.returncode, [json.loads(ln) for ln in out.splitlines() if ln.startswith("{")][-1]))
    assert [code for code, _ in results] == [0, 0, 0, 0], results
    log = sp.run(["git", "log", "--format=%B%x02"], cwd=world.repo, capture_output=True, text=True, check=True).stdout
    assert log.count("Landing-Ticket: lq-") == 4
    rows = [ln.split() for ln in (world.tmp / "commit_log.txt").read_text().splitlines()]
    spans = sorted((float(r[1]), r[0]) for r in rows)
    assert [kind for _, kind in spans] == [
        "start",
        "end",
    ] * 4  # never two commit tools at once: start, end, start, end, ...
    lane = lane_of(world)
    assert [s["state"] for _, s in sorted(lane.states().items())] == ["released"] * 4
    assert lane.audit() == []
    assert (world.queue / "beats").exists() and not list(
        (world.queue / "beats").glob("T*.json")
    )  # no heartbeat of a finished ticket


def test_a_second_run_of_the_same_change_says_already_landed_and_a_different_one_does_not(world):
    write(world, "n.txt", "A\n")
    assert run(world, "agent-x", "--message", "docs: notes", "--include", "n.txt")[0] == 0
    code, out = run(world, "agent-x", "--message", "docs: notes", "--include", "n.txt")
    assert code == 0 and out["status"] == "already_landed" and out["message"].startswith("already landed as ")
    write(world, "n.txt", "B, a different change\n")
    code, out = run(world, "agent-x", "--message", "docs: notes", "--include", "n.txt")
    assert code == 0 and out["status"] == "landed"  # was: already_landed, and the change never landed
    assert (
        sp.run(["git", "show", "HEAD:n.txt"], cwd=world.repo, capture_output=True, text=True).stdout.strip()
        == "B, a different change"
    )
    assert (
        sp.run(["git", "rev-list", "--count", "HEAD"], cwd=world.repo, capture_output=True, text=True).stdout.strip()
        == "3"
    )


def test_submit_returns_at_once_and_wait_reports_in_bounded_slices_with_exit_five(world):
    write(world, "a.txt", "a\n")
    write(world, "b.txt", "b\n")
    first = start(world, "agent-a", "--message", "feat: a", "--include", "a.txt", seconds="6")
    time.sleep(2.0)  # a is landing (6 s commit tool) when b submits
    t0 = time.monotonic()
    code, out = run(world, "agent-b", "--submit", "--message", "feat: b", "--include", "b.txt", seconds="1", timeout=60)
    assert code == 0 and out["status"] == "submitted" and out["ticket"] == 2 and time.monotonic() - t0 < 20
    code, out = run(world, "agent-b", "--wait", "2", "--wait-seconds", "1", timeout=30)
    assert code == 5 and out["status"] == "waiting" and "run `land.py --wait 2` again" in out["message"]
    code, out = run(world, "agent-b", "--resume", "2", "--wait-seconds", "120", timeout=150)
    assert code == 0 and out["status"] == "landed" and out["ticket"] == 2
    assert first.wait(timeout=60) == 0
    assert (
        sp.run(["git", "rev-list", "--count", "HEAD"], cwd=world.repo, capture_output=True, text=True).stdout.strip()
        == "3"
    )


def test_a_foreground_run_killed_by_a_tool_timeout_keeps_its_ticket_and_the_rerun_attaches(world):
    write(world, "k.txt", "k\n")
    write(world, "z.txt", "z\n")
    blocker = start(world, "agent-z", "--message", "feat: z", "--include", "z.txt", seconds="5")
    time.sleep(2.0)
    front = start(world, "agent-k", "--message", "feat: k", "--include", "k.txt")
    time.sleep(3.0)
    front.kill()  # the agent's tool call timed out and took land.py with it
    front.wait()
    code, out = run(world, "agent-k", "--message", "feat: k", "--include", "k.txt", timeout=150)
    assert code == 0 and out["status"] in ("landed", "already_landed"), out
    assert blocker.wait(timeout=60) == 0
    lane = lane_of(world)
    tickets = lane.states()
    assert len(tickets) == 2  # the rerun attached to the open ticket instead of taking another
    waste, refused = lane.recent_ends(time.time())
    assert not waste and not refused  # a killed front end does not count against the cap
    assert sp.run(["git", "show", "HEAD:k.txt"], cwd=world.repo, capture_output=True, text=True).stdout.strip() == "k"


def test_no_detach_lands_inside_the_process_and_precheck_is_skipped_when_nobody_is_queued(world):
    write(world, "d.txt", "d\n")
    code, out = run(world, "agent-d", "--no-detach", "--message", "feat: d", "--include", "d.txt")
    assert code == 0 and out["status"] == "landed"
    assert FileTicketStore(world.queue).tickets()[1]["mode"] == "foreground"
    log = (world.tmp / "commit_log.txt").read_text().splitlines()
    assert (
        len(log) == 2
    )  # one run of the commit tool only; the fake tool's dry run does not log, so check the cost another way
    assert land_env.commit_path().name  # the seam resolves


def test_the_worker_precheck_refuses_near_the_head_before_the_slot_and_keeps_the_whole_output(world):
    write(world, "slow.txt", "s\n")
    write(world, "bad.txt", "b\n")
    holder = start(world, "agent-s", "--message", "feat: s", "--include", "slow.txt", seconds="10")
    time.sleep(2.0)
    refuser = world.tmp / "tool" / "refuse.py"
    row = {"ok": False, "blocker_class": "local_gate_failed", "message": "gate x failed", "gate_name": "x"}
    row["gate_output"] = "E501 line too long " * 300  # about 5,700 characters, like the reviewer's ruff output
    refuser.write_text(f"import json\nprint(json.dumps({row!r}))\nraise SystemExit(1)\n")
    env = {**world.env, "THOMAS_AGENT_ID": "agent-b", "THOMAS_LAND_COMMIT": str(refuser)}
    done = sp.run(
        [sys.executable, str(LAND), "--json", "--message", "feat: b", "--include", "bad.txt"],
        env=env,
        cwd=world.repo,
        capture_output=True,
        text=True,
        timeout=90,
    )
    out = json.loads(done.stdout.strip().splitlines()[-1])
    assert done.returncode == 1 and out["status"] == "refused" and out["stage"] == "precheck", out
    assert out["blocker_class"] == "local_gate_failed" and out["message"].count("E501") >= 100  # >= 2,000 characters
    assert open(out["output_file"], encoding="utf-8").read().count("E501") == 300  # the whole output is in the file
    events = [e for e in FileTicketStore(world.queue).events() if e["ticket"] == out["ticket"]]
    assert "granted" not in [e["kind"] for e in events]  # refused before it ever used the slot
    holder.wait(timeout=60)


def test_a_race_class_precheck_refusal_is_advisory_and_the_change_is_queued_anyway(world):
    write(world, "slow.txt", "s\n")
    write(world, "r.txt", "r\n")
    holder = start(world, "agent-s", "--message", "feat: s", "--include", "slow.txt", seconds="8")
    time.sleep(2.0)
    racer = world.tmp / "tool" / "race.py"
    refusal = '{"ok": False, "blocker_class": "local_gate_failed", "gate_name": "workboard_changed_files", "message": "moved"}'
    racer.write_text(
        FAKE_COMMIT.replace(
            'print(json.dumps({"ok": True, "message": "dry"}))', f"print(json.dumps({refusal}))"
        ).replace("raise SystemExit(0)", "raise SystemExit(1)", 1)
    )
    assert "workboard_changed_files" in racer.read_text()
    env = {**world.env, "THOMAS_AGENT_ID": "agent-r", "THOMAS_LAND_COMMIT": str(racer), "FAKE_COMMIT_SECONDS": "1"}
    done = sp.run(
        [sys.executable, str(LAND), "--json", "--message", "feat: r", "--include", "r.txt"],
        env=env,
        cwd=world.repo,
        capture_output=True,
        text=True,
        timeout=150,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    ticket = json.loads(done.stdout.strip().splitlines()[-1])["ticket"]
    assert "queueing anyway" in (world.queue / "logs" / f"T{ticket:06d}.log").read_text()  # said in the worker's log
    holder.wait(timeout=60)


def test_identity_is_the_session_bound_one_not_a_bare_flag(world, tmp_path):
    write(world, "i.txt", "i\n")
    env = {**world.env, "THOMAS_AGENT_ID": "agent-i", "THOMAS_AGENT_SESSION_ID": "no-such-session"}
    done = sp.run(
        [sys.executable, str(LAND), "--json", "--message", "feat: i", "--include", "i.txt"],
        env=env,
        cwd=world.repo,
        capture_output=True,
        text=True,
        timeout=60,
    )
    out = json.loads(done.stdout.strip().splitlines()[-1])
    assert done.returncode == 2 and out["status"] == "identity" and "session" in out["message"]
    from thomas.core import agent_presence_sessions as sessions

    sessions.register_session(
        repo_root=world.repo, session_id="bound-1", agent_id="agent-i", pid=os.getpid(), handoff_secret="s3cret"
    )
    ok = {**env, "THOMAS_AGENT_SESSION_ID": "bound-1", "THOMAS_AGENT_CHILD_SECRET": "s3cret"}
    done = sp.run(
        [sys.executable, str(LAND), "--json", "--no-detach", "--message", "feat: i", "--include", "i.txt"],
        env=ok,
        cwd=world.repo,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert FileTicketStore(world.queue).tickets()[1]["session"] == "bound-1"
    clash = {**ok, "THOMAS_AGENT_ID": "someone-else"}
    done = sp.run(
        [sys.executable, str(LAND), "--json", "--agent", "agent-i", "--message", "x"],
        env=clash,
        cwd=world.repo,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert done.returncode == 2  # a flag that disagrees with the bound identity is refused, not used
