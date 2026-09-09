"""Architecture-ledger debt pruning for evolve sessions.

Split out of ``evolve.py`` (2026-07-15) to keep the runtime under the
MONOLITH_CEILING. ``evolve.py`` re-exports ``_sync_architecture_health_debt``,
so existing imports keep working.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any

from .evolve_charter import _normalize_relpath, _sha256


def _module_debt_nodes(source: str) -> list[tuple[str, ast.Constant]]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    out: list[tuple[str, ast.Constant]] = []
    for node in tree.body:
        if not isinstance(node, ast.Assign) or not any(
            isinstance(target, ast.Name) and target.id == "MODULES" for target in node.targets
        ):
            continue
        if not isinstance(node.value, ast.Dict):
            continue
        for key, value in zip(node.value.keys, node.value.values, strict=False):
            if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                continue
            if not isinstance(value, ast.Dict):
                continue
            for item_key, item_value in zip(value.keys, value.values, strict=False):
                if (
                    isinstance(item_key, ast.Constant)
                    and item_key.value == "debt"
                    and isinstance(item_value, ast.Constant)
                    and isinstance(item_value.value, str)
                ):
                    out.append((key.value, item_value))
    return out


def _architecture_soft_limit(source: str) -> int:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return 800
    for node in tree.body:
        if not isinstance(node, ast.Assign) or not any(
            isinstance(target, ast.Name) and target.id == "RULES" for target in node.targets
        ):
            continue
        try:
            rules = ast.literal_eval(node.value)
        except (SyntaxError, ValueError):
            return 800
        if isinstance(rules, dict):
            try:
                return int(rules.get("max_new_file_lines") or 800)
            except (TypeError, ValueError):
                return 800
    return 800


_DEBT_SIZE_RE = re.compile(r"(?P<path>[\w\-/]+\.py)\s+(?:exceeds?|over)\s+\d+\s+lines", re.IGNORECASE)


def _remove_debt_match(text: str, match: re.Match[str]) -> str:
    start, end = match.span()
    left = max(text.rfind(",", 0, start), text.rfind(";", 0, start))
    right_candidates = [pos for pos in (text.find(",", end), text.find(";", end)) if pos != -1]
    right = min(right_candidates) if right_candidates else -1
    if left == -1:
        remove_start = 0
        remove_end = right + 1 if right != -1 else end
    else:
        remove_start = left
        remove_end = end
    next_text = text[:remove_start] + text[remove_end:]
    next_text = re.sub(r"\s*([,;])\s*", r"\1 ", next_text)
    next_text = re.sub(r"\s{2,}", " ", next_text)
    return next_text.strip(" ,;")


def _prune_stale_debt_note(
    module_root: Path,
    debt: str,
    *,
    soft_limit: int,
    eligible_paths: set[str],
) -> tuple[str, list[str]]:
    next_debt = str(debt or "")
    removed: list[str] = []
    while True:
        stale: re.Match[str] | None = None
        for match in _DEBT_SIZE_RE.finditer(next_debt):
            rel = _normalize_relpath(match.group("path"))
            if rel not in eligible_paths:
                continue
            candidate = module_root / rel
            if not candidate.exists():
                continue
            try:
                line_count = len(candidate.read_text(encoding="utf-8", errors="replace").splitlines())
            except OSError:
                continue
            if line_count <= int(soft_limit):
                stale = match
                removed.append(rel)
                break
        if stale is None:
            break
        next_debt = _remove_debt_match(next_debt, stale)
    return next_debt, removed


def _sync_architecture_health_debt(paths, changed_files: set[str]) -> dict[str, Any]:
    """Prune stale architecture debt notes after a green refactor.

    The agent must not edit ``thomas/_architecture.py`` directly. This helper
    only runs when that file still matches blue, and only removes stale
    ``file.py exceeds N lines`` fragments for files changed by this session and
    now under the soft limit.
    """
    rel = "thomas/_architecture.py"
    blue_path = paths.blue_root / rel
    green_path = paths.green_root / rel
    if not blue_path.exists() or not green_path.exists():
        return {"changed_files": [], "removed": []}
    try:
        if _sha256(blue_path) != _sha256(green_path):
            return {"changed_files": [], "removed": [], "skipped_reason": "architecture_already_changed"}
    except OSError:
        return {"changed_files": [], "removed": [], "skipped_reason": "architecture_unreadable"}

    changed_by_module: dict[str, set[str]] = {}
    for item in changed_files:
        normalized = _normalize_relpath(item)
        parts = normalized.split("/", 2)
        if len(parts) < 3 or parts[0] != "thomas" or not parts[2].endswith(".py"):
            continue
        changed_by_module.setdefault(parts[1], set()).add(parts[2])
    if not changed_by_module:
        return {"changed_files": [], "removed": []}

    source = green_path.read_text(encoding="utf-8")
    soft_limit = _architecture_soft_limit(source)
    lines = source.splitlines(keepends=True)
    replacements: list[tuple[int, int, int, str]] = []
    removed: list[dict[str, str]] = []
    for module_name, node in _module_debt_nodes(source):
        eligible_paths = changed_by_module.get(module_name, set())
        if not eligible_paths:
            continue
        if node.lineno != node.end_lineno:
            continue
        module_root = paths.green_root / "thomas" / module_name
        new_debt, removed_refs = _prune_stale_debt_note(
            module_root,
            str(node.value),
            soft_limit=soft_limit,
            eligible_paths=eligible_paths,
        )
        if not removed_refs or new_debt == node.value:
            continue
        replacements.append((node.lineno - 1, node.col_offset, node.end_col_offset, json.dumps(new_debt)))
        removed.extend({"module": module_name, "path": item} for item in removed_refs)

    for line_idx, start, end, replacement in sorted(replacements, reverse=True):
        lines[line_idx] = lines[line_idx][:start] + replacement + lines[line_idx][end:]
    if not replacements:
        return {"changed_files": [], "removed": []}
    green_path.write_text("".join(lines), encoding="utf-8")
    return {"changed_files": [rel], "removed": removed}
