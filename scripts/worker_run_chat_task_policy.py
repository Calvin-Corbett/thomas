"""Task policy helpers for background chat task execution."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_PROMPT_PATH_RE = re.compile(
    r"([A-Za-z]:\\[^\s,\"']+|(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+|[A-Za-z0-9_.-]+\.(?:py|toml|json|md|txt|csv|js|mjs))"
)
_ARTIFACT_WRITE_RE = re.compile(
    r"\b(?:write|create\s+(?:a\s+)?(?:python\s+)?script\s+at)\s+"
    r"(?P<path>[A-Za-z]:\\[^\s,\"']+|/[^\s,\"']+|(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+)",
    re.I,
)
_SOURCE_EDIT_RE = re.compile(
    r"\b(?:edit|modify|change|patch|refactor|rewrite|update|replace|fix)\b",
    re.I,
)

_TASK_CAPABILITY_CLASSES = {
    "default",
    "artifact_only",
    "repo_read_only",
    "repo_edit_green_only",
    "repo_edit_private_checkpointable",
}


@dataclass(frozen=True)
class TaskExecutionPolicy:
    capability_class: str = "default"
    allowed_actions: tuple[str, ...] = ("read", "write", "execute")
    allowed_write_roots: tuple[str, ...] = ()
    dirty_worktree_waiver: bool = False
    policy_source: str = "default"


def _normalize_repo_relative_path(value: str) -> str:
    text = str(value or "").strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    while "//" in text:
        text = text.replace("//", "/")
    return text.strip("/")


def _candidate_artifact_target(prompt: str) -> str:
    prompt_text = str(prompt or "").strip()
    if not prompt_text or _SOURCE_EDIT_RE.search(prompt_text):
        return ""
    write_match = _ARTIFACT_WRITE_RE.search(prompt_text)
    if not write_match:
        return ""
    raw_target = str(write_match.group("path") or "").strip()
    if not raw_target:
        return ""
    normalized = _normalize_repo_relative_path(raw_target)
    repo_runtime_prefix = f"{ROOT.as_posix().lower()}/runtime/agentic_bench/"
    lowered = normalized.lower()
    if lowered.startswith("runtime/agentic_bench/") or lowered.startswith(repo_runtime_prefix):
        if lowered.startswith(repo_runtime_prefix):
            normalized = _normalize_repo_relative_path(normalized[len(ROOT.as_posix()) :])
        return normalized
    return ""


def _policy_from_capability_class(
    capability_class: str,
    *,
    allowed_write_roots: tuple[str, ...] = (),
    policy_source: str,
) -> TaskExecutionPolicy:
    resolved = str(capability_class or "").strip().lower() or "default"
    if resolved not in _TASK_CAPABILITY_CLASSES:
        resolved = "default"
    if resolved == "artifact_only":
        actions = ("read", "write")
        waiver = True
    elif resolved == "repo_read_only":
        actions = ("read",)
        waiver = False
    else:
        actions = ("read", "write", "execute")
        waiver = False
    return TaskExecutionPolicy(
        capability_class=resolved,
        allowed_actions=actions,
        allowed_write_roots=allowed_write_roots,
        dirty_worktree_waiver=waiver,
        policy_source=policy_source,
    )


def _legacy_task_execution_policy(prompt: str) -> TaskExecutionPolicy:
    target = _candidate_artifact_target(prompt)
    if not target:
        return TaskExecutionPolicy()
    return _policy_from_capability_class(
        "artifact_only",
        allowed_write_roots=(target,),
        policy_source="legacy_inference",
    )


def _resolve_task_execution_policy(record: dict[str, object], prompt: str) -> TaskExecutionPolicy:
    raw_policy = record.get("task_policy")
    if isinstance(raw_policy, dict):
        roots = tuple(
            _normalize_repo_relative_path(item)
            for item in list(raw_policy.get("allowed_write_roots") or [])
            if _normalize_repo_relative_path(item)
        )
        capability_class = str(raw_policy.get("capability_class") or raw_policy.get("class") or "default").strip()
        return _policy_from_capability_class(
            capability_class,
            allowed_write_roots=roots,
            policy_source="task_record",
        )
    top_level_class = str(record.get("capability_class") or "").strip()
    if top_level_class:
        return _policy_from_capability_class(top_level_class, policy_source="task_record")
    execution_intent = str(record.get("execution_intent") or "").strip().lower()
    if execution_intent == "production_task":
        return _policy_from_capability_class(
            "repo_edit_private_checkpointable",
            policy_source="production_mode",
        )
    return _legacy_task_execution_policy(prompt)


def _task_policy_mismatch_reason(prompt: str, policy: TaskExecutionPolicy) -> str:
    prompt_text = str(prompt or "").strip()
    if policy.capability_class == "artifact_only":
        if _SOURCE_EDIT_RE.search(prompt_text):
            return "artifact_only tasks cannot request repo source edits"
        target = _candidate_artifact_target(prompt_text)
        if not target:
            return "artifact_only tasks must name an explicit runtime/agentic_bench output path"
        if policy.allowed_write_roots and target not in set(policy.allowed_write_roots):
            return f"artifact_only output path `{target}` is outside the allowed write roots"
    if policy.capability_class == "repo_read_only" and _candidate_artifact_target(prompt_text):
        return "repo_read_only tasks cannot request artifact writes"
    return ""


def _background_execution_guidance(prompt: str, *, policy: TaskExecutionPolicy | None = None) -> str:
    prompt_text = str(prompt or "").strip()
    if not prompt_text:
        return ""
    resolved_policy = policy or TaskExecutionPolicy()
    referenced_paths: list[str] = []
    seen: set[str] = set()
    for match in _PROMPT_PATH_RE.findall(prompt_text):
        candidate = str(match or "").strip().strip(",.;")
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        referenced_paths.append(candidate)
        if len(referenced_paths) >= 8:
            break

    lines = [
        "--- Background Execution Guidance ---",
        "- This is an execution task. Act on the request instead of discussing how you might do it.",
        f"- Repository root for this task: {ROOT}",
        "- If the prompt names repo files, folders, or output paths, use those exact paths directly.",
        "- Do not recursively search the whole repository unless the prompt explicitly asks you to find something.",
        "- When a target output path is given, create that artifact directly and put the deliverable there.",
        "- Prefer the smallest direct tool sequence that completes the task and verifies the result.",
        (
            f"- Task capability class: {resolved_policy.capability_class} "
            f"(policy source: {resolved_policy.policy_source})."
        ),
    ]
    if resolved_policy.allowed_write_roots:
        lines.append("- Allowed write roots for this task:")
        lines.extend(f"  - {item}" for item in resolved_policy.allowed_write_roots)
    if referenced_paths:
        lines.append("- Explicit paths/files already named in the task:")
        for item in referenced_paths:
            resolved = ""
            candidate_path = Path(item)
            if candidate_path.is_absolute():
                resolved = str(candidate_path)
            else:
                project_path = (ROOT / candidate_path).resolve()
                if project_path.exists() or item.startswith(
                    ("runtime/", "tests/", "thomas/", "scripts/", "demo/", "skills/", "plugins/")
                ):
                    resolved = str(project_path)
            lines.append(f"  - {item} -> {resolved}" if resolved and resolved != item else f"  - {item}")
    if resolved_policy.dirty_worktree_waiver:
        lines.extend(
            [
                "- This task is pre-approved to bypass dirty-worktree startup checks.",
                "- The allowed scope is: read repo files named in the prompt and create or overwrite only the allowed artifact output path.",
                "- Do not ask the user for a dirty-worktree waiver for this task.",
                "- Do not modify repo source files, tests, or configuration as part of this task.",
            ]
        )
    return "\n".join(lines)


def _should_waive_dirty_worktree_for_artifact_task(prompt: str) -> bool:
    return _legacy_task_execution_policy(prompt).dirty_worktree_waiver


def _base_prompt(record: dict[str, object]) -> str:
    prompt = str(record.get("request_text") or "").strip()
    if prompt:
        return prompt
    summary = str(record.get("summary") or "").strip()
    if summary:
        return summary
    raise ValueError("Task-bot execution is missing request text")


def _apply_task_policy_prompt(prompt: str, policy: TaskExecutionPolicy) -> str:
    prompt_text = str(prompt or "").strip()
    if not policy.dirty_worktree_waiver:
        return prompt_text
    allowed_write_roots = ", ".join(policy.allowed_write_roots) if policy.allowed_write_roots else "runtime/agentic_bench"
    override = (
        f"Administrative task policy for this task: capability_class={policy.capability_class}. "
        "Dirty-worktree startup checks are waived for this task because the task record authorizes "
        "artifact-only execution. You are authorized to read the repo files named in the task and write only the "
        f"approved artifact output path(s): {allowed_write_roots}. Do not ask the user for a dirty-worktree waiver. "
        "Do not modify source files.\n\n"
    )
    return override + prompt_text
