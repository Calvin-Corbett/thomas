"""Base utilities and shared constants for task manager.

Shared helper functions, constants, and parsing utilities used across all modules.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts.forge.gates import workboard_claim_freshness as freshness_gate
    from scripts.forge.gates import workboard_claims as claims_gate
except Exception:  # pragma: no cover
    from forge.gates import workboard_claim_freshness as freshness_gate  # type: ignore
    from forge.gates import workboard_claims as claims_gate  # type: ignore


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WORKBOARD = ROOT / "plans" / "thomas" / "WORKBOARD.md"
DEFAULT_PLAN_ROOT = "plans/thomas/tasks"
DEFAULT_PROBLEM_ROOT = "plans/thomas/problems"
DEFAULT_TASK_MANAGER_AGENT = "thomas"
DEFAULT_ORCHESTRATOR_AGENTS = ("thomas", "task-manager-agent", "task-manager")
DEFAULT_ORCHESTRATOR_ERROR = "auto-start is disabled for orchestrator agents"
MODEL_ALIAS_OWNER_SUFFIX_RE = re.compile(r"^[\s_-]+\d+$")
DEFAULT_MAX_IDLE_MINUTES = 1.0
DEFAULT_MONITOR_INTERVAL_SECONDS = 30.0
DEFAULT_MONITOR_CYCLES = 1
DEFAULT_MAX_AGENT_SILENCE_MINUTES = 5.0
DEFAULT_MAX_DISPATCH_PER_CYCLE = 2
DEFAULT_SESSION_LEASE_MINUTES = 5.0
DEFAULT_INFERRED_EXPIRY_MINUTES = 10.0
TASK_PLANS_HEADING = "Task Plans"
TASK_PROBLEMS_HEADING = "Task Problems"
INACTIVE_AGENTS_HEADING = "Inactive Agents"
AGENT_SESSIONS_HEADING = "Agent Sessions"
TASK_SPECIALIST_HEADING = "Task Specialist Routing"
TASK_ECOSYSTEM_WEIGHTS = {"summary": 0.8, "verbatim": 0.2}
BACKGROUND_TASK_TYPES = {"task_ecosystem_ops"}
BRAINSTORM_TASK_TYPES = {"brainstorm_orchestration"}


def _norm(value: str) -> str:
    return str(value or "").strip().lower()


def _canonical_model_alias_owner(owner_agent: str) -> str:
    return re.sub(r"[\s_-]*\d+$", "", _norm(owner_agent))


def _model_alias_owner_suffix(owner_norm: str) -> str:
    normalized = _norm(owner_norm)
    owner_base = _canonical_model_alias_owner(normalized)
    if not owner_base:
        return ""
    suffix = normalized[len(owner_base) :]
    if MODEL_ALIAS_OWNER_SUFFIX_RE.fullmatch(suffix):
        return suffix
    return ""


def _is_orchestrator_agent(agent: str | None) -> bool:
    return _norm(agent) in {_norm(name) for name in DEFAULT_ORCHESTRATOR_AGENTS}


def _is_authorized_model_alias(preferred_alias: str, owner_agent: str) -> bool:
    alias_norm = _norm(preferred_alias)
    owner_norm = _norm(owner_agent)
    if not alias_norm or not owner_norm:
        return False
    if alias_norm == owner_norm:
        return True
    owner_base = _canonical_model_alias_owner(owner_norm)
    if not owner_base:
        return False
    if alias_norm == owner_base:
        return True
    if not alias_norm.startswith(owner_base):
        return False
    suffix = alias_norm[len(owner_base) :]
    if not suffix:
        return False
    owner_suffix = _model_alias_owner_suffix(owner_norm)
    if not MODEL_ALIAS_OWNER_SUFFIX_RE.fullmatch(suffix):
        return False
    return suffix == owner_suffix


def _strip_blocked_task_violations(
    violations: list[str] | tuple[str, ...],
    *,
    allow_blocked_without_issue: bool,
) -> list[str]:
    if not allow_blocked_without_issue:
        return list(violations)
    normalized_suffix = "must have an open/triaged entry in `## Issues / Blockers`"
    return [
        item
        for item in violations
        if not (item.startswith("blocked task `") and normalized_suffix in str(item).strip())
    ]


def _sanitize(label: str, value: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise ValueError(f"{label} is required")
    if ";" in cleaned or "\n" in cleaned or "\r" in cleaned:
        raise ValueError(f"{label} cannot include ';' or newline characters")
    return cleaned


def _parse_now(raw: str | None) -> datetime:
    return freshness_gate._parse_now(raw)  # type: ignore[attr-defined]


def _line_commit_unix(workboard_path: Path, line_no: int) -> int | None:
    return freshness_gate._line_commit_unix(workboard_path, line_no)  # type: ignore[attr-defined]


def _parse_iso_utc(raw: str) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _to_iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _task_priority_rank(summary: str) -> tuple[int, int, str]:
    text = _norm(summary)
    priority = 1
    if "[p0]" in text:
        priority = 0
    elif "[p2]" in text:
        priority = 2

    urgency = 1
    if "[now]" in text:
        urgency = 0
    elif "[later]" in text:
        urgency = 2
    return priority, urgency, text


TASK_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "queued": {"claimed"},
    "claimed": {"in_progress", "blocked"},
    "in_progress": {"blocked", "review"},
    "blocked": {"in_progress", "review", "done"},
    "review": {"done", "blocked", "in_progress"},
    "done": {"queued", "claimed"},
}


def _normalize_task_status(status: str) -> str:
    normalized, err = claims_gate.normalize_active_task_status(status)
    if err or normalized is None:
        raise ValueError(err or f"invalid status `{status}`")
    return normalized


def _replace_status_field(line: str, *, status: str) -> str:
    stripped = str(line).strip()
    if not stripped.startswith("- "):
        raise ValueError("expected bullet line")
    token = stripped[2:].strip()
    if not token:
        raise ValueError("empty bullet payload")
    parts = [part.strip() for part in token.split(";") if part.strip()]
    updated: list[str] = []
    seen = False
    for part in parts:
        if "=" not in part:
            updated.append(part)
            continue
        key, value = part.split("=", 1)
        key_clean = key.strip().lower()
        if key_clean == "status":
            updated.append(f"status={status}")
            seen = True
            continue
        updated.append(f"{key.strip()}={value.strip()}")
    if not seen:
        updated.append(f"status={status}")
    return "- " + "; ".join(updated)


def _task_priority_source(*, summary: str, task_type: str) -> str:
    text = _norm(summary)
    if "[user]" in text or "user requested" in text or "from user" in text:
        return "user"
    if task_type in BACKGROUND_TASK_TYPES:
        return "background"
    return "user"


def _priority_from_summary(summary: str) -> str:
    text = _norm(summary)
    if "[p0]" in text:
        return "p0"
    if "[p2]" in text:
        return "p2"
    return "p1"


def _task_type_by_task_id(workboard_path: Path) -> dict[str, str]:
    """Best-effort task type lookup keyed by normalized task id."""

    try:
        text = workboard_path.read_text(encoding="utf-8")
    except OSError:
        return {}

    mapping: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("- ") or "task_id=" not in line:
            continue
        fields: dict[str, str] = {}
        for part in line[2:].split(";"):
            token = str(part or "").strip()
            if "=" not in token:
                continue
            key, value = token.split("=", 1)
            fields[_norm(key)] = str(value or "").strip()
        task_id = _norm(fields.get("task_id", ""))
        task_type = _norm(fields.get("task_type", ""))
        if task_id and task_type and task_id not in mapping:
            mapping[task_id] = task_type
    return mapping


def _latest_message_timestamp_by_sender(
    *,
    messages: Sequence[dict[str, str]],
    kinds: Sequence[str] = (),
) -> dict[str, datetime]:
    allowed = {_norm(kind) for kind in kinds if str(kind or "").strip()}
    latest: dict[str, datetime] = {}
    for row in messages:
        sender = _norm(row.get("from", ""))
        if not sender:
            continue
        kind = _norm(row.get("kind", ""))
        if allowed and kind not in allowed:
            continue
        stamp = _parse_iso_utc(row.get("updated_at", "") or row.get("created_at", ""))
        if stamp is None:
            continue
        current = latest.get(sender)
        if current is None or stamp > current:
            latest[sender] = stamp
    return latest


def _find_section(lines: Sequence[str], *, heading_prefix: str) -> tuple[int, int] | None:
    """Find section heading and boundaries."""
    for i, line in enumerate(lines):
        if line.strip().startswith(f"## {heading_prefix}"):
            start = i + 1
            for j in range(i + 1, len(lines)):
                if lines[j].startswith("## "):
                    return start, j
            return start, len(lines)
    return None


def _ensure_section(lines: list[str], *, heading: str) -> tuple[int, int]:
    """Ensure section exists, creating if needed."""
    section = _find_section(lines, heading_prefix=heading)
    if section is not None:
        return section
    lines.append(f"\n## {heading}\n")
    lines.append("- none\n")
    return len(lines) - 1, len(lines)


def _bullet_indices(lines: Sequence[str], start: int, end: int) -> list[int]:
    """Get indices of bullet points in a section."""
    return [i for i in range(start, end) if i < len(lines) and lines[i].startswith("- ")]


def _parse_kv_entry(line_no: int, line: str) -> tuple[str | None, dict[str, str] | None, str | None]:
    """Parse a key-value entry line."""
    stripped = str(line).strip()
    if not stripped.startswith("- "):
        return None, None, f"line {line_no}: expected bullet"
    token = stripped[2:].strip()
    if not token:
        return None, None, None
    if token.lower() in claims_gate.NONE_TOKENS:
        return token, None, None
    fields: dict[str, str] = {}
    for part in token.split(";"):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            return token, None, f"line {line_no}: expected key=value, got {part}"
        key, value = part.split("=", 1)
        fields[key.strip().lower()] = value.strip()
    return token, fields, None


def _write_section_entries(lines: list[str], *, section_start: int, section_end: int, entries: list[str]) -> None:
    """Replace entries in a section."""
    del lines[section_start:section_end]
    for i, entry in enumerate(entries):
        lines.insert(section_start + i, entry)


def _repo_root_from_workboard(workboard_path: Path) -> Path:
    """Get repo root from workboard path."""
    return workboard_path.resolve().parent.parent.parent


def _read_inferred_sync_state(repo_root: Path) -> dict[str, object]:
    """Read inferred sync state from disk."""
    state_path = repo_root / ".workboard_inferred_state.py"
    if not state_path.exists():
        return {}
    try:
        content = state_path.read_text(encoding="utf-8")
        local_dict: dict[str, object] = {}
        exec(content, {"__builtins__": {}}, local_dict)  # noqa: S102
        return local_dict
    except Exception:
        return {}


def _write_inferred_sync_state(repo_root: Path, payload: dict[str, object]) -> None:
    """Write inferred sync state to disk."""
    state_path = repo_root / ".workboard_inferred_state.py"
    lines = ["state = {"]
    for key, value in payload.items():
        repr_val = repr(value)
        lines.append(f"    {repr(key)}: {repr_val},")
    lines.append("}")
    state_path.write_text("\n".join(lines), encoding="utf-8")


def _scope_tokens_from_csv(raw: str | None) -> list[str]:
    """Parse scope tokens from CSV string."""
    return [s.strip() for s in str(raw or "").split(",") if s.strip()]


def _row_is_inferred(fields: dict[str, str]) -> bool:
    """Check if row is inferred."""
    return _norm(fields.get("inferred", "")) == "yes"


def _scope_matches(scope: str, row_scope: str) -> bool:
    """Check if scope matches."""
    return _norm(scope) == _norm(row_scope)


def _row_scope_overlap(scope: str, row_scopes: Sequence[str]) -> bool:
    """Check if scope overlaps with row scopes."""
    scope_key = _norm(scope)
    for row_scope in row_scopes:
        if _norm(row_scope) == scope_key:
            return True
    return False


def _inferred_claim_key(agent: str, scope: str) -> str:
    """Generate inferred claim key."""
    return f"{_norm(agent)}::{_norm(scope)}"


def _inferred_task_id(agent: str, scope: str) -> str:
    """Generate inferred task ID."""
    safe_scope = re.sub(r"[^A-Za-z0-9._-]+", "-", str(scope or "").strip()).strip("-")
    safe_agent = re.sub(r"[^A-Za-z0-9._-]+", "-", str(agent or "").strip()).strip("-")
    return f"{safe_scope}-inferred-{safe_agent}"


def _sanitize_metadata(value: str, *, fallback: str = "none") -> str:
    """Sanitize metadata value."""
    cleaned = str(value or "").strip()
    return cleaned if cleaned else fallback


def _compact_paths(paths: Sequence[str], *, limit: int = 4) -> str:
    """Compact path list for display."""
    listed = list(paths)[:limit]
    result = ", ".join(listed)
    if len(paths) > limit:
        result += f", ... +{len(paths) - limit} more"
    return result


def _format_inferred_claim_entry(*, candidate: dict[str, object], timestamp: str) -> str:
    """Format inferred claim entry."""
    agent = str(candidate.get("agent", "")).strip()
    scope = str(candidate.get("scope", "")).strip()
    task_id = str(candidate.get("task_id", "")).strip()
    reason = str(candidate.get("reason", "")).strip()
    return (
        f"- agent={_sanitize('agent', agent)}; scope={_sanitize('scope', scope)}; "
        f"task_id={_sanitize('task_id', task_id)}; inferred=yes; "
        f"detected_at={_sanitize('detected_at', timestamp)}; reason={_sanitize('reason', reason)}"
    )


def _format_inferred_task_entry(*, candidate: dict[str, object], timestamp: str) -> str:
    """Format inferred task entry."""
    task_id = str(candidate.get("task_id", "")).strip()
    scope = str(candidate.get("scope", "")).strip()
    summary = str(candidate.get("summary", "")).strip()
    reason = str(candidate.get("reason", "")).strip()
    return (
        f"- task_id={_sanitize('task_id', task_id)}; scope={_sanitize('scope', scope)}; "
        f"summary={_sanitize('summary', summary)}; inferred=yes; "
        f"detected_at={_sanitize('detected_at', timestamp)}; reason={_sanitize('reason', reason)}"
    )


def _entry_state_payload(
    *,
    state_key: str,
    candidate: dict[str, object],
    prior: dict[str, object] | None,
) -> dict[str, object]:
    """Generate payload for state entry."""
    payload: dict[str, object] = {}
    for key in candidate:
        new_val = candidate.get(key)
        prior_val = prior.get(key) if prior else None
        if new_val != prior_val:
            payload[f"{key}_changed"] = True
    return payload
