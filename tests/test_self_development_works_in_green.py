"""A self-fix works in green, a private clone, and never in the running checkout.

Your direction, 2026-09-22: "I thought I made a blue-green system just for this,
so he would edit the other version that's not running". The Doppelganger did
that until 2026-06-22; chat self-development, merged six days later, edited the
live checkout directly and never called it. These tests pin the replacement:
green is a real git clone of what is committed, the running copy ("blue") is
byte-identical after green is edited, and green's diff is exactly the change.
"""

from __future__ import annotations

import asyncio
import hashlib
import subprocess
import time
from pathlib import Path

import pytest

from tests.green_support import git as _git
from tests.green_support import make_blue
from thomas.server import green_checkout
from thomas.server.green_checkout import GreenUnavailable


@pytest.fixture
def blue(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv(green_checkout.GREEN_ROOT_ENV, str(tmp_path / "green-root"))
    return make_blue(tmp_path)


def _fingerprint(root: Path) -> str:
    h = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        h.update(path.relative_to(root).as_posix().encode())
        h.update(path.read_bytes())
    return h.hexdigest()


def test_green_is_what_blue_has_committed(blue: Path) -> None:
    (blue / "README.md").write_text("an uncommitted edit in the running copy\n", encoding="utf-8")

    green = green_checkout.create_green(blue, "exec-1")

    assert green.base == _git(blue, "rev-parse", "HEAD")
    assert (green.work / "thomas" / "fix_me.py").read_text(encoding="utf-8") == "VALUE = 1\n"
    assert (green.work / "README.md").read_text(encoding="utf-8") == "blue\n"
    assert green.work.resolve().is_relative_to(green_checkout.green_root().resolve())
    assert not green.work.resolve().is_relative_to(blue.resolve())


@pytest.mark.asyncio
async def test_shared_objects_and_request_to_first_edit(blue: Path) -> None:
    green = green_checkout.create_green(blue, "exec-timed")
    alternates = (green.git_dir / "objects" / "info" / "alternates").read_text(encoding="utf-8").strip()
    assert Path(alternates).resolve() == (blue / ".git" / "objects").resolve()
    assert not (green.work / ".venv").exists()

    started = time.time() - 0.1
    green_checkout.record_request_start(green, started)
    watch = asyncio.create_task(green_checkout.watch_first_edit(green, interval=0.01, timeout=2))
    (green.work / "plans").mkdir()
    (green.work / "plans" / "PLAN.md").write_text("board setup", encoding="utf-8")
    await asyncio.sleep(0.05)
    assert not watch.done()
    (green.work / "thomas" / "fix_me.py").write_text("VALUE = 2\n", encoding="utf-8")
    latency = await watch
    assert latency is not None and latency >= 0.1
    assert green_checkout.first_edit_latency(green) == latency
    green_checkout.remove_green(green)


def test_first_edit_timing_requires_request_clock(blue: Path) -> None:
    green = green_checkout.create_green(blue, "exec-no-clock")
    (green.work / "thomas" / "fix_me.py").write_text("VALUE = 2\n", encoding="utf-8")
    assert green_checkout.first_edit_latency(green) is None


def test_editing_green_leaves_blue_byte_identical(blue: Path) -> None:
    before = _fingerprint(blue)
    green = green_checkout.create_green(blue, "exec-2")

    (green.work / "thomas" / "fix_me.py").write_text("VALUE = 2\n", encoding="utf-8")
    (green.work / "thomas" / "new_module.py").write_text("NEW = True\n", encoding="utf-8")

    assert _fingerprint(blue) == before


def test_the_patch_is_the_change_and_applies_to_blue(blue: Path) -> None:
    green = green_checkout.create_green(blue, "exec-3")
    (green.work / "thomas" / "fix_me.py").write_text("VALUE = 2\n", encoding="utf-8")
    (green.work / "thomas" / "new_module.py").write_text("NEW = True\n", encoding="utf-8")

    patch = green_checkout.green_patch(green)

    assert "+VALUE = 2" in patch
    assert "+NEW = True" in patch
    assert sorted(green_checkout.changed_paths(green)) == ["thomas/fix_me.py", "thomas/new_module.py"]
    raw = patch.encode("utf-8", errors="surrogateescape")  # bytes: a text-mode stdin would add CRs
    check = subprocess.run(["git", "apply", "--check", "-"], cwd=blue, input=raw, capture_output=True)
    assert check.returncode == 0, check.stderr


def test_a_crlf_file_patch_is_byte_exact_and_still_applies(blue: Path) -> None:
    """Read in text mode, the patch lost the CR of every CRLF line and stopped
    applying to the file it came from (found 2026-09-22). Thomas's own repo has
    CRLF files, so a self-fix touching one would have been refused."""
    (blue / "crlf.txt").write_bytes(b"A = 1\r\nB = 2\r\n")
    _git(blue, "add", "crlf.txt")
    _git(blue, "commit", "-qm", "a crlf file")
    green = green_checkout.create_green(blue, "exec-crlf")
    (green.work / "crlf.txt").write_bytes(b"A = 1\r\nB = 3\r\n")

    patch = green_checkout.green_patch(green).encode("utf-8", errors="surrogateescape")

    assert b"-B = 2\r\n" in patch
    applied = subprocess.run(
        ["git", "-c", "core.autocrlf=false", "apply", "--check", "-"], cwd=blue, input=patch, capture_output=True
    )
    assert applied.returncode == 0, applied.stderr


def test_the_server_never_follows_greens_own_git_pointer(blue: Path) -> None:
    """Green's ``.git`` is a file the agent can rewrite. The server's git calls
    name the real git folder themselves, so a rewritten pointer changes nothing."""
    green = green_checkout.create_green(blue, "exec-4")
    (green.work / "thomas" / "fix_me.py").write_text("VALUE = 3\n", encoding="utf-8")
    # Git marks the pointer hidden, and Windows will not overwrite a hidden file
    # in place -- but anything that can write green can delete and recreate it.
    (green.work / ".git").unlink()
    (green.work / ".git").write_text(f"gitdir: {green.work.parent / 'nowhere'}\n", encoding="utf-8")

    patch = green_checkout.green_patch(green)

    assert "+VALUE = 3" in patch
    assert ".git" not in green_checkout.changed_paths(green)


def test_a_folder_that_is_not_a_repo_is_refused_without_a_fallback(tmp_path: Path, blue: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()

    with pytest.raises(GreenUnavailable) as caught:
        green_checkout.create_green(plain, "exec-5")

    # Dispatch falls back to a path that edits blue on these four; a refusal
    # to make green must not be one of them.
    assert not isinstance(caught.value, (RuntimeError, OSError, ValueError, TypeError))


@pytest.mark.parametrize("bad", ["../escape", "a/b", "a\\b", "", "x" * 200])
def test_an_execution_id_cannot_steer_where_green_goes(blue: Path, bad: str) -> None:
    with pytest.raises(GreenUnavailable):
        green_checkout.create_green(blue, bad)


def test_find_green_reads_what_create_recorded(blue: Path) -> None:
    made = green_checkout.create_green(blue, "exec-6")

    found = green_checkout.find_green("exec-6")

    assert found == made
    assert green_checkout.find_green("exec-never-made") is None


def test_removing_green_after_watch_loop_closes(blue: Path) -> None:
    import asyncio
    from unittest.mock import Mock

    green = green_checkout.create_green(blue, "exec-closed-watch")
    loop = asyncio.new_event_loop()
    loop.close()
    green_checkout._EDIT_WATCHES[green.execution_id] = Mock(get_loop=lambda: loop)

    green_checkout.remove_green(green)
    assert not green.work.exists()
    assert not green.git_dir.exists()


def test_removing_green_leaves_nothing(blue: Path) -> None:
    green = green_checkout.create_green(blue, "exec-7")
    (green.work / "scratch.txt").write_text("x", encoding="utf-8")

    green_checkout.remove_green(green)

    assert not green.work.exists()
    assert not green.git_dir.exists()
    assert green_checkout.find_green("exec-7") is None


def _prepare(repo: Path, tmp_path: Path, execution_id: str):
    from thomas.server.chat_delegation_build_session import prepare_workspace

    return prepare_workspace(
        specialist_id="coding",
        targets_live_repo=True,
        title="Fix the thing",
        repo_root=repo,
        execution_id=execution_id,
        task_workspace=lambda eid: tmp_path / "workspaces" / eid,
        catalog_root=tmp_path / "catalog",
    )


def test_a_self_development_task_runs_in_green_not_blue(blue: Path, tmp_path: Path) -> None:
    plan = _prepare(blue, tmp_path, "exec-plan")

    assert plan.refusal == ""
    assert Path(plan.work_dir).resolve() == green_checkout.find_green("exec-plan").work.resolve()
    assert not Path(plan.work_dir).resolve().is_relative_to(blue.resolve())


def test_no_green_means_a_refusal_never_the_running_copy(tmp_path: Path, blue: Path) -> None:
    plain = tmp_path / "not-a-repo"
    plain.mkdir()

    plan = _prepare(plain, tmp_path, "exec-refused")

    assert "private copy" in plan.refusal
    assert Path(plan.work_dir).resolve() != plain.resolve()


def test_a_run_in_green_cannot_write_the_running_copy_by_absolute_path(blue: Path) -> None:
    """Measured live 2026-09-22 (exec-55701f48c328): at "This project" the file
    ladder's project is the running checkout, so a worker in green could still
    write an unprotected file there by absolute path. In green, green is the
    project: the level is capped at the worker's own space."""
    import asyncio

    from thomas.core.file_access import PROJECT, WORKSPACE
    from thomas.tools.filesystem import WriteFileTool

    green = green_checkout.create_green(blue, "exec-fence")
    target = {"path": str(blue / "README.md"), "content": "written from green\n"}

    assert green_checkout.file_access_for(PROJECT, green.work) == WORKSPACE
    assert green_checkout.file_access_for(PROJECT, blue) == PROJECT
    capped = WriteFileTool(green.work, file_access=WORKSPACE, project_root=blue)
    assert not asyncio.run(capped.execute(dict(target))).ok
    assert (blue / "README.md").read_text(encoding="utf-8") == "blue\n"

    # The ruler: uncapped, the same write lands in the running copy.
    uncapped = WriteFileTool(green.work, file_access=PROJECT, project_root=blue)
    assert asyncio.run(uncapped.execute(dict(target))).ok


def test_the_file_ladder_lets_a_run_write_its_own_green(monkeypatch: pytest.MonkeyPatch) -> None:
    """Measured live 2026-09-22 (exec-55701f48c328): green sat in
    C:\\ProgramData\\ThomasGreen, and the ladder refuses ProgramData at every
    level as an OS system directory -- so every write the self-fix tried was
    BLOCKED. The tests had put green in a temp folder and never saw it. This asks
    the ladder about the real default location."""
    from thomas.core.file_access import WORKSPACE, authorize_write

    monkeypatch.delenv(green_checkout.GREEN_ROOT_ENV, raising=False)
    work = green_checkout.green_root() / "work" / "exec-ladder"
    allowed, reason = authorize_write(
        WORKSPACE, work / "thomas" / "fix_me.py", workspace_root=work, project_root=Path(__file__).parents[1]
    )
    assert allowed, reason


def test_sweep_removes_strays_and_keeps_a_live_run(blue: Path) -> None:
    old = green_checkout.create_green(blue, "exec-old")
    fresh = green_checkout.create_green(blue, "exec-fresh")

    removed = green_checkout.sweep(max_age_s=60.0, now=time.time() + 3600.0)
    assert sorted(removed) == ["exec-fresh", "exec-old"]
    assert not old.work.exists() and not fresh.work.exists()

    kept = green_checkout.create_green(blue, "exec-kept")
    assert green_checkout.sweep(max_age_s=60.0) == []
    assert kept.work.exists()
