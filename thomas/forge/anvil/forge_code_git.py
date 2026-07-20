"""Git-truth helpers for Forge Code.

Every function in this module reads *ground truth* from the real ``git``
binary at call time -- nothing is templated, cached, or remembered. The Forge
Code UI uses these to show the actual diff of a build, the actual list of files
a run touched, and to perform a real revert that restores a file to its
committed state on disk.

Low-level process calls stay defensive, but workspace-state readers fail
closed with :class:`ForgeCodeGitError` when Git cannot prove the current
state. Routes translate that typed failure into a structured service error so
the UI can never mistake missing evidence for a clean run.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

# Default timeout (seconds) for a single git invocation.
_DEFAULT_TIMEOUT = 30


class ForgeCodeGitError(RuntimeError):
    """Git evidence could not be read reliably."""


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


def _parse_porcelain(output: str) -> list[tuple[str, str]]:
    """Parse NUL-delimited porcelain v1 into ``(two_char_status, path)`` pairs.

    ``-z`` disables Git's C-style filename quoting, so Unicode and unusual path
    characters remain usable artifact paths. Rename/copy records include a
    second NUL field for the source path; the destination is the first field.
    """
    entries: list[tuple[str, str]] = []
    records = output.split("\0")
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if len(record) < 4:
            continue
        status = record[:2]
        path = record[3:]
        if path:
            entries.append((status, path))
        if "R" in status or "C" in status:
            index += 1
    return entries


_STATUS_ARGS = ["status", "--porcelain=v1", "-z", "--untracked-files=all"]
_RUNTIME_BOOKKEEPING_PREFIXES = (".thomas/evolve/agent/",)


def _status_entries(root: str | Path) -> list[tuple[str, str]]:
    rc, out, err = _run_git(root, _STATUS_ARGS)
    if rc != 0:
        detail = (err or out).strip() or f"git status exited {rc}"
        raise ForgeCodeGitError(f"git status could not confirm workspace state: {detail}")
    return _parse_porcelain(out)


def _content_fingerprint(root: str | Path, path: str, status: str) -> str:
    target = Path(root).resolve() / path
    try:
        if target.is_symlink():
            payload = f"symlink:{os.readlink(target)}".encode("utf-8", errors="surrogatepass")
            digest = hashlib.sha256(payload).hexdigest()
        elif target.is_file():
            hasher = hashlib.sha256()
            with target.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    hasher.update(chunk)
            digest = hasher.hexdigest()
        else:
            digest = "missing"
    except OSError as exc:
        raise ForgeCodeGitError(f"could not fingerprint changed file {path}: {exc}") from exc
    return f"{status}\0{digest}"


def snapshot(root: str | Path) -> dict[str, str]:
    """Return ``{path: status_and_content_fingerprint}`` for changed files.

    This is a point-in-time fingerprint of the working tree, used to later
    diff a run's effect via :func:`delta_since`.
    """
    return {path: _content_fingerprint(root, path, status) for status, path in _status_entries(root)}


def changed_files(root: str | Path) -> list[str]:
    """Return the sorted, de-duplicated list of currently changed file paths.

    Includes both tracked modifications and untracked new files. This is
    ground truth at call time -- it re-reads git on every call.
    """
    return sorted({path for _status, path in _status_entries(root)})


def checkpoint(
    root: str | Path, files: list[str], message: str, *, branch_prefix: str = "thomas-code/"
) -> dict[str, str]:
    """Commit ``files`` on a new ``thomas-code/…`` branch and stay on it.

    Codex-parity checkpoint: turns a run's kept changes into a real commit the
    user can push or PR. Raises :class:`ForgeCodeGitError` on any git failure.
    Returns ``{"branch", "commit", "remote"}`` (remote may be ``""``).
    """
    wanted = [str(f).replace("\\", "/") for f in files if str(f).strip()]
    if not wanted:
        raise ForgeCodeGitError("nothing to checkpoint — no changed files")
    import re as _re
    import time as _time

    slug = _re.sub(r"[^a-z0-9-]+", "-", str(message or "checkpoint").lower()).strip("-")[:40] or "checkpoint"
    branch = f"{branch_prefix}{slug}-{int(_time.time()) % 100_000_000}"
    code, _out, err = _run_git(root, ["checkout", "-b", branch])
    if code != 0:
        raise ForgeCodeGitError(f"could not create branch {branch}: {err.strip() or 'git error'}")
    code, _out, err = _run_git(root, ["add", "--", *wanted])
    if code != 0:
        raise ForgeCodeGitError(f"could not stage files: {err.strip() or 'git error'}")
    code, _out, err = _run_git(root, ["commit", "-m", str(message or "Thomas Code checkpoint")])
    if code != 0:
        raise ForgeCodeGitError(f"could not commit: {err.strip() or 'git error'}")
    code, sha, _err = _run_git(root, ["rev-parse", "--short", "HEAD"])
    code_r, remote, _err_r = _run_git(root, ["remote", "get-url", "origin"])
    return {
        "branch": branch,
        "commit": sha.strip() if code == 0 else "",
        "remote": remote.strip() if code_r == 0 else "",
    }


def delta_since(root: str | Path, snap: dict[str, str]) -> list[str]:
    """Return paths a run newly touched relative to ``snap``.

    A path is included when it is changed *now* and is either absent from
    ``snap`` or present with a different status/content fingerprint.
    """
    current = snapshot(root)
    snap = snap or {}
    changed = [path for path, status in current.items() if snap.get(path) != status]
    return sorted(changed)


def project_delta_since(root: str | Path, snap: dict[str, str]) -> list[str]:
    """Return only user-project paths touched since ``snap``.

    Thomas stores Code transcripts inside the selected repository. Those
    bookkeeping writes are durable evidence, but they are not user-project
    changes and must never inflate completion or artifact counts.
    """

    return [
        path
        for path in delta_since(root, snap)
        if not str(path).replace("\\", "/").lower().startswith(_RUNTIME_BOOKKEEPING_PREFIXES)
    ]


def is_untracked(root: str | Path, file: str) -> bool:
    """True iff ``file`` currently appears as untracked (``??``) in git."""
    return any(status == "??" and path == file for status, path in _status_entries(root))


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
        rc, out, err = _run_git(root, ["diff", "--no-index", "--", "/dev/null", file])
        if rc not in {0, 1}:
            raise ForgeCodeGitError(f"git diff could not confirm {file}: {(err or out).strip() or f'exited {rc}'}")
        if out.strip():
            return out
        # Defensive fallback for an environment where the above did not work.
        rc, out, err = _run_git(root, ["diff", "--no-index", "--", os.devnull, file])
        if rc not in {0, 1}:
            raise ForgeCodeGitError(f"git diff could not confirm {file}: {(err or out).strip() or f'exited {rc}'}")
        return out if out.strip() else ""

    rc, out, err = _run_git(root, ["diff", "--", file])
    if rc != 0:
        raise ForgeCodeGitError(f"git diff could not confirm {file}: {(err or out).strip() or f'exited {rc}'}")
    rc, cached, err = _run_git(root, ["diff", "--cached", "--", file])
    if rc != 0:
        raise ForgeCodeGitError(f"git diff could not confirm {file}: {(err or cached).strip() or f'exited {rc}'}")
    return "\n".join(part.rstrip() for part in (cached, out) if part.strip())


def change_evidence(root: str | Path, files: list[str]) -> list[dict[str, object]]:
    """Return fail-closed diff evidence for the requested changed files."""
    return [{"file": file, "untracked": is_untracked(root, file), "diff": unified_diff(root, file)} for file in files]


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
