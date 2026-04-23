"""Rules-of-the-road quality gate for task completion."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from thomas.core.placeholder_policy import placeholder_policy_report, repo_relative_placeholder_path

VALID_JOB_TYPES = {
    "coding",
    "config",
    "planning",
    "research",
    "video_design",
    "general",
}

_VIDEO_RE = re.compile(r"\b(video|motion|storyboard|animation|editing|design)\b", re.I)
_CONFIG_RE = re.compile(r"\b(config|configuration|settings?|thomas\.toml|\.toml)\b", re.I)
_SHELL_TEST_RE = re.compile(
    r"\b(pytest|unittest|npm\s+test|pnpm\s+test|yarn\s+test|go\s+test|cargo\s+test|dotnet\s+test|mvn\s+test|gradle\s+test)\b",
    re.I,
)
_SHELL_VERIFY_RE = re.compile(
    r"\b(pytest|test|lint|ruff|mypy|typecheck|build|compile|doctor|validate|check)\b",
    re.I,
)
_MONOLITH_GUARD_RE = re.compile(
    r"\bcheck_monolith_guard(?:\.py)?\b",
    re.I,
)
_ISSUE_WORD_RE = re.compile(
    r"\b(issue|bug|error|failure|failing|broken|regression|problem|defect|incident)\b",
    re.I,
)
_UNRESOLVED_ISSUE_STRONG_RE = re.compile(
    r"\b("
    r"unresolved|"
    r"not fixed|"
    r"not resolved|"
    r"still (?:failing|broken|erroring)|"
    r"left (?:unfixed|unresolved)|"
    r"unable to fix|"
    r"can't fix|"
    r"cannot fix|"
    r"couldn't fix|"
    r"won't fix"
    r")\b",
    re.I,
)
_WORKAROUND_LANGUAGE_RE = re.compile(
    r"\b("
    r"workaround|"
    r"temporary fix|"
    r"quick fix|"
    r"band[- ]?aid|"
    r"for now|"
    r"until (?:a )?proper fix|"
    r"follow(?:-| )?up later|"
    r"defer(?:red)?|"
    r"ship with known"
    r")\b",
    re.I,
)
_SKIP_IGNORE_RE = re.compile(r"\b(skip(?:ped|ping)?|ignore(?:d|s|ing)?)\b", re.I)
_MONOLITH_LIMITS = {
    "py": 1200,
    "js": 1200,
    "mjs": 1200,
    "cjs": 1200,
    "jsx": 1200,
    "ts": 1200,
    "tsx": 1200,
    "css": 1600,
    "html": 1000,
}


def _repo_root_path(repo_root: str | Path | None) -> Path:
    return Path(repo_root).resolve() if repo_root else Path.cwd().resolve()


def _load_monolith_baseline(repo_root: Path) -> dict[str, Any]:
    baseline_path = repo_root / "docs" / "monolith_guard_baseline.json"
    if not baseline_path.exists():
        return {
            "hard_limits": dict(_MONOLITH_LIMITS),
            "allowed_large_files": {},
        }
    try:
        raw = json.loads(baseline_path.read_text(encoding="utf-8"))
    except Exception:
        return {
            "hard_limits": dict(_MONOLITH_LIMITS),
            "allowed_large_files": {},
        }
    hard_limits = dict(_MONOLITH_LIMITS)
    if isinstance(raw.get("hard_limits"), dict):
        for key, value in raw["hard_limits"].items():
            try:
                hard_limits[str(key)] = int(value)
            except Exception:
                continue
    allowed = raw.get("allowed_large_files")
    return {
        "hard_limits": hard_limits,
        "allowed_large_files": allowed if isinstance(allowed, dict) else {},
    }


def _resolve_event_path(path_text: str, repo_root: Path) -> Path | None:
    raw = str(path_text or "").strip()
    if not raw:
        return None
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = repo_root / candidate
    try:
        return candidate.resolve()
    except Exception:
        return None


def _iter_written_paths(tool_events: list[dict[str, Any]], repo_root: Path) -> list[Path]:
    seen: set[Path] = set()
    out: list[Path] = []
    for evt in tool_events:
        if not _is_write_tool(str(evt.get("name") or "")):
            continue
        candidate = _resolve_event_path(str(evt.get("path") or ""), repo_root)
        if candidate is None or candidate in seen or not candidate.exists() or not candidate.is_file():
            continue
        seen.add(candidate)
        out.append(candidate)
    return out


def _detect_oversized_written_files(tool_events: list[dict[str, Any]], repo_root: Path) -> list[dict[str, Any]]:
    baseline = _load_monolith_baseline(repo_root)
    hard_limits = dict(baseline.get("hard_limits") or {})
    allowed_large_files = dict(baseline.get("allowed_large_files") or {})
    findings: list[dict[str, Any]] = []
    for candidate in _iter_written_paths(tool_events, repo_root):
        ext = candidate.suffix.lower().lstrip(".")
        hard_limit = int(hard_limits.get(ext) or 0)
        if hard_limit <= 0:
            continue
        try:
            lines = sum(1 for _ in candidate.open("r", encoding="utf-8", errors="ignore"))
        except Exception:
            continue
        try:
            rel = candidate.relative_to(repo_root).as_posix()
        except Exception:
            rel = str(candidate)
        waiver = allowed_large_files.get(rel)
        if isinstance(waiver, dict):
            try:
                max_lines = int(waiver.get("max_lines", hard_limit))
            except Exception:
                max_lines = hard_limit
            if lines > max_lines:
                findings.append(
                    {
                        "path": rel,
                        "lines": lines,
                        "hard_limit": hard_limit,
                        "max_lines": max_lines,
                        "reason": "waived file exceeded max_lines; split or extract before more edits",
                    }
                )
            continue
        if lines > hard_limit:
            findings.append(
                {
                    "path": rel,
                    "lines": lines,
                    "hard_limit": hard_limit,
                    "max_lines": hard_limit,
                    "reason": "file exceeds hard monolith limit; split or extract before more edits",
                }
            )
    return findings


def normalize_job_type(
    *,
    route_path: str,
    prompt_text: str,
    requested_job_type: str | None,
    config_change_detected: bool,
) -> str:
    requested = str(requested_job_type or "").strip().lower()
    if requested in VALID_JOB_TYPES:
        return requested
    if config_change_detected or _CONFIG_RE.search(prompt_text or ""):
        return "config"
    if _VIDEO_RE.search(prompt_text or ""):
        return "video_design"
    path = str(route_path or "").strip().lower()
    if path in {"coding_task", "debug_audit"}:
        return "coding"
    if path == "planning":
        return "planning"
    if path == "research":
        return "research"
    return "general"


def _is_write_tool(name: str) -> bool:
    n = str(name or "").strip().lower()
    return (
        n.startswith("diff.")
        or n in {"fs.write_file", "fs.delete_file"}
        or "write" in n
        or "delete" in n
        or "remove" in n
        or "apply_patch" in n
    )


def _is_verification_tool(name: str) -> bool:
    n = str(name or "").strip().lower()
    if n in {
        "shell.exec",
        "fs.read_file",
        "code.search",
        "code.find_definition",
        "code.find_references",
        "git.diff",
        "rag.search",
    }:
        return True
    return n.startswith("git.diff") or n.startswith("code.search")


def _shell_command_from_event(evt: dict[str, Any]) -> str:
    return str(evt.get("command") or "").strip()


def _config_path_from_event(evt: dict[str, Any]) -> str:
    return str(evt.get("path") or "").strip()


def _response_has_unresolved_issue_language(response_text: str) -> bool:
    text = str(response_text or "")
    if not text.strip():
        return False
    if _UNRESOLVED_ISSUE_STRONG_RE.search(text):
        return True

    has_issue_word = bool(_ISSUE_WORD_RE.search(text))
    has_workaround = bool(_WORKAROUND_LANGUAGE_RE.search(text))
    if has_issue_word and has_workaround:
        return True
    return bool(
        has_issue_word
        and _SKIP_IGNORE_RE.search(text)
        and re.search(r"\b(fix|issue|bug|error|failure|test)\b", text, re.I)
    )


def required_failed_checks(report: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for check in list(report.get("checks") or []):
        if bool(check.get("required")) and (not bool(check.get("passed"))):
            out.append(check)
    return out


def evaluate_rules(
    *,
    route_path: str,
    prompt_text: str,
    response_text: str,
    tool_events: list[dict[str, Any]],
    requested_job_type: str | None,
    config_errors: list[str],
    unknown_core_keys: list[str],
    require_verification_for_coding: bool,
    require_tests_for_code_edits: bool,
    require_monolith_guard_for_coding: bool,
    strict_issue_ownership: bool = False,
    attempt: int = 0,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    prompt_text = str(prompt_text or "")
    response_text = str(response_text or "")
    repo_root_path = _repo_root_path(repo_root)

    writes_detected = False
    verification_detected = False
    verification_after_write_detected = False
    tests_detected = False
    monolith_guard_ran = False
    monolith_guard_passed = False
    config_change_detected = False
    failed_tools = 0
    write_seen = False
    placeholder_reports: list[dict[str, Any]] = []
    placeholder_incomplete_paths: list[str] = []
    placeholder_repo_root = Path(repo_root).resolve() if repo_root else Path(__file__).resolve().parents[2]

    for evt in tool_events:
        name = str(evt.get("name") or "")
        ok = bool(evt.get("ok", False))
        cmd = _shell_command_from_event(evt)
        path = _config_path_from_event(evt)
        is_write = _is_write_tool(name)
        is_verification = _is_verification_tool(name)

        if not ok:
            failed_tools += 1
        if is_write:
            writes_detected = True
            write_seen = True
        if name == "shell.exec" and _SHELL_VERIFY_RE.search(cmd or ""):
            is_verification = True
        if name == "shell.exec" and _SHELL_TEST_RE.search(cmd or ""):
            tests_detected = True
            is_verification = True
        if name == "shell.exec" and _MONOLITH_GUARD_RE.search(cmd or ""):
            monolith_guard_ran = True
            monolith_guard_passed = monolith_guard_passed or ok
        if is_verification:
            verification_detected = True
            if write_seen:
                verification_after_write_detected = True
        if path.lower().endswith(".toml"):
            config_change_detected = True
        if is_write and path:
            candidate = Path(path)
            if not candidate.is_absolute():
                candidate = placeholder_repo_root / candidate
            report = placeholder_policy_report(candidate)
            if bool(report.get("is_placeholder")):
                report["path"] = repo_relative_placeholder_path(candidate, repo_root=placeholder_repo_root)
                placeholder_reports.append(report)
                if not bool(report.get("ok", False)):
                    placeholder_incomplete_paths.append(str(report.get("path") or path))

    oversized_written_files = _detect_oversized_written_files(tool_events, repo_root_path)

    job_type = normalize_job_type(
        route_path=route_path,
        prompt_text=prompt_text,
        requested_job_type=requested_job_type,
        config_change_detected=config_change_detected,
    )

    def add_check(
        check_id: str,
        title: str,
        *,
        required: bool,
        passed: bool,
        detail: str,
    ) -> None:
        checks.append(
            {
                "id": str(check_id),
                "title": str(title),
                "required": bool(required),
                "passed": bool(passed),
                "detail": str(detail),
            }
        )

    add_check(
        "response_present",
        "Assistant returned a non-empty answer",
        required=True,
        passed=bool(response_text.strip()),
        detail="The completion must contain user-facing output.",
    )

    add_check(
        "tool_failures_not_dominant",
        "Tool failures did not dominate execution",
        required=False,
        passed=(failed_tools == 0 or failed_tools < max(1, len(tool_events))),
        detail=f"tool_failures={failed_tools}, tool_calls={len(tool_events)}",
    )

    unresolved_issue_detected = _response_has_unresolved_issue_language(response_text)
    add_check(
        "issue_ownership",
        "No unresolved issues or workaround-only completion",
        required=bool(strict_issue_ownership),
        passed=not unresolved_issue_detected,
        detail="Complete the direct fix. Do not close with unresolved issues or workaround-only outcomes.",
    )

    if job_type == "coding":
        if writes_detected and require_verification_for_coding:
            add_check(
                "coding_verification",
                "Code changes were verified",
                required=True,
                passed=verification_after_write_detected,
                detail="Expected at least one post-change verification action (readback/diff/test/lint/check).",
            )
        if writes_detected and require_tests_for_code_edits:
            add_check(
                "coding_tests",
                "Tests ran after code edits",
                required=True,
                passed=tests_detected,
                detail="Expected at least one explicit test command execution.",
            )
        if writes_detected and require_monolith_guard_for_coding:
            add_check(
                "coding_monolith_guard",
                "Monolith guard passed after code edits",
                required=True,
                passed=monolith_guard_ran and monolith_guard_passed,
                detail="Run and pass `python scripts/check_monolith_guard.py` after code mutations.",
            )
        if writes_detected:
            detail = (
                "Oversized edited files: "
                + ", ".join(
                    f"{row['path']} ({row['lines']} lines; limit {row['max_lines']})" for row in oversized_written_files
                )
                if oversized_written_files
                else "No edited files exceeded hard monolith limits."
            )
            add_check(
                "coding_large_file_refactor",
                "Oversized edited files were split instead of extended inline",
                required=True,
                passed=(len(oversized_written_files) == 0),
                detail=detail,
            )
        if placeholder_reports:
            detail = (
                "Placeholder-backed files must include placeholder-why, placeholder-scope_to_finish, "
                "placeholder-owner, placeholder-exit_rule, and placeholder-acceptance annotations. "
                f"Missing annotations: {', '.join(sorted(set(placeholder_incomplete_paths)))}"
                if placeholder_incomplete_paths
                else "Placeholder-backed file annotations are complete."
            )
            add_check(
                "coding_placeholder_policy",
                "Placeholder-backed files carry a completion note",
                required=True,
                passed=(len(placeholder_incomplete_paths) == 0),
                detail=detail,
            )

    if job_type == "config":
        add_check(
            "config_valid",
            "Configuration validates",
            required=True,
            passed=(len(config_errors) == 0),
            detail="thomas.core.config validation must return no errors.",
        )
        add_check(
            "config_no_unknown_core_keys",
            "No unknown core config keys",
            required=True,
            passed=(len(unknown_core_keys) == 0),
            detail=("Unknown core keys: " + ", ".join(unknown_core_keys[:6]) if unknown_core_keys else "None."),
        )
        if writes_detected:
            add_check(
                "config_verification",
                "Config changes were verified",
                required=True,
                passed=verification_after_write_detected,
                detail="Expected a post-change verification action after config mutation.",
            )

    if job_type == "planning":
        has_steps = bool(re.search(r"(^|\n)\s*(?:\d+\.|-)\s+\S", response_text))
        add_check(
            "planning_actionable",
            "Plan is actionable",
            required=False,
            passed=has_steps,
            detail="Structured steps improve handoff and execution consistency.",
        )

    if job_type == "research":
        has_sources_signal = ("http://" in response_text) or ("https://" in response_text)
        add_check(
            "research_sources",
            "Research includes source signals",
            required=False,
            passed=has_sources_signal,
            detail="Links/citations make claims auditable.",
        )

    if job_type == "video_design":
        has_design_spec = bool(
            re.search(r"\b(shot|scene|timing|duration|palette|typography|motion|layout)\b", response_text, re.I)
        )
        add_check(
            "video_design_spec",
            "Video/design output includes concrete production specs",
            required=False,
            passed=has_design_spec,
            detail="Concrete specs improve repeatability across operators.",
        )

    failed_required = required_failed_checks({"checks": checks})
    passed = len(failed_required) == 0
    recommendations = [f"{c['title']}: {c['detail']}" for c in failed_required]

    if passed:
        summary = "Rules-of-the-road checks passed."
    else:
        summary = f"{len(failed_required)} required rules failed."

    return {
        "job_type": job_type,
        "passed": bool(passed),
        "attempt": int(attempt),
        "required_failed_count": len(failed_required),
        "checks": checks,
        "summary": summary,
        "recommendations": recommendations,
        "signals": {
            "writes_detected": writes_detected,
            "verification_detected": verification_detected,
            "verification_after_write_detected": verification_after_write_detected,
            "tests_detected": tests_detected,
            "monolith_guard_ran": monolith_guard_ran,
            "monolith_guard_passed": monolith_guard_passed,
            "tool_calls": len(tool_events),
            "tool_failures": failed_tools,
            "config_change_detected": config_change_detected,
            "strict_issue_ownership": bool(strict_issue_ownership),
            "unresolved_issue_detected": bool(unresolved_issue_detected),
            "placeholder_file_count": len(placeholder_reports),
            "placeholder_incomplete_paths": sorted(set(placeholder_incomplete_paths)),
            "oversized_written_files": oversized_written_files,
        },
    }


def build_remediation_prompt(report: dict[str, Any]) -> str:
    if bool(report.get("passed", False)):
        return ""
    lines = [
        "Quality gate failed. Continue working now and fix the required checks below before finalizing.",
        f"Job type: {report.get('job_type', 'general')}",
        "Required failures:",
    ]
    failed_required = required_failed_checks(report)
    for check in failed_required:
        lines.append(f"- {check.get('title')}: {check.get('detail')}")
    if any(str(check.get("id") or "") == "issue_ownership" for check in failed_required):
        lines.append(
            "Do not ship a workaround-only outcome. Own the issue and complete the actual fix before final answer."
        )
    oversized_written_files = list((report.get("signals") or {}).get("oversized_written_files") or [])
    if oversized_written_files:
        lines.append("Oversized files touched in this attempt:")
        for row in oversized_written_files:
            lines.append(
                f"- {row.get('path')}: {row.get('lines')} lines (limit {row.get('max_lines')}). "
                "Extract cohesive helpers/modules or move the new behavior into a smaller file."
            )
        lines.append("Do not keep appending to oversized files. Split/refactor them, then retry the task.")
    elif any(str(check.get("id") or "") == "coding_monolith_guard" for check in failed_required):
        lines.append(
            "If the monolith guard fails, do not just rerun it. Split or extract the oversized code first, then rerun the guard."
        )
    lines.append("When done, provide the final answer only after these checks pass.")
    return "\n".join(lines)
