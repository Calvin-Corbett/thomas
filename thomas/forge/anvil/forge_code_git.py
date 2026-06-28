"""Git-truth helpers for Forge Code.

Every function in this module reads *ground truth* from the real ``git``
binary at call time -- nothing is templated, cached, or remembered. The Forge
Code UI uses these to show the actual diff of a build, the actual list of files
a run touched, and to perform a real revert that restores a file to its
committed state on disk.

All operations are defensive: a failing ``git`` invocation, a missing repo, or
an unexpected exception yields a safe default (empty list/str/dict, or an
``ok: false`` result) rather than raising -- this code runs inside the aiohttp
server and must never take it down.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

# Default timeout (seconds) for a single git invocation.
_DEFAULT_TIMEOUT = 30


def _run_git(root: str | Path, args: list[str], timeout: int = _DEFAULT_TIMEOUT) -> tuple[int, str, str]:
    """Run ``git -C <root> <args...>`` and return ``(returncode, stdout, stderr)``.

    stdout and stderr are kept SEPARATE on purpose (text, utf-8,
    ``errors="replace"``). git writes its data on stdout and its chatter on
    stderr -- e.g. ``warning: LF will be replaced by CRLF the next time Git
    touches it``. That chatter must NEVER reach the diff renderer (it would be
    parsed and mis-highlighted as diff rows) nor the porcelain parser (it would
    surface as a phantom changed file), so every reader below consumes ONLY
    stdout. Callers that report a *failure message* (revert) prefer stderr.

    Never raises -- on any exception returns ``(1, "", str(exc))`` so callers can
    treat a git failure as "non-zero with a message".
    """
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        return proc.returncode, (proc.stdout or ""), (proc.stderr or "")
    except Exception as exc:  # noqa: BLE001 -- git must never crash the server.
        return 1, "", str(exc)


def _unquote(path: str) -> str:
    """Strip the surrounding quotes git adds for paths with special chars."""
    if len(path) >= 2 and path.startswith('"') and path.endswith('"'):
        return path[1:-1]
    return path


def _parse_porcelain(output: str) -> list[tuple[str, str]]:
    """Parse ``git status --porcelain`` into ``(two_char_status, path)`` pairs.

    Handles rename/copy entries ("old -> new") by returning the *new* path, and
    unquotes paths git wraps in double quotes. A line shorter than the minimum
    "XY <path>" shape is skipped.
    """
    entries: list[tuple[str, str]] = []
    for line in output.splitlines():
        if len(line) < 4:
            continue
        status = line[:2]
        rest = line[3:]
        if " -> " in rest:
            rest = rest.split(" -> ", 1)[1]
        path = _unquote(rest.strip())
        if path:
            entries.append((status, path))
    return entries


def snapshot(root: str | Path) -> dict[str, str]:
    """Return ``{path: two_char_status}`` from ``git status --porcelain`` now.

    This is a point-in-time fingerprint of the working tree, used to later
    diff a run's effect via :func:`delta_since`.
    """
    _rc, out, _err = _run_git(root, ["status", "--porcelain"])
    return {path: status for status, path in _parse_porcelain(out)}


def changed_files(root: str | Path) -> list[str]:
    """Return the sorted, de-duplicated list of currently changed file paths.

    Includes both tracked modifications and untracked new files. This is
    ground truth at call time -- it re-reads git on every call.
    """
    _rc, out, _err = _run_git(root, ["status", "--porcelain"])
    return sorted({path for _status, path in _parse_porcelain(out)})


def delta_since(root: str | Path, snap: dict[str, str]) -> list[str]:
    """Return paths a run newly touched relative to ``snap``.

    A path is included when it is changed *now* and is either absent from
    ``snap`` or present with a different two-char status code.
    """
    current = snapshot(root)
    snap = snap or {}
    changed = [path for path, status in current.items() if snap.get(path) != status]
    return sorted(changed)


def is_untracked(root: str | Path, file: str) -> bool:
    """True iff ``file`` currently appears as untracked (``??``) in git."""
    _rc, out, _err = _run_git(root, ["status", "--porcelain"])
    return any(status == "??" and path == file for status, path in _parse_porcelain(out))


def file_is_dirty(root: str | Path, file: str) -> bool:
    """True iff ``file`` is among the currently changed files."""
    return file in changed_files(root)


def unified_diff(root: str | Path, file: str) -> str:
    """Return a unified diff for ONE file, read from real git.

    * tracked & modified -> ``git diff -- <file>`` (falling back to
      ``--cached`` when the worktree diff is empty but the change is staged).
    * untracked/new -> ``git diff --no-index -- /dev/null <file>`` so the whole
      new file shows as added (``+`` lines). ``--no-index`` exits 1 when the
      files differ -- that is normal, not an error; its stdout is still
      returned.

    Returns ``""`` when there is genuinely no diff. Never raises.
    """
    # Every branch reads ONLY git's stdout. The unified-diff text the UI renders
    # must be pure ``git diff`` output -- git's stderr warnings (CRLF/LF, etc.)
    # are deliberately discarded so they never appear as bogus diff rows.
    if is_untracked(root, file):
        # git treats the literal "/dev/null" as an empty file on every platform
        # (os.devnull would be "nul" on Windows, which git reads as a real
        # path). --no-index exits 1 because the files differ; the diff is on
        # stdout regardless.
        _rc, out, _err = _run_git(root, ["diff", "--no-index", "--", "/dev/null", file])
        if out.strip():
            return out
        # Defensive fallback for an environment where the above did not work.
        _rc, out, _err = _run_git(root, ["diff", "--no-index", "--", os.devnull, file])
        return out if out.strip() else ""

    _rc, out, _err = _run_git(root, ["diff", "--", file])
    if out.strip():
        return out
    _rc, cached, _cerr = _run_git(root, ["diff", "--cached", "--", file])
    return cached if cached.strip() else ""


def _safe_target(root: str | Path, file: str) -> Path | None:
    """Resolve ``file`` against ``root``, refusing anything outside the repo.

    Returns the resolved :class:`Path` when it is inside ``root``; returns
    ``None`` when ``file`` is absolute or escapes ``root`` (e.g. via ``..``).
    """
    if os.path.isabs(file):
        return None
    root_resolved = Path(root).resolve()
    target = (root_resolved / file).resolve()
    if target == root_resolved or not target.is_relative_to(root_resolved):
        return None
    return target


def revert_file(root: str | Path, file: str) -> dict:
    """Restore ``file`` to its committed state on disk and report the outcome.

    * untracked/new -> delete the file from disk (pathlib, only within root).
    * tracked & modified -> ``git checkout -- <file>`` (falling back to
      ``git restore -- <file>``).

    Returns ``{"ok", "clean", "file", "reason"}`` where ``clean`` is True iff
    ``file`` no longer appears in :func:`changed_files` afterward. ``ok`` is
    False with a reason when the path is unsafe or git failed.
    """
    target = _safe_target(root, file)
    if target is None:
        return {
            "ok": False,
            "clean": False,
            "file": file,
            "reason": "refused: path is absolute or escapes the repo root",
        }

    if is_untracked(root, file):
        try:
            if target.exists():
                target.unlink()
        except OSError as exc:
            return {
                "ok": False,
                "clean": False,
                "file": file,
                "reason": f"failed to delete untracked file: {exc}",
            }
        clean = not file_is_dirty(root, file)
        return {
            "ok": True,
            "clean": clean,
            "file": file,
            "reason": "deleted untracked file" if clean else "deleted, but file still reported dirty",
        }

    rc, out, err = _run_git(root, ["checkout", "--", file])
    if rc != 0:
        # Older/newer git: `restore` is the modern spelling of `checkout --`.
        rc, out, err = _run_git(root, ["restore", "--", file])
    if rc != 0:
        # git reports the actual failure on stderr; fall back to stdout.
        return {
            "ok": False,
            "clean": False,
            "file": file,
            "reason": f"git revert failed: {(err or out).strip()}",
        }

    clean = not file_is_dirty(root, file)
    return {
        "ok": True,
        "clean": clean,
        "file": file,
        "reason": "restored to committed state" if clean else "git reported success but file still dirty",
    }
