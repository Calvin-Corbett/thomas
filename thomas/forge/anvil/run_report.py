"""Structured post-run report builder for Code runs (CAP-141).

Assembles a five-section report dict from a run's REAL recorded data — the
forge-event transcript (``forge_event_stream`` JSON lines), the git-truth
changed-file list, and the recorded outcome — never from invented content:

* ``attempts``            — each edit pass (initial + engine fix passes): goal,
                            outcome, key actions, exit state.
* ``validations``         — each engine check the run actually executed
                            (``tool``/``run`` + its ``tool_result``): command,
                            pass/fail, evidence snippet.
* ``open_risks``          — honest gaps the run data itself shows: failing or
                            missing verification, surfaced errors, refusals,
                            files changed without a matching validation.
* ``attention_pointers``  — ranked file/artifact references a reviewer should
                            look at first (failure sites, then changed files).
* ``rubric_mapping``      — run outcome mapped onto the completion criteria the
                            run was given (goal text + any acceptance bullets).

A degenerate run (empty transcript, no changes) produces an honest minimal
report: empty sections plus a single "no activity recorded" risk — nothing is
ever fabricated to fill a section.
"""

from __future__ import annotations

import json
import re
from typing import Any

_FIX_PASS_RE = re.compile(
    r"verification failed \(exit (?P<exit>-?\d+)\); fix pass (?P<i>\d+)/(?P<n>\d+)",
    re.IGNORECASE,
)
_FILE_LINE_RE = re.compile(r"(?P<ref>[\w][\w./\\-]*\.[A-Za-z]\w{0,7}:\d+)")
_CRITERION_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+(?P<text>\S.{3,})$")

_SNIPPET_CHARS = 240
_MAX_ACTIONS_PER_ATTEMPT = 8
_MAX_RISKS = 12
_MAX_POINTERS = 10
_MAX_CRITERIA = 12


def parse_forge_events(transcript: str) -> list[dict[str, Any]]:
    """Parse the forge-event JSON lines out of a stored run transcript.

    Non-event lines (CLI echo, prose) are skipped; token-progressive ``say``
    deltas are skipped too — the complete text they duplicate is what matters
    for a post-run report. Defensive: a malformed line is skipped, never raised on.
    """
    events: list[dict[str, Any]] = []
    for raw in str(transcript or "").split("\n"):
        line = raw.strip()
        if not line or line[0] != "{":
            continue
        try:
            obj = json.loads(line)
        except (ValueError, TypeError):
            continue
        if not isinstance(obj, dict) or not obj.get("fc"):
            continue
        if obj.get("delta") is True:
            continue
        events.append(obj)
    return events


def _snippet(text: Any, limit: int = _SNIPPET_CHARS) -> str:
    flat = " ".join(str(text or "").split())
    return flat[:limit]


def _segment_attempts(
    events: list[dict[str, Any]],
) -> tuple[list[list[dict[str, Any]]], list[re.Match[str]]]:
    """Split the event stream into per-pass segments at engine fix-pass markers."""
    segments: list[list[dict[str, Any]]] = [[]]
    markers: list[re.Match[str]] = []
    for event in events:
        match = _FIX_PASS_RE.search(str(event.get("text") or "")) if event.get("fc") == "meta" else None
        if match is not None:
            markers.append(match)
            segments.append([])
        else:
            segments[-1].append(event)
    return segments, markers


def _attempt_actions(segment: list[dict[str, Any]]) -> list[str]:
    """Key agent actions in one pass — its tool calls, minus the engine's own checks."""
    actions: list[str] = []
    for event in segment:
        if event.get("fc") != "tool" or str(event.get("name") or "") == "run":
            continue
        label = _snippet(f"{event.get('name') or 'tool'}: {event.get('text') or ''}".rstrip(": "), 120)
        if not actions or actions[-1] != label:
            actions.append(label)
    if len(actions) > _MAX_ACTIONS_PER_ATTEMPT:
        overflow = len(actions) - (_MAX_ACTIONS_PER_ATTEMPT - 1)
        actions = actions[: _MAX_ACTIONS_PER_ATTEMPT - 1] + [f"(+{overflow} more actions)"]
    return actions


def _build_attempts(
    events: list[dict[str, Any]],
    *,
    goal: str,
    outcome: str,
    returncode: int | None,
    reason: str,
) -> list[dict[str, Any]]:
    if not events:
        return []
    segments, markers = _segment_attempts(events)
    attempts: list[dict[str, Any]] = []
    for index, segment in enumerate(segments):
        is_last = index == len(segments) - 1
        if index == 0:
            attempt_goal = _snippet(goal, 200) or "initial edit pass"
        else:
            marker = markers[index - 1]
            attempt_goal = f"repair verification failure (exit {marker.group('exit')}) — fix pass {marker.group('i')}/{marker.group('n')}"
        errors = [_snippet(e.get("text")) for e in segment if e.get("fc") == "error"]
        if is_last:
            attempt_outcome = outcome or ("completed" if returncode == 0 else "failed")
            exit_state = f"exit {returncode}" + (f" — {_snippet(reason, 160)}" if reason else "")
        else:
            next_marker = markers[index]
            attempt_outcome = "verification failed"
            exit_state = (
                f"engine check failed (exit {next_marker.group('exit')}); handed to fix pass {next_marker.group('i')}"
            )
        attempts.append(
            {
                "pass": index + 1,
                "goal": attempt_goal,
                "outcome": attempt_outcome,
                "key_actions": _attempt_actions(segment),
                "errors": errors[:3],
                "exit_state": exit_state,
            }
        )
    return attempts


def _build_validations(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each engine check actually run: the ``run`` tool call paired with its result."""
    validations: list[dict[str, Any]] = []
    pending: str | None = None
    for event in events:
        kind = event.get("fc")
        if kind == "tool":
            pending = _snippet(event.get("text"), 200) if str(event.get("name") or "") == "run" else None
        elif kind == "tool_result" and pending is not None:
            validations.append(
                {
                    "kind": "engine_check",
                    "command": pending,
                    "passed": event.get("is_error") is not True,
                    "evidence": _snippet(event.get("text")),
                }
            )
            pending = None
    return validations


def _build_open_risks(
    events: list[dict[str, Any]],
    validations: list[dict[str, Any]],
    *,
    changed_files: list[str],
    returncode: int | None,
    ok: bool,
    outcome: str,
    reason: str,
    foreign_writes: list[str] | None = None,
) -> list[dict[str, Any]]:
    risks: list[dict[str, Any]] = []
    if not events:
        risks.append({"risk": "no run activity was recorded", "detail": "the transcript contains no forge events"})
    if returncode is None:
        risks.append({"risk": "process exit could not be confirmed", "detail": _snippet(reason)})
    elif returncode != 0:
        risks.append({"risk": f"run exited non-zero ({returncode})", "detail": _snippet(reason)})
    if validations and validations[-1]["passed"] is not True:
        risks.append(
            {
                "risk": "final verification failed",
                "detail": _snippet(f"{validations[-1]['command']} -> {validations[-1]['evidence']}"),
            }
        )
    if changed_files and not validations:
        risks.append(
            {
                "risk": "changed files were never validated",
                "detail": f"{len(changed_files)} file(s) changed but no engine check ran",
            }
        )
    passing_text = " ".join(f"{v['command']} {v['evidence']}" for v in validations if v["passed"])
    uncovered = [f for f in changed_files if f.split("/")[-1] not in passing_text]
    if validations and uncovered:
        shown = ", ".join(uncovered[:5]) + (f" (+{len(uncovered) - 5} more)" if len(uncovered) > 5 else "")
        risks.append(
            {
                "risk": "files changed without a matching passing validation",
                "detail": shown,
            }
        )
    if not ok and "could not complete the requested action" in str(reason or "").lower():
        risks.append({"risk": "the agent reported it could not complete the action", "detail": _snippet(reason)})
    for event in events:
        if event.get("fc") == "error" and len(risks) < _MAX_RISKS:
            risks.append({"risk": "error surfaced during the run", "detail": _snippet(event.get("text"))})
    if outcome == "noop" and not changed_files:
        risks.append({"risk": "run made no changes", "detail": "exit 0 but git shows no project delta"})
    risks.extend(_unopened_page_risks(events, validations, changed_files))
    if foreign_writes:
        shown = ", ".join(foreign_writes[:3]) + (f" (+{len(foreign_writes) - 3} more)" if len(foreign_writes) > 3 else "")
        risks.append(
            {
                "risk": "this run replaced work from another code task",
                "detail": f"{shown} — created by a different task in this shared project, and overwritten here",
            }
        )
    return risks[:_MAX_RISKS]


def _unopened_page_risks(
    events: list[dict[str, Any]],
    validations: list[dict[str, Any]],
    changed_files: list[str],
) -> list[dict[str, Any]]:
    """Flag a changed page that was never actually opened in a browser.

    A check that does not run reads exactly like a check that passed: the report
    said "0 open risks" while the strongest evidence available -- loading the
    page in a real browser -- had been skipped, because Chrome was missing or
    because nothing was found to own a changed asset. Every other risk here
    describes something that went wrong; this one describes something that never
    happened, which is the harder kind to notice and the reason a run can look
    green and still hand back a page nobody has seen.

    Scoped to changed HTML so it stays a fact rather than a guess. A project's
    Node scripts are not pages, and flagging them would train people to ignore
    this line, which is worse than not printing it.
    """

    pages = [name for name in changed_files if str(name).lower().endswith((".html", ".htm"))]
    if not pages:
        return []
    evidence = " ".join(
        [*(str(item.get("evidence") or "") for item in validations), *(str(item.get("text") or "") for item in events)]
    )
    if "BROWSER_SMOKE_OK" in evidence:
        return []
    shown = ", ".join(pages[:3]) + (f" (+{len(pages) - 3} more)" if len(pages) > 3 else "")
    skipped = "BROWSER_SMOKE_SKIPPED" in evidence
    return [
        {
            "risk": "a changed page was never opened in a browser",
            "detail": (
                f"{shown} — the browser check was skipped, so nothing here shows the page loads or draws"
                if skipped
                else f"{shown} — no browser check ran for this change"
            ),
        }
    ]


def _build_attention_pointers(
    events: list[dict[str, Any]],
    validations: list[dict[str, Any]],
    changed_files: list[str],
) -> list[dict[str, Any]]:
    """Ranked reviewer starting points: failure sites first, then changed files."""
    ordered: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(target: str, why: str) -> None:
        if target and target not in seen:
            seen.add(target)
            ordered.append((target, why))

    failure_text = " ".join(
        [f"{v['command']} {v['evidence']}" for v in validations if not v["passed"]]
        + [str(e.get("text") or "") for e in events if e.get("fc") == "error"]
    )
    for match in _FILE_LINE_RE.finditer(failure_text):
        add(match.group("ref"), "referenced by a failing check or error")
    for validation in validations:
        if not validation["passed"]:
            add(validation["command"], "failing engine check")
    for file in changed_files:
        add(file, "changed in this run")
    return [
        {"target": target, "why": why, "rank": rank}
        for rank, (target, why) in enumerate(ordered[:_MAX_POINTERS], start=1)
    ]


def _extract_criteria(goal: str, definition: str) -> list[str]:
    criteria: list[str] = []
    for line in f"{goal}\n{definition}".split("\n"):
        match = _CRITERION_RE.match(line)
        if match:
            criteria.append(_snippet(match.group("text"), 200))
    return criteria[:_MAX_CRITERIA]


def _build_rubric_mapping(
    goal: str,
    definition: str,
    validations: list[dict[str, Any]],
    *,
    ok: bool,
    outcome: str,
    reason: str,
) -> list[dict[str, Any]]:
    goal_text = _snippet(goal, 200)
    if not goal_text:
        return []
    passed = sum(1 for v in validations if v["passed"])
    failed = len(validations) - passed
    evidence = _snippet(
        f"outcome={outcome or ('completed' if ok else 'failed')}; {reason}; "
        f"engine checks: {passed} passed, {failed} failed",
        _SNIPPET_CHARS,
    )
    mapping = [
        {
            "criterion": f"complete the requested goal: {goal_text}",
            "status": "met" if ok else "not_met",
            "evidence": evidence,
        }
    ]
    for criterion in _extract_criteria(goal, definition):
        # Sub-criteria are never individually re-verified by the engine, so they
        # are honestly reported as unverified rather than inferred as met.
        mapping.append(
            {
                "criterion": criterion,
                "status": "unverified",
                "evidence": "not individually verified by an engine check; see overall outcome",
            }
        )
    return mapping


def build_run_report(
    *,
    goal: str = "",
    definition: str = "",
    transcript: str = "",
    events: list[dict[str, Any]] | None = None,
    changed_files: list[str] | None = None,
    returncode: int | None = None,
    ok: bool = False,
    outcome: str = "",
    reason: str = "",
    foreign_writes: list[str] | None = None,
) -> dict[str, Any]:
    """Build the structured post-run report from a run's recorded data.

    ``events`` (already-parsed forge events) wins over ``transcript`` (raw stored
    text). Every section is derived from what the run data actually shows.
    """
    parsed = list(events) if events is not None else parse_forge_events(transcript)
    changed = [str(f) for f in (changed_files or [])]
    validations = _build_validations(parsed)
    return {
        "attempts": _build_attempts(parsed, goal=goal, outcome=outcome, returncode=returncode, reason=reason),
        "validations": validations,
        "open_risks": _build_open_risks(
            parsed,
            validations,
            changed_files=changed,
            returncode=returncode,
            ok=ok,
            outcome=outcome,
            reason=reason,
            foreign_writes=list(foreign_writes or []),
        ),
        "attention_pointers": _build_attention_pointers(parsed, validations, changed),
        "rubric_mapping": _build_rubric_mapping(goal, definition, validations, ok=ok, outcome=outcome, reason=reason),
    }


def report_from_dispatch_result(
    result: Any, *, goal: str = "", definition: str = "", transcript: str = ""
) -> dict[str, Any]:
    """Build a report from a ``CliDispatchResult``-shaped dispatch outcome.

    Duck-typed (``ok``/``reason``/``returncode``/``changed_files``/``stdout_tail``)
    so it works for BOTH the claude-CLI and agent-loop dispatch results without
    importing either dispatcher.
    """
    return build_run_report(
        goal=goal,
        definition=definition,
        transcript=transcript or str(getattr(result, "stdout_tail", "") or ""),
        changed_files=list(getattr(result, "changed_files", None) or []),
        returncode=getattr(result, "returncode", None),
        ok=bool(getattr(result, "ok", False)),
        reason=str(getattr(result, "reason", "") or ""),
    )
