"""Rules-of-the-road quality gate for task completion."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

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


def normalize_job_type(
    *,
    route_path: str,
    prompt_text: str,
    requested_job_type: Optional[str],
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


def _shell_command_from_event(evt: Dict[str, Any]) -> str:
    return str(evt.get("command") or "").strip()


def _config_path_from_event(evt: Dict[str, Any]) -> str:
    return str(evt.get("path") or "").strip()


def evaluate_rules(
    *,
    route_path: str,
    prompt_text: str,
    response_text: str,
    tool_events: List[Dict[str, Any]],
    requested_job_type: Optional[str],
    config_errors: List[str],
    unknown_core_keys: List[str],
    require_verification_for_coding: bool,
    require_tests_for_code_edits: bool,
    require_monolith_guard_for_coding: bool,
    attempt: int = 0,
) -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = []
    prompt_text = str(prompt_text or "")
    response_text = str(response_text or "")

    writes_detected = False
    verification_detected = False
    verification_after_write_detected = False
    tests_detected = False
    monolith_guard_ran = False
    config_change_detected = False
    failed_tools = 0
    write_seen = False

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
        if is_verification:
            verification_detected = True
            if write_seen:
                verification_after_write_detected = True
        if path.lower().endswith(".toml"):
            config_change_detected = True

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
                "Monolith guard ran after code edits",
                required=True,
                passed=monolith_guard_ran,
                detail="Run `python scripts/check_monolith_guard.py` after code mutations.",
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
            detail=(
                "Unknown core keys: " + ", ".join(unknown_core_keys[:6])
                if unknown_core_keys
                else "None."
            ),
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

    failed_required = [c for c in checks if c["required"] and (not c["passed"])]
    passed = len(failed_required) == 0
    recommendations = [
        f"{c['title']}: {c['detail']}" for c in failed_required
    ]

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
            "tool_calls": len(tool_events),
            "tool_failures": failed_tools,
            "config_change_detected": config_change_detected,
        },
    }


def build_remediation_prompt(report: Dict[str, Any]) -> str:
    if bool(report.get("passed", False)):
        return ""
    lines = [
        "Quality gate failed. Continue working now and fix the required checks below before finalizing.",
        f"Job type: {report.get('job_type', 'general')}",
        "Required failures:",
    ]
    for check in list(report.get("checks") or []):
        if bool(check.get("required")) and (not bool(check.get("passed"))):
            lines.append(f"- {check.get('title')}: {check.get('detail')}")
    lines.append(
        "When done, provide the final answer only after these checks pass."
    )
    return "\n".join(lines)
