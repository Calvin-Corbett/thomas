"""Claim, path, and batching helpers for maintenance checkpoints."""

from __future__ import annotations

import importlib
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    agent_commit_module = importlib.import_module("scripts.agent_commit")
    agent_safety_module = importlib.import_module("scripts.agent_safety_config")
    protected_files_gate = importlib.import_module("scripts.check_protected_files_gate")
except (ImportError, ModuleNotFoundError):  # pragma: no cover
    agent_commit_module = importlib.import_module("agent_commit")
    agent_safety_module = importlib.import_module("agent_safety_config")
    protected_files_gate = importlib.import_module("check_protected_files_gate")

load_config = agent_safety_module.load_config
DEFAULT_BATCH_MAX_FILES = 50


def _normalize_repo_path(path: str) -> str:
    normalized = str(path or "").strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    while "//" in normalized:
        normalized = normalized.replace("//", "/")
    return normalized.strip("/")


def _git_status_paths(root: Path) -> list[str]:
    git_path = shutil.which("git")
    if not git_path:
        raise RuntimeError("git is not available on PATH")
    proc = subprocess.run(
        [git_path, "status", "--porcelain=v1", "-z", "-uall"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(str(proc.stderr or "").strip() or "git status --porcelain=v1 -z -uall failed")
    changed: list[str] = []
    entries = str(proc.stdout or "").split("\0")
    index = 0
    while index < len(entries):
        entry = str(entries[index] or "")
        if not entry:
            index += 1
            continue
        status = entry[:2]
        token = entry[3:] if len(entry) > 3 else entry
        if ("R" in status or "C" in status) and index + 1 < len(entries) and str(entries[index + 1] or ""):
            token = str(entries[index + 1] or "")
            index += 1
        normalized = str(token or "").strip().replace("\\", "/")
        while normalized.startswith("./"):
            normalized = normalized[2:]
        normalized = normalized.strip("/")
        if normalized and normalized not in changed:
            changed.append(normalized)
        index += 1
    return changed


def _maintenance_ignore_prefixes() -> tuple[str, ...]:
    config = load_config()
    return tuple(
        _normalize_repo_path(prefix)
        for prefix in config.worktree_maintenance_ignore_prefixes()
        if _normalize_repo_path(prefix)
    )


def _split_ignored_paths(paths: list[str]) -> tuple[list[str], list[str]]:
    ignore_prefixes = _maintenance_ignore_prefixes()
    included: list[str] = []
    ignored: list[str] = []
    for path in paths:
        normalized = _normalize_repo_path(path)
        if not normalized:
            continue
        should_ignore = False
        for prefix in ignore_prefixes:
            if not prefix:
                continue
            if prefix.endswith("/"):
                if normalized == prefix.rstrip("/") or normalized.startswith(prefix):
                    should_ignore = True
                    break
            elif normalized.startswith(prefix):
                should_ignore = True
                break
        if should_ignore:
            ignored.append(normalized)
            continue
        included.append(normalized)
    return included, ignored


def _protected_category(path: str) -> str:
    classifier = getattr(protected_files_gate, "_protected_category", None)
    if callable(classifier):
        return str(classifier(path) or "").strip()
    return ""


def _checkpoint_path_is_blocked(path: str) -> bool:
    category = _protected_category(path)
    return category in {"immutable_policy", "enforcement"}


def _split_checkpointable_paths(paths: list[str]) -> tuple[list[str], list[str]]:
    eligible: list[str] = []
    blocked: list[str] = []
    for path in paths:
        normalized = str(path or "").strip()
        if not normalized:
            continue
        if _checkpoint_path_is_blocked(normalized):
            blocked.append(normalized)
        else:
            eligible.append(normalized)
    return eligible, blocked


def _resolve_active_claim_scopes(agent: str, workboard_path: Path) -> tuple[str, ...]:
    resolver = getattr(agent_commit_module, "_resolve_active_claim", None)
    if not callable(resolver):
        raise RuntimeError("agent_commit._resolve_active_claim is unavailable")
    claim = resolver(agent, workboard_path)
    scopes = tuple(str(scope or "").strip() for scope in getattr(claim, "scopes", ()) if str(scope or "").strip())
    if not scopes:
        raise ValueError(f"agent '{agent}' has no active claim scopes in {workboard_path}")
    return scopes


def _path_matches_claim_scopes(path: str, claim_scopes: tuple[str, ...]) -> bool:
    matcher = getattr(agent_commit_module, "_scope_matches_path", None)
    normalized_path = _normalize_repo_path(path)
    if not normalized_path:
        return False
    if callable(matcher):
        return any(bool(matcher(scope, normalized_path)) for scope in claim_scopes)
    normalized_scopes = {_normalize_repo_path(scope) for scope in claim_scopes if _normalize_repo_path(scope)}
    return normalized_path in normalized_scopes


def _split_claimed_paths(paths: list[str], claim_scopes: tuple[str, ...]) -> tuple[list[str], list[str]]:
    claimed: list[str] = []
    unclaimed: list[str] = []
    for path in paths:
        normalized = _normalize_repo_path(path)
        if not normalized:
            continue
        if _path_matches_claim_scopes(normalized, claim_scopes):
            claimed.append(normalized)
        else:
            unclaimed.append(normalized)
    return claimed, unclaimed


def _batch_scope_key(path: str) -> str:
    parts = Path(path).parts
    if not parts:
        return "<root>"
    if len(parts) == 1:
        return parts[0]
    if parts[0] in {"thomas", "tests"} and len(parts) >= 3:
        return f"{parts[0]}/{parts[1]}"
    return parts[0]


def _checkpoint_batches(paths: list[str], *, max_files: int = DEFAULT_BATCH_MAX_FILES) -> list[list[str]]:
    deduped = list(dict.fromkeys(str(path or "").strip() for path in paths if str(path or "").strip()))
    grouped: dict[str, list[str]] = {}
    for path in deduped:
        grouped.setdefault(_batch_scope_key(path), []).append(path)
    ordered = sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0]))
    batches: list[list[str]] = []
    for _scope, scope_paths in ordered:
        chunk = list(dict.fromkeys(scope_paths))
        for start in range(0, len(chunk), max_files):
            batches.append(chunk[start : start + max_files])
    return batches


def _structured_gate_output(raw: str) -> dict[str, Any] | None:
    payload = str(raw or "").strip()
    if not payload:
        return None
    try:
        value = json.loads(payload)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _group_retry_paths(paths: list[str]) -> list[list[str]]:
    if not paths:
        return []
    return _checkpoint_batches(paths, max_files=DEFAULT_BATCH_MAX_FILES)


def _split_growth_guard_batch(batch: list[str], gate_output: str) -> tuple[list[list[str]], list[dict[str, Any]]]:
    structured = _structured_gate_output(gate_output)
    if not structured:
        return [], []
    raw_violations = structured.get("violations")
    if not isinstance(raw_violations, list) or not raw_violations:
        return [], []
    batch_set = {_normalize_repo_path(path) for path in batch if _normalize_repo_path(path)}
    violations: list[dict[str, Any]] = []
    violating_paths: set[str] = set()
    for raw in raw_violations:
        if not isinstance(raw, dict):
            continue
        path = _normalize_repo_path(str(raw.get("path") or ""))
        if not path or path not in batch_set:
            continue
        normalized = dict(raw)
        normalized["path"] = path
        suggestions = normalized.get("suggested_split_paths")
        if isinstance(suggestions, list):
            normalized["suggested_split_paths"] = [
                _normalize_repo_path(str(item or "")) for item in suggestions if _normalize_repo_path(str(item or ""))
            ]
        violations.append(normalized)
        violating_paths.add(path)
    if not violations:
        return [], []
    retry_paths = [_normalize_repo_path(path) for path in batch if _normalize_repo_path(path) not in violating_paths]
    return _group_retry_paths(retry_paths), violations


def _batch_changed_lines(*, total_changed_lines: int, batch_size: int, total_paths: int, is_last: bool) -> int:
    if total_changed_lines <= 0 or batch_size <= 0 or total_paths <= 0:
        return 0
    if is_last:
        return max(total_changed_lines, 0)
    proportional = math.ceil(total_changed_lines * (batch_size / total_paths))
    return max(proportional, 1)
