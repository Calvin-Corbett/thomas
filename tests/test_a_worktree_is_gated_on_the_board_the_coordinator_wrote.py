"""A coordinator in the primary checkout and a worker in a linked worktree see one board.

The message tool anchored itself to the primary checkout through git's shared
common directory, while the startup router, the inbox gate, its Bash hook and
the commit barrier anchored to the worktree that held the running script copy.
A blocker sent from the primary checkout was therefore delivered to a board the
worker's gates never read: the startup inbox said zero unread, the hook let
Bash run, and the barrier let a commit through.

The scenario runs the real CLIs as fresh processes from disposable git
checkouts built here -- never the project's own board -- with every command on
its default path: no ``--workboard``, no mirrored board, no mirrored ack.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tests._native_coordination_harness import (
    BOARD,
    COORDINATOR,
    REPO,
    SOURCE_FILES,
    TASK_ID,
    WORKER,
    _bare_env,
    _bind,
    _build_checkouts,
    _claim_unit_work,
    _json,
    _lines,
    _norm,
    _receipts,
    _Run,
    _sha256,
)

# The router reads the saved workflow mode from the user's preference store unless it is told; the scenario tells it.
ROUTER = ("scripts/crew/brief/startup_router.py", "--summary", "next unit", "--workflow-mode", "guided")


@pytest.mark.timeout(600)
def test_a_worktree_is_gated_on_the_board_the_coordinator_wrote(tmp_path: Path) -> None:
    primary, worktree = _build_checkouts(tmp_path)
    canonical_board = (primary / "plans" / "thomas" / "WORKBOARD.md").resolve()
    local_board = (worktree / "plans" / "thomas" / "WORKBOARD.md").resolve()
    assert local_board != canonical_board and local_board.exists()
    # What every printed remediation must carry: the judged board, absolute and quoted.
    canonical_board_argument = (
        f'--workboard "{canonical_board}"' if os.name == "nt" else f"--workboard {canonical_board}"
    )

    artifact: dict[str, object] = {
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "primary_checkout": str(primary),
        "linked_worktree": str(worktree),
        "canonical_board": str(canonical_board),
        "worktree_local_board": str(local_board),
        "source_hashes": {rel: _sha256(REPO / rel) for rel in SOURCE_FILES if (REPO / rel).exists()},
        "identities": {"coordinator": COORDINATOR, "worker": WORKER},
        "runs": [],
    }
    runs: list[dict[str, object]] = artifact["runs"]  # type: ignore[assignment]
    run = _Run(runs)

    try:
        # Both identities are bound at the ONE intended coordination root; the worker's claim is on its own board.
        for agent, session in (COORDINATOR, WORKER):
            _bind(primary, agent, session)
        _claim_unit_work(worktree)
        local_before = _sha256(local_board)

        # (1) The coordinator sends one fresh addressed blocker on the default path.
        rc, out, _ = run(
            "coordinator sends blocker",
            primary,
            "scripts/crew/workboard/message.py",
            *("--send", "--to-agent", WORKER[0], "--kind", "blocker", "--priority", "p0", "--task-id", TASK_ID),
            *("--summary", "stop: the scope overlaps mine", "--requested-action", "ack and wait", "--json"),
            actor=COORDINATOR,
        )
        sent = _json(out)
        assert rc == 0 and sent["ok"] is True, out
        msg_id = str(sent["message"]["msg_id"])  # type: ignore[index]
        artifact["message_id"] = msg_id
        assert Path(str(sent["workboard"])).resolve() == canonical_board

        # (2) From the linked worktree every default-path reader names the same message and board.
        rc, out, _ = run(
            "worker inbox", worktree, "scripts/crew/workboard/message.py", "--inbox", "--json", actor=WORKER
        )
        inbox = _json(out)
        assert rc == 0 and [m["msg_id"] for m in inbox["messages"]] == [msg_id], out  # type: ignore[index]
        assert Path(str(inbox["workboard"])).resolve() == canonical_board
        wait = ("--wait", "--timeout-seconds", "2", "--poll-interval-seconds", "0.2", "--json")
        rc, out, _ = run("worker wait", worktree, "scripts/crew/workboard/message.py", *wait, actor=WORKER)
        waited = _json(out)
        assert rc == 0 and Path(str(waited["workboard"])).resolve() == canonical_board, out
        assert msg_id in json.dumps(waited), out

        rc, out, _ = run(
            "worker inbox gate", worktree, "scripts/forge/gates/workboard_inbox.py", "--json", actor=WORKER
        )
        gate = _json(out)
        assert rc == 1 and gate["ok"] is False, "the inbox gate did not block on the unresolved blocker: " + out
        assert Path(str(gate["workboard"])).resolve() == canonical_board, out
        assert [m["msg_id"] for m in gate["unread_messages"]] == [msg_id], out  # type: ignore[index]
        assert canonical_board_argument in str(gate["next_step"]), gate["next_step"]

        hook_payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "git status"}})
        rc, _, err = run(
            "worker bash hook",
            worktree,
            "scripts/forge/gates/workboard_inbox_hook.py",
            actor=WORKER,
            stdin=hook_payload,
        )
        assert rc == 2 and msg_id in err, "the Bash hook let the action run: " + err
        assert err.count(canonical_board_argument) == 2, "the hook's remediation commands do not name the board: " + err

        # The real commit entry point, from the worktree, as the worker whose ONE session is bound at the root.
        rc, out, err = run(
            "worker dry-run commit", worktree, "barrier_probe.py", str(worktree), WORKER[0], actor=WORKER
        )
        assert rc == 0, out + err
        assert _lines(out, "barrier ") == [f"barrier {_norm(canonical_board)}"], (
            "the barrier read another board: " + out
        )
        assert _lines(out, "commit ")[0].startswith("commit False coordination_p0 |") and msg_id in out, (
            "commit.py did not stop at its barrier with the worker's one session binding: " + out
        )

        rc, out, _ = run("worker startup router", worktree, *ROUTER, "--json", actor=WORKER)
        startup = _json(out)
        startup_inbox = startup["inbox"]  # type: ignore[index]
        assert Path(str(startup.get("coordination_board") or "")).resolve() == canonical_board, (
            "the startup router read its inbox on a worktree-local board: " + json.dumps(startup_inbox)
        )
        assert [m["msg_id"] for m in startup_inbox["messages"]] == [msg_id], json.dumps(startup_inbox)  # type: ignore[index]
        # Claims stay where claim.py and the commit gates keep them: this checkout's board.
        assert Path(str(startup["workboard"]["path"])).resolve() == local_board, startup["workboard"]  # type: ignore[index]

        rc, out, _ = run("worker startup router text", worktree, *ROUTER, actor=WORKER)
        inbox_action = _lines(out, "inbox_action:")
        assert inbox_action and canonical_board_argument in inbox_action[0], "the remediation names no board: " + out

        # (3) The worker acks on its default path; the coordinator reads the same row back.
        rc, out, _ = run(
            "worker acks",
            worktree,
            "scripts/crew/workboard/message.py",
            *("--ack", "--msg-id", msg_id, "--by", WORKER[0], "--json"),
            actor=WORKER,
        )
        acked = _json(out)
        assert rc == 0 and acked["ok"] is True, out
        assert Path(str(acked["workboard"])).resolve() == canonical_board

        rc, out, _ = run(
            "coordinator reads back",
            primary,
            "scripts/crew/workboard/message.py",
            "--list",
            "--all",
            "--json",
            actor=COORDINATOR,
        )
        rows = {m["msg_id"]: m for m in _json(out)["messages"]}  # type: ignore[index]
        assert rows[msg_id]["state"] == "acked" and rows[msg_id]["updated_by"] == WORKER[0], out
        # The ack is not the decision: the review hold the coordinator set at send time is untouched.
        assert rows[msg_id]["decision"] == "pending", rows[msg_id]
        artifact["row_after_ack"] = rows[msg_id]

        # A fresh process reflects the recorded ack: no unread mail, and the same dry-run commit now goes through,
        # judged on the worktree's own claim, with the inbox gates handed the board the barrier read.
        rc, out, _ = run(
            "worker inbox gate after ack", worktree, "scripts/forge/gates/workboard_inbox.py", "--json", actor=WORKER
        )
        assert rc == 0 and _json(out)["unread_count"] == 0, out
        rc, out, err = run(
            "worker dry-run after ack", worktree, "barrier_probe.py", str(worktree), WORKER[0], actor=WORKER
        )
        assert _lines(out, "commit ") == ["commit True None | local scoped commit checks passed (dry-run)"], out + err
        assert (
            set(_lines(out, "barrier ")) == {f"barrier {_norm(canonical_board)}"} and len(_lines(out, "barrier ")) == 2
        ), out
        assert _lines(out, "land ") == [f"land {_norm(canonical_board)}"], out
        gate_lines = _lines(out, "gate ")
        assert len(gate_lines) == 2 and all(_norm(canonical_board) in os.path.normcase(line) for line in gate_lines), (
            "commit.py's inbox gate subprocesses would read a different board than its barrier: " + out
        )

        # The decision is the coordinator's separate step, and the worktree reads it back.
        rc, out, _ = run(
            "coordinator decides",
            primary,
            "scripts/crew/workboard/message.py",
            *("--resolve", "--msg-id", msg_id, "--decision", "approved", "--json"),
            actor=COORDINATOR,
        )
        assert rc == 0 and _json(out)["ok"] is True, out
        rc, out, _ = run(
            "worker reads the decision",
            worktree,
            "scripts/crew/workboard/message.py",
            "--list",
            "--all",
            "--json",
            actor=WORKER,
        )
        rows = {m["msg_id"]: m for m in _json(out)["messages"]}  # type: ignore[index]
        assert rows[msg_id]["state"] == "resolved" and rows[msg_id]["decision"] == "approved", out
        artifact["row_after_decision"] = rows[msg_id]

        # (4) Nothing was mirrored: the worktree-local board is byte-identical, the receipt lives at the root.
        assert _sha256(local_board) == local_before, "the worktree-local duplicate board was written"
        receipts = _receipts(primary)
        artifact["receipts"] = {str(p): p.read_text(encoding="utf-8") for p in receipts}
        # One board, one receipt scope: the worker's ack and the coordinator's decision key to the same board.
        assert receipts and len({p.parent for p in receipts}) == 1, receipts
        worker_receipt = [p for p in receipts if p.name == f"{WORKER[0]}.jsonl"]
        assert worker_receipt and msg_id in worker_receipt[0].read_text(encoding="utf-8"), receipts
        assert not (worktree / "runtime" / "coordination").exists(), "coordination state leaked into the worktree"
        artifact["result"] = "pass"
    finally:
        if (failure := sys.exc_info()[1]) is not None:  # the exception on its way out; it propagates unchanged
            artifact["result"] = f"fail: {type(failure).__name__}: {failure}"
        artifact["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        (tmp_path / "artifact.json").write_text(json.dumps(artifact, indent=2, sort_keys=True), encoding="utf-8")


def test_a_missing_board_is_an_error_not_an_empty_inbox(tmp_path: Path) -> None:
    from scripts.crew.workboard import message as message_tool
    from scripts.forge.gates import workboard_inbox

    missing = tmp_path / "nowhere" / "WORKBOARD.md"
    ok, payload = message_tool.unread_messages(missing, agent="worker-b2")
    assert ok is False and payload["missing_workboard"] is True
    assert str(missing) in str(payload["error"])

    ok, payload = workboard_inbox.evaluate(workboard_path=missing, agent="worker-b2")
    assert ok is False and str(missing) in str(payload["error"])


def test_a_printed_board_argument_survives_a_space_in_the_path(tmp_path: Path) -> None:
    import shlex

    from scripts.crew.workboard import coordination_root

    board = tmp_path / "a dir" / "WORKBOARD.md"
    argument = coordination_root.board_argument(board)
    tokens = argument.split(None, 1) if os.name == "nt" else shlex.split(argument)
    assert tokens[0] == "--workboard"
    value = tokens[1].strip('"') if os.name == "nt" else tokens[1]
    assert Path(value) == board.resolve()


def test_commit_runs_its_inbox_gate_on_the_board_its_barrier_reads(tmp_path: Path) -> None:
    from scripts.crew.brief import commit
    from scripts.crew.workboard import coordination_root
    from scripts.crew.workboard import message as message_tool

    board = tmp_path / "WORKBOARD.md"
    board.write_text(BOARD, encoding="utf-8")
    ok, _ = message_tool.send_message(
        board,
        sender="coordinator-a1",
        recipient="worker-b2",
        summary="hold",
        kind="blocker",
        priority="p0",
        task_id="NATIVE-ROOT-2",
        require_claims_to_have_active_task=False,
    )
    assert ok
    handed = coordination_root.with_inbox_board(commit.LOCAL_GATE_COMMANDS, board)
    commands = [argv for name, argv in handed if name.startswith("workboard_inbox")]
    assert len(commands) == 2 and all(list(argv[-2:]) == ["--workboard", str(board.resolve())] for argv in commands)
    assert all("--workboard" not in argv for name, argv in handed if not name.startswith("workboard_inbox"))
    proc = subprocess.run(
        [*commands[0], "--json", "--agent", "worker-b2"],
        cwd=str(REPO),
        env=_bare_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    # On the commit path the inbox gate advises (workboard_inbox.py says why); the board it reports on is the barrier's.
    assert proc.returncode == 0 and payload["advisory"] is True and payload["ok"] is False, proc.stdout
    assert Path(str(payload["workboard"])).resolve() == board.resolve(), proc.stdout
    assert [m["from"] for m in payload["unread_messages"]] == ["coordinator-a1"], proc.stdout
