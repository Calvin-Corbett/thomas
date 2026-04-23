"""Thomas heartbeat — token-free automated project health checks.

All checks are pure Python (file reads, git commands, subprocess calls).
Zero LLM API calls. Designed to catch what the dev agent forgets.

Usage (standalone)::

    python scripts/heartbeat.py
    python scripts/heartbeat.py --fix
    python scripts/heartbeat.py changelog_sync version_consistency
    python scripts/heartbeat.py --list
    python scripts/heartbeat.py --json

Usage (CLI)::

    thomas heartbeat
    thomas heartbeat --fix
    thomas heartbeat changelog_sync version_consistency
"""

from __future__ import annotations

import json
import os
import py_compile
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from thomas.core.py_compile_safe import compile_no_repo_pyc
from typing import Any

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[2]  # repo root
THOMAS_ROOT = ROOT / "thomas"
STATE_DIR = Path.home() / ".thomas"

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CheckResult:
    """Result of a single heartbeat check."""

    name: str
    status: str  # "pass" | "warn" | "fail"
    message: str
    auto_fixable: bool = False
    details: dict[str, Any] = field(default_factory=dict)
    elapsed_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if not d["details"]:
            del d["details"]
        return d


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


@dataclass
class _CheckEntry:
    name: str
    description: str
    check_fn: Callable[[], CheckResult]
    tags: tuple


_REGISTRY: dict[str, _CheckEntry] = {}
_FIX_REGISTRY: dict[str, Callable[[], CheckResult]] = {}


def heartbeat_check(
    name: str,
    *,
    description: str = "",
    tags: tuple = (),
):
    """Decorator to register a heartbeat check function."""

    def decorator(fn: Callable[[], CheckResult]) -> Callable[[], CheckResult]:
        _REGISTRY[name] = _CheckEntry(
            name=name,
            description=description or fn.__doc__ or name,
            check_fn=fn,
            tags=tags,
        )
        return fn

    return decorator


def register_fix(check_name: str):
    """Register an auto-fix function for a named check."""

    def decorator(fn: Callable[[], CheckResult]) -> Callable[[], CheckResult]:
        _FIX_REGISTRY[check_name] = fn
        return fn

    return decorator


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def run_heartbeat(
    *,
    checks: Sequence[str] | None = None,
    fix: bool = False,
    tags: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Execute heartbeat checks and return a structured report."""
    started = time.monotonic()
    selected = _select_checks(checks, tags)
    results: list[CheckResult] = []

    for entry in selected:
        t0 = time.monotonic()
        try:
            result = entry.check_fn()
        except Exception as exc:
            result = CheckResult(
                name=entry.name,
                status="fail",
                message=f"Check raised {type(exc).__name__}: {exc}",
            )
        elapsed = (time.monotonic() - t0) * 1000
        # Attach timing
        result = CheckResult(
            name=result.name,
            status=result.status,
            message=result.message,
            auto_fixable=result.auto_fixable,
            details=result.details,
            elapsed_ms=round(elapsed, 1),
        )

        # Auto-fix path
        if fix and result.status == "fail" and result.auto_fixable:
            fix_fn = _FIX_REGISTRY.get(entry.name)
            if fix_fn is not None:
                try:
                    fix_result = fix_fn()
                    results.append(fix_result)
                    continue
                except Exception as exc:
                    result = CheckResult(
                        name=result.name,
                        status="fail",
                        message=f"Fix failed: {type(exc).__name__}: {exc}",
                        details=result.details,
                        elapsed_ms=result.elapsed_ms,
                    )

        results.append(result)

    total_elapsed = round((time.monotonic() - started) * 1000, 1)
    pass_count = sum(1 for r in results if r.status == "pass")
    warn_count = sum(1 for r in results if r.status == "warn")
    fail_count = sum(1 for r in results if r.status == "fail")

    return {
        "ok": fail_count == 0,
        "results": [r.to_dict() for r in results],
        "summary": {
            "total": len(results),
            "pass": pass_count,
            "warn": warn_count,
            "fail": fail_count,
        },
        "elapsed_ms": total_elapsed,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _select_checks(
    names: Sequence[str] | None,
    tags: Sequence[str] | None,
) -> list[_CheckEntry]:
    entries = list(_REGISTRY.values())
    if names:
        name_set = set(names)
        entries = [e for e in entries if e.name in name_set]
    if tags:
        tag_set = set(tags)
        entries = [e for e in entries if tag_set & set(e.tags)]
    return entries


def list_checks() -> list[dict[str, Any]]:
    """Return metadata for all registered checks."""
    return [
        {
            "name": e.name,
            "description": e.description,
            "tags": list(e.tags),
            "has_fix": e.name in _FIX_REGISTRY,
        }
        for e in _REGISTRY.values()
    ]


# ---------------------------------------------------------------------------
# Reporter
# ---------------------------------------------------------------------------


def format_text_report(report: dict[str, Any]) -> str:
    """Format heartbeat report as human-readable text."""
    lines: list[str] = []
    summary = report.get("summary", {})
    ts = report.get("timestamp", "")

    lines.append(f"Thomas Heartbeat  {ts}")
    lines.append("=" * 60)

    for r in report.get("results", []):
        status = r["status"].upper()
        icon = {"PASS": "+", "WARN": "~", "FAIL": "!"}[status]
        fixable = " [fixable]" if r.get("auto_fixable") else ""
        ms = f" ({r.get('elapsed_ms', 0):.0f}ms)" if r.get("elapsed_ms") else ""
        lines.append(f"  [{icon}] {r['name']}: {status}{fixable}{ms}")
        lines.append(f"      {r['message']}")

        # Show detail items on failure/warn
        details = r.get("details", {})
        if details and r["status"] in ("fail", "warn"):
            for k, v in details.items():
                if isinstance(v, list):
                    for item in v[:5]:
                        lines.append(f"        - {item}")
                    if len(v) > 5:
                        lines.append(f"        ... and {len(v) - 5} more")
                else:
                    lines.append(f"        {k}: {v}")

    lines.append("=" * 60)
    ok_str = "OK" if report.get("ok") else "FAILED"
    lines.append(
        f"Result: {ok_str}  "
        f"{summary.get('pass', 0)} pass, "
        f"{summary.get('warn', 0)} warn, "
        f"{summary.get('fail', 0)} fail  "
        f"({report.get('elapsed_ms', 0):.0f}ms total)"
    )

    return "\n".join(lines)


# ===========================================================================
# CHECKS — all token-free, pure Python
# ===========================================================================


# ---------------------------------------------------------------------------
# 1. changelog_sync
# ---------------------------------------------------------------------------


@heartbeat_check(
    "changelog_sync",
    description="Verify CHANGELOG has entries for recent commits",
    tags=("git", "docs"),
)
def _check_changelog_sync() -> CheckResult:
    changelog = ROOT / "CHANGELOG.md"
    if not changelog.exists():
        return CheckResult("changelog_sync", "fail", "CHANGELOG.md not found")

    text = changelog.read_text(encoding="utf-8")
    # Parse the most recent dated version: ## [x.y.z] - YYYY-MM-DD
    match = re.search(r"##\s+\[[\d.]+\]\s*-\s*(\d{4}-\d{2}-\d{2})", text)
    if not match:
        return CheckResult("changelog_sync", "warn", "No dated version found in CHANGELOG")

    last_date = match.group(1)

    # Git log since that date
    try:
        proc = subprocess.run(
            ["git", "log", "--oneline", f"--after={last_date}", "--no-merges"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError:
        return CheckResult("changelog_sync", "warn", "git not available")
    except Exception as exc:
        return CheckResult("changelog_sync", "warn", f"git log failed: {exc}")

    commits = [ln.strip() for ln in proc.stdout.strip().splitlines() if ln.strip()]

    if not commits:
        return CheckResult("changelog_sync", "pass", "Changelog is up to date")

    # Check if [Unreleased] section has content
    unreleased_match = re.search(
        r"##\s+\[Unreleased\]\s*\n(.*?)(?=\n##\s+\[|\Z)",
        text,
        re.DOTALL,
    )
    has_unreleased = bool(unreleased_match and unreleased_match.group(1).strip())

    if has_unreleased:
        return CheckResult(
            "changelog_sync",
            "pass",
            f"{len(commits)} commits since {last_date}; [Unreleased] section present",
        )

    return CheckResult(
        "changelog_sync",
        "warn",
        f"{len(commits)} commits since {last_date} with no changelog entries",
        auto_fixable=True,
        details={"commits": commits[:20], "since": last_date},
    )


@register_fix("changelog_sync")
def _fix_changelog_sync() -> CheckResult:
    """Generate a stub [Unreleased] entry from commit subjects."""
    changelog = ROOT / "CHANGELOG.md"
    text = changelog.read_text(encoding="utf-8")
    match = re.search(r"##\s+\[[\d.]+\]\s*-\s*(\d{4}-\d{2}-\d{2})", text)
    if not match:
        return CheckResult("changelog_sync", "fail", "Cannot determine last date")

    last_date = match.group(1)
    proc = subprocess.run(
        ["git", "log", "--oneline", f"--after={last_date}", "--no-merges"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=10,
    )
    commits = [ln.strip() for ln in proc.stdout.strip().splitlines() if ln.strip()]

    # Group by conventional commit type
    groups: dict[str, list[str]] = {"Added": [], "Changed": [], "Fixed": []}
    for line in commits:
        msg = re.sub(r"^[0-9a-f]+\s+", "", line)
        lower = msg.lower()
        if any(lower.startswith(p) for p in ("fix", "bugfix", "patch", "hotfix")):
            groups["Fixed"].append(msg)
        elif any(lower.startswith(p) for p in ("add", "new", "create", "implement")):
            groups["Added"].append(msg)
        else:
            groups["Changed"].append(msg)

    stub_lines = [""]
    for section, items in groups.items():
        if items:
            stub_lines.append(f"### {section}\n")
            for item in items[:10]:
                stub_lines.append(f"- {item}")
            stub_lines.append("")

    stub = "\n".join(stub_lines)

    # Insert content under [Unreleased]
    if "## [Unreleased]" in text:
        text = text.replace(
            "## [Unreleased]\n",
            "## [Unreleased]\n" + stub,
            1,
        )
    else:
        text = text.replace(
            match.group(0),
            "## [Unreleased]\n" + stub + "\n" + match.group(0),
            1,
        )

    changelog.write_text(text, encoding="utf-8")
    return CheckResult(
        "changelog_sync",
        "pass",
        f"Generated stub with {len(commits)} commits",
    )


# ---------------------------------------------------------------------------
# 2. version_consistency
# ---------------------------------------------------------------------------


@heartbeat_check(
    "version_consistency",
    description="Verify pyproject.toml version matches thomas/__init__.py",
    tags=("release",),
)
def _check_version_consistency() -> CheckResult:
    pyproject = ROOT / "pyproject.toml"
    init_file = THOMAS_ROOT / "__init__.py"

    if not pyproject.exists():
        return CheckResult("version_consistency", "fail", "pyproject.toml not found")
    if not init_file.exists():
        return CheckResult("version_consistency", "fail", "thomas/__init__.py not found")

    toml_text = pyproject.read_text(encoding="utf-8")
    toml_match = re.search(r'^version\s*=\s*"([^"]+)"', toml_text, re.MULTILINE)
    if not toml_match:
        return CheckResult("version_consistency", "fail", "No version in pyproject.toml")
    toml_ver = toml_match.group(1)

    init_text = init_file.read_text(encoding="utf-8")
    init_match = re.search(r'^__version__\s*=\s*"([^"]+)"', init_text, re.MULTILINE)
    if not init_match:
        return CheckResult("version_consistency", "fail", "No __version__ in __init__.py")
    init_ver = init_match.group(1)

    if toml_ver == init_ver:
        return CheckResult("version_consistency", "pass", f"Versions match: {toml_ver}")

    return CheckResult(
        "version_consistency",
        "fail",
        f"Mismatch: pyproject.toml={toml_ver}, __init__.py={init_ver}",
        auto_fixable=True,
        details={"pyproject": toml_ver, "init": init_ver},
    )


@register_fix("version_consistency")
def _fix_version_consistency() -> CheckResult:
    """Sync thomas/__init__.py to pyproject.toml version."""
    pyproject = ROOT / "pyproject.toml"
    init_file = THOMAS_ROOT / "__init__.py"

    toml_text = pyproject.read_text(encoding="utf-8")
    toml_match = re.search(r'^version\s*=\s*"([^"]+)"', toml_text, re.MULTILINE)
    if not toml_match:
        return CheckResult("version_consistency", "fail", "No version in pyproject.toml")
    target = toml_match.group(1)

    init_text = init_file.read_text(encoding="utf-8")
    new_text = re.sub(
        r'^__version__\s*=\s*"[^"]+"',
        f'__version__ = "{target}"',
        init_text,
        count=1,
        flags=re.MULTILINE,
    )
    init_file.write_text(new_text, encoding="utf-8")
    return CheckResult("version_consistency", "pass", f"Synced __init__.py to {target}")


# ---------------------------------------------------------------------------
# 3. server_boot
# ---------------------------------------------------------------------------


@heartbeat_check(
    "server_boot",
    description="Verify server app factory imports without error",
    tags=("server",),
)
def _check_server_boot() -> CheckResult:
    try:
        proc = subprocess.run(
            [
                sys.executable,
                "-c",
                "from thomas.server.app import create_app; create_app(); print('OK')",
            ],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=15,
        )
    except subprocess.TimeoutExpired:
        return CheckResult("server_boot", "fail", "Server boot timed out (15s)")
    except Exception as exc:
        return CheckResult("server_boot", "fail", f"Subprocess failed: {exc}")

    if proc.returncode == 0 and "OK" in proc.stdout:
        return CheckResult("server_boot", "pass", "Server app factory OK")

    stderr = proc.stderr.strip()[-300:] if proc.stderr else ""
    return CheckResult(
        "server_boot",
        "fail",
        f"Server boot failed (exit {proc.returncode})",
        details={"stderr": stderr},
    )


# ---------------------------------------------------------------------------
# 4. python_compile
# ---------------------------------------------------------------------------


@heartbeat_check(
    "python_compile",
    description="Compile all .py files under thomas/ for syntax errors",
    tags=("syntax",),
)
def _check_python_compile() -> CheckResult:
    errors: list[str] = []
    count = 0
    for py_file in THOMAS_ROOT.rglob("*.py"):
        if "__pycache__" in str(py_file):
            continue
        count += 1
        try:
            compile_no_repo_pyc(py_file, doraise=True)
        except py_compile.PyCompileError as exc:
            rel = py_file.relative_to(ROOT)
            errors.append(f"{rel}: {exc.msg}")

    if errors:
        return CheckResult(
            "python_compile",
            "fail",
            f"{len(errors)} syntax errors in {count} files",
            details={"errors": errors[:10]},
        )
    return CheckResult("python_compile", "pass", f"All {count} files compile OK")


# ---------------------------------------------------------------------------
# 5. js_syntax
# ---------------------------------------------------------------------------


@heartbeat_check(
    "js_syntax",
    description="Run node --check on key JS files",
    tags=("syntax",),
)
def _check_js_syntax() -> CheckResult:
    js_dir = THOMAS_ROOT / "server" / "web" / "js"
    js_files = list(js_dir.glob("*.js")) if js_dir.is_dir() else []
    if not js_files:
        return CheckResult("js_syntax", "warn", "No JS files found")

    node = shutil.which("node")
    if not node:
        return CheckResult("js_syntax", "warn", "node not in PATH, skipping")

    errors: list[str] = []
    for js_file in js_files:
        try:
            proc = subprocess.run(
                [node, "--check", str(js_file)],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                timeout=10,
            )
            if proc.returncode != 0:
                rel = js_file.relative_to(ROOT)
                errors.append(f"{rel}: {proc.stderr.strip()[:200]}")
        except Exception as exc:
            errors.append(f"{js_file.name}: {exc}")

    if errors:
        return CheckResult(
            "js_syntax",
            "fail",
            f"{len(errors)} JS syntax errors",
            details={"errors": errors[:5]},
        )
    return CheckResult("js_syntax", "pass", f"All {len(js_files)} JS files OK")


# ---------------------------------------------------------------------------
# 6. index_freshness
# ---------------------------------------------------------------------------


@heartbeat_check(
    "index_freshness",
    description="Verify PROJECT_INDEX.md references still exist",
    tags=("docs",),
)
def _check_index_freshness() -> CheckResult:
    index = ROOT / "PROJECT_INDEX.md"
    if not index.exists():
        return CheckResult("index_freshness", "warn", "PROJECT_INDEX.md not found")

    text = index.read_text(encoding="utf-8")
    # Extract repo-relative file paths like thomas/foo/bar.py or scripts/x.py
    path_pattern = re.compile(r"(?:thomas|scripts|tests|docs)/[\w/.\-]+\.(?:py|js|html|css|toml|json|md)")
    referenced = set(path_pattern.findall(text))
    # Exclude state-dir paths (e.g. ~/.thomas/foo.json matched as thomas/foo.json)
    # These are user-home state files, not repo files — they won't have a subdir
    referenced = {
        r
        for r in referenced
        if r.count("/") >= 2  # repo paths always have at least 2 segments: thomas/pkg/file.py
        or (ROOT / r).exists()  # if it's a shallow path, only keep if actually exists
    }

    stale: list[str] = []
    for ref in sorted(referenced):
        if not (ROOT / ref).exists():
            stale.append(ref)

    if stale:
        return CheckResult(
            "index_freshness",
            "warn",
            f"{len(stale)} stale references in PROJECT_INDEX.md",
            details={"stale": stale[:15]},
        )
    return CheckResult(
        "index_freshness",
        "pass",
        f"All {len(referenced)} references valid",
    )


# ---------------------------------------------------------------------------
# 7. architecture_fitness
# ---------------------------------------------------------------------------


@heartbeat_check(
    "architecture_fitness",
    description="Run architecture fitness tests",
    tags=("arch",),
)
def _check_architecture_fitness() -> CheckResult:
    test_file = ROOT / "tests" / "test_architecture.py"
    if not test_file.exists():
        return CheckResult("architecture_fitness", "warn", "test_architecture.py not found")

    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", str(test_file), "-x", "--tb=short", "-q"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return CheckResult("architecture_fitness", "fail", "pytest timed out (30s)")
    except Exception as exc:
        return CheckResult("architecture_fitness", "fail", f"pytest failed: {exc}")

    if proc.returncode == 0:
        for line in proc.stdout.splitlines():
            if "passed" in line:
                return CheckResult("architecture_fitness", "pass", line.strip())
        return CheckResult("architecture_fitness", "pass", "All tests passed")

    # Extract failure summary
    output = proc.stdout[-500:] if proc.stdout else ""
    return CheckResult(
        "architecture_fitness",
        "fail",
        f"Fitness tests failed (exit {proc.returncode})",
        details={"output": output},
    )


# ---------------------------------------------------------------------------
# 8. stale_locks
# ---------------------------------------------------------------------------


def _pid_alive(pid: int) -> bool:
    """Check if a PID is alive (cross-platform)."""
    if os.name == "nt":
        try:
            proc = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return str(pid) in proc.stdout
        except (subprocess.CalledProcessError, OSError):
            return True  # assume alive if we can't check
    else:
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True  # exists but we can't signal it


@heartbeat_check(
    "stale_locks",
    description="Check for stale serve.lock with dead PIDs",
    tags=("runtime",),
)
def _check_stale_locks() -> CheckResult:
    lock_path = STATE_DIR / "serve.lock"
    if not lock_path.exists():
        return CheckResult("stale_locks", "pass", "No serve.lock found")

    try:
        content = lock_path.read_text(encoding="utf-8").strip()
        pid = int(content.split()[0]) if content else 0
    except (OSError, FileNotFoundError):
        return CheckResult(
            "stale_locks",
            "warn",
            "serve.lock exists but could not parse PID",
            auto_fixable=True,
        )

    if pid <= 0:
        return CheckResult("stale_locks", "warn", "serve.lock has invalid PID", auto_fixable=True)

    if _pid_alive(pid):
        return CheckResult("stale_locks", "pass", f"serve.lock PID {pid} is alive")

    return CheckResult(
        "stale_locks",
        "fail",
        f"serve.lock PID {pid} is dead (stale lock)",
        auto_fixable=True,
        details={"pid": pid, "lock_path": str(lock_path)},
    )


@register_fix("stale_locks")
def _fix_stale_locks() -> CheckResult:
    """Delete stale serve.lock file."""
    lock_path = STATE_DIR / "serve.lock"
    try:
        lock_path.unlink(missing_ok=True)
    except Exception as exc:
        return CheckResult("stale_locks", "fail", f"Could not remove lock: {exc}")
    return CheckResult("stale_locks", "pass", "Removed stale serve.lock")


# ---------------------------------------------------------------------------
# 9. log_rotation
# ---------------------------------------------------------------------------


@heartbeat_check(
    "log_rotation",
    description="Check server.log size and rotate if > 10MB",
    tags=("runtime",),
)
def _check_log_rotation() -> CheckResult:
    log_path = STATE_DIR / "server.log"
    if not log_path.exists():
        return CheckResult("log_rotation", "pass", "No server.log found")

    try:
        size_mb = log_path.stat().st_size / (1024 * 1024)
    except Exception as exc:
        return CheckResult("log_rotation", "warn", f"Cannot stat server.log: {exc}")

    if size_mb <= 10.0:
        return CheckResult(
            "log_rotation",
            "pass",
            f"server.log is {size_mb:.1f}MB (within 10MB limit)",
        )

    return CheckResult(
        "log_rotation",
        "warn",
        f"server.log is {size_mb:.1f}MB (exceeds 10MB limit)",
        auto_fixable=True,
        details={"size_mb": round(size_mb, 1), "path": str(log_path)},
    )


@register_fix("log_rotation")
def _fix_log_rotation() -> CheckResult:
    """Rotate server.log to server.log.1."""
    log_path = STATE_DIR / "server.log"
    rotated = STATE_DIR / "server.log.1"

    try:
        # Shift existing rotation
        if rotated.exists():
            rotated.unlink()
        if log_path.exists():
            log_path.rename(rotated)
    except Exception as exc:
        return CheckResult("log_rotation", "fail", f"Rotation failed: {exc}")

    return CheckResult("log_rotation", "pass", "Rotated server.log to server.log.1")


# ---------------------------------------------------------------------------
# 10. config_valid
# ---------------------------------------------------------------------------


@heartbeat_check(
    "config_valid",
    description="Validate thomas.toml configuration",
    tags=("config",),
)
def _check_config_valid() -> CheckResult:
    toml_path = ROOT / "thomas.toml"
    if not toml_path.exists():
        return CheckResult("config_valid", "warn", "thomas.toml not found")

    try:
        from thomas.core.config import load_config

        config = load_config()
        # validate() may not exist on all versions — try it
        errors = getattr(config, "validate", lambda: [])()
        if errors is None:
            errors = []
    except Exception as exc:
        return CheckResult(
            "config_valid",
            "fail",
            f"Config load failed: {type(exc).__name__}: {exc}",
        )

    if errors:
        return CheckResult(
            "config_valid",
            "fail",
            f"{len(errors)} config validation errors",
            details={"errors": list(errors)[:10]},
        )
    return CheckResult("config_valid", "pass", "thomas.toml is valid")


# ---------------------------------------------------------------------------
# 11. monolith_guard
# ---------------------------------------------------------------------------


@heartbeat_check(
    "monolith_guard",
    description="Check monolith file size limits",
    tags=("arch",),
)
def _check_monolith_guard() -> CheckResult:
    script_path = ROOT / "scripts" / "check_monolith_guard.py"
    baseline_path = ROOT / "docs" / "monolith_guard_baseline.json"

    if not script_path.exists():
        return CheckResult("monolith_guard", "warn", "check_monolith_guard.py not found")

    try:
        proc = subprocess.run(
            [sys.executable, str(script_path), "--json"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=15,
        )
    except subprocess.TimeoutExpired:
        return CheckResult("monolith_guard", "fail", "monolith guard timed out")
    except Exception as exc:
        return CheckResult("monolith_guard", "fail", f"monolith guard failed: {exc}")

    if proc.returncode == 0:
        return CheckResult("monolith_guard", "pass", "All files within size limits")

    # Try to parse JSON output for details
    violations: list[str] = []
    try:
        data = json.loads(proc.stdout)
        for v in data.get("violations", [])[:5]:
            violations.append(f"{v.get('path', '?')}: {v.get('lines', '?')} lines ({v.get('reason', '')})")
    except json.JSONDecodeError:
        violations = [proc.stdout[:200] if proc.stdout else ""]

    return CheckResult(
        "monolith_guard",
        "fail",
        "Monolith size violations found",
        details={"violations": violations},
    )


# ---------------------------------------------------------------------------
# 12. dead_references
# ---------------------------------------------------------------------------


@heartbeat_check(
    "dead_references",
    description="Check parity_compat.py module references exist",
    tags=("code",),
)
def _check_dead_references() -> CheckResult:
    compat = THOMAS_ROOT / "cli" / "parity_compat.py"
    if not compat.exists():
        return CheckResult("dead_references", "warn", "parity_compat.py not found")

    text = compat.read_text(encoding="utf-8")
    # Find thomas.X module references
    refs = re.findall(r"thomas\.(\w+)\b", text)
    unique_refs = sorted(set(refs))

    missing: list[str] = []
    for mod_name in unique_refs:
        mod_dir = THOMAS_ROOT / mod_name
        mod_file = THOMAS_ROOT / f"{mod_name}.py"
        if not mod_dir.is_dir() and not mod_file.exists():
            missing.append(mod_name)

    if missing:
        return CheckResult(
            "dead_references",
            "fail",
            f"{len(missing)} dead module references in parity_compat.py",
            details={"missing": missing},
        )
    return CheckResult(
        "dead_references",
        "pass",
        f"All {len(unique_refs)} module references valid",
    )


# ---------------------------------------------------------------------------
# 13. git_hygiene
# ---------------------------------------------------------------------------


@heartbeat_check(
    "git_hygiene",
    description="Report uncommitted changes and untracked .py files",
    tags=("git",),
)
def _check_git_hygiene() -> CheckResult:
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError:
        return CheckResult("git_hygiene", "warn", "git not available")
    except Exception as exc:
        return CheckResult("git_hygiene", "warn", f"git status failed: {exc}")

    lines = [ln for ln in proc.stdout.strip().splitlines() if ln.strip()]
    modified = [ln for ln in lines if ln[:2].strip() in ("M", "MM", "AM")]
    untracked_py = [ln for ln in lines if ln.startswith("??") and ln.rstrip().endswith(".py")]

    if not modified and not untracked_py:
        return CheckResult("git_hygiene", "pass", "Working tree clean")

    parts: list[str] = []
    if modified:
        parts.append(f"{len(modified)} modified")
    if untracked_py:
        parts.append(f"{len(untracked_py)} untracked .py")

    return CheckResult(
        "git_hygiene",
        "warn",
        f"Git: {', '.join(parts)}",
        details={
            "modified_count": len(modified),
            "untracked_py_count": len(untracked_py),
            "untracked_py": [ln[3:].strip() for ln in untracked_py[:10]],
        },
    )
