"""Notice which files in the live Thomas repository a worker changed.
When the worker ran in a green copy, measure the change with git against
that green copy's base.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from thomas.core.event_loop_offload import off_loop
from thomas.server.chat_delegation_deliverable import _worker_summary_line, _workspace_mtimes

_LIVE_REPO_IGNORE_PREFIXES = (
    "library/",
    "runtime/",
    "output/",
    "plans/thomas/chat_stress_",
)
_LIVE_REPO_IGNORE_PARTS: frozenset[str] = frozenset(
    {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "node_modules"}
)
_LIVE_REPO_IGNORE_SUFFIXES = ("_test_results.jsonl",)
_LIVE_REPO_WRITE_TOOLS = {"fs.write_file", "fs.write_protected_file"}


def _live_repo_change_ignored(path: str) -> bool:
    rel = str(path or "").replace("\\", "/").lstrip("/")
    if not rel:
        return True
    if any(part in _LIVE_REPO_IGNORE_PARTS for part in rel.split("/")):
        return True
    if any(rel.endswith(suffix) for suffix in _LIVE_REPO_IGNORE_SUFFIXES):
        return True
    return any(rel.startswith(prefix) for prefix in _LIVE_REPO_IGNORE_PREFIXES)


def _file_content_fingerprint(path: Path) -> tuple[int, str] | None:
    try:
        st = path.stat()
        h = hashlib.blake2b(digest_size=16)
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                h.update(chunk)
        return (st.st_size, h.hexdigest())
    except OSError:
        return None


def _live_repo_workspace_mtimes(repo_root: Path) -> dict[str, tuple[int, str]]:
    mtime_markers = _workspace_mtimes(
        repo_root,
        ignored_prefixes=_LIVE_REPO_IGNORE_PREFIXES,
        ignored_parts=_LIVE_REPO_IGNORE_PARTS,
    )
    out: dict[str, tuple[int, str]] = {}
    for rel in mtime_markers:
        if _live_repo_change_ignored(rel):
            continue
        marker = _file_content_fingerprint(repo_root / rel)
        if marker is not None:
            out[rel] = marker
    return out


def _changed_in_green(root: Path) -> list[str] | None:
    """What a green differs by from the commit it started at, or None if *root*
    is not a green. A retry re-measures its baseline from green, which already
    holds the earlier attempt's work, so "since this attempt began" read as
    nothing and a correct fix was thrown away (exec-8ef69b69fb68, 2026-09-22)."""
    from thomas.server import green_checkout

    try:
        resolved = Path(root).resolve()
        if resolved.parent != (green_checkout.green_root() / "work").resolve():
            return None
        green = green_checkout.find_green(resolved.name)
        return None if green is None else green_checkout.changed_paths(green)
    except (OSError, green_checkout.GreenUnavailable):
        return None


def _live_repo_files_changed_since(
    repo_root: Path, baseline: dict[str, tuple[int, str]], *, limit: int = 48
) -> list[str]:
    in_green = _changed_in_green(repo_root)
    if in_green is not None:
        return sorted(p for p in in_green if not _live_repo_change_ignored(p))[:limit]
    after = _live_repo_workspace_mtimes(repo_root)
    changed = [
        rel for rel, marker in after.items() if baseline.get(rel) != marker and not _live_repo_change_ignored(rel)
    ]
    return sorted(changed)[:limit]


async def attempt_change_baseline(
    live_root: Path, work_dir: Path | None, *, in_live_repo: bool, attempt: int
) -> tuple[list[str] | None, dict[str, Any]]:
    """The picture one attempt starts from, measured in a worker thread.

    Two reads of the whole work copy, and one of them opens and hashes every
    byte it finds: measured on this checkout, 8,446 files and 98.2 MB, which a
    native read-and-hash alone takes 1.67 s to get through. Both ran straight
    on the server's event loop -- at the top of every attempt, and again when
    the attempt finished -- so while Thomas worked on Thomas, Thomas stopped
    answering. Same two questions, same functions, one thread that is not the
    loop.

    The functions are looked up as this module's globals deliberately:
    ``chat_delegation._sync_runner_legacy_globals`` rebinds
    ``_workspace_mtimes`` here, and tests patch it under that name.
    """

    def read() -> tuple[list[str] | None, dict[str, Any]]:
        # One lookup, reused for the replan prompt: it is a git diff of the green.
        green = _changed_in_green(live_root) if attempt > 1 or in_live_repo else None
        if in_live_repo:
            return green, _live_repo_workspace_mtimes(live_root)
        return green, _workspace_mtimes(work_dir)

    return await off_loop("delegation.attempt_baseline", read)


def _live_repo_result_summary(result_text_parts: list[str], changed_files: list[str]) -> str:
    worker_line = _worker_summary_line(result_text_parts)
    shown = changed_files[:8]
    files_str = ", ".join(shown)
    if len(changed_files) > len(shown):
        files_str += f" (+{len(changed_files) - len(shown)} more)"
    # The change is in green, not the running Thomas; saying "live" here told you
    # a fix was in place when it was waiting for your approval.
    base = f"Changed Thomas's code in a private copy: {files_str}. It reaches the running Thomas once you approve it."
    if worker_line and not all(name in worker_line for name in shown):
        return f"{base} {worker_line}"[:400]
    return base


# The visible header varies (N3: a green worker is told the truth), but the
# idempotency check below uses this invariant tail instead, so either header
# is recognised as "already added" regardless of which one is present.
_LIVE_REPO_REQUIREMENT_TAIL = "is not complete until you modify at least one non-ignored, tracked source/test/doc file"


def _live_repo_change_requirement(root: Path | None = None, *, in_green: bool | None = None) -> str:
    """The completion requirement; *in_green* when the caller already looked it up."""
    if in_green is None:
        in_green = root is not None and _changed_in_green(root) is not None
    header = (
        "SELF-FIX COMPLETION REQUIREMENT: this self-fix run"
        if in_green
        else "LIVE REPO COMPLETION REQUIREMENT: this self-development task"
    )
    return (
        f"{header} {_LIVE_REPO_REQUIREMENT_TAIL} with "
        "an allowed write tool such as diff.create (fs.write_file for a new file). "
        "Pure inspection does not count. "
        "Ignored/generated files such as thomas_test_results.jsonl, runtime/, output/, "
        "library/, node_modules/, and cache directories do not count. If a protected runtime file "
        "is blocked, make the smallest relevant unprotected test/doc change or report "
        "the blocker honestly."
    )


def _with_live_repo_change_requirement(prompt: str, root: Path | None = None, *, in_green: bool | None = None) -> str:
    text = str(prompt or "")
    if _LIVE_REPO_REQUIREMENT_TAIL in text:
        return text
    return f"{text}\n\n{_live_repo_change_requirement(root, in_green=in_green)}"
