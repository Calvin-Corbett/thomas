"""Protected coordination helpers for the commit-master submission inbox."""

from __future__ import annotations

import importlib
import re
from pathlib import Path
from types import ModuleType
from typing import Any

ALWAYS_BLOCK_KINDS = frozenset({"blocker", "scope_change"})
PATH_TOKEN_RE = re.compile(r"(?:[A-Za-z0-9_.\-]+/)+[A-Za-z0-9_.\-]+")
SUBMISSION_HOLD_RE = re.compile(
    r"\b(?:do\s+not|don't|dont|stop|hold|pause|wait|block)\s+"
    r"(?:the\s+)?(?:submit|submission|commit|commits|land|landing|push|merge)\b"
    r"|\b(?:submit|submission|commit|commits|land|landing|push|merge)\s+"
    r"(?:(?:is|are)\s+)?(?:blocked|paused|held|on\s+hold)\b"
    r"|\back\s+before\s+(?:submit|submission|commit|land|landing|push|merge)\b"
    r"|\bread\b.*\b(?:before|prior\s+to)\s+"
    r"(?:submit|submission|commit|land|landing|push|merge)\b",
    re.IGNORECASE,
)


class InboxBlockedError(RuntimeError):
    """Raised when a worker tries to submit with unread messages."""

    def __init__(self, agent: str, blocking: list[dict[str, Any]]) -> None:
        self.agent = str(agent or "")
        self.blocking = list(blocking or [])
        super().__init__(f"{len(self.blocking)} unread coordination message(s) must be acked before submitting")


def _core_module(core: ModuleType | None) -> ModuleType:
    return core or importlib.import_module("scripts.forge.commit_master")


def paths_from_patch(patch_text: str) -> list[str]:
    """Extract changed repo paths from a unified diff's ``+++ b/<path>`` lines."""
    out: list[str] = []
    for line in str(patch_text or "").splitlines():
        if line.startswith("+++ b/"):
            path = line[6:].strip()
            if path and path != "/dev/null" and path not in out:
                out.append(path)
    return out


def submission_changed_files(
    repo: Path,
    patch_file: str | None,
    *,
    core: ModuleType | None = None,
) -> list[str]:
    """Return repo-relative paths in this submission."""
    owner = _core_module(core)
    if patch_file:
        try:
            return owner._paths_from_patch(Path(patch_file).read_text(encoding="utf-8", errors="replace"))
        except OSError:
            return []
    proc = owner._git(repo, "diff", "--cached", "--name-only")
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def norm_path(value: str) -> str:
    raw = str(value or "").strip().replace("\\", "/").strip("`'\" ")
    while raw.startswith("./"):
        raw = raw[2:]
    return raw.strip("/")


def paths_overlap(a: str, b: str, *, core: ModuleType | None = None) -> bool:
    owner = _core_module(core)
    left = owner._co_norm_path(a)
    right = owner._co_norm_path(b)
    if not left or not right:
        return False
    return left == right or left.startswith(right + "/") or right.startswith(left + "/")


def path_tokens(text: str, *, core: ModuleType | None = None) -> list[str]:
    owner = _core_module(core)
    text = str(text or "")
    out: list[str] = []
    for match in owner._PATH_TOKEN_RE.finditer(text):
        if text[: match.start()].rstrip().endswith("/"):
            continue
        token = match.group(0).strip("`'\"()[] ").rstrip(".,;:")
        if "://" in token or "@" in token:
            continue
        token = owner._co_norm_path(token)
        if token and "/" in token and token not in out:
            out.append(token)
    return out


def submission_hold(text: str, *, core: ModuleType | None = None) -> bool:
    owner = _core_module(core)
    return bool(owner._SUBMISSION_HOLD_RE.search(str(text or "")))


def active_task_scopes(workboard_text: str) -> dict[str, list[str]]:
    """Map ``task_id`` to scope paths from the Active Tasks section."""
    scopes: dict[str, list[str]] = {}
    in_section = False
    for line in workboard_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            in_section = stripped[3:].strip().lower().startswith("active tasks")
            continue
        if not in_section or not stripped.startswith("- "):
            continue
        fields: dict[str, str] = {}
        for part in [piece.strip() for piece in stripped[2:].split(";") if piece.strip()]:
            if "=" in part:
                key, value = part.split("=", 1)
                fields[key.strip().lower()] = value.strip()
        task_id = str(fields.get("task_id", "")).strip().lower()
        if task_id and task_id not in {"none", "_none_"}:
            scopes[task_id] = [seg.strip() for seg in str(fields.get("scope", "")).split(",") if seg.strip()]
    return scopes


def unread_messages(workboard: Path, agent: str, *, core: ModuleType | None = None) -> list[dict[str, Any]]:
    """Return open messages addressed to ``agent`` via the shared primitive."""
    owner = _core_module(core)
    try:
        from scripts.crew.workboard import message as message_mod
    except (ImportError, ModuleNotFoundError):
        return []
    fn = getattr(message_mod, "unread_messages", None)
    if fn is not None:
        ok, payload = fn(workboard, agent=agent)
    else:  # pragma: no cover - fallback if the helper is unavailable
        ok, payload = message_mod.list_messages(workboard, recipient=agent, state="open")
    return list(payload.get("messages") or []) if ok else []


def inbox_blocking(
    workboard: Path,
    agent: str,
    repo: Path,
    patch_file: str | None,
    *,
    core: ModuleType | None = None,
) -> list[dict[str, Any]]:
    """Return relevant unread messages that block this submission."""
    owner = _core_module(core)
    workboard = Path(workboard)
    if not workboard.exists() or not str(agent or "").strip():
        return []
    messages = owner._co_unread_messages(workboard, agent)
    if not messages:
        return []
    task_scopes = owner._co_active_task_scopes(workboard.read_text(encoding="utf-8"))
    changed = [owner._co_norm_path(path) for path in owner._submission_changed_files(repo, patch_file)]
    changed = [path for path in changed if path]
    blocking: list[dict[str, Any]] = []
    for msg in messages:
        kind = str(msg.get("kind", "")).strip().lower()
        reasons = [f"{kind} addressed to you (must-read)"] if kind in owner._ALWAYS_BLOCK_KINDS else []
        message_text = f"{msg.get('summary', '')} {msg.get('requested_action', '')}"
        if owner._co_submission_hold(message_text):
            reasons.append("submit/commit hold directive addressed to you")
        subject = list(task_scopes.get(str(msg.get("task_id", "")).strip().lower(), []))
        subject += owner._co_path_tokens(msg.get("summary", ""))
        subject += owner._co_path_tokens(msg.get("requested_action", ""))
        hits = sorted({path for path in changed for scope in subject if owner._co_paths_overlap(path, scope)})
        if hits:
            reasons.append("concerns paths you are committing: " + ", ".join(hits[:5]))
        if reasons:
            enriched = dict(msg)
            enriched["_reasons"] = reasons
            blocking.append(enriched)
    return blocking


def default_workboard(repo: Path) -> Path:
    return repo / "plans" / "thomas" / "WORKBOARD.md"
