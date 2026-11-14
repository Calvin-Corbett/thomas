"""Every green is saved before Thomas deletes it (the keeper design, section 6.3).

On dev 6c8719bd ``green_checkout.remove_green``, the one place a green is deleted, saved nothing first. Now it writes
a capture of the change as it would land, and a create-only receipt, and keeps the green when it cannot (keeper_guard).
"""

from __future__ import annotations

import errno
import hashlib
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.green_support import git
from tests.landing_support import copy_blue, isolated_landing_git, landing_blue_template, prepare_green_root
from thomas.core.git_launcher import real_git_first
from thomas.server import green_checkout

pytestmark = pytest.mark.usefixtures(isolated_landing_git.__name__)

DROP_ENV = "THOMAS_KEEPER_DROP"
windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows junctions and access lists")
# Stored with LF, so a checkout on a machine with core.autocrlf=true (this one) writes them with CRLF.
BASE_FILES = {"README.md": b"blue\n", "thomas/fix_me.py": b"VALUE = 1\n", "gone.txt": b"bye\n",
              ".gitignore": b"runtime/\nnode_modules/\n.venv/\n/build/\n*.egg-info/\n",
              "plans/thomas/WORKBOARD.md": b"# board\n"}  # fmt: skip


@pytest.fixture(scope="module")
def keeper_blue_template(tmp_path_factory: pytest.TempPathFactory, isolated_landing_git: None) -> Path:
    blue = copy_blue(landing_blue_template(tmp_path_factory), tmp_path_factory.mktemp("keeper-template"))
    git(blue, "config", "core.autocrlf", "false")
    for rel, data in BASE_FILES.items():
        (blue / rel).parent.mkdir(parents=True, exist_ok=True)
        (blue / rel).write_bytes(data)
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("PATH", real_git_first(os.environ)["PATH"])
        git(blue, "add", "-A")
        git(blue, "commit", "-qm", "more")
    return blue


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, keeper_blue_template: Path) -> SimpleNamespace:
    monkeypatch.setenv(green_checkout.GREEN_ROOT_ENV, str(prepare_green_root(tmp_path / "green-root")))
    monkeypatch.setenv("PATH", real_git_first(os.environ)["PATH"])
    (tmp_path / "drop" / "captures").mkdir(parents=True)
    monkeypatch.setenv(DROP_ENV, str(tmp_path / "drop"))
    blue = copy_blue(keeper_blue_template, tmp_path)
    return SimpleNamespace(blue=blue, drop=tmp_path / "drop" / "captures", fallback=tmp_path / "captures", tmp=tmp_path)


def _receipts(folder: Path) -> list[Path]:
    return sorted(folder.glob("*.json")) if folder.is_dir() else []


def _record(world: SimpleNamespace) -> tuple[dict, bytes]:
    [receipt] = _receipts(world.drop)
    record = json.loads(receipt.read_bytes())
    return record, (receipt.parent / record["patch"]).read_bytes() if record["patch"] else b""


def _landed(blue: Path, top: Path) -> dict[str, str]:
    """Every file under *top* as git here would store it: what would land, whatever the line endings on disk."""
    paths = sorted(
        path.relative_to(top).as_posix()
        for path in top.rglob("*")
        if path.is_file() and path.relative_to(top).parts[0] not in (".git", "node_modules")
    )
    hashed = subprocess.run(
        ["git", f"--git-dir={blue / '.git'}", f"--work-tree={top}", "hash-object", "--stdin-paths"],
        cwd=top,
        input="".join(f"{path}\n" for path in paths),
        capture_output=True,
        text=True,
        check=True,
    )
    return dict(zip(paths, hashed.stdout.splitlines(), strict=True))


def _green(world: SimpleNamespace, name: str, value: bytes = b"VALUE = 2\r\n") -> green_checkout.Green:
    green = green_checkout.create_green(world.blue, name)
    (green.work / "thomas" / "fix_me.py").write_bytes(value)
    return green


def _blocked(world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:  # the drop and the fallback are files
    (world.tmp / "drop-file").write_text("not a folder", encoding="utf-8")
    monkeypatch.setenv(DROP_ENV, str(world.tmp / "drop-file"))
    world.fallback.write_text("not a folder", encoding="utf-8")


@pytest.mark.parametrize("autocrlf", ["true", "false"])
def test_a_removed_green_leaves_a_capture_that_lands_what_it_held(world: SimpleNamespace, autocrlf: str) -> None:
    git(world.blue, "config", "core.autocrlf", autocrlf)
    green = _green(world, "exec-saved")
    git(green.git_dir, "config", "core.autocrlf", autocrlf)
    work = green.work
    (work / "gone.txt").unlink()
    (work / "thomas" / "new_crlf.py").write_bytes(b"A = 1\r\nB = 2\r\n")
    (work / "thomas" / "picture.bin").write_bytes(bytes(range(256)) * 64)
    (work / "thomas" / "big.txt").write_bytes(b"0123456789abcdef\n" * 16_000)  # over 200 KB
    (work / "runtime").mkdir()
    (work / "runtime" / "notes.md").write_bytes(b"what I found\n")  # untracked, and ignored by the repo
    (work / "plans" / "thomas" / "WORKBOARD.md").write_bytes(b"# board\r\nmine\r\n")  # never handed in
    (work / "node_modules" / "x").mkdir(parents=True)
    (work / "node_modules" / "x" / "i.js").write_bytes(b"rebuilt by npm\n")
    before = _landed(world.blue, work)

    green_checkout.remove_green(green)

    assert not work.exists() and not green.git_dir.exists()
    record, patch = _record(world)
    assert record["sha256"] == hashlib.sha256(patch).hexdigest() and record["bytes"] == len(patch)
    assert (record["execution"], record["base"]) == ("exec-saved", green.base)
    assert record["apply_with"] == "git apply --binary <patch>, onto a checkout of base"
    assert {"thomas/fix_me.py", "gone.txt", "thomas/new_crlf.py", "thomas/picture.bin"} <= set(record["files"])
    assert {"runtime/notes.md", "plans/thomas/WORKBOARD.md"} <= set(record["left_out"])
    assert b"diff --git a/runtime/notes.md b/runtime/notes.md\nnew file mode" in patch
    assert {"path": "node_modules/", "why": "rebuilt by tools"} in record["not_saved"]
    hunk = patch.split(b"diff --git a/thomas/fix_me.py")[1].split(b"diff --git")[0].splitlines()
    assert [line[:1] for line in hunk if line[:1] in b"+-" and line[:3] not in (b"+++", b"---")] == [b"-", b"+"]

    restored = world.tmp / "restored"  # a normal checkout of base, then the receipt's own instruction
    subprocess.run(["git", "clone", "-q", "--no-checkout", str(world.blue), str(restored)], check=True)
    git(restored, "config", "core.autocrlf", autocrlf)
    subprocess.run(["git", "-C", str(restored), "checkout", "-q", "--detach", green.base], check=True)
    subprocess.run(["git", "-C", str(restored), "apply", "--binary", str(world.drop / record["patch"])], check=True)
    assert _landed(world.blue, restored) == before


@windows_only
def test_nothing_behind_a_junction_is_read_into_the_capture(world: SimpleNamespace) -> None:
    """git on Windows follows a junction, also one inside a tracked file that is a folder now (staged by name)."""
    import _winapi

    outside = world.tmp / "outside"
    outside.mkdir()
    (outside / "owner-secret.txt").write_bytes(b"not the team's\n")
    green = _green(world, "exec-linked")
    (green.work / "runtime").mkdir()
    (green.work / "README.md").unlink()
    (green.work / "README.md").mkdir()
    for link in (green.work / "thomas" / "linked", green.work / "runtime" / "linked", green.work / "README.md" / "x"):
        _winapi.CreateJunction(str(outside), str(link))
        assert link.is_junction() and not link.is_symlink()

    green_checkout.remove_green(green)

    record, patch = _record(world)
    assert b"not the team's" not in patch and b"diff --git a/thomas/fix_me.py" in patch
    why = {item["path"]: item["why"] for item in record["not_saved"]}
    linked = {"thomas/linked/owner-secret.txt", "runtime/linked/owner-secret.txt", "README.md/x/owner-secret.txt"}
    assert {path for path, said in why.items() if "link" in said} == linked
    assert why["README.md"].startswith("a folder now") and "README.md" in record["files"]
    assert b"deleted file mode" in patch.split(b"diff --git a/README.md b/README.md")[1][:80]
    assert (outside / "owner-secret.txt").read_bytes() == b"not the team's\n"


@windows_only
def test_a_file_that_cannot_be_read_is_named_and_the_green_still_goes(world: SimpleNamespace) -> None:
    green = _green(world, "ratchet-cand-1234567-89abcde")
    (green.work / "runtime").mkdir()
    held = green.work / "runtime" / "held.log"
    held.write_bytes(b"a log a process holds\n")
    subprocess.run(["icacls", str(held), "/deny", f"{os.environ['USERNAME']}:(RD)"], check=True, capture_output=True)

    green_checkout.remove_green(green)

    record, patch = _record(world)
    why = {item["path"]: item["why"] for item in record["not_saved"]}
    assert why["runtime/held.log"].startswith("could not be read")
    assert b"diff --git a/thomas/fix_me.py" in patch and not green.work.exists()
    assert green_checkout.create_green(world.blue, green.execution_id).work.is_dir(), "a ratchet restart can go on"


def test_a_green_no_folder_takes_a_capture_of_is_kept_says_why_and_loses_its_rebuildable_folders(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    green = _green(world, "exec-blocked")
    (green.work / "node_modules" / "x").mkdir(parents=True)
    (green.work / "node_modules" / "x" / "i.js").write_bytes(b"rebuilt by npm\n")
    _blocked(world, monkeypatch)

    with caplog.at_level(logging.WARNING), pytest.raises(OSError) as raised:
        green_checkout.remove_green(green)

    assert type(raised.value).__name__ == "GreenKept" and "exec-blocked is kept" in caplog.text
    assert green_checkout.find_green("exec-blocked") is not None and green.git_dir.is_dir()
    failed = json.loads((green.git_dir / "capture-failed.json").read_bytes())
    assert failed["error"] == "OSError" and "no capture folder took it" in failed["message"] and failed["at"]
    assert not (green.work / "node_modules").exists(), "never captured, so a kept green does not keep them"


def test_a_full_disk_spends_the_reserve_and_the_reserve_comes_back(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from thomas.server import keeper_guard
    from thomas.server import keeper_guard_capture as capture

    monkeypatch.setattr(keeper_guard, "RESERVE_BYTES", 4096)
    keeper_guard.keep_reserve()
    reserve = world.fallback / keeper_guard.RESERVE_NAME
    assert reserve.stat().st_size == 4096
    real = capture.write_patch

    def full_while_reserved(green, index, handle):  # noqa: ANN001, ANN202
        if reserve.exists():
            raise OSError(errno.ENOSPC, "No space left on device")
        return real(green, index, handle)

    monkeypatch.setattr(capture, "write_patch", full_while_reserved)
    green = _green(world, "exec-full")

    green_checkout.remove_green(green)

    assert len(_receipts(world.drop)) == 1 and not green.work.exists()
    assert reserve.stat().st_size == 4096, "set aside again once the green was deleted"


@pytest.mark.parametrize("read_back", ["0" * 64, None], ids=["differs", "denied"])
def test_a_capture_is_read_back_before_its_green_goes(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, read_back: str | None
) -> None:
    """Reads back different: kept. Reading back denied (create-only drop): saved, and no second copy elsewhere."""
    from thomas.server import keeper_guard, keeper_guard_files

    monkeypatch.setattr(keeper_guard_files, "read_back", lambda handle: read_back)
    green = _green(world, "exec-read-back")
    if read_back is None:
        green_checkout.remove_green(green)
        assert len(_receipts(world.drop)) == 1 and not world.fallback.exists() and not green.work.exists()
    else:
        with pytest.raises(keeper_guard.GreenKept, match="does not match"):
            green_checkout.remove_green(green)
        assert green.work.is_dir()


def test_a_receipt_is_never_overwritten(world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    from thomas.server import keeper_guard

    monkeypatch.setattr(keeper_guard, "_stamp", lambda: "20261011T120000Z")
    taken = world.drop / "exec-twice-20261011T120000Z.json"
    taken.write_bytes(b"a receipt already here")
    for value in (b"VALUE = 2\n", b"VALUE = 3\n"):
        green_checkout.remove_green(_green(world, "exec-twice", value))

    assert taken.read_bytes() == b"a receipt already here"
    made = [world.drop / f"exec-twice-20261011T120000Z-{n}.json" for n in (2, 3)]
    assert _receipts(world.drop) == sorted([taken, *made])
    hashes = [json.loads(receipt.read_bytes())["sha256"] for receipt in made]
    assert hashes == [hashlib.sha256(receipt.with_suffix(".patch").read_bytes()).hexdigest() for receipt in made]
    assert hashes[0] != hashes[1]


def test_an_unchanged_green_leaves_only_a_receipt(world: SimpleNamespace) -> None:
    green = green_checkout.create_green(world.blue, "exec-quiet")
    green_checkout.remove_green(green)
    record, _ = _record(world)
    assert (record["changed"], record["patch"], record["files"], record["left_out"]) == (False, None, [], [])
    assert list(world.drop.glob("*.patch")) == [] and not green.work.exists()


def test_the_card_checks_scratch_copies_of_dev_are_not_captured_but_a_teams_green_is(world: SimpleNamespace) -> None:
    from thomas.server import green_handoff

    scratch = _green(world, f"{green_handoff.SCRATCH_PREFIX}exec-1-change", b"VALUE = 3\n")
    team = _green(world, "exec-team")
    green_checkout.remove_green(scratch)
    green_checkout.remove_green(team)
    assert [json.loads(r.read_bytes())["execution"] for r in _receipts(world.drop)] == ["exec-team"]
    assert not scratch.work.exists() and not team.work.exists()


def test_a_tools_folder_is_left_out_only_when_ignored_and_left_out_files_are_capped(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A folder named like one tools rebuild is left out, and cleared from a kept green, only when the repo's own
    rules ignore it; with such a name and not ignored, it is a team's work like any other untracked file."""
    from thomas.server import keeper_guard_capture as capture

    monkeypatch.setattr(capture, "LEFT_OUT_TOTAL_BYTES", 250)
    ignored = (".venv", "build", "pkg.egg-info", "runtime/.tox")  # by the repo's own .gitignore
    work = ("thomas/build/new_module.py", "env/x.py")  # the same names, not ignored

    def made(name: str) -> green_checkout.Green:
        green = _green(world, name)
        for rel in [f"{folder}/f.txt" for folder in ignored] + list(work):
            (green.work / rel).parent.mkdir(parents=True, exist_ok=True)
            (green.work / rel).write_bytes(b"WORK = True\n")
        return green

    green = made("exec-capped")
    for name, size in (("small.log", 100), ("mid.log", 120), ("large.log", 200)):
        (green.work / "runtime" / name).write_bytes(b"x" * size)
    green_checkout.remove_green(green)

    record, patch = _record(world)
    assert record["left_out"] == ["runtime/mid.log", "runtime/small.log"]
    why = {item["path"]: item["why"] for item in record["not_saved"]}
    assert why["runtime/large.log"].startswith("past the")
    assert {path for path, said in why.items() if said == "rebuilt by tools"} == {f"{f}/" for f in ignored}
    assert set(work) <= set(record["files"]) and all(f"diff --git a/{rel} ".encode() in patch for rel in work)

    kept = made("exec-kept")
    _blocked(world, monkeypatch)
    with pytest.raises(OSError, match="kept"):
        green_checkout.remove_green(kept)
    assert all((kept.work / rel).is_file() for rel in work), "a team's folder named like a tool's is never cleared"
    assert not any((kept.work / folder).exists() for folder in ignored)
