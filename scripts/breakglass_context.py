"""Build human-readable breakglass decision context from gate failures."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Any

BREAKGLASS_CONTEXT_ENV = "THOMAS_BREAKGLASS_CONTEXT_JSON"
MAX_CONTEXT_CHARS = 8000
MAX_GATE_BLOCK_CHARS = 3000
MAX_ISSUES = 5
MAX_EVIDENCE_LINES = 4

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_GATE_HEADER_RE = re.compile(r"^(?P<name>.+?)\.{3,}(?P<status>Failed|Passed|Skipped)\b", re.I)
_NOISE_PREFIXES = (
    "- hook id:",
    "- exit code:",
    "====",
    "warning: the following rules have been removed",
    "what happened:",
    "how to fix it:",
    "if this is legitimate:",
    "if this is suspicious:",
)
_EVIDENCE_RE = re.compile(
    r"("
    r"\b\d+\b.*\b(?:limit|exceed|exceeds|max|file|files|lines)\b|"
    r"\b(?:failed|fail|missing|required|protected|unclaimed|stacked|conflict|warning|error)\b|"
    r"\b(?:must|cannot|should|blocked|rejected)\b"
    r")",
    re.I,
)


@dataclass(frozen=True)
class BreakglassIssue:
    gate: str
    why: str
    evidence: tuple[str, ...] = ()
    recommendation: str = ""
    plain_reason: str = ""
    impact: str = ""
    next_step: str = ""


@dataclass(frozen=True)
class BreakglassContext:
    title: str
    summary: str
    recommendation: str
    issues: tuple[BreakglassIssue, ...]
    action_label: str = "Authorize recommended commit"
    cancel_label: str = "Back out and talk to Thomas"
    resolution_label: str = ""
    resolution_prompt: str = ""


def _clean_line(value: str) -> str:
    line = _ANSI_RE.sub("", str(value or "")).strip()
    line = re.sub(r"\s+", " ", line)
    return line


def _clean_output(output: str) -> str:
    text = _ANSI_RE.sub("", str(output or ""))
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _is_noise(line: str) -> bool:
    lowered = line.strip().lower()
    if not lowered or any(lowered.startswith(prefix) for prefix in _NOISE_PREFIXES):
        return True
    if re.fullmatch(r"-?\s*[a-z]{2,4}\d{3,4}", lowered):
        return True
    return bool(re.fullmatch(r".+:\s*fail(?:ed)?", lowered))


def _dedupe_lines(lines: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        key = line.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(line)
    return out


def _failed_gate_blocks(output: str) -> list[tuple[str, list[str]]]:
    current_gate = ""
    current_lines: list[str] = []
    current_failed = False
    blocks: list[tuple[str, list[str]]] = []

    for raw_line in _clean_output(output).splitlines():
        line = raw_line.rstrip()
        match = _GATE_HEADER_RE.match(line)
        if match:
            if current_failed and current_gate:
                blocks.append((current_gate, current_lines))
            current_gate = _clean_line(match.group("name"))
            current_failed = match.group("status").lower() == "failed"
            current_lines = []
            continue
        if current_failed:
            current_lines.append(line)

    if current_failed and current_gate:
        blocks.append((current_gate, current_lines))
    return blocks


def _first_meaningful_line(lines: list[str]) -> str:
    cleaned = [_clean_line(raw) for raw in lines]
    for raw in cleaned:
        line = raw
        if line.lower().startswith("safety gate failed:"):
            continue
        if line and not _is_noise(line):
            return line
    for raw in cleaned:
        line = _clean_line(raw)
        if line and not _is_noise(line):
            return line
    return "This gate reported a blocker."


def _evidence_lines(lines: list[str]) -> tuple[str, ...]:
    selected: list[str] = []
    for raw in lines:
        line = _clean_line(raw)
        if not line or _is_noise(line):
            continue
        if _EVIDENCE_RE.search(line):
            selected.append(line)
        if len(selected) >= MAX_EVIDENCE_LINES:
            break

    if not selected:
        for raw in lines:
            line = _clean_line(raw)
            if line and not _is_noise(line):
                selected.append(line)
                if len(selected) >= MAX_EVIDENCE_LINES:
                    break
    return tuple(_dedupe_lines(selected))


def _fallback_recommendation_for_gate(gate: str, evidence: tuple[str, ...]) -> str:
    joined = " ".join([gate, *evidence]).lower()
    if "ruff format" in joined:
        return "I would format the files first, then retry the commit."
    if "protected" in joined or "enforcement" in joined:
        return "I would review exactly which protected Thomas files changed before authorizing."
    if "changed lines exceeds" in joined or "change budget" in joined or "large" in joined:
        return "I would split this into smaller commits unless these changes are one clear checkpoint."
    if "worktree branch" in joined or "stacked" in joined:
        return "I would reconcile the branch path before committing so the work lands in the right place."
    if "claim" in joined or "unclaimed" in joined or "ownership" in joined:
        return "I would create or update the workboard ownership before committing."
    if "visual proof" in joined or "screenshots" in joined:
        return "I would refresh the visual proof before treating this as release-ready."
    if "architecture" in joined or "soft limit" in joined:
        return "I would split or document this larger file before release."
    return "I would stop and inspect this blocker before authorizing."


def _normalize_ai_recommendation(value: str) -> str:
    text = " ".join(str(value or "").split()).strip()
    return re.sub(r"^recommendation:\s*", "", text, flags=re.I)


def _normalize_gate_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _coerce_guidance(raw: str) -> dict[str, Any]:
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {"recommendation": _normalize_ai_recommendation(text)}
    return payload if isinstance(payload, dict) else {}


def _guidance_for_issue(guidance: dict[str, Any], gate: str, index: int) -> dict[str, Any]:
    issues = guidance.get("issues")
    if not isinstance(issues, list):
        return {}
    gate_key = _normalize_gate_key(gate)
    for row in issues:
        if not isinstance(row, dict):
            continue
        raw_gate = str(row.get("gate") or "")
        if raw_gate and _normalize_gate_key(raw_gate) == gate_key:
            return row
    if index < len(issues) and isinstance(issues[index], dict):
        return issues[index]
    return {}


def _guided_text(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = str(row.get(key) or "").strip()
        if value:
            return _normalize_ai_recommendation(value)
    return ""


def build_commit_blocker_context(
    output: str,
    *,
    ai_recommendation: str = "",
    ai_guidance_json: str = "",
    action_label: str = "Authorize recommended commit",
    cancel_label: str = "Back out and talk to Thomas",
) -> BreakglassContext:
    guidance = _coerce_guidance(ai_guidance_json)
    issues: list[BreakglassIssue] = []
    for index, (gate, lines) in enumerate(_failed_gate_blocks(output)[:MAX_ISSUES]):
        trimmed = "\n".join(lines)[:MAX_GATE_BLOCK_CHARS].splitlines()
        evidence = _evidence_lines(trimmed)
        issue_guidance = _guidance_for_issue(guidance, gate, index)
        fallback_reason = _first_meaningful_line(trimmed)
        fallback_recommendation = _fallback_recommendation_for_gate(gate, evidence)
        guided_recommendation = _guided_text(issue_guidance, "recommendation", "suggestion", "advice")
        issues.append(
            BreakglassIssue(
                gate=gate,
                why=fallback_reason,
                evidence=evidence,
                recommendation=guided_recommendation or fallback_recommendation,
                plain_reason=_guided_text(issue_guidance, "plain_reason", "reason", "what_happened"),
                impact=_guided_text(issue_guidance, "impact", "why_it_matters", "risk"),
                next_step=_guided_text(issue_guidance, "next_step", "next", "action"),
            )
        )

    if issues:
        summary = (
            f"Thomas found {len(issues)} issue(s) that stopped the commit. Read the recommendation before authorizing."
        )
    else:
        summary = "Thomas could not commit normally, but the gate output did not include structured failure headers."
        fallback = tuple(_clean_line(line) for line in _clean_output(output).splitlines() if _clean_line(line))[:3]
        issues.append(
            BreakglassIssue(
                gate="Commit blocker",
                why=fallback[0] if fallback else "The normal commit command failed.",
                evidence=fallback,
                recommendation="I would stop and inspect the full commit output before authorizing.",
            )
        )

    recommendation = _normalize_ai_recommendation(
        str(guidance.get("recommendation") or guidance.get("overall_recommendation") or ai_recommendation or "")
    )
    if not recommendation:
        recommendation = (
            "No model-written recommendation was provided for this blocker. "
            "I would back out and ask Thomas to explain the risk in plain English before authorizing."
        )

    return BreakglassContext(
        title="Thomas commit blocker",
        summary=summary,
        recommendation=recommendation,
        issues=tuple(issues),
        action_label=str(guidance.get("action_label") or action_label),
        cancel_label=str(guidance.get("cancel_label") or cancel_label),
        resolution_label=str(guidance.get("resolution_label") or guidance.get("fix_label") or ""),
        resolution_prompt=str(guidance.get("resolution_prompt") or guidance.get("fix_prompt") or ""),
    )


def breakglass_context_to_json(context: BreakglassContext) -> str:
    return json.dumps(asdict(context), ensure_ascii=True, sort_keys=True)[:MAX_CONTEXT_CHARS]


def breakglass_context_from_json(raw: str) -> BreakglassContext | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    issues_raw = payload.get("issues")
    issues: list[BreakglassIssue] = []
    if isinstance(issues_raw, list):
        for row in issues_raw[:MAX_ISSUES]:
            if not isinstance(row, dict):
                continue
            evidence_raw = row.get("evidence")
            evidence = (
                tuple(str(item) for item in evidence_raw if str(item).strip()) if isinstance(evidence_raw, list) else ()
            )
            issues.append(
                BreakglassIssue(
                    gate=str(row.get("gate") or "Commit blocker"),
                    why=str(row.get("why") or "This gate reported a blocker."),
                    evidence=evidence[:MAX_EVIDENCE_LINES],
                    recommendation=str(row.get("recommendation") or ""),
                    plain_reason=str(row.get("plain_reason") or ""),
                    impact=str(row.get("impact") or ""),
                    next_step=str(row.get("next_step") or ""),
                )
            )
    if not issues:
        return None
    return BreakglassContext(
        title=str(payload.get("title") or "Thomas commit blocker"),
        summary=str(payload.get("summary") or "Thomas found a commit blocker."),
        recommendation=str(payload.get("recommendation") or ""),
        issues=tuple(issues),
        action_label=str(payload.get("action_label") or "Authorize recommended commit"),
        cancel_label=str(payload.get("cancel_label") or "Back out and talk to Thomas"),
        resolution_label=str(payload.get("resolution_label") or ""),
        resolution_prompt=str(payload.get("resolution_prompt") or ""),
    )


def breakglass_context_from_env(env: dict[str, str] | None = None) -> BreakglassContext | None:
    source = env if env is not None else {}
    return breakglass_context_from_json(str(source.get(BREAKGLASS_CONTEXT_ENV) or ""))


def breakglass_context_payload(context: BreakglassContext | dict[str, Any] | None) -> BreakglassContext | None:
    if context is None:
        return None
    if isinstance(context, BreakglassContext):
        return context
    try:
        return breakglass_context_from_json(json.dumps(context, ensure_ascii=True))
    except (TypeError, ValueError):
        return None
