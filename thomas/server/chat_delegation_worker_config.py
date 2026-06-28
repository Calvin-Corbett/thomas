from __future__ import annotations

import re
from typing import Any

from thomas.core.file_access import clamp_file_access_level, file_access_spec
from thomas.server.chat_delegation_live_repo import _with_live_repo_change_requirement

TASK_MANAGER_BACKEND = "task_manager"
PROVIDER_NATIVE_BACKEND = "provider_native"

_COUNT_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "couple": 2,
    "few": 3,
}
_MULTI_AGENT_COUNT_RE = re.compile(
    r"(?:spawn|start|launch|run|create|use)\s+"
    r"(?:exactly\s+)?(?:a\s+)?(?P<count>\d+|one|two|three|four|five|couple|few)\s+"
    r"(?:real\s+|live\s+|tiny\s+|distinct\s+|lightweight\s+|small\s+|task\s+)*"
    r"(?:sub[- ]?agents?|agents?|helpers?|workers?)",
    re.I,
)
_EFFORT_UI_LABELS = {
    "cheap": "Quick",
    "balanced": "Standard",
    "optimal": "Standard",
    "max": "Thorough",
    "exhaustive": "Thorough",
}
_WORKER_FIRST_EVENT_TIMEOUT_S = 75.0
_WORKER_IDLE_EVENT_TIMEOUT_S = 240.0


def _infer_specialist(prompt: str) -> str:
    text = str(prompt or "").lower()
    if any(token in text for token in ("code", "bug", "endpoint", "api", "test", "refactor", "implement")):
        return "coding"
    if any(token in text for token in ("research", "find", "look up", "compare", "investigate")):
        return "research"
    if any(token in text for token in ("tool", "command", "run ", "install", "configure", "setup", "set up")):
        return "tools"
    return "reasoning"


def _requested_delegate_count(prompt: str) -> int:
    text = str(prompt or "").strip().lower()
    if not text:
        return 1
    match = _MULTI_AGENT_COUNT_RE.search(text)
    if not match:
        return 1
    raw = str(match.group("count") or "").strip().lower()
    if raw.isdigit():
        value = int(raw)
    else:
        value = _COUNT_WORDS.get(raw, 1)
    return max(1, min(5, int(value or 1)))


def _helper_prompt(prompt: str, *, helper_index: int, helper_count: int, bot_name: str) -> str:
    if helper_count <= 1:
        return prompt
    return (
        f"{prompt.rstrip()}\n\n"
        f"[Helper assignment]\n"
        f"You are helper {helper_index} of {helper_count} ({bot_name}). "
        f"Take a distinct slice of the work from the other helpers, avoid duplicating them, "
        f"and report concise progress."
    ).strip()


def _self_recovery_attempts(autonomy_level: int) -> int:
    """Bounded replan budget: 3 retries at max autonomy (L4), 1 pass below."""
    return 3 if int(autonomy_level or 0) >= 4 else 1


def _safe_autonomy_level(value: Any) -> int:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        parsed = 0
    return max(1, min(4, parsed or 1))


def _agent_worker_runtime_profile(
    *,
    autonomy_level: int,
    file_access: int | None,
    effort: str,
    guardrails: str,
    requires_live_repo_change: bool,
) -> dict[str, Any]:
    effective_autonomy = _safe_autonomy_level(autonomy_level)
    effective_file_access = clamp_file_access_level(file_access if file_access is not None else 1)
    spec = file_access_spec(effective_file_access)
    return {
        "backend_type": PROVIDER_NATIVE_BACKEND,
        "autonomy_level": effective_autonomy,
        "file_access": effective_file_access,
        "file_access_label": spec.ui_label,
        "effort": str(effort or "").strip() or "diligent",
        "build_quality_label": _EFFORT_UI_LABELS.get(str(effort or "").strip().lower(), str(effort or "").strip()),
        "guardrails": str(guardrails or "").strip(),
        "requires_live_repo_change": bool(requires_live_repo_change),
        "max_attempts": _self_recovery_attempts(effective_autonomy),
    }


def _replan_prompt(original: str, last_error: str, attempt: int, total: int) -> str:
    """Augment the task prompt with the prior failure so the next attempt adapts."""
    error_text = str(last_error or "")
    prompt = (
        f"{original}\n\n"
        f"[Self-recovery — attempt {attempt} of {total}]\n"
        f"A previous attempt did not succeed. The failure was:\n{error_text}\n\n"
        "Diagnose why it failed and take a DIFFERENT approach this time — do not "
        "repeat the steps that just failed. If a tool or capability seems missing, "
        "find another way to reach the goal with the tools you have."
    )
    error_lower = error_text.lower()
    if "no write tool was used" in error_lower:
        prompt += (
            "\n\nThe previous attempt only inspected the repo. Stop broad inspection now: "
            "make the smallest scoped live-repo edit with fs.write_file, run the focused "
            "verification, or report the exact blocker that prevents the write. Your next "
            "substantive tool call must be fs.write_file or fs.write_protected_file. Do not "
            "call code.search, fs.read_file, fs.list_dir, git.status, or shell.exec again "
            "unless you first make a tracked source/test/doc edit or explicitly report why "
            "no edit is possible. For broad cleanup tasks, prefer a small regression test or "
            "catalog policy edit over continued architecture discovery."
        )
    elif "write tools used did not change counted files" in error_lower:
        prompt += (
            "\n\nA previous attempt called a write tool, but the write did not change any "
            "counted live-repo source/test/doc content. The next edit must change file "
            "content, not rewrite identical bytes, and it must target a non-ignored path "
            "outside runtime/, output/, library/, cache directories, and generated logs. "
            "Use fs.write_file on the smallest relevant tracked source/test/doc file with "
            "different content, then run focused verification. If you cannot identify a "
            "safe content change, report that blocker explicitly."
        )
    if "no live repo files" in error_lower:
        prompt = _with_live_repo_change_requirement(prompt)
    return prompt
