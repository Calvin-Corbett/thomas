"""Starting a self-fix no longer sweeps away a green a project is in, or one kept for your verdict.

``chat_delegation_build_session.prepare_workspace`` sweeps greens as a self-fix starts. On dev 6c8719bd it called
``green_checkout.sweep()`` with no ``skip``, so every green past its age went with the strays the sweep is for: one a
Build run was still working in, and one kept for your verdict (``green_handoff.held``). Now it spares the greens
``chat_self_project._greens_in_use`` reads from the server, and ``green_handoff.held()``, as the hourly sweep does.
A green the sweep cannot save first is kept, says why, and does not stop the sweep; a green another caller is
removing is left to it (thomas/server/keeper_guard.py).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from tests.green_support import make_blue
from thomas.server import green_checkout, green_handoff
from thomas.server.chat_delegation_build_session import prepare_workspace, prepare_workspace_async
from thomas.server.routes.evolve_agent_run_state import APP_EVOLVE_AGENT_RUNS

DAY = 24 * 3600.0


@pytest.fixture
def blue(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv(green_checkout.GREEN_ROOT_ENV, str(tmp_path / "green-root"))
    return make_blue(tmp_path)


def _green_made_days_ago(blue: Path, execution_id: str, days: float) -> green_checkout.Green:
    green = green_checkout.create_green(blue, execution_id)
    record = green.git_dir / green_checkout.METADATA_NAME
    meta = json.loads(record.read_text(encoding="utf-8"))
    record.write_text(json.dumps({**meta, "created_at": time.time() - days * DAY}), encoding="utf-8")
    return green


def _held_for_your_verdict(blue: Path, execution_id: str) -> None:
    """A Thomas project's green, handed in eight days after it was made and now waiting for your verdict: past even
    a kept green's 7 days by its age, and spared only because green_handoff.held() counts from the hand-in."""
    green = _green_made_days_ago(blue, execution_id, days=8)
    green_handoff.await_verdict(execution_id)
    green_handoff._hold(green, green_handoff._state(green), f"self-{execution_id}")
    assert execution_id in green_handoff.held()


def _plan(blue: Path, tmp_path: Path) -> dict[str, Any]:
    return {
        "specialist_id": "coding",
        "targets_live_repo": True,
        "title": "Fix the thing",
        "repo_root": blue,
        "execution_id": "exec-new",
        "task_workspace": lambda eid: tmp_path / "workspaces" / eid,
        "catalog_root": tmp_path / "catalog",
    }


def _there(execution_id: str) -> bool:
    return green_checkout.find_green(execution_id) is not None


def test_a_green_kept_for_your_verdict_survives_a_self_fix_starting(blue: Path, tmp_path: Path) -> None:
    _held_for_your_verdict(blue, "thomas-held")
    _green_made_days_ago(blue, "exec-old", days=2)

    plan = prepare_workspace(**_plan(blue, tmp_path))

    assert plan.work_dir == green_checkout.find_green("exec-new").work
    assert _there("thomas-held"), "a green kept for your verdict was swept"
    assert not _there("exec-old"), "the sweep still takes a stray past its 24 hours"


def test_a_green_a_build_run_is_in_survives_a_self_fix_starting(blue: Path, tmp_path: Path) -> None:
    in_use = _green_made_days_ago(blue, "thomas-in-use", days=2)
    _held_for_your_verdict(blue, "thomas-held")
    _green_made_days_ago(blue, "exec-old", days=2)
    run = {"session": {"proc": SimpleNamespace(returncode=None), "project_root": str(in_use.work)}}

    asyncio.run(prepare_workspace_async(app={APP_EVOLVE_AGENT_RUNS: {"conv-1": run}}, **_plan(blue, tmp_path)))

    assert _there("thomas-in-use"), "a green a Build run is working in was swept"
    assert _there("thomas-held") and _there("exec-new")
    assert not _there("exec-old")


def test_chat_dispatch_hands_its_server_to_the_self_fix_workspace(tmp_path: Path) -> None:
    """Without the app the sweep cannot see which greens Build runs are in: the real dispatch must pass it."""
    import thomas.server.chat_delegation_build_session as build_session
    from thomas.core.file_access import PROJECT
    from thomas.server import chat_delegation as cd

    seen: dict[str, Any] = {}

    class Stop(Exception):
        pass

    async def prepare(**kwargs: Any) -> None:
        seen.update(kwargs)
        raise Stop

    class Emitter:
        async def started(self, *args: Any, **kwargs: Any) -> None:
            return None

    app = {"server": "this one"}
    runtime = cd.task_bot_runtime
    with (
        patch.object(runtime, "create_execution", lambda **k: {"execution_id": "exec-probe"}),
        patch.object(runtime, "update_execution", lambda *a, **k: None),
        patch.object(runtime, "get_execution", lambda *a, **k: {"execution_id": "exec-probe"}),
        patch.object(runtime, "fail_execution", lambda *a, **k: None),
        patch.object(build_session, "prepare_workspace_async", prepare),
        pytest.raises(Stop),
    ):
        asyncio.run(
            cd._start_agent_worker_delegation(
                app,
                session_id="s",
                prompt="Fix the value in thomas/fix_me.py.",
                specialist_id="coding",
                bot=SimpleNamespace(name="Byte", id="byte"),
                emitter=Emitter(),
                repo_root=tmp_path,
                autonomy_level=5,
                file_access=PROJECT,
                workspace="project",
            )
        )

    assert seen.get("app") is app and seen.get("targets_live_repo") is True


def _settled(blue: Path, execution_id: str) -> green_checkout.Green:
    green = green_checkout.create_green(blue, execution_id)
    (green.work / "thomas" / "fix_me.py").write_bytes(b"VALUE = 2\n")
    green_checkout.mark_settled(green)
    return green


def test_the_sweep_keeps_a_green_it_cannot_save_says_why_and_takes_it_once_it_can(
    blue: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    green = _settled(blue, "exec-swept")
    fallback = tmp_path / "captures"  # beside the green root; the drop this test run has holds no captures folder
    fallback.write_text("not a folder", encoding="utf-8")

    assert green_checkout.sweep() == [] and green.work.is_dir()
    failed = json.loads((green.git_dir / "capture-failed.json").read_bytes())
    assert failed["error"] == "OSError" and "no capture folder took it" in failed["message"]

    fallback.unlink()
    assert green_checkout.sweep() == ["exec-swept"] and not green.work.exists()
    assert len(list(fallback.glob("exec-swept-*.json"))) == 1


def test_the_sweep_goes_on_past_a_green_whose_capture_breaks_unexpectedly(
    blue: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from thomas.server import keeper_guard_capture

    broken, fine = _settled(blue, "exec-broken"), _settled(blue, "exec-fine")
    real = keeper_guard_capture.changes

    def changes(green: green_checkout.Green) -> Any:
        if green.execution_id == "exec-broken":
            raise RuntimeError("something nobody planned for")
        return real(green)

    monkeypatch.setattr(keeper_guard_capture, "changes", changes)

    assert green_checkout.sweep() == ["exec-fine"]
    assert broken.work.is_dir() and not fine.work.exists()
    assert json.loads((broken.git_dir / "capture-failed.json").read_bytes())["error"] == "RuntimeError"


def test_a_green_another_caller_is_removing_is_kept_until_its_lock_is_old_and_its_process_gone(
    blue: Path, tmp_path: Path
) -> None:
    from thomas.server import keeper_guard

    green = _settled(blue, "exec-locked")
    lock = green.git_dir / keeper_guard.LOCK_NAME
    old = time.time() - keeper_guard.LOCK_STALE_S - 60
    ended = subprocess.run([sys.executable, "-c", "import os; print(os.getpid())"], capture_output=True, text=True)
    for pid, age in ((os.getpid(), None), (os.getpid(), old)):  # held now; old, but its process still runs
        lock.write_text(json.dumps({"pid": pid}), encoding="utf-8")
        if age:
            os.utime(lock, (age, age))
        with pytest.raises(keeper_guard.GreenKept, match="another caller"):
            green_checkout.remove_green(green)
    assert green.work.is_dir() and not (tmp_path / "captures").exists(), "kept, and nothing saved twice"

    lock.write_text(json.dumps({"pid": int(ended.stdout)}), encoding="utf-8")  # old, and its process has ended
    os.utime(lock, (old, old))
    green_checkout.remove_green(green)
    assert not green.work.exists() and len(list((tmp_path / "captures").glob("exec-locked-*.json"))) == 1


def test_a_full_disk_is_seen_past_a_flood_of_line_ending_warnings(blue: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from thomas.server import keeper_guard_capture as capture

    green = green_checkout.create_green(blue, "exec-flood")
    warning = b"warning: in the working copy of 'thomas/x.py', LF will be replaced by CRLF the next time Git touches\n"
    said = warning * 5 + b"error: unable to write new index file: No space left on device\nfatal: adding files failed\n"
    assert said.index(b"No space left on device") > 300
    monkeypatch.setattr(capture.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 128, b"", said))
    with pytest.raises(OSError) as raised:
        capture.git(green, ("update-index", "--add", "-z", "--stdin"))
    assert capture.disk_full(raised.value), "a full disk frees the reserve and tries again; anything else keeps it"


def test_a_drop_it_cannot_reach_sends_the_capture_beside_the_green_root(
    blue: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from thomas.server import keeper_guard

    drop = tmp_path / "drop" / "captures"
    drop.mkdir(parents=True)
    monkeypatch.setenv(keeper_guard.DROP_ENV, str(drop.parent))
    green = _settled(blue, "exec-fallback")
    is_dir = Path.is_dir

    def unlisted(path: Path) -> bool:  # thomas-agent may not list the drop itself
        if path == drop:
            raise PermissionError(13, "Access is denied", str(path))
        return is_dir(path)

    monkeypatch.setattr(Path, "is_dir", unlisted)
    with caplog.at_level(logging.WARNING):
        green_checkout.remove_green(green)
    assert len(list((tmp_path / "captures").glob("exec-fallback-*.json"))) == 1
    assert os.listdir(drop) == [] and "cannot be reached" in caplog.text
    monkeypatch.delenv("PYTEST_CURRENT_TEST")
    assert keeper_guard.drop_folder() == keeper_guard.KEEPER_DROP, "only a test may move the drop"


def test_a_green_create_green_could_not_finish_is_removed_with_nothing_to_save(
    blue: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Guard (passes on dev too): create_green's own clean-up still removes a half-made green and raises
    GreenUnavailable. It wrote no record, so no run was ever given it, and there is nothing to save."""
    real = green_checkout._git

    def refuse_checkout(green: green_checkout.Green, *args: str) -> subprocess.CompletedProcess[str]:
        if args[:1] == ("checkout",):
            return subprocess.CompletedProcess(list(args), 1, "", "refused for the test")
        return real(green, *args)

    monkeypatch.setattr(green_checkout, "_git", refuse_checkout)
    with pytest.raises(green_checkout.GreenUnavailable, match="refused for the test"):
        green_checkout.create_green(blue, "exec-half")
    root = tmp_path / "green-root"
    assert not (root / "work" / "exec-half").exists() and not (root / "git" / "exec-half").exists()
    assert not (tmp_path / "captures").exists()
