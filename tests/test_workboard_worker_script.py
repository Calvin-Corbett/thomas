from __future__ import annotations

import json
from pathlib import Path

import scripts.crew.workboard.message as message_tool
import scripts.crew.workboard.worker as mod
import scripts.forge.gates.workboard_claims as gate


class _Completed:
    def __init__(self, stdout: str = "ok\n", stderr: str = "", returncode: int = 0) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _fake_subprocess_run_landing_a_commit(head_shas: list[str]):
    """A `subprocess.run` stand-in for tests whose task pipeline should read
    as having landed a commit (phase-1.4 task-2: `done` now requires
    evidence, and worker.py's auto-done reads that evidence from the repo's
    HEAD sha before/after the pipeline runs -- see `_git_head_sha` in
    scripts/crew/workboard/worker.py).

    `git rev-parse HEAD` calls answer with `head_shas` in order (so the
    before/after reads can differ, simulating a landed commit); every other
    `git ...` list-form call (the evidence library's ancestor/message/time
    lookups, and the claim release's dirty-scope check) answers with an
    empty success response; anything else (the task's own shell command)
    gets the generic success stub. Fully hermetic -- git is never actually
    invoked.
    """
    shas = list(head_shas)

    def _run(*args, **kwargs):  # noqa: ANN002, ANN003
        cmd = args[0] if args else kwargs.get("args")
        if isinstance(cmd, list) and cmd and cmd[0] == "git":
            if len(cmd) >= 3 and cmd[1] == "rev-parse" and cmd[2] == "HEAD":
                sha = shas.pop(0) if shas else "0" * 40
                return _Completed(stdout=f"{sha}\n")
            return _Completed(stdout="")
        return _Completed()

    return _run


def _fake_subprocess_run_landing_a_commit_but_evidence_refused(head_shas: list[str]):
    """Same as `_fake_subprocess_run_landing_a_commit`, except the merge-base
    ancestry check (`_verify_commit` in claim_evidence.py) reports the
    landed sha as NOT an ancestor of `dev` (exit 1 -- the ordinary "real
    finding" case; the separate `dev`-resolves probe `_ref_resolves` runs
    on any nonzero merge-base exit still succeeds via the catch-all below,
    so this exercises the T1-pinned "unknown/non-ancestor sha stays
    failed" path, not the target-unresolvable GIT_UNAVAILABLE path).
    Simulates a commit that landed somewhere other than `dev` by the time
    evidence verification ran -- worker.py's attempted `done` transition is
    REFUSED, not held (a commit DID land, unlike the no-commit-landed
    REVIEW HOLD case).
    """
    shas = list(head_shas)

    def _run(*args, **kwargs):  # noqa: ANN002, ANN003
        cmd = args[0] if args else kwargs.get("args")
        if isinstance(cmd, list) and cmd and cmd[0] == "git":
            if len(cmd) >= 3 and cmd[1] == "rev-parse" and cmd[2] == "HEAD":
                sha = shas.pop(0) if shas else "0" * 40
                return _Completed(stdout=f"{sha}\n")
            if len(cmd) >= 3 and cmd[1] == "merge-base" and cmd[2] == "--is-ancestor":
                return _Completed(stdout="", returncode=1)
            return _Completed(stdout="")
        return _Completed()

    return _run


def _final_json_payload(captured_stdout: str) -> dict:
    """Parse the trailing (pretty-printed, `indent=2`) JSON payload out of
    worker.py's stdout, discarding any single-line prints ahead of it (an
    ATTESTED-NOT-VERIFIED or REVIEW HOLD line -- see phase-1.4 task-2).
    `json.loads` on the raw captured text would fail once those lines exist,
    since they aren't part of the JSON document.
    """
    json_start = captured_stdout.index("{")
    return json.loads(captured_stdout[json_start:])


def _write_workboard(
    tmp_path: Path,
    *,
    claims_block: str = "- none",
    active_tasks_block: str = "- none",
    issues_block: str = "- none",
    up_for_grabs_block: str = "- none",
) -> Path:
    path = tmp_path / "WORKBOARD.md"
    path.write_text(
        (
            "# Thomas Workboard\n\n"
            "## Agent Claims (Active)\n\n"
            "Claim format:\n"
            "`- \\`agent=<id>; scope=<path[,path...]>; task=<short text>\\``\n\n"
            f"{claims_block}\n\n"
            "## Active Tasks\n\n"
            "Task format:\n"
            "`- \\`task_id=<id>; agent=<id>; scope=<path[,path...]>; summary=<short text>; status=<active|blocked>\\``\n\n"
            f"{active_tasks_block}\n\n"
            "## Issues / Blockers\n\n"
            "Issue format:\n"
            "`- \\`issue_id=<id>; task_id=<task_id>; reporter=<id>; owner=<id|unassigned>; state=<open|triaged|resolved>; summary=<short text>\\``\n\n"
            f"{issues_block}\n\n"
            "## Up For Grabs\n\n"
            "Task format:\n"
            "`- \\`task_id=<id>; scope=<path[,path...]>; summary=<short text>; reported_by=<id>\\``\n\n"
            f"{up_for_grabs_block}\n\n"
            "## Supporting Docs (Not Plan Sources)\n\n"
            "- docs/PROJECT_SCOPE.md\n"
        ),
        encoding="utf-8",
    )
    return path


def test_worker_stops_before_task_when_inbox_has_unread_message(tmp_path: Path, monkeypatch, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        claims_block="- agent=Worker 1; scope=scripts/forge/gates/plan_structure_gate.py; task=[WIP] automation lane",
        active_tasks_block=(
            "- task_id=task-a; agent=Worker 1; scope=scripts/forge/gates/plan_structure_gate.py; "
            "summary=[P1][NEXT] run automation lane; status=active"
        ),
    )
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"tasks": {"task-a": ["python -c \"print('should not run')\""]}}, indent=2), encoding="utf-8")

    ok_send, send_payload = message_tool.send_message(
        workboard,
        sender="Coordinator",
        recipient="Worker 1",
        task_id="task-a",
        kind="blocker",
        priority="p0",
        summary="Stop and read this first",
        requested_action="Ack/respond before continuing.",
    )
    assert ok_send, send_payload

    def _unexpected_run(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("worker executed a task command before clearing unread inbox messages")

    monkeypatch.setattr(mod.subprocess, "run", _unexpected_run)

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--agent",
            "Worker 1",
            "--task-manager-agent",
            "task-manager-agent",
            "--catalog",
            str(catalog),
            "--cycles",
            "1",
            "--poll-seconds",
            "0",
            "--idle-heartbeat-seconds",
            "0",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    text = workboard.read_text(encoding="utf-8")

    assert rc == 1
    assert payload["ok"] is False
    assert payload["completed_count"] == 0
    assert payload["failure_count"] == 0
    assert payload["inbox_blocked_count"] == 1
    assert payload["last_inbox_message_ids"] == [send_payload["message"]["msg_id"]]
    assert "task_id=task-a; agent=Worker 1;" in text
    assert "worker paused: `Worker 1` has 1 unread workboard message(s)" in text


def test_worker_executes_assigned_task_and_releases_on_success(tmp_path: Path, monkeypatch, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        claims_block="- agent=Worker 1; scope=scripts/forge/gates/plan_structure_gate.py; task=[WIP] automation lane",
        active_tasks_block=(
            "- task_id=task-a; agent=Worker 1; scope=scripts/forge/gates/plan_structure_gate.py; "
            "summary=[P1][NEXT] run automation lane; status=active"
        ),
    )
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"tasks": {"task-a": ["python -c \"print('ok')\""]}}, indent=2), encoding="utf-8")

    # phase-1.4 task-2: `done` requires evidence. This fake makes the repo's
    # HEAD sha read as having changed across the pipeline run, so the task
    # reads as having landed a commit and the auto-done path has evidence to
    # offer (see `_fake_subprocess_run_landing_a_commit`'s docstring).
    monkeypatch.setattr(
        mod.subprocess, "run", _fake_subprocess_run_landing_a_commit(["a" * 40, "b" * 40])
    )

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--agent",
            "Worker 1",
            "--catalog",
            str(catalog),
            "--cycles",
            "2",
            "--max-completions",
            "1",
            "--poll-seconds",
            "0",
            "--idle-heartbeat-seconds",
            "0",
            "--json",
        ]
    )
    # The evidence library's ancestor/message/time lookups are faked empty
    # (see the helper docstring), so binding falls back to unbound and the
    # transition proceeds as `attested`, which prints an ATTESTED-NOT-VERIFIED
    # line ahead of the final JSON payload line -- parse the last line only.
    payload = _final_json_payload(capsys.readouterr().out)
    text = workboard.read_text(encoding="utf-8")

    assert rc == 0
    assert payload["ok"] is True
    assert payload["completed_count"] == 1
    assert "agent=Worker 1; scope=scripts/forge/gates/plan_structure_gate.py; task=[WIP] automation lane" not in text
    assert "task_id=task-a; agent=Worker 1;" not in text
    assert "completed `task-a`" in text
    assert gate.evaluate(workboard) == []


def test_worker_failure_keeps_claim_by_default(tmp_path: Path, monkeypatch, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        claims_block="- agent=Worker 1; scope=scripts/forge/gates/plan_structure_gate.py; task=[WIP] automation lane",
        active_tasks_block=(
            "- task_id=task-a; agent=Worker 1; scope=scripts/forge/gates/plan_structure_gate.py; "
            "summary=[P1][NEXT] run automation lane; status=active"
        ),
    )
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps({"tasks": {"task-a": ['python -c "import sys; sys.exit(5)"']}}, indent=2), encoding="utf-8"
    )

    class _Completed:
        def __init__(self) -> None:
            self.returncode = 5
            self.stdout = ""
            self.stderr = "boom\n"

    monkeypatch.setattr(mod.subprocess, "run", lambda *args, **kwargs: _Completed())

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--agent",
            "Worker 1",
            "--catalog",
            str(catalog),
            "--cycles",
            "1",
            "--poll-seconds",
            "0",
            "--idle-heartbeat-seconds",
            "0",
            "--stop-on-failure",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    text = workboard.read_text(encoding="utf-8")

    assert rc == 1
    assert payload["ok"] is False
    assert payload["failure_count"] >= 1
    assert "agent=Worker 1; scope=scripts/forge/gates/plan_structure_gate.py; task=[WIP] automation lane" in text
    assert "task_id=task-a; agent=Worker 1;" in text
    assert "automation failed for `task-a`" in text
    assert gate.evaluate(workboard) == []


def test_worker_release_on_no_command_flag(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        claims_block="- agent=Worker 1; scope=scripts/forge/gates/plan_structure_gate.py; task=[WIP] automation lane",
        active_tasks_block=(
            "- task_id=task-a; agent=Worker 1; scope=scripts/forge/gates/plan_structure_gate.py; "
            "summary=[P1][NEXT] run automation lane; status=active"
        ),
    )
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"tasks": {}}, indent=2), encoding="utf-8")

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--agent",
            "Worker 1",
            "--catalog",
            str(catalog),
            "--cycles",
            "1",
            "--poll-seconds",
            "0",
            "--idle-heartbeat-seconds",
            "0",
            "--release-on-no-command",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    text = workboard.read_text(encoding="utf-8")

    assert rc == 0
    assert payload["ok"] is True
    assert payload["no_command_count"] == 1
    assert "agent=Worker 1; scope=scripts/forge/gates/plan_structure_gate.py; task=[WIP] automation lane" not in text
    assert "task_id=task-a; agent=Worker 1;" not in text
    assert "no automation command configured for `task-a`" in text
    assert gate.evaluate(workboard) == []


def test_worker_success_triggers_immediate_redispatch(tmp_path: Path, monkeypatch, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        claims_block="- agent=Worker 1; scope=scripts/forge/gates/plan_structure_gate.py; task=[WIP] automation lane",
        active_tasks_block=(
            "- task_id=task-a; agent=Worker 1; scope=scripts/forge/gates/plan_structure_gate.py; "
            "summary=[P1][NEXT] run automation lane; status=claimed"
        ),
        up_for_grabs_block=(
            "- task_id=task-b; scope=scripts/forge/gates/plan_structure_gate.py; "
            "summary=[P1][NEXT] follow-up automation lane; reported_by=task-manager-agent"
        ),
    )
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"tasks": {"task-a": ["python -c \"print('ok')\""]}}, indent=2), encoding="utf-8")

    # phase-1.4 task-2: `done` requires evidence -- see
    # `_fake_subprocess_run_landing_a_commit`'s docstring.
    monkeypatch.setattr(
        mod.subprocess, "run", _fake_subprocess_run_landing_a_commit(["a" * 40, "b" * 40])
    )

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--agent",
            "Worker 1",
            "--catalog",
            str(catalog),
            "--cycles",
            "2",
            "--max-completions",
            "1",
            "--poll-seconds",
            "0",
            "--idle-heartbeat-seconds",
            "0",
            "--json",
        ]
    )
    # See the ancestor/message/time lookups note in the prior test: the
    # transition proceeds as `attested`, printing an ATTESTED-NOT-VERIFIED
    # line before the final JSON payload line.
    payload = _final_json_payload(capsys.readouterr().out)
    text = workboard.read_text(encoding="utf-8")

    assert rc == 0
    assert payload["ok"] is True
    assert payload["completed_count"] == 1
    assert payload["dispatch_request_count"] == 1
    assert payload["dispatch_assigned_count"] == 1
    assert "task_id=task-b; agent=Worker 1;" in text
    assert "task_id=task-b; scope=scripts/forge/gates/plan_structure_gate.py;" not in text
    assert gate.evaluate(workboard) == []


def test_worker_auto_done_passes_commit_evidence_when_the_pipeline_lands_a_commit(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """phase-1.4 task-2, contract 5: pipeline-with-commit passes `commit:<sha>`
    evidence and reaches `done`. --no-auto-release-success keeps the Active
    Task line around afterward so the evidence= / evidence_recorded_at=
    fields it stamped are visible to assert on.
    """
    workboard = _write_workboard(
        tmp_path,
        claims_block="- agent=Worker 1; scope=scripts/forge/gates/plan_structure_gate.py; task=[WIP] automation lane",
        active_tasks_block=(
            "- task_id=task-a; agent=Worker 1; scope=scripts/forge/gates/plan_structure_gate.py; "
            "summary=[P1][NEXT] run automation lane; status=active"
        ),
    )
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"tasks": {"task-a": ["python -c \"print('ok')\""]}}, indent=2), encoding="utf-8")

    monkeypatch.setattr(mod.subprocess, "run", _fake_subprocess_run_landing_a_commit(["a" * 40, "b" * 40]))

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--agent",
            "Worker 1",
            "--catalog",
            str(catalog),
            "--cycles",
            "1",
            "--poll-seconds",
            "0",
            "--idle-heartbeat-seconds",
            "0",
            "--no-auto-release-success",
        ]
    )
    text = workboard.read_text(encoding="utf-8")
    out = capsys.readouterr().out

    assert rc == 0
    assert "task_id=task-a; agent=Worker 1;" in text
    assert "status=done" in text
    assert ("evidence=commit:" + "b" * 40) in text
    assert "evidence_recorded_at=" in text
    assert "REVIEW HOLD" not in out


def test_worker_leaves_review_hold_when_the_pipeline_lands_no_commit(tmp_path: Path, monkeypatch, capsys) -> None:
    """phase-1.4 task-2, contract 5, review-round fix 1: pipeline-without-
    commit leaves the task in `review` with a loud REVIEW HOLD line -- the
    honest regression from the old auto-done-on-exit-0 behavior. Same sha
    before/after simulates a pipeline that succeeded (tests passed, lint
    was clean) without ever landing a commit.

    A held task is not a clean completion, so it must mirror the failure
    branch's convention on all three fronts: (a) no completed/approved
    message goes out -- a distinct blocker message names the hold instead;
    (b) the claim is NOT released (auto-release-success defaults on here,
    unlike the with-commit test, specifically to prove release is skipped
    rather than merely not requested); (c) the loop as a whole reports
    non-clean via a nonzero exit code, never silent success.
    """
    workboard = _write_workboard(
        tmp_path,
        claims_block="- agent=Worker 1; scope=scripts/forge/gates/plan_structure_gate.py; task=[WIP] automation lane",
        active_tasks_block=(
            "- task_id=task-a; agent=Worker 1; scope=scripts/forge/gates/plan_structure_gate.py; "
            "summary=[P1][NEXT] run automation lane; status=active"
        ),
    )
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"tasks": {"task-a": ["python -c \"print('ok')\""]}}, indent=2), encoding="utf-8")

    monkeypatch.setattr(mod.subprocess, "run", _fake_subprocess_run_landing_a_commit(["a" * 40, "a" * 40]))

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--agent",
            "Worker 1",
            "--catalog",
            str(catalog),
            "--cycles",
            "1",
            "--poll-seconds",
            "0",
            "--idle-heartbeat-seconds",
            "0",
            "--json",
        ]
    )
    text = workboard.read_text(encoding="utf-8")
    out = capsys.readouterr().out
    payload = _final_json_payload(out)

    # (c) non-clean loop: nonzero exit, held_count counted, never silent.
    assert rc == 1
    assert payload["ok"] is False
    assert payload["held_count"] == 1

    # (a) message content: the distinct hold message fired, not the completed/approved one.
    assert "pipeline succeeded for `task-a` but landed no commit" in text
    assert "done withheld, task remains in review" in text
    assert "kind=blocker" in text
    assert "completed `task-a` using" not in text

    # (b) claim intact: still held by Worker 1, task still in review, never released.
    assert "agent=Worker 1; scope=scripts/forge/gates/plan_structure_gate.py; task=[WIP] automation lane" in text
    assert "task_id=task-a; agent=Worker 1;" in text
    assert "status=review" in text
    assert "evidence=" not in text

    assert "REVIEW HOLD task-a: pipeline succeeded but landed no commit - done requires evidence" in out


def test_worker_refuses_done_when_the_landed_commit_fails_evidence_verification(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Coordinator review, whole-branch fix wave, finding 3 (IMPORTANT): a
    REFUSED done (a commit landed, but its evidence failed verification)
    used to fall through the SAME path as a real completion -- still
    counted `completion_count`, still sent the `decision=approved`
    completed message, and (with `--no-auto-release-success` specifically)
    `ok` could read `True` with the refusal hidden inside it, since nothing
    else touched `failure_count`/`held_count`/`inbox_blocked_count`.
    Mirrors `test_worker_leaves_review_hold_when_the_pipeline_lands_no_commit`
    on all three fronts, for the DIFFERENT failure shape -- a commit DID
    land here, unlike the held case.
    """
    workboard = _write_workboard(
        tmp_path,
        claims_block="- agent=Worker 1; scope=scripts/forge/gates/plan_structure_gate.py; task=[WIP] automation lane",
        active_tasks_block=(
            "- task_id=task-a; agent=Worker 1; scope=scripts/forge/gates/plan_structure_gate.py; "
            "summary=[P1][NEXT] run automation lane; status=active"
        ),
    )
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"tasks": {"task-a": ["python -c \"print('ok')\""]}}, indent=2), encoding="utf-8")

    monkeypatch.setattr(
        mod.subprocess, "run", _fake_subprocess_run_landing_a_commit_but_evidence_refused(["a" * 40, "b" * 40])
    )

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--agent",
            "Worker 1",
            "--catalog",
            str(catalog),
            "--cycles",
            "1",
            "--poll-seconds",
            "0",
            "--idle-heartbeat-seconds",
            "0",
            "--no-auto-release-success",
            "--json",
        ]
    )
    text = workboard.read_text(encoding="utf-8")
    out = capsys.readouterr().out
    payload = _final_json_payload(out)

    # (c) non-clean loop even with --no-auto-release-success -- the exact shape the
    # reviewer flagged: before the fix, nothing here touched
    # failure_count/held_count/inbox_blocked_count, so `ok` read True.
    assert rc == 1
    assert payload["ok"] is False
    assert payload["refused_count"] == 1
    assert payload["completed_count"] == 0

    # (a) message content: the refusal blocker fired, not the completed/approved one.
    assert "done refused for `task-a`" in text
    assert "task remains in review" in text
    assert "kind=blocker" in text
    assert "completed `task-a` using" not in text

    # (b) claim/task state: still review, no evidence recorded, claim never released.
    assert "agent=Worker 1; scope=scripts/forge/gates/plan_structure_gate.py; task=[WIP] automation lane" in text
    assert "task_id=task-a; agent=Worker 1;" in text
    assert "status=review" in text
    assert "evidence=" not in text

    assert "DONE REFUSED task-a:" in out
