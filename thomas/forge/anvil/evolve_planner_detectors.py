"""Deterministic detectors that survey Thomas and propose evolve goals.

Each detector reads cheap signals (file scans, the health ledger) and returns
candidate goals for one category. ``collect_candidates`` runs them all; the
facade (``evolve_planner``) ranks and trims the result. No model calls -- this
is the deterministic floor the loop can always fall back on.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from .evolve_planner_models import EvolveGoal, goal_id, now_iso
from .health_ledger import build_review_queue, load_health_ledger
from .refactor_pass import HARD_LIMIT, SOFT_LIMIT, detect_oversized_files

logger = logging.getLogger(__name__)

# Conservative heuristics -- they err toward *flagging a category to work on*,
# not toward making the change themselves. The agent pass does the real audit.
_BARE_EXCEPT_RE = re.compile(r"except\s+Exception\s*:|except\s*:")
_SECURITY_MARKERS = (
    "shell=True",
    "# nosec",
    "verify=False",
    "eval(",
    "pickle.loads",
    "yaml.load(",
    "md5(",
)
_XFAIL_RE = re.compile(r"xfail|@pytest\.mark\.skip")
_TODO_RE = re.compile(r"#\s*(TODO|FIXME|HACK|XXX)\b")

# Bound the scan so planning stays fast on a large tree.
_MAX_SCAN_FILES = 600


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


def _count_substrings(files: list[tuple[str, str]], needles: tuple[str, ...]) -> tuple[int, list[str]]:
    total = 0
    hot: list[tuple[int, str]] = []
    for rel, text in files:
        n = sum(text.count(needle) for needle in needles)
        if n:
            total += n
            hot.append((n, rel))
    hot.sort(reverse=True)
    return total, [rel for _n, rel in hot[:8]]


def _detect_refactor(project_root: Path, signals: dict[str, Any]) -> list[EvolveGoal]:
    goals: list[EvolveGoal] = []
    oversized = detect_oversized_files(project_root)
    signals["oversized_files"] = len(oversized)
    for f in sorted(oversized, key=lambda x: -int(x["line_count"]))[:3]:
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
    review_queue = build_review_queue(project_root, ledger, min_lines=SOFT_LIMIT)
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


def _detect_reliability(thomas_files: list[tuple[str, str]], signals: dict[str, Any]) -> list[EvolveGoal]:
    count, hot = _count_matches(thomas_files, _BARE_EXCEPT_RE)
    signals["bare_except_handlers"] = count
    if count < 8:
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


def _detect_security(thomas_files: list[tuple[str, str]], signals: dict[str, Any]) -> list[EvolveGoal]:
    count, hot = _count_substrings(thomas_files, _SECURITY_MARKERS)
    signals["security_markers"] = count
    if count <= 0:
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


def _detect_tests(project_root: Path, signals: dict[str, Any]) -> list[EvolveGoal]:
    test_files = _iter_py_text(project_root, "tests")
    count, hot = _count_matches(test_files, _XFAIL_RE)
    signals["xfail_markers"] = count
    if count < 4:
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


def _detect_features(thomas_files: list[tuple[str, str]], signals: dict[str, Any]) -> list[EvolveGoal]:
    count, hot = _count_matches(thomas_files, _TODO_RE)
    signals["todo_markers"] = count
    if count < 5:
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
    signals["scanned_py_files"] = len(thomas_files)
    candidates: list[EvolveGoal] = []
    detectors: list[tuple[str, Any]] = [
        ("refactor", lambda: _detect_refactor(project_root, signals)),
        ("reliability", lambda: _detect_reliability(thomas_files, signals)),
        ("security", lambda: _detect_security(thomas_files, signals)),
        ("tests", lambda: _detect_tests(project_root, signals)),
        ("features", lambda: _detect_features(thomas_files, signals)),
    ]
    for name, run in detectors:
        try:
            candidates.extend(run())
        except (OSError, ValueError, KeyError) as exc:
            logger.warning("evolve planner detector %s failed (non-fatal): %s", name, exc)
    return candidates
