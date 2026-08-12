"""Deterministic detectors that survey Thomas and propose evolve goals.

Each detector reads cheap signals (file scans, the health ledger) and returns
candidate goals for one category. ``collect_candidates`` runs them all; the
facade (``evolve_planner``) ranks and trims the result. No model calls -- this
is the deterministic floor the loop can always fall back on.
"""

from __future__ import annotations

import ast
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tomllib

from .doppelganger import SUPERVISOR_OWNED_PATHS, TEST_INFRA_FILES
from .evolve_planner_models import EvolveGoal, goal_id, now_iso
from .health_ledger import build_review_queue, load_health_ledger
from .refactor_pass import HARD_LIMIT, SOFT_LIMIT, detect_oversized_files

logger = logging.getLogger(__name__)

# Conservative heuristics -- they err toward *flagging a category to work on*,
# not toward making the change themselves. The agent pass does the real audit.
_BARE_EXCEPT_RE = re.compile(r"except\s+Exception\s*:|except\s*:")
_XFAIL_RE = re.compile(r"xfail|@pytest\.mark\.skip")
_TODO_RE = re.compile(r"#\s*(TODO|FIXME|HACK|XXX)\b")

# Bound the scan so planning stays fast on a large tree.
_MAX_SCAN_FILES = 600


@dataclass(frozen=True)
class TargetPolicy:
    blocked_paths: frozenset[str]
    blocked_prefixes: tuple[str, ...]


def _normalize_relpath(value: str | Path) -> str:
    return str(value or "").replace("\\", "/").lstrip("./")


def _load_target_policy(project_root: Path) -> TargetPolicy:
    """Return paths the green agent should not target before a supervisor exists."""
    blocked_paths = {_normalize_relpath(path) for path in SUPERVISOR_OWNED_PATHS}
    blocked_paths.update(_normalize_relpath(path) for path in TEST_INFRA_FILES)
    blocked_prefixes: set[str] = set()

    config_path = project_root / "agent_safety.toml"
    if config_path.exists():
        try:
            payload = tomllib.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            payload = {}
        project = payload.get("project") if isinstance(payload.get("project"), dict) else {}
        for test_dir in project.get("test_dirs") or payload.get("test_dirs") or []:
            norm = _normalize_relpath(str(test_dir or "")).rstrip("/")
            if norm:
                blocked_prefixes.add(f"{norm}/")
        protected = payload.get("protected")
        if isinstance(protected, dict):
            for key in ("policy_files", "guardrails_files", "enforcement_files", "enforcement_scripts"):
                rows = protected.get(key) or []
                if not isinstance(rows, list):
                    continue
                for item in rows:
                    norm = _normalize_relpath(str(item or "")).strip()
                    if norm:
                        blocked_paths.add(norm)

    return TargetPolicy(
        blocked_paths=frozenset(blocked_paths),
        blocked_prefixes=tuple(sorted(blocked_prefixes)),
    )


def _is_blocked_target(rel: str, policy: TargetPolicy) -> bool:
    norm = _normalize_relpath(rel)
    return norm in policy.blocked_paths or any(norm.startswith(prefix) for prefix in policy.blocked_prefixes)


def _filter_editable_paths(paths: list[str], policy: TargetPolicy) -> list[str]:
    return [path for path in paths if not _is_blocked_target(path, policy)]


def _filter_editable_files(files: list[tuple[str, str]], policy: TargetPolicy) -> list[tuple[str, str]]:
    return [(rel, text) for rel, text in files if not _is_blocked_target(rel, policy)]


def _iter_py_text(root: Path, subdir: str) -> list[tuple[str, str]]:
    base = root / subdir
    out: list[tuple[str, str]] = []
    if not base.exists():
        return out
    for path in sorted(base.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = str(path.relative_to(root)).replace("\\", "/")
        try:
            out.append((rel, path.read_text(encoding="utf-8", errors="replace")))
        except OSError:
            continue
        if len(out) >= _MAX_SCAN_FILES:
            break
    return out


def _count_matches(files: list[tuple[str, str]], pattern: re.Pattern[str]) -> tuple[int, list[str]]:
    total = 0
    hot: list[tuple[int, str]] = []
    for rel, text in files:
        n = len(pattern.findall(text))
        if n:
            total += n
            hot.append((n, rel))
    hot.sort(reverse=True)
    return total, [rel for _n, rel in hot[:8]]


def _qualified_call_name(node: ast.AST, aliases: dict[str, str]) -> str:
    if isinstance(node, ast.Name):
        return aliases.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        parent = _qualified_call_name(node.value, aliases)
        if parent:
            return f"{parent}.{node.attr}"
        return node.attr
    return ""


def _import_aliases(tree: ast.AST) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = str(alias.name or "").split(".", 1)[0]
                if root in {"builtins", "hashlib", "pickle", "yaml"}:
                    aliases[alias.asname or root] = root
        elif isinstance(node, ast.ImportFrom):
            module = str(node.module or "")
            if module not in {"builtins", "hashlib", "pickle", "yaml"}:
                continue
            for alias in node.names:
                if alias.name == "*":
                    continue
                aliases[alias.asname or alias.name] = f"{module}.{alias.name}"
    return aliases


def _literal_bool(node: ast.AST | None) -> bool | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, bool):
        return node.value
    return None


def _literal_str(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _is_builtins_eval_getattr_call(node: ast.Call, aliases: dict[str, str]) -> bool:
    if _qualified_call_name(node.func, aliases) != "getattr" or len(node.args) < 2:
        return False
    if _literal_str(node.args[1]) != "eval":
        return False
    target = node.args[0]
    if _qualified_call_name(target, aliases) in {"builtins", "__builtins__"}:
        return True
    return (
        isinstance(target, ast.Call)
        and _qualified_call_name(target.func, aliases) == "__import__"
        and bool(target.args)
        and _literal_str(target.args[0]) == "builtins"
    )


def _is_builtins_eval_subscript_call(node: ast.Call, aliases: dict[str, str]) -> bool:
    func = node.func
    return (
        isinstance(func, ast.Subscript)
        and _qualified_call_name(func.value, aliases) == "__builtins__"
        and _literal_str(func.slice) == "eval"
    )


def _count_security_markers_in_source(text: str) -> int:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return 0
    aliases = _import_aliases(tree)
    count = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        call_name = _qualified_call_name(node.func, aliases)
        if (
            call_name in {"eval", "builtins.eval", "pickle.loads", "yaml.load"}
            or _is_builtins_eval_getattr_call(node, aliases)
            or _is_builtins_eval_subscript_call(node, aliases)
        ):
            count += 1
        elif call_name in {"hashlib.md5", "md5"}:
            used_for_security = next(
                (_literal_bool(keyword.value) for keyword in node.keywords if keyword.arg == "usedforsecurity"),
                None,
            )
            if used_for_security is not False:
                count += 1
        for keyword in node.keywords:
            if (keyword.arg == "shell" and _literal_bool(keyword.value) is True) or (
                keyword.arg == "verify" and _literal_bool(keyword.value) is False
            ):
                count += 1
    return count


def _count_security_markers(files: list[tuple[str, str]]) -> tuple[int, list[str]]:
    total = 0
    hot: list[tuple[int, str]] = []
    for rel, text in files:
        n = _count_security_markers_in_source(text)
        if n:
            total += n
            hot.append((n, rel))
    hot.sort(reverse=True)
    return total, [rel for _n, rel in hot[:8]]


def _detect_refactor(project_root: Path, signals: dict[str, Any], policy: TargetPolicy) -> list[EvolveGoal]:
    goals: list[EvolveGoal] = []
    oversized = detect_oversized_files(project_root)
    signals["oversized_files"] = len(oversized)
    editable_oversized = [f for f in oversized if not _is_blocked_target(str(f.get("path") or ""), policy)]
    signals["editable_oversized_files"] = len(editable_oversized)
    signals["blocked_oversized_files"] = len(oversized) - len(editable_oversized)
    for f in sorted(editable_oversized, key=lambda x: -int(x["line_count"]))[:3]:
        path = f["path"]
        lines = int(f["line_count"])
        leverage = min(1.0, 0.55 + (lines - HARD_LIMIT) / (HARD_LIMIT * 3))
        goals.append(
            EvolveGoal(
                id=goal_id("refactor", path),
                category="refactor",
                title=f"Split oversized file {path} ({lines} lines)",
                rationale=(
                    f"{path} is {lines} lines, over the {HARD_LIMIT}-line hard limit. "
                    "Large files hide bugs and slow every future change."
                ),
                goal_prompt=(
                    f"Refactor the oversized file {path} ({lines} lines, hard limit {HARD_LIMIT}). "
                    "Split it into smaller cohesive modules with descriptive names and normal imports "
                    "(never *_part*.py, never exec). Preserve the public API so existing imports keep working. "
                    "Run py_compile on every file you touch."
                ),
                target_paths=[path],
                risk_tier="low",
                leverage=leverage,
                source="oversized_file",
                created_at=now_iso(),
            )
        )

    ledger = load_health_ledger(project_root)
    review_queue = [
        item
        for item in build_review_queue(project_root, ledger, min_lines=SOFT_LIMIT)
        if not _is_blocked_target(item["path"], policy)
    ]
    signals["stale_review_files"] = len(review_queue)
    if review_queue:
        top = [item["path"] for item in review_queue[:6]]
        goals.append(
            EvolveGoal(
                id=goal_id("refactor", "stale-health"),
                category="refactor",
                title=f"Code-health review of {len(review_queue)} stale file(s)",
                rationale=(
                    f"{len(review_queue)} file(s) over {SOFT_LIMIT} lines have not been "
                    "reviewed recently. Stale large files accumulate quiet rot."
                ),
                goal_prompt=(
                    "Run a code-health review on these stale files and fix what you safely can "
                    "(error handling, type hints, extracting overly long functions, replacing print with logging): "
                    + ", ".join(top)
                ),
                target_paths=top,
                risk_tier="low",
                leverage=0.42,
                source="ledger_stale",
                created_at=now_iso(),
            )
        )
    return goals


def _detect_reliability(
    thomas_files: list[tuple[str, str]], signals: dict[str, Any], policy: TargetPolicy
) -> list[EvolveGoal]:
    total_count, _all_hot = _count_matches(thomas_files, _BARE_EXCEPT_RE)
    count, hot = _count_matches(_filter_editable_files(thomas_files, policy), _BARE_EXCEPT_RE)
    signals["bare_except_handlers"] = total_count
    signals["editable_bare_except_handlers"] = count
    if count < 8 or not hot:
        return []
    leverage = min(0.78, 0.3 + count / 120.0)
    return [
        EvolveGoal(
            id=goal_id("reliability", "silent-failures"),
            category="reliability",
            title=f"Harden {count} broad/silent exception handler(s)",
            rationale=(
                f"Found {count} broad 'except Exception:'/'except:' handlers. "
                "Silent catches hide production failures and make incidents undebuggable."
            ),
            goal_prompt=(
                "Improve reliability by auditing broad exception handlers in the listed modules. "
                "For each, either narrow the caught type or add logger.exception() plus a short comment "
                "explaining why the broad catch is safe. Do not weaken behavior. Focus files: " + ", ".join(hot)
            ),
            target_paths=hot,
            risk_tier="low",
            leverage=leverage,
            source="bare_except_scan",
            created_at=now_iso(),
        )
    ]


def _detect_security(
    thomas_files: list[tuple[str, str]], signals: dict[str, Any], policy: TargetPolicy
) -> list[EvolveGoal]:
    total_count, _all_hot = _count_security_markers(thomas_files)
    count, hot = _count_security_markers(_filter_editable_files(thomas_files, policy))
    signals["security_markers"] = total_count
    signals["editable_security_markers"] = count
    if count <= 0 or not hot:
        return []
    leverage = min(0.92, 0.5 + count / 40.0)
    return [
        EvolveGoal(
            id=goal_id("security", "hardening-sweep"),
            category="security",
            title=f"Security hardening sweep ({count} risk marker(s))",
            rationale=(
                f"Detected {count} potential risk marker(s) (shell=True, eval, verify=False, "
                "unsafe deserialization, weak hashes). Each is a candidate vulnerability."
            ),
            goal_prompt=(
                "Run a security hardening pass over the listed modules. Audit each flagged construct "
                "(shell=True, eval, verify=False, pickle/yaml.load, md5) and remediate where safe: "
                "use argument lists instead of shell strings, validate inputs, enable TLS verification, "
                "switch to safe loaders/strong hashes. Never disable a guard to make a check pass. Focus files: "
                + ", ".join(hot)
            ),
            target_paths=hot,
            risk_tier="high",
            leverage=leverage,
            source="security_marker_scan",
            created_at=now_iso(),
        )
    ]


def _detect_tests(project_root: Path, signals: dict[str, Any], policy: TargetPolicy) -> list[EvolveGoal]:
    test_files = _iter_py_text(project_root, "tests")
    total_count, _all_hot = _count_matches(test_files, _XFAIL_RE)
    count, hot = _count_matches(_filter_editable_files(test_files, policy), _XFAIL_RE)
    signals["xfail_markers"] = total_count
    signals["editable_xfail_markers"] = count
    if count < 4 or not hot:
        return []
    leverage = min(0.7, 0.3 + count / 90.0)
    return [
        EvolveGoal(
            id=goal_id("tests", "xfail-debt"),
            category="tests",
            title=f"Pay down {count} xfail/skip test marker(s)",
            rationale=(
                f"{count} test(s) are marked xfail/skip. Each is a deferred failure that "
                "erodes the safety net the evolve loop itself relies on to promote safely."
            ),
            goal_prompt=(
                "Reduce test debt: pick a handful of xfail/skip-marked tests in the listed files, "
                "fix the underlying code or test so they pass, and remove the marker. "
                "Do not delete tests or weaken assertions to make them green. Focus files: " + ", ".join(hot)
            ),
            target_paths=hot,
            risk_tier="low",
            leverage=leverage,
            source="xfail_scan",
            created_at=now_iso(),
        )
    ]


def _detect_features(
    thomas_files: list[tuple[str, str]], signals: dict[str, Any], policy: TargetPolicy
) -> list[EvolveGoal]:
    total_count, _all_hot = _count_matches(thomas_files, _TODO_RE)
    count, hot = _count_matches(_filter_editable_files(thomas_files, policy), _TODO_RE)
    signals["todo_markers"] = total_count
    signals["editable_todo_markers"] = count
    if count < 5 or not hot:
        return []
    leverage = min(0.55, 0.25 + count / 200.0)
    return [
        EvolveGoal(
            id=goal_id("features", "todo-backlog"),
            category="features",
            title=f"Resolve high-value TODO/FIXME items ({count} found)",
            rationale=(
                f"{count} TODO/FIXME/HACK markers indicate unfinished work and known rough edges. "
                "Closing the high-value ones turns latent intent into shipped capability."
            ),
            goal_prompt=(
                "Survey the TODO/FIXME/HACK markers in the listed modules, pick the single highest-value "
                "item that is safe to complete in one pass, implement it end-to-end with a test, and remove "
                "the marker. Prefer user-visible capability over cosmetic cleanups. Focus files: " + ", ".join(hot)
            ),
            target_paths=hot,
            risk_tier="medium",
            leverage=leverage,
            source="todo_scan",
            created_at=now_iso(),
        )
    ]


def collect_candidates(project_root: Path, signals: dict[str, Any]) -> list[EvolveGoal]:
    """Run every detector and return all candidate goals (unranked).

    Each detector is independent; a failure in one must not sink the plan.
    """
    thomas_files = _iter_py_text(project_root, "thomas")
    policy = _load_target_policy(project_root)
    signals["scanned_py_files"] = len(thomas_files)
    signals["blocked_target_paths"] = len(policy.blocked_paths)
    candidates: list[EvolveGoal] = []
    detectors: list[tuple[str, Any]] = [
        ("refactor", lambda: _detect_refactor(project_root, signals, policy)),
        ("reliability", lambda: _detect_reliability(thomas_files, signals, policy)),
        ("security", lambda: _detect_security(thomas_files, signals, policy)),
        ("tests", lambda: _detect_tests(project_root, signals, policy)),
        ("features", lambda: _detect_features(thomas_files, signals, policy)),
    ]
    for name, run in detectors:
        try:
            candidates.extend(run())
        except (OSError, ValueError, KeyError) as exc:
            logger.warning("evolve planner detector %s failed (non-fatal): %s", name, exc)
    return candidates
