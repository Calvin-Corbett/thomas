#!/usr/bin/env python3
"""Evidence grammar and workboard-line storage (split out of claim_evidence.py).

Split out of ``scripts/crew/workboard/claim_evidence.py`` (which had grown
past the monolith guard's unbaselined 800-line soft limit) so the split has
a real seam: everything here is the evidence VALUE TYPE (parsing/formatting
the ``kind:payload`` grammar, see ``claim_evidence.py``'s module docstring
for the full grammar spec) plus its storage as an ``evidence=``/
``evidence_recorded_at=`` field on a WORKBOARD.md Active Task line, with
zero dependency back on ``claim_evidence.py``'s verification logic
(``Verdict``/``verify_evidence``/git-binding helpers). ``claim_evidence.py``
imports and re-exports every name defined here under its original spot, so
no external caller needed to change. Precedent: ``worker_pipeline.py`` split
out of ``worker.py`` the same way.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

DEFAULT_WORKBOARD = _REPO_ROOT / "plans" / "thomas" / "WORKBOARD.md"

_VALID_KINDS: tuple[str, ...] = ("commit", "run", "gate")
_COMMIT_SHA_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")
_ACTIVE_TASKS_HEADING = "## active tasks"


# ---------------------------------------------------------------------------
# Grammar
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Evidence:
    """A parsed `kind:payload` evidence string. Construct via `parse_evidence`."""

    kind: str
    payload: str

    @property
    def sha(self) -> str:
        if self.kind != "commit":
            raise ValueError(f"evidence kind `{self.kind}` has no commit sha")
        return self.payload

    @property
    def run_id(self) -> str:
        if self.kind != "run":
            raise ValueError(f"evidence kind `{self.kind}` has no run_id")
        return self.payload.split(":", 1)[0]

    @property
    def seq_range(self) -> tuple[int, int]:
        if self.kind != "run":
            raise ValueError(f"evidence kind `{self.kind}` has no seq range")
        _, range_part = self.payload.split(":", 1)
        from_str, to_str = range_part.split("-", 1)
        return int(from_str), int(to_str)

    @property
    def gate_name(self) -> str:
        if self.kind != "gate":
            raise ValueError(f"evidence kind `{self.kind}` has no gate_name")
        return self.payload.split(":", 1)[0]

    @property
    def exit_code(self) -> int:
        if self.kind != "gate":
            raise ValueError(f"evidence kind `{self.kind}` has no exit_code")
        _, exit_code_str = self.payload.split(":", 1)
        return int(exit_code_str)


def parse_evidence(raw: str) -> Evidence:
    """Parse `kind:payload` into an `Evidence`. Raises ValueError naming the defect."""
    text = str(raw or "").strip()
    if not text:
        raise ValueError("evidence is empty")
    if ":" not in text:
        raise ValueError(f"evidence `{text}` is missing a `:` separator between kind and payload")
    kind, payload = text.split(":", 1)
    kind = kind.strip().lower()
    payload = payload.strip()
    if kind not in _VALID_KINDS:
        raise ValueError(f"evidence `{text}` has kind `{kind}` which is not one of {_VALID_KINDS}")
    if not payload:
        raise ValueError(f"evidence `{text}` has an empty payload after `{kind}:`")
    if kind == "commit":
        _validate_commit_payload(text, payload)
    elif kind == "run":
        _validate_run_payload(text, payload)
    else:
        _validate_gate_payload(text, payload)
    return Evidence(kind=kind, payload=payload)


def format_evidence_field(ev: Evidence) -> str:
    """Render `Evidence` back into its `kind:payload` string. Inverse of `parse_evidence`."""
    return f"{ev.kind}:{ev.payload}"


def _validate_commit_payload(raw: str, payload: str) -> None:
    if not _COMMIT_SHA_RE.match(payload):
        raise ValueError(f"evidence `{raw}` has commit payload `{payload}` which is not 7-40 hex characters")


def _validate_run_payload(raw: str, payload: str) -> None:
    if ":" not in payload:
        raise ValueError(f"evidence `{raw}` run payload `{payload}` is missing `:` between run_id and seq range")
    run_id, range_part = payload.split(":", 1)
    if not run_id.strip():
        raise ValueError(f"evidence `{raw}` run payload has an empty run_id")
    if "-" not in range_part:
        raise ValueError(f"evidence `{raw}` run payload `{range_part}` is missing `-` between from and to seq")
    from_str, to_str = range_part.split("-", 1)
    if not _is_int(from_str) or not _is_int(to_str):
        raise ValueError(f"evidence `{raw}` run payload seq range `{range_part}` is not two integers")
    from_seq, to_seq = int(from_str), int(to_str)
    if from_seq < 0 or to_seq < 0:
        raise ValueError(f"evidence `{raw}` run payload seq range `{range_part}` cannot be negative")
    if from_seq > to_seq:
        raise ValueError(f"evidence `{raw}` run payload seq range `{range_part}` has from greater than to")


def _validate_gate_payload(raw: str, payload: str) -> None:
    if ":" not in payload:
        raise ValueError(f"evidence `{raw}` gate payload `{payload}` is missing `:` between gate_name and exit_code")
    gate_name, exit_code_str = payload.split(":", 1)
    if not gate_name.strip():
        raise ValueError(f"evidence `{raw}` gate payload has an empty gate_name")
    if not _is_int(exit_code_str):
        raise ValueError(f"evidence `{raw}` gate payload exit_code `{exit_code_str}` is not an integer")


def _is_int(text: str) -> bool:
    token = str(text or "").strip()
    if token.startswith("-"):
        token = token[1:]
    return bool(token) and token.isdigit()


# ---------------------------------------------------------------------------
# Storage: evidence rides the Active Task line (see module docstring)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvidenceRecord:
    """What `record_evidence` stored for a task: the evidence and when it was recorded."""

    evidence: Evidence | None
    recorded_at: str | None


def record_evidence(
    task_id: str,
    ev: Evidence,
    *,
    workboard_path: Path = DEFAULT_WORKBOARD,
    recorded_at: str | None = None,
) -> None:
    """Write `evidence=` and `evidence_recorded_at=` onto the task's Active Task line."""
    lines = workboard_path.read_text(encoding="utf-8").splitlines(keepends=True)
    idx = _find_task_line(lines, task_id)
    fields = _parse_task_line_fields(lines[idx])
    fields["evidence"] = format_evidence_field(ev)
    fields["evidence_recorded_at"] = str(recorded_at or _utcnow_iso())
    newline = "\n" if lines[idx].endswith("\n") else ""
    lines[idx] = _format_task_line_fields(fields) + newline
    workboard_path.write_text("".join(lines), encoding="utf-8")


def read_evidence(task_id: str, *, workboard_path: Path = DEFAULT_WORKBOARD) -> EvidenceRecord:
    """Read back what `record_evidence` stored. Raises ValueError if the stored string is malformed."""
    lines = workboard_path.read_text(encoding="utf-8").splitlines(keepends=True)
    idx = _find_task_line(lines, task_id)
    fields = _parse_task_line_fields(lines[idx])
    raw = fields.get("evidence")
    recorded_at = fields.get("evidence_recorded_at")
    if not raw:
        return EvidenceRecord(evidence=None, recorded_at=recorded_at)
    return EvidenceRecord(evidence=parse_evidence(raw), recorded_at=recorded_at)


def strip_evidence(task_id: str, *, workboard_path: Path = DEFAULT_WORKBOARD) -> bool:
    """Remove `evidence=`/`evidence_recorded_at=` from the task's Active Task
    line, if either is present. Returns whether anything was actually
    removed (a no-op returns False without writing).

    EVIDENCE IS PER-CYCLE (fix round, post-review): a reviewer reproduced
    that a `done -> queued -> claimed -> in_progress -> review` round trip
    left the ORIGINAL `evidence=` field on the line untouched -- only
    `status=` ever changed on that path, because leaving `done` never used
    to write to the line at all. That meant a task could be hand-flipped
    back to `done` (bypassing `reactivate.set_task_status` entirely, the
    same issue.py-class shape `workboard_evidence_gate.py` exists to catch)
    and the gate would still see the PRIOR cycle's -- possibly genuinely
    verified -- evidence and pass it, even though that evidence proves
    nothing about the work done in THIS cycle. `reactivate.set_task_status`
    calls this function on every transition whose FROM-status is `done`
    (`done -> queued`, `done -> claimed`), so a reopened task starts every
    subsequent cycle with no evidence on its line at all -- a later
    hand-flip straight to `done` is caught the ordinary way, as missing
    evidence, not as stale-but-present evidence.
    """
    lines = workboard_path.read_text(encoding="utf-8").splitlines(keepends=True)
    idx = _find_task_line(lines, task_id)
    fields = _parse_task_line_fields(lines[idx])
    if "evidence" not in fields and "evidence_recorded_at" not in fields:
        return False
    fields.pop("evidence", None)
    fields.pop("evidence_recorded_at", None)
    newline = "\n" if lines[idx].endswith("\n") else ""
    lines[idx] = _format_task_line_fields(fields) + newline
    workboard_path.write_text("".join(lines), encoding="utf-8")
    return True


def _utcnow_iso() -> str:
    return _dt.datetime.now(tz=_dt.timezone.utc).isoformat(timespec="seconds")


def _active_tasks_bounds(lines: list[str]) -> tuple[int, int]:
    start: int | None = None
    for idx, line in enumerate(lines):
        if line.strip().lower() == _ACTIVE_TASKS_HEADING:
            start = idx + 1
            break
    if start is None:
        raise ValueError("workboard has no `## Active Tasks` section")
    end = len(lines)
    for idx in range(start, len(lines)):
        if lines[idx].strip().startswith("## "):
            end = idx
            break
    return start, end


def _find_task_line(lines: list[str], task_id: str) -> int:
    start, end = _active_tasks_bounds(lines)
    task_key = str(task_id or "").strip().lower()
    for idx in range(start, end):
        if not lines[idx].strip().startswith("-"):
            continue
        fields = _parse_task_line_fields(lines[idx])
        if str(fields.get("task_id", "")).strip().lower() == task_key:
            return idx
    raise ValueError(f"no Active Task line found for task_id `{task_id}`")


# NOTE (reviewer-requested): `_split_field_segments` and `_parse_field_value`
# below are an intentional duplicate of the same-named helpers in
# scripts/forge/gates/workboard_claims.py (pinned, read-only) and their reuse
# in scripts/crew/workboard/claim_utils.py (unpinned). This module cannot
# import them because workboard_claims.py is pinned for this phase -- forking
# the small line-grammar parser is the only lawful way for an unpinned module
# to write an `evidence=` field without touching a pinned file. SOURCE OF
# TRUTH: scripts/forge/gates/workboard_claims.py's `_split_field_segments` /
# `_parse_field_value`. If that grammar ever changes, these copies must
# change with it -- there is no shared import to keep them in sync
# automatically.
def _split_field_segments(entry: str) -> list[str]:
    segments: list[str] = []
    current: list[str] = []
    quote: str | None = None
    escaped = False
    for char in str(entry or ""):
        if escaped:
            current.append(char)
            escaped = False
            continue
        if char == "\\" and quote == '"':
            current.append(char)
            escaped = True
            continue
        if quote:
            current.append(char)
            if char == quote:
                quote = None
            continue
        if char in {'"', "'", "`"}:
            quote = char
            current.append(char)
            continue
        if char == ";":
            segment = "".join(current).strip()
            if segment:
                segments.append(segment)
            current = []
            continue
        current.append(char)
    segment = "".join(current).strip()
    if segment:
        segments.append(segment)
    return segments


def _parse_field_value(raw: str) -> str:
    value = str(raw or "").strip()
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        try:
            return str(json.loads(value)).strip()
        except json.JSONDecodeError:
            pass
    return value.strip("`").strip("'").strip('"')


def _parse_task_line_fields(line: str) -> dict[str, str]:
    body = line.strip()
    if body.startswith("-"):
        body = body[1:].strip()
    fields: dict[str, str] = {}
    for segment in _split_field_segments(body):
        if "=" not in segment:
            continue
        key, value = segment.split("=", 1)
        fields[key.strip().lower()] = _parse_field_value(value)
    return fields


def _format_task_line_fields(fields: dict[str, str]) -> str:
    parts: list[str] = []
    for key, value in fields.items():
        raw = str(value)
        if any(ch in raw for ch in (";", "`", '"', "'")):
            parts.append(f"{key}={json.dumps(raw)}")
        else:
            parts.append(f"{key}={raw}")
    return "- " + "; ".join(parts)

