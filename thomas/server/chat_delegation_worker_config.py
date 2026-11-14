"""Structured worker runtime configuration and deterministic retry guidance.

Semantic choices such as specialist, fanout, workspace, and whether a prompt asks
for an artifact belong to Thomas's model tool call.  This module intentionally
contains no natural-language intent classifier.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from thomas.core.file_access import clamp_file_access_level, file_access_spec
from thomas.server.chat_delegation_live_repo import _changed_in_green, _with_live_repo_change_requirement
from thomas.server.chat_delegation_runner_events import _PASS_BUDGET_EXHAUSTED_RE

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
# _replan_prompt's green_changes when the caller did not look it up: look it up here.
_LOOK_UP = object()


def _self_recovery_attempts(autonomy_level: int) -> int:
    """Bounded replan budget: 12 attempts on Autopilot (L5), 3 at L4, 1 below.

    L5 (Autopilot) is a runaway guard, not a cap on normal work. You asked
    that Thomas "shouldnt stop until it ha[s] a finoisherfd product it deems
    good," so exhausting a *pass* budget mid-task (still active work, just
    out of steps this attempt) must lead to another attempt in the same
    workspace rather than a report back asking you to say go.
    """

    level = int(autonomy_level or 0)
    if level >= 5:
        return 12
    if level >= 4:
        return 3
    return 1


def _safe_autonomy_level(value: Any) -> int:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        parsed = 0
    return max(1, min(5, parsed or 1))


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


def _replan_prompt(
    original: str,
    last_error: str,
    attempt: int,
    total: int,
    progress_summary: str | list[str] = "",
    root: Path | None = None,
    green_changes: Any = _LOOK_UP,
) -> str:
    """Augment the task prompt with deterministic failure evidence for retry.

    ``progress_summary`` is the execution's own progress from just before the
    failure (e.g. the tools it finished) — a pass-budget exhaustion is not a
    reason to throw the attempt's progress away, so the next attempt is told
    what was already done, not just what went wrong. It accepts either a
    single line (backward compatible) or a list of lines, of which only the
    most recent three are kept: one line was too little context for an
    attempt to pick its work back up without redoing it (self-fix evidence,
    2026-09-24). ``root`` is the workspace to look up ``_changed_in_green``
    in. ``green_changes`` is that lookup already made: the runner makes it
    once per retry and hands it to this and to the completion requirement, so
    a green's git diff is not run again for each sentence (fix round 3).
    """

    error_text = str(last_error or "")
    # N3: the runner calls this on every retry, for isolated and self-development
    # workers alike, so whether the workspace is a green is checked, not assumed.
    if green_changes is _LOOK_UP:
        green_changes = _changed_in_green(root) if root is not None else None
    in_green = green_changes is not None
    # Ruling: "when it really is the live repo, keep the wording" -- these two
    # branches predate N3 and are pinned verbatim by an existing test, so the
    # non-green case must render identically to before, not just similarly.
    scope_adj = "self-fix" if in_green else "live-repo"
    displayed_error_text = (
        error_text.replace("no live repo files", "no tracked files in this workspace").replace(
            "live-repo proof persistence failed", "this self-fix run's proof could not be saved"
        )
        if in_green
        else error_text
    )
    prompt = (
        f"{original}\n\n"
        f"[Self-recovery — attempt {attempt} of {total}]\n"
        f"A previous attempt did not succeed. The failure was:\n{displayed_error_text}\n\n"
    )
    raw_lines = [progress_summary] if isinstance(progress_summary, str) else list(progress_summary or [])
    progress_lines = [line for line in (str(item or "").strip() for item in raw_lines) if line and line != error_text]
    progress_lines = progress_lines[-3:]
    if progress_lines:
        rendered = "\n".join(f"- {line}" for line in progress_lines)
        prompt += f"Progress so far, before that failure:\n{rendered}\n\n"
    if _PASS_BUDGET_EXHAUSTED_RE.match(error_text):
        # A pass-budget stop is not a failed approach -- the task was still
        # being worked when this attempt ran out of steps. "Take a DIFFERENT
        # approach" told a worker mid-repair to abandon a plan that was
        # working (fix round 1, I3).
        files_clause = f" so far: {', '.join(green_changes[:8])}" if green_changes else ""
        prompt += (
            "You ran out of passes while this work was still active, not because "
            "the approach failed. Continue exactly where the last attempt stopped. "
            f"Your changes are still in this workspace{files_clause}. Do not redo "
            "finished steps — check what is already done before repeating any of it."
        )
    else:
        prompt += (
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
                "values, then use fs.write_file with replace_whole_file: true to OVERWRITE "
                "the exact filename requested by the user with those values and no "
                "placeholders -- this is a deliberate full rewrite. Finally call "
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
                "For every rejected file, call fs.write_file with replace_whole_file: true and complete "
                "corrected contents containing every listed literal, then call fs.read_file and confirm "
                "each literal is present before finishing."
            )
    if "no write tool was used" in error_lower:
        prompt += (
            "\n\nThe previous attempt only inspected the repo. Stop broad inspection now: "
            f"patch the smallest scoped {scope_adj} edit with diff.create (fs.write_file "
            "only for a file that does not exist yet), run the focused verification, or report "
            "the exact blocker that prevents the write. Your next substantive tool call must "
            "be diff.create, fs.write_file, or fs.write_protected_file. Do not call "
            "code.search, fs.read_file, fs.list_dir, git.status, or shell.exec again unless "
            "you first make a tracked source/test/doc edit or explicitly report why no edit "
            "is possible. For broad cleanup tasks, prefer a small regression test or catalog "
            "policy edit over continued architecture discovery."
        )
    elif "write tools used did not change counted files" in error_lower:
        prompt += (
            "\n\nA previous attempt called a write tool, but the write did not change any "
            f"counted {scope_adj} source/test/doc content. The next edit must change "
            "file content, not rewrite identical bytes, and it must target a non-ignored path "
            "outside runtime/, output/, library/, cache directories, and generated logs. "
            "Patch the smallest relevant tracked source/test/doc file with diff.create (or "
            "fs.write_file, for a file that does not exist yet), then run focused "
            "verification. If you cannot identify a safe content change, report that "
            "blocker explicitly."
        )
    if "no live repo files" in error_lower:
        prompt = _with_live_repo_change_requirement(prompt, root, in_green=in_green)
    return prompt
