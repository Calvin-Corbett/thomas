"""Blue-only candidate evaluator for Thomas evolve promotions.

This module deliberately avoids importing ``thomas`` or ``scripts``. The green
mirror can rewrite those trees, so the supervisor must re-derive trust-bearing
facts from the blue/green filesystem state with its own code.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import tomllib

from .coverage_floor import (
    execution_coverage_failures,
    normalize_relpath,
    select_blast_radius_tests,
)

DEFAULT_SCOPE_DIRS = ("thomas", "scripts", "tests", "definitions", "evolve_supervisor", "evolve_corpus")
DEFAULT_SCOPE_FILES = (
    "pyproject.toml",
    "README.md",
    "CHANGELOG.md",
    "thomas.toml",
    "pytest.ini",
    "run-ui.cmd",
    "run-repl.cmd",
    ".gitignore",
    "SOUL.md",
)
DEFAULT_SUPERVISOR_OWNED_PATHS = frozenset(
    {
        "thomas/forge/anvil/doppelganger.py",
        "thomas/forge/anvil/evolve.py",
        "thomas/forge/anvil/evolve_autonomy.py",
        "thomas/forge/anvil/evolve_loop.py",
    }
)
DEFAULT_RUNTIME_PROTECTED_PREFIXES = (
    "thomas/tools/",
    "thomas/agent/",
    "thomas/core/",
    "thomas/server/",
    "scripts/",
)
DEFAULT_RUNTIME_PROTECTED_FILES = frozenset(
    {
        "agent_safety.toml",
        "AGENTS.md",
        "GUARDRAILS.md",
        ".pre-commit-config.yaml",
        "pyproject.toml",
        "thomas.toml",
        "thomas.prod.toml",
        "runtime/.runtime_protection_disabled",
        "runtime/.runtime_protection_key",
        "runtime/.breakglass_window",
        "runtime/.breakglass_window_key",
    }
)
LOOP_PACKAGE_PREFIX = "thomas/forge/anvil/"
SUPERVISOR_PACKAGE_PREFIX = "evolve_supervisor/"
CORPUS_DIR = "evolve_corpus"
CORPUS_LOCK_FILE = "LOCK.json"
RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


@dataclass(frozen=True)
class TreeDelta:
    """Blue-to-green filesystem delta re-derived by the supervisor."""

    added: tuple[str, ...] = ()
    modified: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()

    @property
    def changed_files(self) -> tuple[str, ...]:
        return (*self.added, *self.modified, *self.removed)

    @property
    def changed_count(self) -> int:
        return len(self.changed_files)

    def to_dict(self) -> dict[str, Any]:
        return {
            "added": list(self.added),
            "modified": list(self.modified),
            "removed": list(self.removed),
            "changed_files": list(self.changed_files),
            "changed_count": self.changed_count,
        }


@dataclass(frozen=True)
class SupervisorFinding:
    """A supervisor-derived reason a candidate cannot be trusted."""

    code: str
    severity: str
    path: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "severity": self.severity,
            "path": self.path,
            "message": self.message,
        }


@dataclass(frozen=True)
class SupervisorVerdict:
    """Supervisor output. `session_payload` is never part of this decision."""

    ok: bool
    risk_floor: str
    delta: TreeDelta
    findings: tuple[SupervisorFinding, ...] = field(default_factory=tuple)
    ignored_session_keys: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "risk_floor": self.risk_floor,
            "delta": self.delta.to_dict(),
            "findings": [item.to_dict() for item in self.findings],
            "ignored_session_keys": list(self.ignored_session_keys),
        }


def _normalize_relpath(value: str | Path) -> str:
    return normalize_relpath(value)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _corpus_sha256(path: Path) -> str:
    """Hash locked text canonically across Git's LF/CRLF materialization."""

    payload = path.read_bytes()
    if path.suffix.lower() in {".json", ".md", ".txt"}:
        payload = payload.replace(b"\r\n", b"\n")
    return hashlib.sha256(payload).hexdigest()


def _corpus_lock_findings(candidate_root: Path) -> list[SupervisorFinding]:
    corpus_root = candidate_root / CORPUS_DIR
    lock_path = corpus_root / CORPUS_LOCK_FILE
    if not corpus_root.is_dir():
        return [
            SupervisorFinding(
                code="corpus_missing",
                severity="reject",
                path=CORPUS_DIR,
                message="frozen evolve corpus is missing",
            )
        ]
    if not lock_path.is_file():
        return [
            SupervisorFinding(
                code="corpus_lock_missing",
                severity="reject",
                path=f"{CORPUS_DIR}/{CORPUS_LOCK_FILE}",
                message="frozen evolve corpus lockfile is missing",
            )
        ]
    try:
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [
            SupervisorFinding(
                code="corpus_lock_invalid",
                severity="reject",
                path=f"{CORPUS_DIR}/{CORPUS_LOCK_FILE}",
                message=f"frozen evolve corpus lockfile is invalid: {exc}",
            )
        ]

    locked_files_raw = payload.get("files") if isinstance(payload, dict) else None
    if not isinstance(locked_files_raw, dict) or not locked_files_raw:
        return [
            SupervisorFinding(
                code="corpus_lock_empty",
                severity="reject",
                path=f"{CORPUS_DIR}/{CORPUS_LOCK_FILE}",
                message="frozen evolve corpus lockfile has no files",
            )
        ]

    findings: list[SupervisorFinding] = []
    locked: dict[str, str] = {}
    for raw_rel, raw_hash in locked_files_raw.items():
        rel = _normalize_relpath(str(raw_rel or "")).strip()
        expected = str(raw_hash or "").strip().lower()
        if (
            not rel
            or rel == CORPUS_LOCK_FILE
            or rel.startswith("../")
            or Path(rel).is_absolute()
            or ".." in Path(rel).parts
            or not expected
        ):
            findings.append(
                SupervisorFinding(
                    code="corpus_lock_invalid_entry",
                    severity="reject",
                    path=f"{CORPUS_DIR}/{rel}",
                    message="frozen evolve corpus lockfile contains an invalid entry",
                )
            )
            continue
        locked[rel] = expected

    actual_files: dict[str, Path] = {}
    for candidate in corpus_root.rglob("*"):
        if candidate.is_dir():
            continue
        rel = candidate.relative_to(corpus_root).as_posix()
        if rel == CORPUS_LOCK_FILE:
            continue
        actual_files[rel] = candidate

    for rel, expected in sorted(locked.items()):
        path = actual_files.get(rel)
        if path is None:
            findings.append(
                SupervisorFinding(
                    code="corpus_file_missing",
                    severity="reject",
                    path=f"{CORPUS_DIR}/{rel}",
                    message="frozen evolve corpus lockfile references a missing file",
                )
            )
            continue
        try:
            actual = _corpus_sha256(path)
        except OSError as exc:
            findings.append(
                SupervisorFinding(
                    code="corpus_file_unreadable",
                    severity="reject",
                    path=f"{CORPUS_DIR}/{rel}",
                    message=f"frozen evolve corpus file is unreadable: {exc}",
                )
            )
            continue
        if actual.lower() != expected:
            findings.append(
                SupervisorFinding(
                    code="corpus_hash_mismatch",
                    severity="reject",
                    path=f"{CORPUS_DIR}/{rel}",
                    message="frozen evolve corpus file hash does not match the lockfile",
                )
            )

    for rel in sorted(set(actual_files) - set(locked)):
        findings.append(
            SupervisorFinding(
                code="corpus_unlocked_file",
                severity="reject",
                path=f"{CORPUS_DIR}/{rel}",
                message="frozen evolve corpus contains a file not listed in the lockfile",
            )
        )
    return findings


def _iter_scope_files(root: Path) -> dict[str, Path]:
    files: dict[str, Path] = {}
    for item in DEFAULT_SCOPE_FILES:
        candidate = root / item
        if candidate.is_file():
            files[candidate.relative_to(root).as_posix()] = candidate
    for dirname in DEFAULT_SCOPE_DIRS:
        base = root / dirname
        if not base.exists():
            continue
        for candidate in base.rglob("*"):
            if candidate.is_dir():
                continue
            if candidate.name.endswith(".pyc"):
                continue
            if any(part in {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"} for part in candidate.parts):
                continue
            files[candidate.relative_to(root).as_posix()] = candidate
    return files


def collect_tree_delta(blue_root: Path, green_root: Path) -> TreeDelta:
    """Re-derive the candidate delta from blue and green trees."""
    blue_root = Path(blue_root)
    green_root = Path(green_root)
    blue = _iter_scope_files(blue_root)
    green = _iter_scope_files(green_root)

    added: list[str] = []
    modified: list[str] = []
    removed: list[str] = []
    for rel in sorted(set(blue) | set(green)):
        blue_path = blue.get(rel)
        green_path = green.get(rel)
        if blue_path is None and green_path is not None:
            added.append(rel)
        elif green_path is None and blue_path is not None:
            removed.append(rel)
        elif blue_path is not None and green_path is not None and _sha256(blue_path) != _sha256(green_path):
            modified.append(rel)
    return TreeDelta(added=tuple(added), modified=tuple(modified), removed=tuple(removed))


def _load_agent_safety_paths(blue_root: Path) -> tuple[frozenset[str], tuple[str, ...]]:
    blocked_paths = {
        *(_normalize_relpath(path) for path in DEFAULT_SUPERVISOR_OWNED_PATHS),
        *(_normalize_relpath(path) for path in DEFAULT_RUNTIME_PROTECTED_FILES),
    }
    blocked_paths.add("pytest.ini")
    blocked_prefixes = {"tests/", SUPERVISOR_PACKAGE_PREFIX, *DEFAULT_RUNTIME_PROTECTED_PREFIXES}

    config_path = blue_root / "agent_safety.toml"
    if not config_path.exists():
        return frozenset(blocked_paths), tuple(sorted(blocked_prefixes))

    try:
        payload = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return frozenset(blocked_paths), tuple(sorted(blocked_prefixes))

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
                if not norm:
                    continue
                if str(item).replace("\\", "/").endswith("/"):
                    blocked_prefixes.add(norm.rstrip("/") + "/")
                else:
                    blocked_paths.add(norm)
    return frozenset(blocked_paths), tuple(sorted(blocked_prefixes))


def _is_test_infra_path(rel: str, blocked_prefixes: tuple[str, ...]) -> bool:
    norm = _normalize_relpath(rel)
    if Path(norm).name == "conftest.py":
        return True
    return norm == "pytest.ini" or any(
        norm.startswith(prefix)
        for prefix in blocked_prefixes
        if prefix not in {LOOP_PACKAGE_PREFIX, SUPERVISOR_PACKAGE_PREFIX, *DEFAULT_RUNTIME_PROTECTED_PREFIXES}
    )


def _is_runtime_protected_relpath(rel: str) -> bool:
    norm = _normalize_relpath(rel)
    return norm in DEFAULT_RUNTIME_PROTECTED_FILES or any(
        norm.startswith(prefix) for prefix in DEFAULT_RUNTIME_PROTECTED_PREFIXES
    )


def _is_non_python_delta_path(rel: str) -> bool:
    norm = _normalize_relpath(rel)
    return bool(norm) and not norm.endswith(".py")


def _blast_radius_tests(changed_py: list[str], candidate_root: Path) -> list[str]:
    return select_blast_radius_tests(changed_py, candidate_root)


def _verification_floor_findings(delta: TreeDelta, blue_root: Path, candidate_root: Path) -> list[SupervisorFinding]:
    changed_py = [_normalize_relpath(rel) for rel in delta.changed_files if _normalize_relpath(rel).endswith(".py")]
    return [
        SupervisorFinding(
            code="verification_floor_missing",
            severity="reject",
            path="",
            message=failure,
        )
        for failure in execution_coverage_failures(
            changed_py,
            blue_root=blue_root,
            candidate_root=candidate_root,
        )
    ]


def _static_policy_findings(
    delta: TreeDelta,
    *,
    protected_paths: frozenset[str],
    blocked_prefixes: tuple[str, ...],
) -> tuple[list[SupervisorFinding], str]:
    findings: list[SupervisorFinding] = []
    risk_floor = "low"
    for rel in delta.changed_files:
        norm = _normalize_relpath(rel)
        if norm in protected_paths or _is_runtime_protected_relpath(norm):
            findings.append(
                SupervisorFinding(
                    code="protected_path_changed",
                    severity="reject",
                    path=norm,
                    message="candidate changes a protected path",
                )
            )
            risk_floor = _max_risk(risk_floor, "critical")
        if _is_test_infra_path(norm, blocked_prefixes):
            findings.append(
                SupervisorFinding(
                    code="test_infra_changed",
                    severity="reject",
                    path=norm,
                    message="candidate changes test infrastructure",
                )
            )
            risk_floor = _max_risk(risk_floor, "critical")
        if norm.startswith(LOOP_PACKAGE_PREFIX):
            risk_floor = _max_risk(risk_floor, "critical")
        if norm in delta.added and norm.startswith(LOOP_PACKAGE_PREFIX) and norm.endswith(".py"):
            findings.append(
                SupervisorFinding(
                    code="loop_package_new_file",
                    severity="reject",
                    path=norm,
                    message="candidate creates a new evolve-loop Python file",
                )
            )
            risk_floor = _max_risk(risk_floor, "critical")
        if norm.startswith(SUPERVISOR_PACKAGE_PREFIX):
            findings.append(
                SupervisorFinding(
                    code="supervisor_package_changed",
                    severity="reject",
                    path=norm,
                    message="candidate changes blue-only supervisor support code",
                )
            )
            risk_floor = _max_risk(risk_floor, "critical")
        if _is_non_python_delta_path(norm):
            risk_floor = _max_risk(risk_floor, "critical")
    return findings, risk_floor


def _max_risk(left: str, right: str) -> str:
    left_key = str(left or "low").lower()
    right_key = str(right or "low").lower()
    return left_key if RISK_ORDER.get(left_key, 0) >= RISK_ORDER.get(right_key, 0) else right_key


def evaluate_candidate(
    blue_root: Path,
    green_root: Path,
    *,
    claimed_category: str = "",
    claimed_risk: str = "low",
    session_payload: Mapping[str, Any] | None = None,
) -> SupervisorVerdict:
    """Evaluate a green candidate without trusting agent-authored metadata."""
    blue_root = Path(blue_root)
    green_root = Path(green_root)
    delta = collect_tree_delta(blue_root, green_root)
    protected_paths, blocked_prefixes = _load_agent_safety_paths(blue_root)
    findings: list[SupervisorFinding] = []
    risk_floor = str(claimed_risk or "low").lower()

    if delta.changed_count <= 0:
        findings.append(
            SupervisorFinding(
                code="no_rederived_changes",
                severity="reject",
                path="",
                message="supervisor re-derived no blue/green changes",
            )
        )

    if str(claimed_category or "").lower() == "meta":
        risk_floor = _max_risk(risk_floor, "critical")

    corpus_findings = _corpus_lock_findings(green_root)
    if corpus_findings:
        findings.extend(corpus_findings)
        risk_floor = _max_risk(risk_floor, "critical")

    static_findings, static_risk_floor = _static_policy_findings(
        delta,
        protected_paths=protected_paths,
        blocked_prefixes=blocked_prefixes,
    )
    risk_floor = _max_risk(risk_floor, static_risk_floor)
    if static_findings:
        findings.extend(static_findings)

    if not any(item.severity == "reject" for item in findings):
        floor_findings = _verification_floor_findings(delta, blue_root, green_root)
        if floor_findings:
            findings.extend(floor_findings)
            risk_floor = _max_risk(risk_floor, "critical")

    ignored_keys = tuple(sorted(str(key) for key in (session_payload or {}).keys()))
    return SupervisorVerdict(
        ok=not any(item.severity == "reject" for item in findings),
        risk_floor=risk_floor,
        delta=delta,
        findings=tuple(findings),
        ignored_session_keys=ignored_keys,
    )
