"""When a self-fix run ends, its change heads for your approval -- and only then.

A self-fix is made in green (tests/test_self_development_works_in_green.py).
These pin the end of the run: completion is measured in green, where the work
happened; a finished run leaves exactly one submission in the commit-master's
inbox and no green behind; a failed run submits nothing and keeps its report;
and a submission that cannot be written never costs you the work.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

from tests.green_support import make_blue
from thomas.server import green_checkout


@pytest.fixture
def blue(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv(green_checkout.GREEN_ROOT_ENV, str(tmp_path / "green-root"))
    return make_blue(tmp_path)


def _finish(blue: Path, green: green_checkout.Green, baseline: dict, *, measure_green: bool):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, patch

    from thomas.server.chat_delegation_runner import _finalize_live_repo_completion

    emitter = SimpleNamespace(completed=AsyncMock(), failed=AsyncMock())
    runtime = "thomas.server.chat_delegation_runner.task_bot_runtime"
    with (
        patch(f"{runtime}.attach_proof"),
        patch(f"{runtime}.complete_execution"),
        patch(f"{runtime}.get_execution", return_value={"execution_id": green.execution_id, "state": "completed"}),
    ):
        asyncio.run(
            _finalize_live_repo_completion(
                emitter,
                green.execution_id,
                blue,
                "Fix the value.",
                baseline,
                ["Changed VALUE and ran the tests."],
                ["fs.write_file"],
                ["fs.write_file"],
                [],
                SimpleNamespace(name="Nova"),
                "coding",
                **({"work_dir": green.work} if measure_green else {}),
            )
        )
    return emitter


def test_completion_is_measured_in_green(blue: Path) -> None:
    from thomas.server.chat_delegation_live_repo import _live_repo_workspace_mtimes

    green = green_checkout.create_green(blue, "exec-done")
    baseline = _live_repo_workspace_mtimes(green.work)
    (green.work / "thomas" / "fix_me.py").write_text("VALUE = 2\n", encoding="utf-8")

    emitter = _finish(blue, green, baseline, measure_green=True)

    emitter.completed.assert_awaited_once()
    text = emitter.completed.await_args.kwargs["text"]
    assert "thomas/fix_me.py" in text
    assert "approve" in text, "the reply must say the change is waiting for you, not that it is live"


def test_a_later_attempt_still_sees_what_an_earlier_one_changed(blue: Path) -> None:
    """Measured live 2026-09-22 (exec-8ef69b69fb68): attempt 1 made the change,
    hit a snag, and attempt 2 re-measured its baseline from green -- which already
    held the change -- so "changed since this attempt began" read as nothing, and
    a correct fix was headed for the bin. In green, changed means changed from the
    commit green started at."""
    from thomas.server.chat_delegation_live_repo import _live_repo_files_changed_since, _live_repo_workspace_mtimes

    green = green_checkout.create_green(blue, "exec-retry")
    (green.work / "thomas" / "fix_me.py").write_text("VALUE = 2\n", encoding="utf-8")
    second_attempt_baseline = _live_repo_workspace_mtimes(green.work)

    assert _live_repo_files_changed_since(green.work, second_attempt_baseline) == ["thomas/fix_me.py"]


def test_a_green_that_cannot_be_removed_yet_is_swept_as_soon_as_it_can(blue: Path) -> None:
    """Something still holding green (a process, an open file) made the removal
    fail and left green for the 24-hour sweep. A settled green is now swept on the
    next pass, whatever its age."""
    from thomas.server import green_handoff

    green = green_checkout.create_green(blue, "exec-held")
    held = (green.work / "held.txt").open("w", encoding="utf-8")
    try:
        green_handoff.settle("exec-held", promote=False)
        assert green.work.exists(), "the ruler: an open file stops the removal"
    finally:
        held.close()

    assert green_checkout.sweep() == ["exec-held"]
    assert not green.work.exists() and not green.git_dir.exists()


def test_measuring_blue_would_miss_a_change_made_in_green(blue: Path) -> None:
    """The ruler for the test above: the old measurement, pointed at blue, sees
    nothing -- which is why the runner has to be told where the work happened."""
    from thomas.server.chat_delegation_deliverable import _WorkerRetry
    from thomas.server.chat_delegation_live_repo import _live_repo_workspace_mtimes

    green = green_checkout.create_green(blue, "exec-missed")
    baseline = _live_repo_workspace_mtimes(blue)
    (green.work / "thomas" / "fix_me.py").write_text("VALUE = 2\n", encoding="utf-8")

    with pytest.raises(_WorkerRetry, match="changed no"):
        _finish(blue, green, baseline, measure_green=False)


def _submissions() -> list[Path]:
    from thomas.server import green_handoff

    inbox = green_handoff.inbox_dir()
    return sorted(p for p in inbox.iterdir() if p.is_dir()) if inbox.is_dir() else []


def test_a_finished_self_fix_becomes_one_submission_and_green_is_gone(blue: Path) -> None:
    import json

    from thomas.server import green_handoff

    green = green_checkout.create_green(blue, "exec-ship")
    (green.work / "thomas" / "fix_me.py").write_text("VALUE = 2\n", encoding="utf-8")
    (green.work / "thomas" / "new_module.py").write_text("NEW = True\n", encoding="utf-8")

    sub = green_handoff.settle("exec-ship", promote=True, summary="Fixed VALUE.", chat="chat-9")

    assert _submissions() == [sub]
    manifest = json.loads((sub / "submission.json").read_text(encoding="utf-8"))
    assert manifest["kind"] == "self_change"
    assert manifest["base"] == green.base
    assert manifest["execution_id"] == "exec-ship"
    assert manifest["chat"] == "chat-9"
    assert manifest["summary"] == "Fixed VALUE."
    assert sorted(manifest["files"]) == ["thomas/fix_me.py", "thomas/new_module.py"]
    patch_bytes = (sub / manifest["patch"]).read_bytes()
    assert b"\r\r\n" not in patch_bytes, "a patch passed through text mode on Windows gains CRs and stops applying"
    assert manifest["patch_sha256"] == hashlib.sha256(patch_bytes).hexdigest()
    check = subprocess.run(["git", "apply", "--check", "-"], cwd=blue, input=patch_bytes, capture_output=True)
    assert check.returncode == 0, check.stderr
    assert green_checkout.find_green("exec-ship") is None
    assert not green.work.exists()


def test_a_failed_self_fix_submits_nothing_and_keeps_its_report(blue: Path) -> None:
    from thomas.server import green_handoff

    green = green_checkout.create_green(blue, "exec-blocked")
    (green.work / "thomas" / "fix_me.py").write_text("VALUE = 99\n", encoding="utf-8")
    report_dir = green.work / "runtime" / "self_development" / "exec-blocked"
    report_dir.mkdir(parents=True)
    (report_dir / "SELF_DEVELOPMENT_REPORT.md").write_text("Blocked by X.\n", encoding="utf-8")

    assert green_handoff.settle("exec-blocked", promote=False) is None

    assert _submissions() == []
    kept = blue / "runtime" / "self_development" / "exec-blocked" / "SELF_DEVELOPMENT_REPORT.md"
    assert kept.read_text(encoding="utf-8") == "Blocked by X.\n"
    assert not green.work.exists()


def test_an_unchanged_green_submits_nothing(blue: Path) -> None:
    from thomas.server import green_handoff

    green_checkout.create_green(blue, "exec-noop")

    assert green_handoff.settle("exec-noop", promote=True, summary="Nothing.") is None
    assert _submissions() == []
    assert green_checkout.find_green("exec-noop") is None


def test_a_submission_that_cannot_be_written_keeps_the_work(blue: Path) -> None:
    """Losing a finished fix because the inbox was unwritable would be silent
    data loss. Green stays, for the next attempt or for you to look at."""
    from thomas.server import green_handoff

    green = green_checkout.create_green(blue, "exec-stuck")
    (green.work / "thomas" / "fix_me.py").write_text("VALUE = 7\n", encoding="utf-8")
    inbox = green_handoff.inbox_dir()
    inbox.parent.mkdir(parents=True, exist_ok=True)
    inbox.write_text("not a folder", encoding="utf-8")

    assert green_handoff.settle("exec-stuck", promote=True, summary="Fixed.") is None

    assert green.work.exists()


def test_settling_a_run_with_no_green_does_nothing(blue: Path) -> None:
    from thomas.server import green_handoff

    assert green_handoff.settle("exec-ordinary-deliverable", promote=True) is None
    assert green_handoff.settle("../../etc", promote=True) is None


def test_the_emitter_settles_green_when_a_run_ends() -> None:
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, patch

    from thomas.server.chat_delegation_emitter import _DelegationEmitter

    emitter = _DelegationEmitter(AsyncMock(), notifier=lambda *a, **k: None)
    bot = SimpleNamespace(to_event_dict=lambda: {})
    record = {"execution_id": "exec-e", "session_id": "chat-e", "summary": "Fix."}
    with patch("thomas.server.green_handoff.settle", return_value=None) as settle:
        asyncio.run(emitter.completed(record, specialist_id="coding", bot=bot, text="Fixed it."))
        # An emitter passes on one ending per execution, so the failed run is announced by its own.
        failed_run = _DelegationEmitter(AsyncMock(), notifier=lambda *a, **k: None)
        asyncio.run(failed_run.failed(record, specialist_id="coding", bot=bot, text="Could not."))

    assert [c.kwargs["promote"] for c in settle.call_args_list] == [True, False]
    assert {c.args[0] for c in settle.call_args_list} == {"exec-e"}
    assert settle.call_args_list[0].kwargs["summary"] == "Fixed it."
    assert settle.call_args_list[0].kwargs["chat"] == "chat-e"


def test_a_submission_is_followed_in_the_chat_that_asked() -> None:
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, patch

    from thomas.server.chat_delegation_emitter import _DelegationEmitter

    emitter = _DelegationEmitter(AsyncMock(), notifier=lambda *a, **k: None)
    bot = SimpleNamespace(to_event_dict=lambda: {})
    record = {"execution_id": "exec-f", "session_id": "chat-f", "summary": "Fix."}
    with (
        patch("thomas.server.green_handoff.settle", return_value=Path("inbox") / "self-exec-f"),
        patch("thomas.server.self_change_status.follow", new=AsyncMock(return_value="landed")) as follow,
    ):
        asyncio.run(emitter.completed(record, specialist_id="coding", bot=bot, text="Fixed it."))

    follow.assert_called_once_with("self-exec-f", "chat-f", checked="")  # no green here, so nothing was checked


def test_nothing_is_followed_when_nothing_was_submitted() -> None:
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, patch

    from thomas.server.chat_delegation_emitter import _DelegationEmitter

    emitter = _DelegationEmitter(AsyncMock(), notifier=lambda *a, **k: None)
    bot = SimpleNamespace(to_event_dict=lambda: {})
    with (
        patch("thomas.server.green_handoff.settle", return_value=None),
        patch("thomas.server.self_change_status.follow", new=AsyncMock()) as follow,
    ):
        asyncio.run(emitter.failed({"execution_id": "exec-g"}, specialist_id="coding", bot=bot, text="No."))

    follow.assert_not_called()
