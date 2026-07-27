"""Rules-of-the-road quality gate for task completion."""

from __future__ import annotations

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

_SHELL_TEST_RE = re.compile(
    r"\b(pytest|unittest|npm\s+test|pnpm\s+test|yarn\s+test|go\s+test|cargo\s+test|dotnet\s+test|mvn\s+test|gradle\s+test)\b",
    re.I,
)
_SHELL_VERIFY_RE = re.compile(
    r"\b(pytest|test|lint|ruff|mypy|typecheck|build|compile|doctor|validate|check)\b",
    re.I,
)
_GIT_TOPOLOGY_MUTATION_RE = re.compile(
    r"(?:"
    r"\bgit\s+(?:clone|init)\b|"
    r"\bgit\s+worktree\s+(?:add|move|remove|prune|repair)\b|"
    r"\bgit\s+(?:checkout|switch)\s+[^;&|\n]*(?:-b|-B|-c|-C|--create|--orphan)\b|"
    r"\bgit\s+branch\s+"
    r"(?!(?:$|-(?:a|r|v|vv|av|va|rv|vr|ar|ra)\b|"
    r"--(?:all|list|show-current|contains|merged|no-merged|remotes|verbose|"
    r"format|points-at|sort|color|column|abbrev)(?:=|\b)))"
    r")",
    re.I,
)
_MONOLITH_GUARD_RE = re.compile(
    r"\bmonolith_guard(?:\.py)?\b",
    re.I,
)
# Shell commands whose TEXT mutates files. rules_of_road previously classified
# writes by tool name only, so an agent could mutate a file through shell.exec
# (e.g. python -c "...write_text(...)" or `echo x > file`) and the engine saw
# writes_detected=False, skipping every post-write quality requirement (B/R1).
# This detector marks such commands as writes regardless of the tool name.
# NOTE (B11): command-text matching is an inherently incomplete denylist — an
# agent can always reach for another file-write API. This catches the known
# forms; the robust long-term fix is provenance-based write detection (the tool
# layer reporting which files actually changed), not string matching. Tracked
# as a follow-up in praxis-unbypassable-2026-05-29/PROBLEM.md.
_SHELL_MUTATING_RE = re.compile(
    r"(?:"
    r"\bwrite_text\b|\bwrite_bytes\b|\bwritelines\b|"  # pathlib / Python
    r"\.write\s*\(|\.writelines\s*\(|\.touch\s*\(|\.rename\s*\(|\.unlink\s*\(|"  # file-object / Path write/rename/unlink
    r"\bos\.replace\s*\(|"  # os.replace (Path.replace shares str.replace text, so cannot be matched safely)
    r"open\s*\([^)]*,\s*['\"][wax]|\.open\s*\(\s*['\"][wax]|"  # open(...,'w'/'a'/'x')
    r"\bshutil\.(?:copy|copy2|copyfile|copytree|move)\b|"  # shutil
    r"\bos\.(?:remove|unlink|rename|replace|rmdir|mkdir|makedirs|truncate)\b|"  # os
    r"\bSet-Content\b|\bAdd-Content\b|\bOut-File\b|\bNew-Item\b|\bSet-Item\b|"  # PowerShell
    r"\bTee-Object\b|\btee\b|"
    r"WriteAllText|WriteAllBytes|WriteAllLines|AppendAllText|AppendAllLines|"  # .NET
    r"writeFileSync|appendFileSync|createWriteStream|\bfs\.write\b|\bfs\.append\b|"  # Node
    r"\bsed\s+-i|\bperl\s+-[a-z]*i\b|"  # in-place stream edit
    r"\btruncate\b|\bdd\s|"
    r"\bRemove-Item\b|\bMove-Item\b|\bCopy-Item\b|"
    r"\bcp\b|\bmv\b|\brm\b|\bdel\b|\berase\b|"
    r"\bgit\s+apply\b|\bgit\s+checkout\s+--|\bpatch\s|\bapply_patch\b|"
    r">>?\s*[^&\s|>]"  # redirection to a file (excludes 2>&1 / >&)
    r")",
    re.I,
)
# Commands that merely emit text. They cannot serve as evidence that a skill
# probe actually ran — otherwise `echo "<snippet> []"` spoofs the check (R3).
_ECHO_LIKE_RE = re.compile(
    r"^\s*(?:@?echo\b|echo\.|printf\b|print\s*\(|write-output\b|write-host\b|:\s|true\b|cat\b|type\b|get-content\b)",
    re.I,
)


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
    del prompt_text
    if config_change_detected:
        return "config"
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
        or n.startswith("edit:")
        or n.startswith("filechange")
        or n in {"fs.write_file", "fs.delete_file"}
        or "write" in n
        or "delete" in n
        or "remove" in n
        or "apply_patch" in n
    )


def _is_verification_tool(name: str) -> bool:
    n = str(name or "").strip().lower()
    # B15 (praxis-unbypassable-2026-05-29): `shell.exec` is intentionally NOT
    # treated as verification by name. Otherwise any successful shell command
    # (pwd, sleep, `python -c pass`, Write-Host) satisfied the post-write
    # verification requirement. A shell command only earns verification credit
    # when its TEXT matches a real verifier (_SHELL_VERIFY_RE / _SHELL_TEST_RE)
    # in evaluate_rules. Structured read/inspect tools below still count.
    if n in {
        "fs.read_file",
        "code.search",
        "code.find_definition",
        "code.find_references",
        "git.diff",
        "rag.search",
    }:
        return True
    return n.startswith("git.diff") or n.startswith("code.search")


def _is_mutating_shell_command(cmd: str) -> bool:
    """True if a shell command's text mutates files on disk (R1)."""
    text = str(cmd or "").strip()
    if not text:
        return False
    return bool(_SHELL_MUTATING_RE.search(text))


def _is_git_topology_mutation_command(cmd: str) -> bool:
    """True if a shell command attempts to create a side repo, branch, or worktree."""
    text = str(cmd or "").strip()
    if not text:
        return False
    normalized = re.sub(r"\s+", " ", text)
    return bool(_GIT_TOPOLOGY_MUTATION_RE.search(normalized))


def _is_echo_like_command(cmd: str) -> bool:
    """True if a command merely emits text (echo/print/cat), so it cannot
    stand as evidence that a real skill probe executed (R3)."""
    return bool(_ECHO_LIKE_RE.search(str(cmd or "")))


def _shell_command_from_event(evt: dict[str, Any]) -> str:
    command = str(evt.get("command") or "").strip()
    if command:
        return command
    name = str(evt.get("name") or "").strip()
    if not name:
        return ""
    lowered = name.lower()
    if lowered.startswith(("diff.", "fs.", "code.", "git.diff", "edit:")):
        return ""
    if re.search(
        r"\b(python|pytest|unittest|npm|pnpm|yarn|go|cargo|dotnet|mvn|gradle|ruff|mypy|node|git|rg|powershell|pwsh|cmd|bash|sh)\b",
        lowered,
    ):
        return name
    if " -command " in lowered or " /c " in lowered:
        return name
    return ""


def _config_path_from_event(evt: dict[str, Any]) -> str:
    path = str(evt.get("path") or "").strip()
    if path:
        return path
    name = str(evt.get("name") or "").strip()
    if name.lower().startswith("edit:"):
        candidate = name.split(":", 1)[1].strip()
        if candidate and candidate != "?":
            return candidate
    return ""


def _event_observation_text(evt: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("name", "command", "path", "output_preview", "result", "result_text"):
        value = str(evt.get(key) or "")
        if value:
            parts.append(value)
    return "\n".join(parts)


def _event_output_text(evt: dict[str, Any]) -> str:
    return "\n".join(str(evt.get(key) or "") for key in ("output_preview", "result", "result_text") if evt.get(key))


def _contains_text(haystack: str, needle: str) -> bool:
    if not needle:
        return True
    return needle in haystack or needle.lower() in haystack.lower()


def _missing_skill_required_checks(
    *,
    required_checks: list[dict[str, Any]],
    tool_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    # R3: a skill probe only counts as run if a command actually executed
    # successfully (ok=True) and was not a text-emitting command (echo/print/
    # cat). Otherwise `echo "<snippet> <expected_output> []"` spoofs the check.
    observations: list[tuple[str, str]] = []
    for evt in tool_events:
        if not bool(evt.get("ok", False)):
            continue
        probe_cmd = str(evt.get("command") or evt.get("name") or "")
        if _is_echo_like_command(probe_cmd):
            continue
        observations.append((_event_observation_text(evt), _event_output_text(evt)))
    missing: list[dict[str, Any]] = []
    for check in required_checks:
        snippets = [str(item or "").strip() for item in list(check.get("snippets") or []) if str(item or "").strip()]
        expected_outputs = [
            str(item or "").strip() for item in list(check.get("expected_outputs") or []) if str(item or "").strip()
        ]
        if not snippets and not expected_outputs:
            continue
        passed = any(
            all(_contains_text(observed, snippet) for snippet in snippets)
            and all(_contains_text(output, expected) for expected in expected_outputs)
            for observed, output in observations
        )
        if not passed:
            best_observed = ""
            best_output = ""
            best_score = -1
            for observed, output in observations:
                score = sum(1 for snippet in snippets if _contains_text(observed, snippet))
                score += sum(1 for expected in expected_outputs if _contains_text(output, expected))
                if score > best_score:
                    best_score = score
                    best_observed = observed
                    best_output = output
            missing_snippets = [snippet for snippet in snippets if not _contains_text(best_observed, snippet)]
            missing_outputs = [expected for expected in expected_outputs if not _contains_text(best_output, expected)]
            missing.append(
                {
                    "skill": str(check.get("skill") or ""),
                    "text": str(check.get("text") or "")[:240],
                    "missing_snippets": missing_snippets[:4],
                    "missing_expected_outputs": missing_outputs[:4],
                }
            )
    return missing


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
    skill_required_checks: list[dict[str, Any]] | None = None,
    attempt: int = 0,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
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
    failed_test_after_write = False
    git_topology_mutation_detected = False
    placeholder_reports: list[dict[str, Any]] = []
    placeholder_incomplete_paths: list[str] = []
    skill_required_checks = [dict(row) for row in list(skill_required_checks or []) if isinstance(row, dict)]
    placeholder_repo_root = Path(repo_root).resolve() if repo_root else Path(__file__).resolve().parents[2]
    monolith_guard_available = (placeholder_repo_root / "scripts" / "forge" / "gates" / "monolith_guard.py").exists()

    for evt in tool_events:
        name = str(evt.get("name") or "")
        ok = bool(evt.get("ok", False))
        cmd = _shell_command_from_event(evt)
        path = _config_path_from_event(evt)
        is_write = _is_write_tool(name)
        is_verification = _is_verification_tool(name)
        # R1: a shell command that mutates files counts as a write even though
        # the tool name (shell.exec) is not a write tool.
        mutating = bool(cmd and _is_mutating_shell_command(cmd))
        git_topology_mutation = bool(cmd and _is_git_topology_mutation_command(cmd))
        echo_like = bool(cmd and _is_echo_like_command(cmd))
        if git_topology_mutation:
            git_topology_mutation_detected = True
        if mutating and not is_write:
            is_write = True
        # Neither a file mutation (R1) nor a bare text-emit like `echo verified`
        # (B10) is a verification action, even though shell.exec is otherwise
        # treated as a verification-capable tool. Without this, such a command
        # would "verify itself" and satisfy the post-write verification
        # requirement.
        if mutating or echo_like:
            is_verification = False

        if not ok:
            failed_tools += 1
        if is_write:
            writes_detected = True
            write_seen = True
        # R2/B10: only credit verification/tests when the command actually
        # succeeded (ok=True) and is neither a mutation nor a bare echo/print.
        # A failing pytest must not satisfy "tests ran"; `echo verified` must
        # not satisfy "verified".
        if cmd and ok and not mutating and not echo_like and _SHELL_VERIFY_RE.search(cmd):
            is_verification = True
        if cmd and ok and not mutating and not echo_like and _SHELL_TEST_RE.search(cmd):
            tests_detected = True
            is_verification = True
        # R2: a test command that FAILED after a write is a hard failure — the
        # agent cannot run a failing test and call the work verified.
        if cmd and (not ok) and write_seen and _SHELL_TEST_RE.search(cmd):
            failed_test_after_write = True
        if cmd and _MONOLITH_GUARD_RE.search(cmd):
            monolith_guard_ran = True
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

    add_check(
        "git_topology_protection",
        "No side clones, branches, or worktrees were created",
        required=True,
        passed=not git_topology_mutation_detected,
        detail=(
            "Agents must work in the assigned checkout. Repository topology changes require "
            "explicit human action outside an agent run."
        ),
    )

    del strict_issue_ownership

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
            # R2: even if some test ran, a test command that reported failure
            # after a write blocks completion. Stops "run a failing test then
            # declare done".
            add_check(
                "coding_tests_passed",
                "Tests passed after code edits",
                required=True,
                passed=(not failed_test_after_write),
                detail="A test command run after code edits reported failure (ok=False). Fix the failing tests before finalizing.",
            )
        if writes_detected and require_monolith_guard_for_coding and monolith_guard_available:
            add_check(
                "coding_monolith_guard",
                "Monolith guard ran after code edits",
                required=True,
                passed=monolith_guard_ran,
                detail="Run `python scripts/forge/gates/monolith_guard.py` after code mutations.",
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
        if writes_detected and skill_required_checks:
            missing_skill_checks = _missing_skill_required_checks(
                required_checks=skill_required_checks,
                tool_events=tool_events,
            )
            detail = (
                "Missing required skill probe snippets: "
                + "; ".join(
                    f"{row.get('skill')}: {', '.join(row.get('missing_snippets') or [])}"
                    + (
                        f" (expected output: {', '.join(row.get('missing_expected_outputs') or [])})"
                        if row.get("missing_expected_outputs")
                        else ""
                    )
                    for row in missing_skill_checks[:4]
                )
                if missing_skill_checks
                else "All skill-required probe snippets were observed in tool commands or output."
            )
            add_check(
                "coding_skill_required_checks",
                "Skill-required probes ran",
                required=True,
                passed=(len(missing_skill_checks) == 0),
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
            "failed_test_after_write": failed_test_after_write,
            "git_topology_mutation_detected": bool(git_topology_mutation_detected),
            "monolith_guard_ran": monolith_guard_ran,
            "monolith_guard_available": monolith_guard_available,
            "tool_calls": len(tool_events),
            "tool_failures": failed_tools,
            "config_change_detected": config_change_detected,
            "placeholder_file_count": len(placeholder_reports),
            "placeholder_incomplete_paths": sorted(set(placeholder_incomplete_paths)),
            "skill_required_check_count": len(skill_required_checks),
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
    lines.append("When done, provide the final answer only after these checks pass.")
    return "\n".join(lines)
