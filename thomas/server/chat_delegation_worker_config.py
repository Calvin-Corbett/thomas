"""Structured worker runtime configuration and deterministic retry guidance.

Semantic choices such as specialist, fanout, workspace, and whether a prompt asks
for an artifact belong to Thomas's model tool call.  This module intentionally
contains no natural-language intent classifier.
"""

from __future__ import annotations

import re
from typing import Any

from thomas.core.file_access import clamp_file_access_level, file_access_spec
from thomas.server.chat_delegation_live_repo import _with_live_repo_change_requirement

TASK_MANAGER_BACKEND = "task_manager"
PROVIDER_NATIVE_BACKEND = "provider_native"

_EFFORT_UI_LABELS = {
    "cheap": "Quick",
    "balanced": "Standard",
    "optimal": "Standard",
    "max": "Thorough",
    "exhaustive": "Thorough",
}

# A sizeable fs.write_file call (for example a complete playable HTML game) can
# legitimately spend more than a minute generating its JSON arguments before the
# next event arrives. Keep a bounded watchdog, but do not kill healthy builds at
# the old 60-second boundary.
_WORKER_FIRST_EVENT_TIMEOUT_S = 180.0
_WORKER_IDLE_EVENT_TIMEOUT_S = 120.0
_WORKER_STREAM_CLOSE_TIMEOUT_S = 5.0
_WORKER_WATCHDOG_GRACE_S = 15.0


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
    model_id: str | None = None,
    reasoning_effort: str | None = None,
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
        "model_id": str(model_id or "").strip(),
        "reasoning_effort": str(reasoning_effort or "").strip().lower(),
        "build_quality_label": _EFFORT_UI_LABELS.get(
            str(effort or "").strip().lower(),
            str(effort or "").strip(),
        ),
        "guardrails": str(guardrails or "").strip(),
        "requires_live_repo_change": bool(requires_live_repo_change),
        "max_attempts": _self_recovery_attempts(effective_autonomy),
    }


def _replan_prompt(original: str, last_error: str, attempt: int, total: int) -> str:
    """Augment the task prompt with deterministic failure evidence for retry."""

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
    if "requested artifact verification failed" in error_lower:
        missing_text = [
            (name, literal)
            for name, _quote, literal in re.findall(
                r"requested artifact\s+([A-Za-z0-9][A-Za-z0-9_.-]{1,160})\s+"
                r"is missing required text\s+(['\"])(.*?)\2",
                error_text,
                re.IGNORECASE,
            )
        ]
        missing = list(
            dict.fromkeys(
                re.findall(
                    r"missing exact requested artifact\s+([A-Za-z0-9][A-Za-z0-9_.-]{1,160})",
                    error_text,
                    re.IGNORECASE,
                )
            )
        )
        if missing:
            prompt += (
                "\n\nNo acceptable requested file exists yet. Your next substantive tool "
                "calls MUST be fs.write_file, one for each missing exact filename: "
                + ", ".join(missing)
                + ". Do not inspect or explain first. Write complete contents with no "
                "placeholders, then call fs.read_file on every filename and correct any "
                "mismatch before finishing."
            )
        else:
            prompt += (
                "\n\nThe prior run produced an artifact, but deterministic proof rejected its "
                "name or contents. Do not abandon the requested workflow and do not only "
                "explain the correction. Re-run every source/read tool needed for real "
                "values, then use fs.write_file to OVERWRITE the exact filename requested "
                "by the user with those values and no placeholders. Finally call "
                "fs.read_file on that exact filename and correct any remaining mismatch "
                "before finishing."
            )
        if missing_text:
            repair_lines = "\n".join(
                f"- {name} MUST contain this exact literal: {literal}" for name, literal in missing_text
            )
            affected = ", ".join(dict.fromkeys(name for name, _literal in missing_text))
            prompt += (
                "\n\nDeterministic verification identified these exact repairs:\n"
                f"{repair_lines}\n"
                f"Repair ONLY these rejected files: {affected}. Do not rewrite artifacts that already passed. "
                "For every rejected file, call fs.write_file with complete corrected contents containing "
                "every listed literal, then call fs.read_file and confirm each literal is present before "
                "finishing."
            )
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
