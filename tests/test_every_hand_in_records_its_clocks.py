"""Hand-in clocks observe real checks and failures without affecting their answers."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from thomas.forge.anvil import forge_code_projects, forge_code_store
from thomas.server import capacity_ledger, green_checkout, green_handoff, precard, thomas_project
from thomas.server.precard import check, clocks, pool, slot
from thomas.server.precard.lint import LintResult
from thomas.server.proof import ProofRun, Selection, Verdict

EXECUTION = "thomas-checked1"
CLEAN_ADDER = "def add(a: int, b: int) -> int:\n    return a + b  # exact same sum\n"
CLEAN_TEST = "from pkg.adder import add\n\ndef test_add() -> None:\n    assert add(2, 2) == 4\n"


@pytest.fixture
def repository_world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """A real repository for the submission boundary, without importing another test module's launchers."""
    blue, greens = tmp_path / "blue", tmp_path / "greens"
    (blue / "pkg").mkdir(parents=True)
    (blue / "tests").mkdir()
    (blue / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (blue / "pkg" / "adder.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (blue / "tests" / "test_adder.py").write_text(CLEAN_TEST, encoding="utf-8")
    (blue / "tests" / "test_architecture.py").write_text("def test_architecture():\n    pass\n", encoding="utf-8")
    (blue / ".gitignore").write_text(".thomas/\nruntime/\n__pycache__/\n", encoding="utf-8")
    for args in (
        ["init", "-b", "dev"],
        ["config", "user.email", "test@example.com"],
        ["config", "user.name", "Test"],
        ["config", "core.autocrlf", "false"],
        ["add", "."],
        ["commit", "-m", "fixture"],
    ):
        subprocess.run(["git", *args], cwd=blue, check=True, capture_output=True)
    for folder in (greens / "work", greens / "git"):
        folder.mkdir(parents=True)
    monkeypatch.setenv(green_checkout.GREEN_ROOT_ENV, str(greens))
    monkeypatch.setattr(green_handoff, "inbox_dir", lambda: tmp_path / "inbox")
    monkeypatch.setenv(capacity_ledger.ROOT_ENV, str(tmp_path / "ledger"))
    monkeypatch.setenv(check.proofs.PYTHON_ENV, sys.executable)
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    monkeypatch.setenv("THOMAS_PRECARD_PARALLEL", "off")
    monkeypatch.setenv(precard.review.REVIEW_ENV, "on")
    monkeypatch.setattr(green_handoff, "_end_processes", lambda *_: None)
    monkeypatch.setattr(forge_code_projects, "thomas_source_repo_root", lambda: blue)
    # This repository has no Thomas size policy; that gate has its own integration tests.
    monkeypatch.setattr(green_handoff, "size_problems", lambda _eid: [])
    catalog = tmp_path / "catalog"
    monkeypatch.setattr(thomas_project, "_catalog_root", lambda: catalog)
    green = green_checkout.create_green(blue=blue, execution_id=EXECUTION)
    return SimpleNamespace(tmp=tmp_path, blue=blue, greens=greens, catalog=catalog, green=green)


def _records(catalog: Path) -> list[dict[str, Any]]:
    path = clocks.clocks_path(catalog)
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.is_file() else []


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Clock-only cases exercise settlement with in-memory repository boundaries."""
    work, catalog = tmp_path / "work", tmp_path / "catalog"
    work.mkdir()
    catalog.mkdir()
    green = green_checkout.Green(EXECUTION, work, tmp_path / "git", "base", tmp_path / "blue")
    monkeypatch.setattr(green_handoff, "size_problems", lambda _eid: [])
    monkeypatch.setattr(precard.review, "held_check", lambda _eid: None)
    monkeypatch.setenv(precard.review.REVIEW_ENV, "on")
    monkeypatch.setattr(thomas_project, "_patch_files", lambda _eid: ["pkg/adder.py", "tests/test_adder.py"])
    conversations: dict[tuple[Path, str], dict[str, Any]] = {}

    def write_conversation(root: Path, conversation: dict[str, Any]) -> None:
        conversations[Path(root), conversation["id"]] = copy.deepcopy(conversation)

    monkeypatch.setattr(
        forge_code_store,
        "load_conversation",
        lambda root, cid: copy.deepcopy(conversations.get((Path(root), cid))),
    )
    monkeypatch.setattr(forge_code_store, "write_conversation", write_conversation)
    monkeypatch.setattr(forge_code_store, "mark_thomas_project_settled", lambda *_: None)
    monkeypatch.setattr(green_checkout, "find_green", lambda _eid: green)
    monkeypatch.setattr(green_checkout, "green_patch", lambda _green: "clock fixture patch")
    monkeypatch.setattr(green_handoff, "end_green_processes", lambda _eid: None)
    monkeypatch.setattr(green_handoff, "await_verdict", lambda _eid: None)
    monkeypatch.setattr(green_handoff, "awaiting_verdict", lambda _eid: True)
    submission = tmp_path / "inbox" / f"self-{EXECUTION}"
    monkeypatch.setattr(green_handoff, "settle", lambda *_a, **_kw: submission)
    return SimpleNamespace(tmp=tmp_path, green=green, catalog=catalog, clock_only=True)


def _ready(world: SimpleNamespace) -> str:
    changes = ["pkg/adder.py", "tests/test_adder.py"]
    if not getattr(world, "clock_only", False):
        (world.green.work / "pkg/adder.py").write_text("def add(a, b):\n    return a + b + 1\n", encoding="utf-8")
        (world.green.work / "tests/test_adder.py").write_text(
            "from pkg.adder import add\n\ndef test_add():\n    assert add(2, 2) == 5\n", encoding="utf-8"
        )
    if getattr(world, "clock_only", False):
        cid = "clock-case"
        forge_code_store.write_conversation(
            world.green.work,
            {
                "id": cid,
                "thomas_project": {"execution_id": EXECUTION},
                "turns": [{"role": "agent", "ok": True, "text": "Finished clock case"}],
            },
        )
        return cid
    cid = str(
        forge_code_store.new_conversation(
            world.green.work, title="make it double", thomas_project={"execution_id": EXECUTION}
        )["id"]
    )
    forge_code_store.append_user_turn(world.green.work, cid, "make it double")
    forge_code_store.append_agent_turn(
        world.green.work,
        cid,
        model="claude",
        transcript="",
        changed_files=changes,
        returncode=0,
        ok=True,
        noop=False,
        reason="2 file(s) changed",
        outcome="completed",
    )
    forge_code_projects.bind_conversation(world.catalog, cid, world.green.work, allow_without_history=True)
    return cid


def _passing_review(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(precard.review, "second_look", lambda _eid, _goal, checked: checked)

    def review_verdict(*_a):
        clocks.note("review_observed", True)
        until = time.monotonic() + 0.05
        while (remaining := until - time.monotonic()) > 0:
            time.sleep(remaining)
        return "SAFE"

    monkeypatch.setattr(precard.review, "review_verdict", review_verdict)
    monkeypatch.setattr(precard.review, "apply_verdict", lambda _eid, checked, _verdict: checked)


def _passing_check(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(precard, "check_for_hand_in", lambda _eid: precard.Checked(precard.PASSED, "checked"))


def test_a_real_hand_in_records_all_stages_separately_from_its_manifest(
    repository_world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = repository_world
    monkeypatch.delenv(precard.CHECK_ENV, raising=False)
    monkeypatch.delenv(pool.PARALLEL_ENV, raising=False)
    _passing_review(monkeypatch)
    cid = _ready(world)
    submission = thomas_project.settle_if_finished(world.green.work, world.catalog, cid)
    assert submission is not None and submission.name == f"self-{EXECUTION}"
    [record] = _records(world.catalog)
    assert record["conversation_id"] == cid and record["execution_id"] == EXECUTION
    assert record["outcome"] == "handed_in" and record["submission"] == submission.name
    assert record["check_state"] == precard.PASSED and record["reused_held_check"] is False
    assert record["shard_workers"] >= 1 and record["selected_files"] >= 1
    assert record["parallel"] is True, "the pool is on unless it is turned off"
    assert "free_ram_bytes" in record
    stages = record["stages"]
    for name in (
        "size_rule",
        "check_for_hand_in",
        "slot_wait",
        "in_slot",
        "leftovers",
        "copies",
        "apply",
        "check_size_rule",
        "selection",
        "change_run",
        "confirm",
        "ruff",
        "removal",
        "second_look",
        "hand_off",
    ):
        assert name in stages, name
        assert stages[name]["start"] <= stages[name]["end"]
    assert "dev_run" not in stages, "a clean change never runs dev in full"
    assert record["change_shards"]
    assert all(shard["files"] and shard["seconds"] >= 0 for shard in record["change_shards"])
    assert sum(len(shard["files"]) for shard in record["change_shards"]) == record["selected_files"]
    assert record["pool_wait_s"] >= 0 and record["pool_run_s"] > 0
    assert stages["check_for_hand_in"]["start"] <= stages["slot_wait"]["start"]
    assert stages["removal"]["end"] <= stages["check_for_hand_in"]["end"]
    assert record["review_observed"] is True
    assert stages["second_look"]["seconds"] >= 0.05
    assert stages["second_look"]["start"] <= stages["check_for_hand_in"]["end"]
    assert "review_apply" in stages
    assert stages["second_look"]["end"] <= stages["hand_off"]["start"]
    manifest = json.loads((submission / "submission.json").read_text(encoding="utf-8"))
    assert not {"stages", "clocks", "shard_workers", "free_ram_bytes"} & manifest.keys()


def test_failed_check_keeps_findings_and_skips_review_and_hand_off(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    cid = _ready(world)
    findings = "a real regression"
    monkeypatch.setattr(precard, "check_for_hand_in", lambda _eid: precard.Checked(precard.FAILED, "failed", findings))
    with pytest.raises(precard.ChangeFailedCheck) as caught:
        thomas_project.settle_if_finished(world.green.work, world.catalog, cid)
    assert str(caught.value) == findings
    [record] = _records(world.catalog)
    assert record["outcome"] == "ChangeFailedCheck"
    assert "review_apply" not in record["stages"] and "hand_off" not in record["stages"]


@pytest.mark.parametrize("error_type", [precard.ReviewUnavailable, precard.ChangeFailedReview])
def test_review_errors_escape_unchanged_and_are_timed(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, error_type: type[Exception]
) -> None:
    cid = _ready(world)
    _passing_check(monkeypatch)
    error = error_type("second look stopped")

    def fail(*_args: Any) -> None:
        time.sleep(0.2)
        raise error

    monkeypatch.setattr(precard.review, "second_look", fail)
    with pytest.raises(error_type) as caught:
        thomas_project.settle_if_finished(world.green.work, world.catalog, cid)
    assert caught.value is error
    [record] = _records(world.catalog)
    assert record["outcome"] == error_type.__name__
    assert record["stages"]["second_look"]["seconds"] >= 0.15
    assert "hand_off" not in record["stages"]
    assert not (world.tmp / "inbox").exists()


def test_second_look_switched_off_does_not_read_a_review_snapshot(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    cid = _ready(world)
    monkeypatch.setenv(precard.review.REVIEW_ENV, "off")
    _passing_check(monkeypatch)

    def forbidden_snapshot(_green: Any) -> str:
        pytest.fail("a disabled second look requested a review snapshot")

    monkeypatch.setattr(green_checkout, "green_patch", forbidden_snapshot)
    submission = thomas_project.settle_if_finished(world.green.work, world.catalog, cid)
    assert submission is not None
    [record] = _records(world.catalog)
    assert "review_snapshot" not in record["stages"]


def test_checks_switched_off_reuse_the_one_parallel_second_look(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    cid = _ready(world)
    calls: list[str] = []

    def verdict(_eid: str, _request: str, patch: str) -> precard.review.Verdict:
        calls.append(patch)
        return precard.review.Verdict(True, "", "")

    monkeypatch.setattr(precard.review, "review_verdict", verdict)
    submission = thomas_project.settle_if_finished(world.green.work, world.catalog, cid)
    assert submission is not None
    assert len(calls) == 1
    [record] = _records(world.catalog)
    assert "review_apply" in record["stages"]


@pytest.mark.parametrize("changed_patch", ["different checked patch", ""])
def test_checks_switched_off_still_reject_a_different_reviewed_snapshot(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, changed_patch: str
) -> None:
    cid = _ready(world)

    original_check = precard.check_for_hand_in

    def changed_check(eid: str) -> precard.Checked:
        monkeypatch.setattr(green_checkout, "green_patch", lambda _green: changed_patch)
        return original_check(eid)

    monkeypatch.setattr(precard.review, "review_verdict", lambda *_: precard.review.Verdict(True, "", ""))
    monkeypatch.setattr(precard, "check_for_hand_in", changed_check)
    with pytest.raises(precard.ChangeFailedCheck, match="changed while it was being checked"):
        thomas_project.settle_if_finished(world.green.work, world.catalog, cid)
    assert not (world.tmp / "inbox").exists()


@pytest.mark.parametrize("error_type", [OSError, subprocess.SubprocessError])
def test_snapshot_read_trouble_keeps_the_checks_hold_semantics(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, error_type: type[Exception]
) -> None:
    cid = _ready(world)
    checked_calls: list[str] = []

    def fail_snapshot(_green: Any) -> str:
        raise error_type("snapshot read failed")

    def held(eid: str) -> precard.Checked:
        checked_calls.append(eid)
        return precard.Checked(precard.UNAVAILABLE, "could not read the patch", cause="unexpected", costly=True)

    monkeypatch.setattr(green_checkout, "green_patch", fail_snapshot)
    monkeypatch.setattr(precard, "check_for_hand_in", held)
    with pytest.raises(precard.review.CheckUnavailable, match="could not read the patch"):
        thomas_project.settle_if_finished(world.green.work, world.catalog, cid)
    assert checked_calls == [EXECUTION]
    assert not (world.tmp / "inbox").exists()


@pytest.mark.parametrize("state", [precard.FAILED, precard.UNAVAILABLE])
def test_a_failed_check_cancels_and_joins_its_reviewer(world, monkeypatch, state):
    from thomas.server.precard import review_job

    cid = _ready(world)
    started, stopped = threading.Event(), threading.Event()

    def reviewer(*_args):
        started.set()
        try:
            until = time.monotonic() + 2
            while time.monotonic() < until:
                review_job.check_cancelled()
                time.sleep(0.01)
            pytest.fail("the failed check did not cancel its reviewer")
        finally:
            stopped.set()

    def checked(_eid):
        assert started.wait(2)
        return precard.Checked(state, "check stopped", "finding")

    monkeypatch.setattr(precard.review, "review_verdict", reviewer)
    monkeypatch.setattr(precard, "check_for_hand_in", checked)
    error = precard.ChangeFailedCheck if state == precard.FAILED else precard.review.CheckUnavailable
    with pytest.raises(error):
        thomas_project.settle_if_finished(world.green.work, world.catalog, cid)
    assert stopped.is_set()
    assert _records(world.catalog)[0]["stages"]["second_look"]["seconds"] < 1
    assert not (world.tmp / "inbox").exists()


def test_failed_precondition_never_writes_a_line(world: SimpleNamespace) -> None:
    cid = _ready(world)
    from thomas.forge.anvil import forge_code_store

    conversation = forge_code_store.load_conversation(world.green.work, cid)
    conversation["turns"][-1]["ok"] = False
    forge_code_store.write_conversation(world.green.work, conversation)
    assert thomas_project.settle_if_finished(world.green.work, world.catalog, cid) is None
    assert _records(world.catalog) == []


@pytest.mark.parametrize("failed", [False, True])
def test_unwritable_clocks_do_not_change_a_hand_in_or_failure(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, failed: bool
) -> None:
    cid = _ready(world)
    target = clocks.clocks_path(world.catalog)
    target.mkdir(parents=True)
    _passing_review(monkeypatch)
    if failed:
        monkeypatch.setattr(
            precard, "check_for_hand_in", lambda _eid: precard.Checked(precard.FAILED, "bad", "finding")
        )
        with pytest.raises(precard.ChangeFailedCheck, match="finding"):
            thomas_project.settle_if_finished(world.green.work, world.catalog, cid)
        assert not (world.tmp / "inbox").exists()
    else:
        _passing_check(monkeypatch)
        submission = thomas_project.settle_if_finished(world.green.work, world.catalog, cid)
        assert submission is not None and submission.name == f"self-{EXECUTION}"


def test_the_slot_wait_includes_time_queued_for_another_check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(precard.CHECK_ENV, raising=False)
    monkeypatch.setenv(check.pool.PARALLEL_ENV, "off")  # it holds the one-at-a-time lock
    held = threading.Event()

    def occupy() -> None:
        with slot.one_at_a_time():
            held.set()
            time.sleep(0.5)

    thread = threading.Thread(target=occupy)
    thread.start()
    try:
        assert held.wait(2)
        monkeypatch.setattr(check, "_decide", lambda _eid, _files, *_on: precard.Checked(precard.PASSED, "checked"))
        with clocks.recording(tmp_path, "conversation") as record:
            clocks.note("execution_id", "example")
            assert check.check_before_card("example").state == precard.PASSED
        assert record["stages"]["slot_wait"]["seconds"] >= 0.3
        assert record["check_state"] == precard.PASSED
    finally:
        thread.join(timeout=2)


def test_snapshot_fault_cancels_reviewer_before_executor_join(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from thomas.server import thomas_project_settle as settle
    from thomas.server.precard import review_job

    cid = _ready(world)
    started, cancelled = threading.Event(), threading.Event()

    def review(*_args: Any, **_kwargs: Any) -> str:
        event = review_job._cancel.get()
        assert event is not None
        started.set()
        if event.wait(10):
            cancelled.set()
        return "OK"

    def checked(_execution_id: str) -> precard.Checked:
        assert started.wait(1)
        return precard.Checked(precard.PASSED, "passed", dev_tip="dev", patch="different", patch_sha256="moved")

    def broken_snapshot(*_args: Any) -> None:
        raise RuntimeError("snapshot validation failed")

    monkeypatch.setattr(precard.review, "review_verdict", review)
    monkeypatch.setattr(precard, "check_for_hand_in", checked)
    monkeypatch.setattr(settle.precard, "moved", broken_snapshot)
    with pytest.raises(RuntimeError, match="snapshot validation failed"):
        thomas_project.settle_if_finished(world.green.work, world.catalog, cid)
    assert cancelled.is_set(), "reviewer must stop before executor joins it"


def test_steps_keep_the_answer_and_note_the_existing_memory_reading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(check.scratch, "apply_change", lambda *_: "")
    monkeypatch.setattr(check.green_handoff, "size_problems", lambda *_: [])
    monkeypatch.setattr(check.proofs, "select", lambda *_a, **_k: Selection(("tests/test_ok.py",), ()))
    monkeypatch.setattr(check.proofs, "run_tests", lambda *_args, **_kwargs: ProofRun(True, "", (), 1, 1))
    monkeypatch.setattr(check.proofs, "confirm", lambda *_args, **_kwargs: Verdict((), (), (), (), ()))
    monkeypatch.setattr(check.lint, "ruff_findings", lambda *_args, **_kwargs: LintResult(True, "", (), ()))
    monkeypatch.setattr(check.machine_capacity, "_memory", lambda: (32 * 1024**3, 20 * 1024**3))
    args = (
        SimpleNamespace(execution_id="example"),
        "abc123",
        "patch",
        ["pkg/adder.py"],
        sys.executable,
        SimpleNamespace(work=tmp_path / "base"),
        SimpleNamespace(work=tmp_path / "change"),
        tmp_path / "data",
        check.proofs.Deadline(10),
    )
    outside = check._steps(*args)
    with clocks.recording(tmp_path, "conversation") as record:
        clocks.note("execution_id", "example")
        inside = check._steps(*args)
    assert inside == outside
    assert record["free_ram_bytes"] == 20 * 1024**3
    assert record["total_ram_bytes"] == 32 * 1024**3
    assert record["shard_workers"] == check._width()
    assert len(_records(tmp_path)) == 1


def test_rotation_keeps_the_newest_line(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clocks, "CLOCKS_MAX_BYTES", 450)
    path = clocks.clocks_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    old_records = [{"conversation_id": f"conversation-{index}", "padding": "x" * 80} for index in range(6)]
    path.write_text("".join(json.dumps(record) + "\n" for record in old_records), encoding="utf-8")
    assert path.stat().st_size > 450
    with clocks.recording(tmp_path, "conversation-newest"):
        clocks.note("execution_id", "run-newest")
    assert path.stat().st_size < 900
    records = _records(tmp_path)
    assert records[-1]["conversation_id"] == "conversation-newest"
    assert len(records) == (len(old_records) + 1) // 2
    assert records[:-1] == old_records[-len(records) + 1 :]
