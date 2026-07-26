"""Workspace snapshots used to verify delegated worker deliverables."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
log = logging.getLogger(__name__)


def ensure_task_workspace(execution_id: str) -> Path:
    """Return a per-task workspace outside the source repo when possible."""
    safe_id = "".join(ch for ch in str(execution_id or "") if ch.isalnum() or ch in "-_") or "task"
    base = Path.home() / ".thomas" / "workspaces" / safe_id
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError:
        base = (ROOT / "runtime" / "workspaces" / safe_id).resolve()
        base.mkdir(parents=True, exist_ok=True)
    return base


def seed_workspace_from_previous(
    work_dir: Path,
    session_id: str,
    *,
    exclude_execution_id: str = "",
    repo_root: str | Path | None = None,
    max_files: int = 24,
    max_bytes: int = 20_000_000,
) -> list[str]:
    """Copy the latest finished deliverables of this chat session into a new workspace.

    A follow-up like "add a 6th row to it" spawns a FRESH worker whose empty
    workspace cannot see the CSV made one turn earlier — the worker then asks
    the user to upload the file it just delivered. Seeding the new workspace
    with the previous execution's files makes follow-ups actually continuous.
    """
    import shutil

    from thomas.core import task_bot_runtime

    sid = str(session_id or "").strip()
    if not sid:
        return []
    try:
        rows = task_bot_runtime.list_executions(repo_root, refresh=False)
    except (OSError, RuntimeError, ValueError, TypeError):
        return []
    candidates = [
        row
        for row in rows
        if str(row.get("conversation_id") or "") == sid
        and str(row.get("execution_id") or "") not in ("", str(exclude_execution_id or ""))
        and str(row.get("state") or "").lower() in {"completed", "complete", "verified", "succeeded", "done"}
    ]
    candidates.sort(key=lambda row: str(row.get("updated_at") or row.get("created_at") or ""), reverse=True)
    copied: list[str] = []
    for row in candidates:
        prev_dir = ensure_task_workspace(str(row.get("execution_id") or ""))
        files = snapshot_workspace_files(prev_dir, limit=max_files)
        if not files:
            continue
        budget = max_bytes
        for rel in files:
            src = prev_dir / rel
            dst = Path(work_dir) / rel
            try:
                size = src.stat().st_size
                if size > budget:
                    continue
                dst.parent.mkdir(parents=True, exist_ok=True)
                if not dst.exists():
                    shutil.copy2(src, dst)
                    budget -= size
                    copied.append(rel)
            except OSError as exc:
                log.debug("workspace seed copy failed for %s: %s", rel, exc)
        if copied:
            log.info("Seeded follow-up workspace with %d file(s) from %s", len(copied), row.get("execution_id"))
            break
    return copied


def snapshot_workspace_files(work_dir: Path | None, *, limit: int = 24) -> list[str]:
    """List real, non-hidden deliverable files relative to a worker workspace."""

    if work_dir is None:
        return []
    base = Path(work_dir)
    if not base.exists() or not base.is_dir():
        return []
    files: list[str] = []
    try:
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(base)
            if any(part.startswith(".") for part in rel.parts):
                continue
            files.append(rel.as_posix())
            if len(files) >= limit:
                break
    except (OSError, RuntimeError, ValueError) as exc:
        log.debug("workspace snapshot error in %s: %s", work_dir, exc)
    return files


def workspace_mtimes(
    work_dir: Path | None,
    *,
    ignored_prefixes: tuple[str, ...] = (),
    ignored_parts: frozenset[str] = frozenset(),
) -> dict[str, tuple[int, int]]:
    """Map workspace files to mtime and size while honoring ignored paths."""

    out: dict[str, tuple[int, int]] = {}
    if work_dir is None:
        return out
    base = Path(work_dir)
    if not base.exists() or not base.is_dir():
        return out
    normalized_prefixes = tuple(str(prefix or "").replace("\\", "/").lstrip("/") for prefix in ignored_prefixes)

    def ignored_rel(rel: str) -> bool:
        rel = rel.replace("\\", "/").lstrip("/")
        if not rel:
            return False
        if any(part in ignored_parts for part in rel.split("/")):
            return True
        return any(rel.startswith(prefix) for prefix in normalized_prefixes if prefix)

    try:
        for root, dirs, files in os.walk(base):
            root_path = Path(root)
            try:
                rel_root = "" if root_path == base else root_path.relative_to(base).as_posix().rstrip("/") + "/"
            except ValueError:
                continue
            dirs[:] = [
                dirname
                for dirname in dirs
                if not dirname.startswith(".")
                and dirname not in ignored_parts
                and not ignored_rel(rel_root + dirname + "/")
            ]
            for filename in files:
                if filename.startswith("."):
                    continue
                path = root_path / filename
                rel = path.relative_to(base)
                if any(part.startswith(".") for part in rel.parts):
                    continue
                rel_posix = rel.as_posix()
                if ignored_rel(rel_posix):
                    continue
                try:
                    stat = path.stat()
                    out[rel_posix] = (stat.st_mtime_ns, stat.st_size)
                except OSError:
                    continue
    except (OSError, RuntimeError, ValueError) as exc:
        log.debug("workspace mtimes walk error in %s: %s", work_dir, exc)
    return out


def files_changed_since(
    work_dir: Path | None,
    baseline: dict[str, tuple[int, int]],
    *,
    limit: int = 24,
) -> list[str]:
    """Return files created or modified since a workspace baseline."""

    after = workspace_mtimes(work_dir)
    return sorted(filename for filename, metadata in after.items() if baseline.get(filename) != metadata)[:limit]


# A self-contained NEW build: a build verb + "a/an" + a deliverable noun. This is
# the one case where files from earlier in the conversation are certainly
# irrelevant, so it is the only thing that suppresses seeding.
_FRESH_BUILD_RE = re.compile(
    r"^\s*(?:please\s+|can you\s+|could you\s+|i(?:'?d| would)?\s+(?:like|want|need)\s+(?:you\s+to\s+)?)*"
    r"(?:make|build|create|write|generate|design|develop|code|implement|produce|draw|render|scaffold)\s+"
    r"(?:me\s+)?(?:a|an)\s+(?:\w+[\s-]+){0,3}"
    r"(?:app|application|game|page|website|site|webpage|web[\s-]*app|script|tool|dashboard|form|"
    r"component|widget|api|server|bot|landing[\s-]*page|report|document|spreadsheet|chart|graph|"
    r"diagram|slideshow|presentation|story|poem|essay|article|cli|extension|plugin|calculator|"
    r"timer|clock|quiz|survey|chatbot|portfolio|blog|store|shop|simulator|visuali[sz]er|tracker|"
    r"generator|editor|viewer|player|browser|terminal|notebook|wiki|forum|gallery|map)\b",
    re.IGNORECASE,
)
# "the second one", "that list" — a reference to an earlier result, which is a
# genuine follow-up even when phrased like a fresh build.
_LIST_REF_RE = re.compile(
    r"^\s*(?:the\s+)?(?:first|second|third|fourth|fifth|last|next|previous|other)\b"
    r"|^\s*(?:that|those|these|this)\s+(?:one|list|file|chart|table|item)s?\b",
    re.IGNORECASE,
)


def prompt_allows_workspace_seed(prompt: str) -> bool:
    """Whether earlier deliverables should be COPIED into this task's workspace.

    Deliberately more permissive than ``prompt_needs_handoff``, because the two
    decisions carry opposite risk. Attaching the prior conversation can make a
    worker build the wrong thing, so that gate is strict and its docstring is
    right that a false negative is cheap there. Copying files is not that bet:
    a false positive leaves a few unused files in a scratch directory, while a
    false negative means the worker cannot SEE the file it was told to edit.

    Sharing the strict gate is why "change tuesday to 9 and add sat 7" failed.
    It is plainly about the chart from one turn earlier, but it names none of
    the pronouns the follow-up patterns look for, so nothing was copied, the
    worker opened an empty directory, produced nothing, and the run was
    recorded as failed(no_evidence) -- the second most common failure in the
    logs. "can you update that to include saturday" and "change the title"
    failed the same way.

    So: copy unless the request is a self-contained NEW build.
    """
    text = str(prompt or "").strip()
    if not text:
        return False
    return not (_FRESH_BUILD_RE.match(text) and not _LIST_REF_RE.match(text))
