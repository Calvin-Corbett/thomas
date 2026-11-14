"""A receipt never names a file it did not save, and a pid Windows handed on does not hold a green (keeper F13).

On dev 144b1954 ``keeper_guard_capture.stage`` gave every changed path to ``git update-index``. Git for Windows skips
a name Windows reserves (aux.py, con.txt, nul.md, com1.py, lpt1.log) or one ``.git``'s short name could take (GIT~1)
with "Ignoring path" and exit code 0, so the receipt listed those files under ``files``, its patch held none of them,
and the green was deleted. Now the capture lists its own index after staging, and a file it was asked to hold but
does not is a failed capture: the green is kept and capture-failed.json names the files.

A name that ends in a space or a dot ("sub /file.py", "trail.") is listed by git, but a normal Windows path drops that
end, so ``sort_out`` found no file and put the name in ``gone``. The base never tracked it, so removing it from the
index changed nothing, the receipt named it, and the green was deleted with it. Now a gone name the base does not
track fails the capture the same way.

A removal lock older than an hour kept its green for as long as its pid was a live process, also once Windows had
given that pid to another process. The lock now records when its process started (``serve_instance_guard``'s
``process_started_at``), and a live pid that started at another time is not the lock's remover. A lock younger than
an hour still keeps its green, whoever holds it.
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.green_support import make_blue
from thomas.server import green_checkout, keeper_guard, serve_instance_guard

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="names only Windows treats this way")
# GIT~1 is in a subfolder: at the top of a work tree it is the short name of the .git file itself.
RESERVED = ("aux.py", "con.txt", "nul.md", "com1.py", "lpt1.log", "thomas/GIT~1")
# Git lists these; a normal Windows path drops the trailing space or dot and finds no such file.
UNREACHABLE = ("sub /file.py", "trail.", "thomas/space.py ")


def _long(path: Path) -> str:
    """A \\\\?\\ path: Windows takes the name as it is, so a file named like a device can be made, read and removed."""
    return "\\\\?\\" + str(path).replace("/", "\\")


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    monkeypatch.setenv(green_checkout.GREEN_ROOT_ENV, str(tmp_path / "green-root"))
    return SimpleNamespace(blue=make_blue(tmp_path), captures=tmp_path / "captures")


@pytest.fixture
def made() -> Iterator[list[str]]:
    """Every file or folder a test makes by its \\\\?\\ path, removed by it afterwards (last made first)."""
    paths: list[str] = []
    yield paths
    for path in reversed(paths):
        try:
            if os.path.isdir(path):
                os.rmdir(path)
            else:
                os.remove(path)
        except FileNotFoundError:
            pass


def _make(made: list[str], green: green_checkout.Green, names: tuple[str, ...]) -> None:
    for rel in names:
        if "/" in rel and not os.path.isdir(_long(green.work / rel.rsplit("/", 1)[0])):
            made.append(_long(green.work / rel.rsplit("/", 1)[0]))
            os.mkdir(made[-1])
        made.append(_long(green.work / rel))
        with open(made[-1], "xb") as stream:
            stream.write(f"WORK = {rel!r}\n".encode())


def _receipts(world: SimpleNamespace) -> list[Path]:
    return sorted(world.captures.glob("*.json")) if world.captures.is_dir() else []


def _kept_and_named(world: SimpleNamespace, green: green_checkout.Green, names: tuple[str, ...]) -> str:
    """Removing the green fails, every file keeps its bytes, no receipt is written, and NotStaged is recorded."""
    with pytest.raises(keeper_guard.GreenKept) as raised:
        green_checkout.remove_green(green)

    assert f"{green.execution_id} is kept" in str(raised.value)
    assert green_checkout.find_green(green.execution_id) is not None, "the green was deleted"
    for rel in names:
        with open(_long(green.work / rel), "rb") as stream:
            assert stream.read() == f"WORK = {rel!r}\n".encode(), f"{rel} was lost"
    assert _receipts(world) == [], "a receipt was written for a capture that left files out"
    failed = json.loads((green.git_dir / keeper_guard.FAILED_NAME).read_bytes())
    assert failed["reason"] == "green kept: capture failed" and failed["error"] == "NotStaged"
    assert all(rel in failed["message"] for rel in names), failed["message"]
    return failed["message"]


@windows_only
@pytest.mark.parametrize("beside_a_change", [True, False], ids=["beside-a-real-change", "alone"])
def test_a_file_git_will_not_stage_keeps_the_green_and_the_failure_names_it(
    world: SimpleNamespace, made: list[str], beside_a_change: bool
) -> None:
    green = green_checkout.create_green(world.blue, "exec-reserved")
    if beside_a_change:
        (green.work / "thomas" / "fix_me.py").write_bytes(b"VALUE = 2\n")
    _make(made, green, RESERVED)
    assert sorted(os.listdir(green.work)) == [".git", "README.md", "aux.py", "com1.py", "con.txt", "lpt1.log",
                                              "nul.md", "thomas"]  # fmt: skip

    assert "Windows reserves" in _kept_and_named(world, green, RESERVED)


@windows_only
@pytest.mark.parametrize("beside_a_change", [True, False], ids=["beside-a-real-change", "alone"])
def test_a_file_a_windows_path_cannot_reach_keeps_the_green_and_the_failure_names_it(
    world: SimpleNamespace, made: list[str], beside_a_change: bool
) -> None:
    green = green_checkout.create_green(world.blue, "exec-unreachable")
    if beside_a_change:
        (green.work / "thomas" / "fix_me.py").write_bytes(b"VALUE = 2\n")
        (green.work / "README.md").unlink()  # a real deletion: the base tracks it, so the check does not name it
    _make(made, green, UNREACHABLE)
    assert {"sub ", "trail."} <= set(os.listdir(_long(green.work))), "the names were not made as they are"
    assert "space.py " in os.listdir(_long(green.work / "thomas"))

    message = _kept_and_named(world, green, UNREACHABLE)
    assert "a normal Windows path cannot reach" in message and "README.md" not in message


@windows_only
def test_the_green_is_saved_once_the_reserved_name_is_gone(world: SimpleNamespace, made: list[str]) -> None:
    green = green_checkout.create_green(world.blue, "exec-renamed")
    (green.work / "thomas" / "fix_me.py").write_bytes(b"VALUE = 2\n")
    _make(made, green, ("aux.py",))
    with pytest.raises(keeper_guard.GreenKept):
        green_checkout.remove_green(green)

    os.replace(made[-1], _long(green.work / "aux_module.py"))
    green_checkout.remove_green(green)

    [receipt] = _receipts(world)
    record = json.loads(receipt.read_bytes())
    assert set(record["files"]) == {"thomas/fix_me.py", "aux_module.py"} and not green.work.exists()
    assert b"diff --git a/aux_module.py b/aux_module.py" in (world.captures / record["patch"]).read_bytes()


def _settled(world: SimpleNamespace, execution_id: str) -> green_checkout.Green:
    green = green_checkout.create_green(world.blue, execution_id)
    (green.work / "thomas" / "fix_me.py").write_bytes(b"VALUE = 2\n")
    green_checkout.mark_settled(green)
    return green


def test_the_removal_lock_records_when_its_process_started(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    green = _settled(world, "exec-lock-shape")
    seen: dict[str, object] = {}

    def look_at_the_lock(green: green_checkout.Green) -> None:
        seen.update(json.loads((green.git_dir / keeper_guard.LOCK_NAME).read_text(encoding="utf-8")))

    monkeypatch.setattr(keeper_guard, "before_delete", look_at_the_lock)
    green_checkout.remove_green(green)

    started = serve_instance_guard.process_started_at(os.getpid())
    assert started is not None and seen.get("pid") == os.getpid()
    assert seen.get("started_at") == started, f"the lock records no start time: {seen}"


def test_an_old_lock_whose_pid_another_process_now_has_does_not_hold_the_green(world: SimpleNamespace) -> None:
    green = _settled(world, "exec-reused")
    lock = green.git_dir / keeper_guard.LOCK_NAME
    old = time.time() - keeper_guard.LOCK_STALE_S - 60
    started = serve_instance_guard.process_started_at(os.getpid())
    assert started is not None
    # The same pid, started an hour later than the lock's remover did: Windows handed the pid on.
    reused = {"pid": os.getpid(), "started_at": started - 3600}

    lock.write_text(json.dumps({**reused, "at": time.time()}), encoding="utf-8")
    with pytest.raises(keeper_guard.GreenKept, match="another caller"):  # young: it keeps the green, whoever holds it
        green_checkout.remove_green(green)
    assert green.work.is_dir() and lock.exists() and _receipts(world) == []

    lock.write_text(json.dumps({"pid": os.getpid(), "started_at": started, "at": old}), encoding="utf-8")
    with pytest.raises(keeper_guard.GreenKept, match="another caller"):  # old, but its remover still runs
        green_checkout.remove_green(green)
    assert green.work.is_dir() and _receipts(world) == []

    lock.write_text(json.dumps({**reused, "at": old}), encoding="utf-8")
    green_checkout.remove_green(green)

    assert not green.work.exists() and not lock.exists()
    assert [json.loads(r.read_bytes())["execution"] for r in _receipts(world)] == ["exec-reused"]
