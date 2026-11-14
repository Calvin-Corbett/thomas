"""Find green changes, safely stage exact paths in a private index, and stream a patch."""

from __future__ import annotations

import errno
import fnmatch
import hashlib
import logging
import os
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import BinaryIO

from thomas.server import green_checkout
from thomas.server.keeper_guard_files import CHUNK, remove, write_all

__all__ = ("REBUILDABLE", "LEFT_OUT_MAX_BYTES", "LEFT_OUT_TOTAL_BYTES", "APPLY_WITH", "LINKS", "disk_full", "git", "rebuilt", "changes", "sort_out", "NotStaged", "stage", "differs", "write_patch")  # fmt: skip

log = logging.getLogger(__name__)
REBUILDABLE = (
    ".venv", "venv", "env", "node_modules", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".tox", ".nox", ".hypothesis", "htmlcov", "build", "dist", ".cache", ".playwright-cli", "*.egg-info",
)  # fmt: skip
LEFT_OUT_MAX_BYTES = 10 * 1024 * 1024
LEFT_OUT_TOTAL_BYTES = 100 * 1024 * 1024
APPLY_WITH = "git apply --binary <patch>, onto a checkout of base"
LINKS = "is or passes through a link, which is never followed"
TIMEOUT = 600


def disk_full(exc: BaseException) -> bool:
    return isinstance(exc, OSError) and (exc.errno == errno.ENOSPC or getattr(exc, "winerror", None) in (39, 112))


def _command(green: green_checkout.Green, args: tuple[str, ...]) -> list[str]:
    return green_checkout._git_command(green, "--no-optional-locks", "-c", "core.safecrlf=false", *args)


def _env(index: Path | None = None) -> dict[str, str]:
    env = green_checkout._clean_env()
    if index is not None:
        env["GIT_INDEX_FILE"] = str(index)
    return env


def _failure(args: tuple[str, ...], message: str) -> None:
    message = message.strip()
    tail = message[-300:]
    if "no space left on device" in message.lower() or "not enough space on the disk" in message.lower():
        raise OSError(errno.ENOSPC, f"git {args[0]} failed: {tail}")
    raise green_checkout.GreenUnavailable(f"git {args[0]} failed: {tail}")


def git(
    green: green_checkout.Green,
    args: tuple[str, ...],
    *,
    index: Path | None = None,
    stdin: bytes | None = None,
    ok: tuple[int, ...] = (0,),
) -> subprocess.CompletedProcess[bytes]:
    try:
        result = subprocess.run(
            _command(green, args),
            cwd=green.git_dir.parent,
            env=_env(index),
            input=stdin,
            capture_output=True,
            timeout=TIMEOUT,
        )
    except subprocess.TimeoutExpired as exc:
        raise green_checkout.GreenUnavailable(f"git {args[0]} did not finish in {TIMEOUT}s") from exc
    if result.returncode not in ok:
        _failure(args, (result.stdout + result.stderr).decode("utf-8", "replace"))
    return result


def _names(data: bytes) -> list[str]:
    return [item.decode("utf-8", "surrogateescape") for item in data.split(b"\0") if item]


def _running_exclude(green: green_checkout.Green) -> tuple[str, ...]:
    if green.blue.is_absolute():
        path = green.blue / ".git" / "info" / "exclude"
        if path.is_file():
            return ("-c", f"core.excludesFile={path}")
    return ()


def _escape(name: str) -> str:
    return "".join("\\" + c if c in "[]*?\\" else c for c in name)


def rebuilt(green: green_checkout.Green) -> list[str]:
    exclude = _running_exclude(green)
    ignored = _names(
        git(green, (*exclude, "ls-files", "--others", "--ignored", "--exclude-standard", "--directory", "-z")).stdout
    )
    folders = {
        name
        for name in ignored
        if name.endswith("/")
        and any(fnmatch.fnmatchcase(name.rstrip("/").split("/")[-1], pattern) for pattern in REBUILDABLE)
    }
    extra = tuple(f"--exclude={name}/" for name in REBUILDABLE)
    nested = _names(git(green, (*exclude, "ls-files", "--others", "--ignored", "--directory", "-z", *extra)).stdout)
    folders.update(
        name
        for name in nested
        if name.endswith("/")
        and any(fnmatch.fnmatchcase(name.rstrip("/").split("/")[-1], pattern) for pattern in REBUILDABLE)
        and any(name.startswith(parent) for parent in ignored if parent.endswith("/"))
    )
    outermost: list[str] = []
    for name in sorted(folders):
        if not any(name.startswith(parent) for parent in outermost):
            outermost.append(name)
    return outermost


def _coordination(name: str) -> bool:
    return any(
        name == prefix or name.startswith(prefix.rstrip("/") + "/") for prefix in green_checkout.COORDINATION_PATHS
    )


def changes(green: green_checkout.Green) -> tuple[list[str], list[str], list[dict[str, str]]]:
    tracked = git(green, ("diff", "--no-renames", "--name-status", "-z", green.base, "--")).stdout.split(b"\0")
    status = {
        tracked[i + 1].decode("utf-8", "surrogateescape"): tracked[i][:1]
        for i in range(0, len(tracked) - 1, 2)
        if tracked[i]
    }
    folders = rebuilt(green)
    pattern_file = green.git_dir / f"keeper-exclude-{os.getpid()}.txt"
    try:
        pattern_file.write_text(
            "".join("/" + _escape(folder.rstrip("/")) + "/\n" for folder in folders), encoding="utf-8"
        )
        options = (f"--exclude-from={pattern_file}",)
        all_new = _names(git(green, ("ls-files", "--others", "-z", *options)).stdout)
        plain = set(_names(git(green, ("ls-files", "--others", "--exclude-standard", "-z", *options)).stdout))
    finally:
        remove(pattern_file, "temporary exclude patterns")
    new = plain | {name for name, letter in status.items() if letter == b"A"}
    ignored = (
        set(
            _names(
                git(
                    green,
                    (*_running_exclude(green), "check-ignore", "--no-index", "-z", "--stdin"),
                    stdin=b"\0".join(os.fsencode(name) for name in sorted(new)) + b"\0",
                    ok=(0, 1),
                ).stdout
            )
        )
        if new
        else set()
    )
    selected, excluded, not_saved = [], [], [{"path": name, "why": "rebuilt by tools"} for name in folders]
    for name in sorted(set(status) | set(all_new)):
        if any(name.startswith(folder) for folder in folders):
            continue
        if name.endswith("/"):
            not_saved.append({"path": name, "why": "a git repository of its own"})
        elif (name in status or name in plain) and not _coordination(name) and name not in ignored:
            selected.append(name)
        else:
            excluded.append(name)

    def size(name: str) -> int:
        try:
            return os.lstat(green.work / name).st_size
        except OSError:
            return 0

    left_out, total = [], 0
    for name in sorted(excluded, key=lambda n: (size(n), n)):
        count = size(name)
        if count > LEFT_OUT_MAX_BYTES:
            not_saved.append({"path": name, "why": "over 10 MB"})
        elif count + total > LEFT_OUT_TOTAL_BYTES:
            not_saved.append({"path": name, "why": "past the 100 MB all left-out files may take"})
        else:
            left_out.append(name)
            total += count
    return selected, left_out, not_saved


def first_link(root: Path, path: str) -> str | None:
    """Name the first link from *root* outward; a missing component ends the walk."""
    current = root
    parts: list[str] = []
    for component in (None, *Path(path).parts):
        if component is not None:
            current = current / component
            parts.append(component)
        try:
            info = os.lstat(current)
        except (FileNotFoundError, NotADirectoryError):
            return None
        if stat.S_ISLNK(info.st_mode) or (
            getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        ):
            return "/".join(parts)
    return None


def linked(root: Path, path: str) -> bool:
    """True if any component, including the root, is a link or junction."""
    return first_link(root, path) is not None


def sort_out(
    green: green_checkout.Green, paths: list[str], not_saved: list[dict[str, str]]
) -> tuple[list[str], list[str]]:
    add, gone = [], []
    for name in paths:
        path = green.work
        try:
            parts = ("", *Path(name).parts)
            linked = False
            for part in parts:
                path = path / part
                info = os.lstat(path)
                if (
                    stat.S_ISLNK(info.st_mode) or info.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT
                    if hasattr(info, "st_file_attributes")
                    else stat.S_ISLNK(info.st_mode)
                ):
                    linked = True
                    break
            if linked:
                not_saved.append({"path": name, "why": LINKS})
            elif stat.S_ISDIR(info.st_mode):
                gone.append(name)
                not_saved.append(
                    {"path": name, "why": "a folder now: saved as deleted, and nothing in it under this name"}
                )
            else:
                try:
                    with path.open("rb") as handle:
                        while handle.read(CHUNK):
                            pass
                    add.append(name)
                except OSError as exc:
                    not_saved.append({"path": name, "why": f"could not be read ({type(exc).__name__}: {exc.strerror})"})
        except FileNotFoundError:
            gone.append(name)
        except OSError as exc:
            not_saved.append({"path": name, "why": f"could not be looked at ({type(exc).__name__}: {exc.strerror})"})
    return add, gone


class NotStaged(OSError):
    """A changed file is missing from the private capture index."""


def stage(green: green_checkout.Green, add: list[str], gone: list[str], index: Path) -> None:
    git(green, ("read-tree", green.base), index=index)
    if gone:
        # A gone name the base never tracked can still be on disk when its trailing
        # space or dot makes a normal Windows path miss it during inspection.
        tracked = set(_names(git(green, ("ls-files", "-z"), index=index).stdout))
        missing = [name for name in gone if name not in tracked]
        if missing:
            raise NotStaged(
                f"git listed {len(tracked)} files; a normal Windows path cannot reach "
                f"{', '.join(missing)}; none of this green is saved"
            )
        git(
            green,
            ("update-index", "--force-remove", "-z", "--stdin"),
            index=index,
            stdin=b"\0".join(os.fsencode(name) for name in gone) + b"\0",
        )
    if add:
        git(
            green,
            ("update-index", "--add", "--remove", "--replace", "-z", "--stdin"),
            index=index,
            stdin=b"\0".join(os.fsencode(name) for name in add) + b"\0",
        )
        # Git skips Windows reserves with "Ignoring path" and exit code 0.
        staged = set(_names(git(green, ("ls-files", "-z"), index=index).stdout))
        missing = [name for name in add if name not in staged]
        if missing:
            raise NotStaged(
                f"git did not stage {len(missing)} files; Windows reserves: "
                f"{', '.join(missing)}; none of this green is saved"
            )


def differs(green: green_checkout.Green, index: Path) -> bool:
    return git(green, ("diff", "--cached", "--quiet", green.base), index=index, ok=(0, 1)).returncode == 1


def write_patch(green: green_checkout.Green, index: Path, handle: BinaryIO) -> tuple[str, int]:
    args = ("diff", "--cached", "--no-renames", "--binary", "--full-index", green.base)
    with tempfile.TemporaryFile() as errors:
        proc = subprocess.Popen(
            _command(green, args), cwd=green.git_dir.parent, env=_env(index), stdout=subprocess.PIPE, stderr=errors
        )
        digest, size = hashlib.sha256(), 0
        try:
            assert proc.stdout is not None
            with proc.stdout:
                while block := proc.stdout.read(CHUNK):
                    digest.update(block)
                    write_all(handle, block)
                    size += len(block)
            proc.wait(timeout=TIMEOUT)
        except (OSError, subprocess.SubprocessError):
            proc.kill()
            proc.wait()
            raise
        if proc.returncode:
            errors.seek(0)
            _failure(args, errors.read().decode("utf-8", "replace"))
    return digest.hexdigest(), size
