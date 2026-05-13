#!/usr/bin/env python3
"""High-confidence preflight checks before publishing this repo to GitHub."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

try:
    import tomllib
except Exception:  # pragma: no cover
    import tomli as tomllib  # type: ignore


ROOT = Path(__file__).resolve().parents[1]

BLOCKED_TRACKED_EXACT = {
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
    "secrets.json",
    "thomas.db",
    "thomas.marketplace.asset_studio.db",
    "thomas_search.db",
}
BLOCKED_TRACKED_SUFFIXES = (
    ".pem",
    ".key",
    ".p12",
    ".pfx",
    ".jks",
    ".kdbx",
)
REQUIRED_GITIGNORE_SNIPPETS = (
    ".env",
    ".env.local",
    ".thomas/",
    "runtime/",
    "thomas.db",
    "thomas.marketplace.asset_studio.db",
)
DEFAULT_REQUIRED_BRANCHES = ("dev", "prod")
SCAN_SKIP_PREFIXES = (
    "tests/",
    "docs/",
    "library/",
    "plans/",
)
SCAN_SKIP_SUFFIXES = (
    ".md",
    ".rst",
    ".txt",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".ico",
    ".zip",
    ".tar",
    ".gz",
)
MAX_SCAN_BYTES = 2_000_000
SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("openai_api_key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("github_pat", re.compile(r"\bghp_[A-Za-z0-9]{36}\b")),
    ("github_pat_fine_grained", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{30,}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("aws_temp_access_key", re.compile(r"\bASIA[0-9A-Z]{16}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("private_key_block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PRIVATE )?PRIVATE KEY-----")),
)
ALLOWLIST_FRAGMENTS = (
    "example",
    "placeholder",
    "dummy",
    "test",
    "sample",
    "your_",
    "your-",
    "noreply",
    "local.invalid",
)


def _run_git(args: Sequence[str], repo_root: Path) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"git {' '.join(args)} failed")
    return str(proc.stdout or "")


def _tracked_files(repo_root: Path) -> list[str]:
    out = _run_git(["ls-files"], repo_root)
    files: list[str] = []
    for line in out.splitlines():
        path = str(line or "").strip().replace("\\", "/")
        if path:
            files.append(path)
    return sorted(set(files))


def _local_branches(repo_root: Path) -> set[str]:
    out = _run_git(["for-each-ref", "--format=%(refname:short)", "refs/heads"], repo_root)
    return {str(line or "").strip() for line in out.splitlines() if str(line or "").strip()}


def _gitignore_text(repo_root: Path) -> str:
    path = repo_root / ".gitignore"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def _is_allowed_secret_line(line: str) -> bool:
    normalized = str(line or "").lower()
    return any(fragment in normalized for fragment in ALLOWLIST_FRAGMENTS)


def _is_scan_candidate(path: str) -> bool:
    normalized = str(path or "").strip().replace("\\", "/")
    if not normalized:
        return False
    lower_path = normalized.lower()
    if any(lower_path.startswith(prefix) for prefix in SCAN_SKIP_PREFIXES):
        return False
    return not any(lower_path.endswith(suffix) for suffix in SCAN_SKIP_SUFFIXES)


def _scan_for_live_secrets(repo_root: Path, tracked: Sequence[str]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for rel_path in tracked:
        if not _is_scan_candidate(rel_path):
            continue
        full_path = repo_root / rel_path
        if not full_path.exists() or not full_path.is_file():
            continue
        try:
            size = full_path.stat().st_size
        except OSError:
            continue
        if size > MAX_SCAN_BYTES:
            continue
        try:
            text = full_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for index, line in enumerate(text.splitlines(), start=1):
            if _is_allowed_secret_line(line):
                continue
            for name, pattern in SECRET_PATTERNS:
                if pattern.search(line):
                    findings.append(
                        {
                            "file": rel_path,
                            "line": index,
                            "pattern": name,
                            "snippet": line.strip()[:200],
                        }
                    )
                    break
    return findings


def _check_blocked_tracked_files(tracked: Sequence[str]) -> list[str]:
    violations: list[str] = []
    for raw in tracked:
        path = str(raw or "").strip().replace("\\", "/")
        lower = path.lower()
        if lower in {item.lower() for item in BLOCKED_TRACKED_EXACT}:
            violations.append(path)
            continue
        if any(lower.endswith(suffix) for suffix in BLOCKED_TRACKED_SUFFIXES):
            violations.append(path)
    return sorted(set(violations))


def _check_gitignore_hardening(repo_root: Path) -> list[str]:
    text = _gitignore_text(repo_root)
    missing = []
    for snippet in REQUIRED_GITIGNORE_SNIPPETS:
        if snippet not in text:
            missing.append(snippet)
    return missing


def _check_repo_remote(repo_root: Path) -> list[str]:
    warnings: list[str] = []
    try:
        remote = _run_git(["remote", "get-url", "origin"], repo_root).strip()
    except Exception as exc:
        warnings.append(f"could not resolve git remote origin: {exc}")
        return warnings
    if "github.com" not in remote:
        warnings.append(f"origin remote is not GitHub: {remote}")
    return warnings


def _check_worktree_clean(repo_root: Path) -> list[str]:
    out = _run_git(["status", "--porcelain"], repo_root)
    dirty = [line.rstrip() for line in out.splitlines() if str(line or "").strip()]
    if not dirty:
        return []
    preview = ", ".join(dirty[:5])
    if len(dirty) > 5:
        preview += f", ... (+{len(dirty) - 5} more)"
    return [f"git worktree is not clean: {preview}"]


def _check_release_branch_presence(repo_root: Path, required: Sequence[str]) -> list[str]:
    missing: list[str] = []
    branches = _local_branches(repo_root)
    for name in required:
        branch = str(name or "").strip()
        if branch and branch not in branches:
            missing.append(branch)
    return missing


def _check_toml_safety(repo_root: Path) -> list[str]:
    errors: list[str] = []
    prod_path = repo_root / "thomas.prod.toml"
    if not prod_path.exists():
        errors.append("missing thomas.prod.toml")
        return errors
    try:
        prod_data = tomllib.loads(prod_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"failed to parse thomas.prod.toml: {exc}"]

    server = dict(prod_data.get("server") or {})
    tools = dict(prod_data.get("tools") or {})
    if str(server.get("access_mode") or "").strip().lower() != "local":
        errors.append("thomas.prod.toml server.access_mode must be 'local'")
    if bool(server.get("allow_unauthenticated_version", True)):
        errors.append("thomas.prod.toml server.allow_unauthenticated_version must be false")
    if bool(tools.get("allow_shell", True)):
        errors.append("thomas.prod.toml tools.allow_shell must be false")
    api_token = str(server.get("api_token") or "").strip()
    if api_token:
        errors.append("thomas.prod.toml server.api_token must not contain a committed token")

    return errors


def _run_optional_deep_checks(repo_root: Path) -> list[str]:
    failures: list[str] = []
    commands = [
        [sys.executable, "scripts/forge/gates/repo_hygiene.py", "--require-clean-worktree", "--strict", "--json"],
        [sys.executable, "scripts/forge/gates/release_hygiene.py"],
        [sys.executable, "scripts/forge/gates/claim_integrity.py", "--json"],
        [sys.executable, "scripts/security_audit.py", "--repo-root", ".", "--json", "--strict"],
    ]
    for cmd in commands:
        proc = subprocess.run(cmd, cwd=repo_root, capture_output=True, text=True)
        if proc.returncode != 0:
            stderr = (proc.stderr or "").strip()
            stdout = (proc.stdout or "").strip()
            details = stderr or stdout or f"exit {proc.returncode}"
            failures.append(f"{' '.join(cmd)} failed: {details}")
    return failures


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Preflight safety checks before publishing repository changes to GitHub."
    )
    parser.add_argument("--repo-root", default=".", help="Repository root path (default: current repo).")
    parser.add_argument(
        "--required-branch",
        action="append",
        default=[],
        help="Required local branch name (repeatable). Defaults to dev + prod.",
    )
    parser.add_argument("--skip-worktree-clean-check", action="store_true", help="Skip dirty worktree check.")
    parser.add_argument("--deep", action="store_true", help="Run deep checks (repo hygiene + release + security).")
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero on any failure.")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    required_branches = [str(x).strip() for x in (args.required_branch or []) if str(x).strip()]
    if not required_branches:
        required_branches = list(DEFAULT_REQUIRED_BRANCHES)

    errors: list[str] = []
    warnings: list[str] = []

    try:
        tracked = _tracked_files(repo_root)
    except Exception as exc:
        payload = {"ok": False, "errors": [f"failed to enumerate tracked files: {exc}"], "warnings": []}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print("github publish preflight: FAIL")
            print(f"- failed to enumerate tracked files: {exc}")
        return 1

    if not args.skip_worktree_clean_check:
        errors.extend(_check_worktree_clean(repo_root))

    blocked = _check_blocked_tracked_files(tracked)
    if blocked:
        errors.append(
            "blocked sensitive files are tracked: "
            + ", ".join(blocked[:8])
            + (f", ... (+{len(blocked) - 8} more)" if len(blocked) > 8 else "")
        )

    missing_gitignore = _check_gitignore_hardening(repo_root)
    if missing_gitignore:
        warnings.append("gitignore missing recommended entries: " + ", ".join(missing_gitignore))

    missing_branches = _check_release_branch_presence(repo_root, required_branches)
    if missing_branches:
        errors.append("required local release branches missing: " + ", ".join(missing_branches))

    errors.extend(_check_toml_safety(repo_root))
    warnings.extend(_check_repo_remote(repo_root))

    secret_findings = _scan_for_live_secrets(repo_root, tracked)
    if secret_findings:
        sample = secret_findings[:5]
        preview = "; ".join(f"{item['file']}:{item['line']} [{item['pattern']}]" for item in sample)
        suffix = f"; ... (+{len(secret_findings) - 5} more)" if len(secret_findings) > 5 else ""
        errors.append(f"potential live secrets detected: {preview}{suffix}")

    deep_failures: list[str] = []
    if args.deep:
        deep_failures = _run_optional_deep_checks(repo_root)
        errors.extend(deep_failures)

    ok = not errors
    payload: dict[str, Any] = {
        "ok": ok,
        "repo_root": str(repo_root),
        "required_branches": required_branches,
        "summary": {
            "tracked_file_count": len(tracked),
            "secret_finding_count": len(secret_findings),
            "error_count": len(errors),
            "warning_count": len(warnings),
            "deep_checks_enabled": bool(args.deep),
            "deep_check_failure_count": len(deep_failures),
        },
        "errors": errors,
        "warnings": warnings,
    }
    if secret_findings:
        payload["secret_findings"] = secret_findings[:20]

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        if ok:
            print("github publish preflight: PASS")
            print(f"- tracked files: {len(tracked)}")
            print(f"- deep checks: {'enabled' if args.deep else 'disabled'}")
            for item in warnings:
                print(f"- WARN: {item}")
        else:
            print("github publish preflight: FAIL")
            for item in errors:
                print(f"- {item}")
            for item in warnings:
                print(f"- WARN: {item}")

    if args.strict and not ok:
        return 1
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(run())
