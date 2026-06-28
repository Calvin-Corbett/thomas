from __future__ import annotations

import hashlib
import re
from pathlib import Path

from thomas.server.chat_delegation_deliverable import (
    _FAILURE_LANGUAGE_RE,
    _claims_action_success,
    _claims_file_creation,
    _worker_summary_line,
    _workspace_mtimes,
)

_LIVE_REPO_IGNORE_PREFIXES = (
    "library/",
    "runtime/",
    "output/",
    "plans/thomas/chat_stress_",
)
_LIVE_REPO_IGNORE_PARTS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "node_modules"}
_LIVE_REPO_IGNORE_SUFFIXES = ("_test_results.jsonl",)
_LIVE_REPO_WRITE_TOOLS = {"fs.write_file", "fs.write_protected_file"}

_DOC_ONLY_EXTENSIONS = (".md", ".mdx", ".rst", ".adoc")
_DOC_ONLY_PREFIXES = ("docs/", "documentation/")
_IMPLEMENTATION_PROMPT_HINTS = (
    "api",
    "bug",
    "code",
    "endpoint",
    "endpoints",
    "fix",
    "implementation",
    "install",
    "route",
    "routes",
    "test",
    "tests",
    "ui",
)
_DOCUMENTATION_PROMPT_HINTS = ("doc", "docs", "documentation", "markdown", "readme")


def _prompt_has_hint(prompt_lower: str, hints: tuple[str, ...]) -> bool:
    return any(re.search(rf"\b{re.escape(hint)}\b", prompt_lower) for hint in hints)


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
        ignored_parts=frozenset(_LIVE_REPO_IGNORE_PARTS),
    )
    out: dict[str, tuple[int, str]] = {}
    for rel in mtime_markers:
        if _live_repo_change_ignored(rel):
            continue
        marker = _file_content_fingerprint(repo_root / rel)
        if marker is not None:
            out[rel] = marker
    return out


def _live_repo_files_changed_since(
    repo_root: Path, baseline: dict[str, tuple[int, str]], *, limit: int = 48
) -> list[str]:
    after = _live_repo_workspace_mtimes(repo_root)
    changed = [
        rel for rel, marker in after.items() if baseline.get(rel) != marker and not _live_repo_change_ignored(rel)
    ]
    return sorted(changed)[:limit]


def _live_repo_result_summary(result_text_parts: list[str], changed_files: list[str]) -> str:
    worker_line = _worker_summary_line(result_text_parts)
    shown = changed_files[:8]
    files_str = ", ".join(shown)
    if len(changed_files) > len(shown):
        files_str += f" (+{len(changed_files) - len(shown)} more)"
    base = f"Changed live Thomas files: {files_str}."
    if worker_line and not all(name in worker_line for name in shown):
        return f"{base} {worker_line}"[:400]
    return base


def _live_repo_changes_are_docs_only(changed_files: list[str]) -> bool:
    if not changed_files:
        return False
    for rel in changed_files:
        normalized = rel.replace("\\", "/").lower()
        if normalized.startswith(_DOC_ONLY_PREFIXES):
            continue
        if normalized.endswith(_DOC_ONLY_EXTENSIONS):
            continue
        return False
    return True


def _prompt_allows_docs_only_completion(prompt: str) -> bool:
    lower = str(prompt or "").lower()
    if _prompt_has_hint(lower, _IMPLEMENTATION_PROMPT_HINTS):
        return False
    return _prompt_has_hint(lower, _DOCUMENTATION_PROMPT_HINTS)


def _worker_text_is_confirmed_answer(result_text_parts: list[str]) -> bool:
    worker_line = _worker_summary_line(result_text_parts)
    if not worker_line:
        return False
    if _FAILURE_LANGUAGE_RE.search(worker_line):
        return False
    if _claims_file_creation(worker_line) or _claims_action_success(worker_line):
        return False
    return True
