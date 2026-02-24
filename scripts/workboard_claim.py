#!/usr/bin/env python3
"""Manage active agent claims in plans/thomas/WORKBOARD.md."""

from __future__ import annotations

import argparse
import getpass
import os
import re
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

try:
    from scripts import agent_identity
    from scripts import check_workboard_claims as claims_gate
except Exception:  # pragma: no cover
    import agent_identity  # type: ignore
    import check_workboard_claims as claims_gate  # type: ignore


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WORKBOARD = ROOT / "plans" / "thomas" / "WORKBOARD.md"
COORDINATION_DIR = ROOT / "runtime" / "coordination"
LOCK_FILE = COORDINATION_DIR / "workboard_claim.lock"
LOCK_TIMEOUT_SECONDS = 10.0
LOCK_STALE_SECONDS = 60.0
NONE_ENTRY = "- none"
ACTIVE_TASK_HEADING_PREFIX = "active tasks"
ACTIVE_TASK_HEADING_LABEL = "Active Tasks"


def _agent_key(agent: str) -> str:
    return str(agent or "").strip().lower()


def _normalize_scope_token(scope: str) -> str:
    token = str(scope or "").strip().replace("\\", "/")
    if token.startswith("./"):
        token = token[2:]
    while "//" in token:
        token = token.replace("//", "/")
    return token.rstrip("/")


def _task_id_from_agent(agent: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(agent or "").strip().lower()).strip("-")
    if not slug:
        slug = "agent"
    return f"{slug}-task"


def _sanitize_field(label: str, value: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise ValueError(f"{label} is required")
    if ";" in cleaned or "\n" in cleaned or "\r" in cleaned:
        raise ValueError(f"{label} cannot include ';' or newline characters")
    return cleaned


def _run_git(args: Sequence[str]) -> str | None:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    out = (proc.stdout or "").strip()
    return out or None


def _detect_agent_default() -> str | None:
    explicit_env = agent_identity.resolve_agent(None, include_name_fallback=True)
    if explicit_env:
        return explicit_env
    git_name = _run_git(["config", "user.name"])
    if git_name:
        return git_name
    user = str(getpass.getuser() or "").strip()
    return user or None


def _detect_branch_name() -> str | None:
    branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"])
    if not branch or branch.upper() == "HEAD":
        return None
    return branch


def _resolve_agent(agent: str | None) -> str:
    if agent:
        return _sanitize_field("agent", agent)
    detected = _detect_agent_default()
    if detected:
        return _sanitize_field("agent", detected)
    raise ValueError(
        "agent is required (pass --agent or set THOMAS_AGENT_ID/AGENT_ID or THOMAS_AGENT_NAME)"
    )


def _resolve_task(task: str | None) -> str:
    if task:
        return _sanitize_field("task", task)
    branch = _detect_branch_name()
    if branch:
        return f"branch {branch}"
    return "active claim"


def _normalize_scope_value(scope_value: str) -> str:
    raw = _sanitize_field("scope", scope_value)
    scopes: List[str] = []
    for token in raw.split(","):
        normalized = _normalize_scope_token(token)
        if normalized:
            scopes.append(normalized)
    if not scopes:
        raise ValueError("scope must contain at least one non-empty path")
    return ",".join(scopes)


def _format_claim(agent: str, scope: str, task: str) -> str:
    agent_clean = _sanitize_field("agent", agent)
    scope_clean = _normalize_scope_value(scope)
    task_clean = _sanitize_field("task", task)
    return f"- agent={agent_clean}; scope={scope_clean}; task={task_clean}"


def _format_active_task(
    *,
    task_id: str,
    agent: str,
    scope: str,
    summary: str,
    status: str,
) -> str:
    task_id_clean = _sanitize_field("task_id", task_id)
    agent_clean = _sanitize_field("agent", agent)
    scope_clean = _normalize_scope_value(scope)
    summary_clean = _sanitize_field("summary", summary)
    status_clean = _sanitize_field("status", status).lower()
    return (
        f"- task_id={task_id_clean}; agent={agent_clean}; scope={scope_clean}; "
        f"summary={summary_clean}; status={status_clean}"
    )


def _find_section(lines: Sequence[str], *, heading_prefix: str, heading_label: str) -> Tuple[int, int]:
    start: Optional[int] = None
    end = len(lines)
    wanted = str(heading_prefix or "").strip().lower()
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("## "):
            heading = stripped[3:].strip().lower()
            if start is None:
                if heading.startswith(wanted):
                    start = idx + 1
            else:
                end = idx
                break
    if start is None:
        raise ValueError(f"missing `## {heading_label}` section in workboard")
    return start, end


def _find_claim_section(lines: Sequence[str]) -> Tuple[int, int]:
    return _find_section(lines, heading_prefix="agent claims", heading_label="Agent Claims")


def _find_active_tasks_section(lines: Sequence[str]) -> Tuple[int, int]:
    return _find_section(
        lines,
        heading_prefix=ACTIVE_TASK_HEADING_PREFIX,
        heading_label=ACTIVE_TASK_HEADING_LABEL,
    )


def _ensure_active_tasks_section(lines: List[str]) -> Tuple[int, int]:
    try:
        return _find_active_tasks_section(lines)
    except ValueError:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(f"## {ACTIVE_TASK_HEADING_LABEL}")
        lines.append("")
        lines.append(NONE_ENTRY)
        return _find_active_tasks_section(lines)


def _bullet_indices(lines: Sequence[str], start: int, end: int) -> List[int]:
    out: List[int] = []
    for idx in range(start, end):
        if lines[idx].strip().startswith("- "):
            out.append(idx)
    return out


def _parse_claim_line(line_no: int, line: str) -> Tuple[Optional[str], Optional[Dict[str, str]], Optional[str]]:
    stripped = line.strip()
    if not stripped.startswith("- "):
        return None, None, f"line {line_no}: expected claim bullet entry"
    entry = stripped[2:].strip()
    if entry.lower() in claims_gate.NONE_TOKENS:
        return entry, None, None
    claim, err = claims_gate._parse_claim_entry(line_no, entry)  # type: ignore[attr-defined]
    if err:
        return entry, None, err
    if claim is None:
        return entry, None, None

    fields: Dict[str, str] = {"agent": claim.agent, "scope": ",".join(claim.scopes), "task": claim.task}
    return entry, fields, None


def _parse_active_task_line(
    line_no: int, line: str
) -> Tuple[Optional[str], Optional[Dict[str, str]], Optional[str]]:
    stripped = line.strip()
    if not stripped.startswith("- "):
        return None, None, f"line {line_no}: expected active task bullet entry"
    entry = stripped[2:].strip()
    if entry.lower() in claims_gate.NONE_TOKENS:
        return entry, None, None
    task, err = claims_gate._parse_active_task_entry(line_no, entry)  # type: ignore[attr-defined]
    if err:
        return entry, None, err
    if task is None:
        return entry, None, None

    fields: Dict[str, str] = {
        "task_id": task.task_id,
        "agent": task.agent,
        "scope": ",".join(task.scopes),
        "summary": task.summary,
        "status": task.status,
    }
    return entry, fields, None


def _upsert_active_task(lines: List[str], *, agent: str, scope: str, task: str) -> Tuple[bool, str]:
    section_start, section_end = _ensure_active_tasks_section(lines)
    bullet_idxs = _bullet_indices(lines, section_start, section_end)

    existing_idx: Optional[int] = None
    duplicate_idx: Optional[int] = None
    none_idxs: List[int] = []
    existing_task_id = _task_id_from_agent(agent)
    existing_status = "active"
    agent_norm = _agent_key(agent)

    for idx in bullet_idxs:
        entry, fields, err = _parse_active_task_line(idx + 1, lines[idx])
        if err:
            return False, err
        if entry is not None and entry.lower() in claims_gate.NONE_TOKENS:
            none_idxs.append(idx)
            continue
        if not fields:
            continue
        current_agent = _agent_key(fields.get("agent", ""))
        if current_agent == agent_norm:
            if existing_idx is None:
                existing_idx = idx
                existing_task_id = fields.get("task_id", existing_task_id) or existing_task_id
                existing_status = fields.get("status", existing_status) or existing_status
            else:
                duplicate_idx = idx

    if duplicate_idx is not None:
        return (
            False,
            f"duplicate existing active-task entries for `{agent}` at lines "
            f"{existing_idx + 1} and {duplicate_idx + 1}",
        )

    formatted = _format_active_task(
        task_id=existing_task_id,
        agent=agent,
        scope=scope,
        summary=task,
        status=existing_status if existing_status in {"active", "blocked"} else "active",
    )
    if existing_idx is not None:
        lines[existing_idx] = formatted
        return True, "updated active task entry"

    for idx in sorted(none_idxs, reverse=True):
        del lines[idx]
        if idx < section_end:
            section_end -= 1
    lines.insert(section_end, formatted)
    return True, "added active task entry"


def _release_active_task(lines: List[str], *, agent: str) -> Tuple[bool, str]:
    section_start, section_end = _ensure_active_tasks_section(lines)
    bullet_idxs = _bullet_indices(lines, section_start, section_end)
    remove_idxs: List[int] = []
    keep_active = 0
    agent_norm = _agent_key(agent)

    for idx in bullet_idxs:
        entry, fields, err = _parse_active_task_line(idx + 1, lines[idx])
        if err:
            return False, err
        if entry is not None and entry.lower() in claims_gate.NONE_TOKENS:
            continue
        if not fields:
            continue
        current_agent = _agent_key(fields.get("agent", ""))
        if current_agent == agent_norm:
            remove_idxs.append(idx)
        else:
            keep_active += 1

    for idx in sorted(remove_idxs, reverse=True):
        del lines[idx]
        if idx < section_end:
            section_end -= 1

    if keep_active == 0:
        lines.insert(section_end, NONE_ENTRY)
    return True, "released active task entry"


@contextmanager
def _file_lock(lock_file: Path, timeout: float = LOCK_TIMEOUT_SECONDS):
    COORDINATION_DIR.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + max(0.1, float(timeout))
    fd: int | None = None

    while True:
        try:
            fd = os.open(str(lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, f"pid={os.getpid()} ts={time.time():.3f}".encode("utf-8", errors="ignore"))
            break
        except FileExistsError:
            try:
                age = time.time() - lock_file.stat().st_mtime
            except FileNotFoundError:
                age = 0.0
            if age > LOCK_STALE_SECONDS:
                try:
                    lock_file.unlink()
                except FileNotFoundError:
                    pass
                continue
            if time.time() >= deadline:
                raise TimeoutError(f"timed out waiting for lock: {lock_file}")
            time.sleep(0.1)

    try:
        yield
    finally:
        if fd is not None:
            os.close(fd)
        try:
            lock_file.unlink()
        except FileNotFoundError:
            pass


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _validate_and_write(workboard_path: Path, original_text: str, new_text: str) -> Tuple[bool, List[str]]:
    _atomic_write(workboard_path, new_text)
    violations = claims_gate.evaluate(workboard_path)
    if violations:
        _atomic_write(workboard_path, original_text)
        return False, violations
    return True, []


def claim(workboard_path: Path, *, agent: str, scope: str, task: str) -> Tuple[bool, str]:
    with _file_lock(LOCK_FILE):
        formatted = _format_claim(agent, scope, task)
        agent_norm = _agent_key(agent)
        original_text = workboard_path.read_text(encoding="utf-8")
        lines = original_text.splitlines()

        section_start, section_end = _find_claim_section(lines)
        bullet_idxs = _bullet_indices(lines, section_start, section_end)

        existing_idx: Optional[int] = None
        duplicate_idx: Optional[int] = None
        none_idxs: List[int] = []

        for idx in bullet_idxs:
            entry, fields, err = _parse_claim_line(idx + 1, lines[idx])
            if err:
                return False, err
            if entry is not None and entry.lower() in claims_gate.NONE_TOKENS:
                none_idxs.append(idx)
                continue
            if not fields:
                continue
            current_agent = _agent_key(fields.get("agent", ""))
            if current_agent == agent_norm:
                if existing_idx is None:
                    existing_idx = idx
                else:
                    duplicate_idx = idx

        if duplicate_idx is not None:
            return (
                False,
                f"duplicate existing claim entries for `{agent}` at lines {existing_idx + 1} and {duplicate_idx + 1}",
            )

        if existing_idx is not None:
            lines[existing_idx] = formatted
            action = f"updated claim for `{agent}`"
        else:
            for idx in sorted(none_idxs, reverse=True):
                del lines[idx]
                if idx < section_end:
                    section_end -= 1
            insert_at = section_end
            lines.insert(insert_at, formatted)
            action = f"added claim for `{agent}`"

        task_ok, task_msg = _upsert_active_task(lines, agent=agent, scope=scope, task=task)
        if not task_ok:
            return False, task_msg

        new_text = "\n".join(lines) + ("\n" if original_text.endswith("\n") else "")
        ok, violations = _validate_and_write(workboard_path, original_text, new_text)
        if not ok:
            joined = "; ".join(violations)
            return False, f"claim update rejected by gate: {joined}"
        return True, f"{action}; {task_msg}"


def release(workboard_path: Path, *, agent: str) -> Tuple[bool, str]:
    with _file_lock(LOCK_FILE):
        agent_norm = _agent_key(agent)
        original_text = workboard_path.read_text(encoding="utf-8")
        lines = original_text.splitlines()
        section_start, section_end = _find_claim_section(lines)
        bullet_idxs = _bullet_indices(lines, section_start, section_end)

        remove_idxs: List[int] = []
        keep_active = 0
        for idx in bullet_idxs:
            entry, fields, err = _parse_claim_line(idx + 1, lines[idx])
            if err:
                return False, err
            if entry is not None and entry.lower() in claims_gate.NONE_TOKENS:
                continue
            if not fields:
                continue
            current_agent = _agent_key(fields.get("agent", ""))
            if current_agent == agent_norm:
                remove_idxs.append(idx)
            else:
                keep_active += 1

        if not remove_idxs:
            return False, f"no active claim found for `{agent}`"

        for idx in sorted(remove_idxs, reverse=True):
            del lines[idx]
            if idx < section_end:
                section_end -= 1

        if keep_active == 0:
            lines.insert(section_end, NONE_ENTRY)

        task_ok, task_msg = _release_active_task(lines, agent=agent)
        if not task_ok:
            return False, task_msg

        new_text = "\n".join(lines) + ("\n" if original_text.endswith("\n") else "")
        ok, violations = _validate_and_write(workboard_path, original_text, new_text)
        if not ok:
            joined = "; ".join(violations)
            return False, f"claim release rejected by gate: {joined}"
        return True, f"released claim for `{agent}`; {task_msg}"


def list_claims(workboard_path: Path) -> Tuple[bool, List[str] | str]:
    text = workboard_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    section_start, section_end = _find_claim_section(lines)
    bullet_idxs = _bullet_indices(lines, section_start, section_end)

    claims: List[str] = []
    for idx in bullet_idxs:
        entry, fields, err = _parse_claim_line(idx + 1, lines[idx])
        if err:
            return False, err
        if entry is not None and entry.lower() in claims_gate.NONE_TOKENS:
            continue
        if fields:
            claims.append(lines[idx].strip())
    return True, claims


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Add/list/release active agent claims in WORKBOARD.md.")
    parser.add_argument(
        "--workboard",
        default=str(DEFAULT_WORKBOARD),
        help="Path to workboard markdown file (default: plans/thomas/WORKBOARD.md)",
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--claim", action="store_true", help="Add or update an active claim for --agent.")
    action.add_argument("--release", action="store_true", help="Release active claim for --agent.")
    action.add_argument("--list", action="store_true", help="List active claims.")
    parser.add_argument("--agent", help="Agent identifier (defaults to env/git user when omitted).")
    parser.add_argument("--scope", help="Claim scope path(s), comma separated.")
    parser.add_argument("--task", help="Short task description (defaults to current git branch).")
    args = parser.parse_args(argv)

    workboard_path = Path(args.workboard).expanduser()
    if not workboard_path.is_absolute():
        workboard_path = (ROOT / workboard_path).resolve()

    if not workboard_path.exists():
        print(f"Workboard claim tool: FAIL\n- missing workboard file: {workboard_path}")
        return 1

    try:
        if args.list:
            ok, result = list_claims(workboard_path)
            if not ok:
                print(f"Workboard claim tool: FAIL\n- {result}")
                return 1
            claims = result if isinstance(result, list) else []
            print("Workboard claim tool: PASS")
            if claims:
                for line in claims:
                    print(line)
            else:
                print("- no active claims")
            return 0

        if args.claim:
            if not args.scope:
                print("Workboard claim tool: FAIL\n- --scope is required for --claim")
                return 1
            agent = _resolve_agent(args.agent)
            task = _resolve_task(args.task)
            ok, msg = claim(workboard_path, agent=agent, scope=args.scope, task=task)
            if not ok:
                print(f"Workboard claim tool: FAIL\n- {msg}")
                return 1
            print("Workboard claim tool: PASS")
            print(f"- {msg}")
            return 0

        agent = _resolve_agent(args.agent)
        ok, msg = release(workboard_path, agent=agent)
        if not ok:
            print(f"Workboard claim tool: FAIL\n- {msg}")
            return 1
        print("Workboard claim tool: PASS")
        print(f"- {msg}")
        return 0
    except ValueError as exc:
        print(f"Workboard claim tool: FAIL\n- {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(run())
