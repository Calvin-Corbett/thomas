"""land.py driven in-process against a throwaway git repo and a fake commit tool (never the real commit tool)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import time

import pytest
from scripts.crew.brief import land, land_commit, land_env
from scripts.crew.brief.landing_store import ENV_ROOT, FileTicketStore
from scripts.crew.tasks import claim_liveness

from tests._landing_fakes import sp
from thomas.core import agent_presence_sessions as sessions

FAKE_COMMIT = textwrap.dedent(
    """
    import json, os, subprocess, sys
    args = sys.argv[1:]
    message = args[args.index("--message") + 1]
    mode = open(os.path.join(os.path.dirname(__file__), "mode.txt")).read().strip()
    dry = "--dry-run" in args
    with open(os.path.join(os.path.dirname(__file__), "calls.txt"), "a") as fh:
        fh.write(("dry " if dry else "real ") + " ".join(a for a in args if a.startswith("--") and a != "--message") + "\\n")
    if mode == "refuse":
        print(json.dumps({"ok": False, "blocker_class": "local_gate_failed", "message": "gate x failed", "gate_name": "x", "gate_output": "boom"}))
        raise SystemExit(1)
    if mode == "hang" and not dry:
        import time
        time.sleep(60)
    sha = None
    if not dry:
        open("work.txt", "a").write("x\\n")
        subprocess.run(["git", "add", "work.txt"], check=True)
        subprocess.run(["git", "commit", "-q", "-m", message], check=True)
        sha = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    print(json.dumps({"ok": True, "commit_sha": sha, "message": "ok"}))
    """
)


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    work = tmp_path / "repo"
    work.mkdir()
    for cmd in (
        ["init", "-q"],
        ["config", "user.email", "t@example.test"],
        ["config", "user.name", "t"],
        ["config", "commit.gpgsign", "false"],
        ["config", "core.autocrlf", "false"],
    ):
        sp.run(["git", *cmd], cwd=work, check=True)
    sp.run(["git", "commit", "--allow-empty", "-q", "-m", "base"], cwd=work, check=True)
    tool = tmp_path / "tool"
    tool.mkdir()
    (tool / "fake_commit.py").write_text(FAKE_COMMIT)
    (tool / "mode.txt").write_text("ok")
    monkeypatch.setenv("THOMAS_LAND_ROOT", str(work))
    monkeypatch.setenv("THOMAS_LAND_COMMIT", str(tool / "fake_commit.py"))
    monkeypatch.setenv(ENV_ROOT, str(tmp_path / "queue"))
    monkeypatch.setenv("THOMAS_AGENT_ID", "agent-x")
    for key in ("THOMAS_AGENT_SESSION_ID", "AGENT_SESSION_ID", "AGENT_ID"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(work)
    return work


def tool_dir(work):
    return work.parent / "tool"


def last_json(capsys) -> dict:
    return json.loads([ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("{")][-1])


def git_log(work) -> str:
    return sp.run(["git", "log", "--format=%B%x1e"], cwd=work, capture_output=True, text=True, check=True).stdout


def test_a_landing_carries_the_ticket_trailer_and_runs_the_commit_tool_once_with_no_precheck_when_alone(repo, capsys):
    assert land.run(["--no-detach", "--message", "feat: x", "--include", "a.py", "--json"]) == 0
    out = last_json(capsys)
    assert out["status"] == "landed" and out["ticket"] == 1
    assert f"Landing-Ticket: {land.intent_key('agent-x', 'feat: x', ['a.py'])}" in git_log(repo)
    assert (tool_dir(repo) / "calls.txt").read_text().splitlines() == ["real --json --include"]  # one ladder, not two


def test_a_refusal_inside_the_slot_comes_back_with_the_reason_and_frees_the_slot(repo, capsys):
    (tool_dir(repo) / "mode.txt").write_text("refuse")
    assert land.run(["--no-detach", "--message", "feat: x", "--json"]) == 1
    out = last_json(capsys)
    assert (
        out["status"] == "refused" and "gate x failed" in out["message"] and out["blocker_class"] == "local_gate_failed"
    )
    lane = land_env.make_lane(repo, "agent-x", "", land.Config(), print)
    status = land.landing_status.build_status(lane)
    assert status["queue_length"] == 0 and status["recent_trouble"][0]["reason"] == "local_gate_failed"


def test_missing_message_or_agent_is_a_usage_error(repo, monkeypatch, capsys):
    assert land.run(["--json"]) == 2
    monkeypatch.delenv("THOMAS_AGENT_ID")
    assert land.run(["--message", "x", "--json"]) == 2


def test_status_prints_and_changes_nothing(repo, capsys):
    land.run(["--no-detach", "--message", "feat: x", "--json"])
    capsys.readouterr()
    before = len(FileTicketStore(land.resolve_queue_root()).events())
    assert land.run(["--status", "--verify"]) == 0
    text = capsys.readouterr().out
    assert "0 open ticket" in text and "Last landings:" in text and "Tamper check: clean" in text
    assert len(FileTicketStore(land.resolve_queue_root()).events()) == before


def test_the_commit_tool_command_line_is_the_one_the_agent_gave(repo):
    args = land.parser().parse_args(
        [
            "--message",
            "m",
            "--agent",
            "z",
            "--include",
            "a",
            "--include",
            "b",
            "--allow-scope-fallback",
            "--fallback-reason",
            "why",
        ]
    )
    cmd = land_commit.commit_cmd(land_env.commit_path(), args, "m", dry=False)
    assert cmd[0] == sys.executable and cmd[1].endswith("fake_commit.py")
    assert cmd[2:] == [
        "--message",
        "m",
        "--json",
        "--agent",
        "z",
        "--include",
        "a",
        "--include",
        "b",
        "--allow-scope-fallback",
        "--fallback-reason",
        "why",
    ]
    assert land_commit.commit_cmd(land_env.commit_path(), args, "m", dry=True)[-1] == "--dry-run"


def test_a_commit_that_outlives_the_lease_is_stopped_and_reported_within_the_lease(repo, capsys):
    (tool_dir(repo) / "mode.txt").write_text("hang")
    t0 = time.monotonic()
    assert land.run(["--no-detach", "--message", "feat: x", "--max-hold", "3", "--json"]) == 1
    out = last_json(capsys)
    assert out["blocker_class"] == "lease_expired" and "was stopped" in out["message"]
    assert time.monotonic() - t0 < 20


def test_the_presence_beat_is_the_evidence_the_dead_claim_sweep_reads(tmp_path):
    sessions.register_session(repo_root=tmp_path, session_id="s1", agent_id="agent-x", pid=os.getpid())
    path = tmp_path / "runtime" / "coordination" / "presence" / "s1.json"
    row = json.loads(path.read_text())
    path.write_text(json.dumps({**row, "last_heartbeat_at": "2000-01-01T00:00:00Z"}))
    presence = path.parent
    assert claim_liveness.latest_heartbeat_unix("agent-x", presence) < time.time() - 86400 * 365
    land_env.presence_beat(tmp_path, "s1")  # what a waiting agent does while its ticket is open
    assert claim_liveness.latest_heartbeat_unix("agent-x", presence) > time.time() - 120


def test_a_closed_session_is_never_revived_by_a_waiting_ticket(tmp_path):
    sessions.register_session(repo_root=tmp_path, session_id="s2", agent_id="agent-x", pid=os.getpid())
    sessions.close_session(repo_root=tmp_path, session_id="s2")
    path = tmp_path / "runtime" / "coordination" / "presence" / "s2.json"
    before = json.loads(path.read_text())
    land_env.presence_beat(tmp_path, "s2")  # was: forced the state back to active
    after = json.loads(path.read_text())
    assert after["state"] == "closed" and after["last_heartbeat_at"] == before["last_heartbeat_at"]
    land_env.presence_beat(tmp_path, "no-such-session")  # and a missing one is not created
    assert not (path.parent / "no-such-session.json").exists()
