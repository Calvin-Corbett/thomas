from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import agent_presence_inference

ROOT = Path(__file__).resolve().parents[2]
AGENT_ENV_KEYS = ("THOMAS_AGENT_ID", "AGENT_ID", "CODEX_AGENT_ID", "GEMINI_AGENT_ID", "CLAUDE_AGENT_ID")
SESSION_ENV_KEYS = ("THOMAS_AGENT_SESSION_ID", "AGENT_SESSION_ID")
PROCESS_HINTS = ("codex", "claude", "gemini", "thomas", "cursor", "agent")
DEFAULT_STALE_SECONDS = 120
DEFAULT_INFERRED_EXPIRY_SECONDS = 600
OVERRIDE_REASON_MIN_LEN = 12


def resolve_repo_root(repo_root: str | Path | None = None) -> Path:
    return (Path(repo_root).expanduser() if repo_root is not None else ROOT).resolve()


def coordination_dir(repo_root: str | Path | None = None) -> Path:
    return resolve_repo_root(repo_root) / "runtime" / "coordination"


def presence_dir(repo_root: str | Path | None = None) -> Path:
    return coordination_dir(repo_root) / "presence"


def session_file_path(session_id: str, repo_root: str | Path | None = None) -> Path:
    return presence_dir(repo_root) / f"{session_id}.json"


def summary_path(repo_root: str | Path | None = None) -> Path:
    return presence_dir(repo_root) / "repo-summary.json"


def inferred_state_path(repo_root: str | Path | None = None) -> Path:
    return coordination_dir(repo_root) / "inferred_presence_sync.json"


def override_audit_log(repo_root: str | Path | None = None) -> Path:
    return coordination_dir(repo_root) / "agent_presence_override_audit.jsonl"


def active_folders_state_path(repo_root: str | Path | None = None) -> Path:
    return coordination_dir(repo_root) / "active_folders.json"


def default_workboard_path(repo_root: str | Path | None = None) -> Path:
    return resolve_repo_root(repo_root) / "plans" / "thomas" / "WORKBOARD.md"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _to_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def _from_iso(value: str | None) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _env_int(name: str, default: int) -> int:
    raw = str(os.getenv(name, "")).strip()
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _dedupe(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        token = str(value or "").strip()
        if token and token not in seen:
            seen.add(token)
            out.append(token)
    return out


def _normalize_scope(scope: str | Sequence[str] | None) -> list[str]:
    if scope is None:
        return []
    parts = str(scope).split(",") if isinstance(scope, str) else [str(item or "") for item in scope]
    out: list[str] = []
    for raw in parts:
        token = str(raw or "").strip().replace("\\", "/")
        while token.startswith("./"):
            token = token[2:]
        while "//" in token:
            token = token.replace("//", "/")
        token = token.strip("/") or "."
        out.append(token)
    return _dedupe(out)


def _paths_overlap(a: str, b: str) -> bool:
    left = _normalize_scope([a])[0]
    right = _normalize_scope([b])[0]
    return left == right or left == "." or right == "." or left.startswith(f"{right}/") or right.startswith(f"{left}/")


def _scope_overlaps(left: Sequence[str], right: Sequence[str]) -> bool:
    return any(_paths_overlap(a, b) for a in left for b in right)


def _scope_sample(left: Sequence[str], right: Sequence[str]) -> list[str]:
    sample: list[str] = []
    for a in left:
        for b in right:
            if _paths_overlap(a, b):
                sample.append(a if len(a) <= len(b) else b)
    return _dedupe(sample)[:5]


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def current_session_id() -> str:
    for key in SESSION_ENV_KEYS:
        value = str(os.getenv(key, "")).strip()
        if value:
            return value
    return ""


def resolve_agent_id(explicit_agent: str | None = None) -> str:
    explicit = str(explicit_agent or "").strip()
    if explicit:
        return explicit
    for key in AGENT_ENV_KEYS:
        value = str(os.getenv(key, "")).strip()
        if value:
            return value
    return ""


def session_env_exports(session_id: str) -> dict[str, str]:
    token = str(session_id or "").strip()
    return {"THOMAS_AGENT_SESSION_ID": token, "AGENT_SESSION_ID": token} if token else {}


def register_session(
    *,
    repo_root: str | Path | None = None,
    session_id: str | None = None,
    agent_id: str | None = None,
    display_name: str | None = None,
    launcher: str = "",
    task_summary: str = "",
    scope: str | Sequence[str] | None = None,
    claim_status: str = "",
    folder_claims: Sequence[dict[str, Any]] | None = None,
    pid: int | None = None,
    command: str = "",
    warnings: Sequence[str] | None = None,
    origin: str = "explicit",
) -> dict[str, Any]:
    repo = resolve_repo_root(repo_root)
    sid = str(session_id or current_session_id() or uuid.uuid4()).strip()
    existing = _read_json(session_file_path(sid, repo), {})
    now = _now()
    payload = {
        "session_id": sid,
        "agent_id": resolve_agent_id(agent_id),
        "display_name": str(display_name or existing.get("display_name") or resolve_agent_id(agent_id) or sid).strip(),
        "repo_root": str(repo),
        "pid": int(pid if pid is not None else existing.get("pid") or os.getpid()),
        "launcher": str(launcher or existing.get("launcher") or Path(sys.argv[0] or "python").name),
        "task_summary": str(task_summary or existing.get("task_summary") or "").strip(),
        "scope": _normalize_scope(scope if scope is not None else existing.get("scope")),
        "claim_status": str(claim_status or existing.get("claim_status") or "").strip(),
        "folder_claims": list(folder_claims if folder_claims is not None else existing.get("folder_claims") or []),
        "started_at": str(existing.get("started_at") or _to_iso(now)),
        "last_heartbeat_at": _to_iso(now),
        "last_activity_at": _to_iso(now),
        "state": "active",
        "confidence": "high",
        "source_signals": _dedupe([*list(existing.get("source_signals") or []), "session"]),
        "warnings": _dedupe(
            [*list(existing.get("warnings") or []), *[str(item) for item in (warnings or []) if str(item).strip()]]
        ),
        "command": str(command or existing.get("command") or " ".join(sys.argv)).strip(),
        "origin": str(origin or existing.get("origin") or "explicit").strip(),
    }
    _write_json(session_file_path(sid, repo), payload)
    return payload


def heartbeat_session(
    *,
    repo_root: str | Path | None = None,
    session_id: str | None = None,
    task_summary: str | None = None,
    scope: str | Sequence[str] | None = None,
    claim_status: str | None = None,
    folder_claims: Sequence[dict[str, Any]] | None = None,
    mark_active: bool = True,
) -> dict[str, Any] | None:
    repo = resolve_repo_root(repo_root)
    sid = str(session_id or current_session_id()).strip()
    if not sid:
        return None
    path = session_file_path(sid, repo)
    payload = _read_json(path, {}) if path.exists() else {}
    if not payload:
        return None
    now = _now()
    payload["last_heartbeat_at"] = _to_iso(now)
    if mark_active:
        payload["last_activity_at"] = _to_iso(now)
        payload["state"] = "active"
    if task_summary is not None:
        payload["task_summary"] = str(task_summary).strip()
    if scope is not None:
        payload["scope"] = _normalize_scope(scope)
    if claim_status is not None:
        payload["claim_status"] = str(claim_status).strip()
    if folder_claims is not None:
        payload["folder_claims"] = list(folder_claims)
    payload["source_signals"] = _dedupe([*list(payload.get("source_signals") or []), "session"])
    _write_json(path, payload)
    return payload


def close_session(*, repo_root: str | Path | None = None, session_id: str | None = None, state: str = "closed") -> bool:
    repo = resolve_repo_root(repo_root)
    sid = str(session_id or current_session_id()).strip()
    path = session_file_path(sid, repo)
    if not sid or not path.exists():
        return False
    payload = _read_json(path, {})
    if not payload:
        return False
    now = _now()
    payload["state"] = str(state or "closed").strip() or "closed"
    payload["last_heartbeat_at"] = _to_iso(now)
    payload["closed_at"] = _to_iso(now)
    _write_json(path, payload)
    return True


def _is_pid_alive(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


PROCESS_FAMILY_PATTERNS: dict[str, tuple[str, ...]] = {
    "codex": ("codex.exe", "@openai/codex", "openai.codex", "resources\\codex.exe", " codex "),
    "claude": ("claude.exe", "appdata/roaming/claude", "chrome-native-host.exe", " claude "),
    "gemini": ("gemini",),
    "cursor": ("cursor",),
}
PROCESS_SERVICE_PATTERNS = (
    "run-ui.ps1",
    "run-ui.cmd",
    "-m thomas.server",
    "scripts\\run-ui.ps1",
    "scripts/run-ui.ps1",
)
PROCESS_TOOL_PATTERNS = ("playwright-mcp", "@playwright/mcp")
PROCESS_PROBE_PATTERNS = ("agent_presence.py status",)
NOISY_ACTIVITY_PATTERNS = (
    ".git/",
    "node_modules/",
    ".next/",
    "runtime/.thomas/",
    ".thomas/",
    "runtime/logs/",
    "runtime/coordination/presence/",
    "__pycache__/",
    ".pyc",
    ".tmp_",
    "server_startup_log.txt",
)
DEFAULT_RECENT_ACTIVITY_SECONDS = 1800


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value or default).strip())
    except ValueError:
        return default


def _normalize_relpath(value: str | Path | None) -> str:
    token = str(value or "").strip().replace("\\", "/")
    while token.startswith("./"):
        token = token[2:]
    while "//" in token:
        token = token.replace("//", "/")
    return token.strip("/")


def _is_noise_activity_path(path: str) -> bool:
    token = _normalize_relpath(path).lower()
    if not token:
        return True
    return any(pattern in token for pattern in NOISY_ACTIVITY_PATTERNS)


def _coerce_warning_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
    return _dedupe(out)


def _collect_sessions(repo_root: Path) -> list[dict[str, Any]]:
    stale_seconds = _env_int("THOMAS_AGENT_PRESENCE_STALE_SECONDS", DEFAULT_STALE_SECONDS)
    now = _now()
    rows: list[dict[str, Any]] = []
    summary = summary_path(repo_root).resolve()
    for path in sorted(presence_dir(repo_root).glob("*.json")):
        if path.resolve() == summary:
            continue
        payload = _read_json(path, {})
        if not isinstance(payload, dict):
            continue
        if str(payload.get("repo_root") or "") not in {"", str(repo_root)}:
            continue
        session_id = str(payload.get("session_id") or "").strip()
        if not session_id:
            continue
        if str(payload.get("state") or "").strip().lower() == "closed":
            continue
        heartbeat = _from_iso(payload.get("last_heartbeat_at"))
        state = "stale"
        confidence = "low"
        if heartbeat and (now - heartbeat).total_seconds() <= stale_seconds:
            state, confidence = "active", "high"
        elif _is_pid_alive(_safe_int(payload.get("pid"), 0)):
            state, confidence = "alive", "high"
        elif payload.get("claim_status") or payload.get("scope"):
            confidence = "medium"
        payload["state"] = state
        payload["confidence"] = confidence
        payload["scope"] = _normalize_scope(payload.get("scope"))
        payload["folder_claims"] = list(payload.get("folder_claims") or [])
        payload["source_signals"] = _dedupe([*list(payload.get("source_signals") or []), "session"])
        payload["warnings"] = _coerce_warning_list(payload.get("warnings"))
        rows.append(payload)
    return rows


def _parse_key_values(body: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for piece in str(body or "").split(";"):
        if "=" in piece:
            key, value = piece.split("=", 1)
            key = key.strip().lower()
            if key:
                fields[key] = value.strip()
    return fields


def _parse_workboard_claims(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    in_claims = False
    rows: list[dict[str, Any]] = []
    for line in lines:
        if line.startswith("## "):
            in_claims = "agent claims" in line.lower()
            continue
        if not in_claims:
            continue
        token = line.strip()
        if not token.startswith("- "):
            continue
        body = token[2:].strip()
        if body.lower() == "none":
            continue
        fields = _parse_key_values(body)
        agent_id = str(fields.get("agent") or "").strip()
        if agent_id:
            rows.append(
                {
                    "agent_id": agent_id,
                    "display_name": str(fields.get("name") or agent_id).strip(),
                    "name": str(fields.get("name") or agent_id).strip(),
                    "role": str(fields.get("role") or "").strip(),
                    "parent": str(fields.get("parent") or "").strip(),
                    "scope": _normalize_scope(fields.get("scope")),
                    "task_summary": str(fields.get("task") or "").strip(),
                    "claim_status": "claimed",
                    "source_signals": ["workboard_claim"],
                    "inferred": str(fields.get("inferred") or "").strip().lower() == "true",
                    "fields": dict(fields),
                }
            )
    return rows


def _parse_folder_claims(repo_root: Path) -> list[dict[str, Any]]:
    payload = _read_json(active_folders_state_path(repo_root), {})
    claims = payload.get("claims") if isinstance(payload, dict) else []
    now = _now()
    out: list[dict[str, Any]] = []
    for claim in claims or []:
        if not isinstance(claim, dict):
            continue
        expires_at = _from_iso(str(claim.get("expires_at") or ""))
        if expires_at and expires_at <= now:
            continue
        out.append(
            {
                "claim_id": str(claim.get("claim_id") or "").strip(),
                "agent_id": str(claim.get("agent_id") or "").strip(),
                "session_id": str(claim.get("session_id") or "").strip(),
                "paths": _normalize_scope(claim.get("paths")),
                "note": str(claim.get("note") or "").strip(),
                "last_heartbeat_at": str(claim.get("last_heartbeat_at") or "").strip(),
                "expires_at": str(claim.get("expires_at") or "").strip(),
            }
        )
    return out


def _porcelain_path(line: str) -> str:
    if len(line) <= 3:
        return ""
    token = line[3:].strip()
    if " -> " in token:
        token = token.split(" -> ", 1)[1].strip()
    return _normalize_scope([token])[0] if token else ""


def _git_dirty_paths(repo_root: Path) -> list[str]:
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain"], cwd=repo_root, capture_output=True, text=True, check=False
        )
    except OSError:
        return []
    if proc.returncode != 0:
        return []
    paths = [
        _porcelain_path(str(line or "").rstrip())
        for line in str(proc.stdout or "").splitlines()
        if str(line or "").strip() and not str(line).startswith("!!")
    ]
    return _dedupe([path for path in paths if path])


def _classify_process_family(name: str, command: str) -> str:
    combined = f"{name} {command}".lower().replace("\\", "/")
    for family, patterns in PROCESS_FAMILY_PATTERNS.items():
        if any(pattern in combined for pattern in patterns):
            return family
    return ""


def _classify_process_role(name: str, command: str, family: str) -> str:
    combined = f"{name} {command}".lower().replace("\\", "/")
    if any(pattern in combined for pattern in PROCESS_PROBE_PATTERNS):
        return "probe"
    if any(pattern in combined for pattern in PROCESS_SERVICE_PATTERNS):
        return "service"
    if any(pattern in combined for pattern in PROCESS_TOOL_PATTERNS):
        return "tool"
    if family:
        return "agent"
    return "generic"


def _query_process_records(repo_root: Path) -> list[dict[str, Any]]:
    repo_token = str(repo_root).lower().replace("\\", "/")
    repo_name = repo_root.name.lower()
    try:
        if os.name == "nt":
            proc = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,Name,CommandLine,CreationDate | ConvertTo-Json -Depth 4",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            raw = json.loads(proc.stdout or "[]") if proc.returncode == 0 else []
            rows = raw if isinstance(raw, list) else ([raw] if isinstance(raw, dict) else [])
        else:
            proc = subprocess.run(["ps", "-axo", "pid=,ppid=,comm=,args="], capture_output=True, text=True, check=False)
            rows = []
            if proc.returncode == 0:
                for raw_line in str(proc.stdout or "").splitlines():
                    parts = raw_line.strip().split(None, 3)
                    if len(parts) >= 3:
                        rows.append(
                            {
                                "ProcessId": parts[0],
                                "ParentProcessId": parts[1],
                                "Name": parts[2],
                                "CommandLine": parts[3] if len(parts) > 3 else parts[2],
                            }
                        )
    except (OSError, json.JSONDecodeError):
        return []
    out: list[dict[str, Any]] = []
    for item in rows:
        name = str(item.get("Name") or "").strip()
        command = str(item.get("CommandLine") or "").strip()
        combined = f"{name} {command}".lower().replace("\\", "/")
        if not combined:
            continue
        family = _classify_process_family(name, command)
        repo_related = repo_token in combined or (repo_name in combined and (family or "thomas" in combined))
        role = _classify_process_role(name, command, family)
        if not (family or repo_related or role in {"service", "tool"}):
            continue
        out.append(
            {
                "pid": _safe_int(item.get("ProcessId"), 0),
                "parent_pid": _safe_int(item.get("ParentProcessId"), 0),
                "name": name,
                "command": command,
                "family": family,
                "role": role,
                "repo_related": repo_related,
                "created_at": str(item.get("CreationDate") or "").strip(),
            }
        )
    return out


def _short_command(command: str, limit: int = 160) -> str:
    token = " ".join(str(command or "").split())
    return token if len(token) <= limit else token[: limit - 3] + "..."


def _display_name_for_family(family: str) -> str:
    return {"codex": "Codex", "claude": "Claude", "gemini": "Gemini", "cursor": "Cursor"}.get(family, family or "agent")


def _family_from_agent_label(label: str) -> str:
    token = str(label or "").strip().lower()
    for family in PROCESS_FAMILY_PATTERNS:
        if family in token:
            return family
    return ""


def _global_agent_presence(repo_root: Path) -> dict[str, dict[str, Any]]:
    presence: dict[str, dict[str, Any]] = {}
    for row in _query_process_records(repo_root):
        family = str(row.get("family") or "").strip()
        if not family:
            continue
        role = str(row.get("role") or "")
        if role != "agent":
            continue
        item = presence.setdefault(family, {"family": family, "pids": [], "commands": []})
        item["pids"] = _dedupe([*list(item.get("pids") or []), str(int(row.get("pid") or 0))])
        snippet = _short_command(str(row.get("command") or ""))
        if snippet:
            item["commands"] = _dedupe([*list(item.get("commands") or []), snippet])[:5]
    return presence


def _ancestor_family(pid: int, records: dict[int, dict[str, Any]]) -> str:
    seen: set[int] = set()
    current = pid
    while current and current not in seen:
        seen.add(current)
        row = records.get(current)
        if not row:
            return ""
        family = str(row.get("family") or "").strip()
        if family:
            return family
        current = int(row.get("parent_pid") or 0)
    return ""


def _list_processes(repo_root: Path) -> list[dict[str, Any]]:
    records = _query_process_records(repo_root)
    by_pid = {int(row.get("pid") or 0): row for row in records if int(row.get("pid") or 0) > 0}
    groups: dict[str, dict[str, Any]] = {}
    for row in records:
        role = str(row.get("role") or "")
        if role in {"service", "tool"}:
            continue
        repo_related = bool(row.get("repo_related"))
        family = str(row.get("family") or "").strip()
        owner_family = family or _ancestor_family(int(row.get("parent_pid") or 0), by_pid)
        if not repo_related:
            continue
        if role == "probe" and not owner_family:
            continue
        key = owner_family or f"process:{int(row.get('pid') or 0)}"
        group = groups.setdefault(
            key,
            {
                "agent_id": key,
                "display_name": _display_name_for_family(owner_family) if owner_family else str(row.get("name") or key),
                "pid": int(row.get("pid") or 0),
                "process_pids": [],
                "process_family": owner_family,
                "command_samples": [],
                "state": "unregistered",
                "confidence": "medium" if owner_family else "low",
                "source_signals": ["process_tree" if owner_family else "process"],
                "warnings": [],
                "last_activity_at": _to_iso(_now()),
            },
        )
        group["process_pids"] = _dedupe([*list(group.get("process_pids") or []), str(int(row.get("pid") or 0))])
        snippet = _short_command(str(row.get("command") or ""))
        if snippet:
            group["command_samples"] = _dedupe([*list(group.get("command_samples") or []), snippet])[:5]
        if owner_family:
            group["warnings"] = _dedupe(
                [
                    *list(group.get("warnings") or []),
                    f"{_display_name_for_family(owner_family)} has live repo-linked process activity.",
                ]
            )
        else:
            group["warnings"] = _dedupe(
                [
                    *list(group.get("warnings") or []),
                    f"Unregistered process '{row.get('name') or key}' references this repo.",
                ]
            )
        if not group.get("pid"):
            group["pid"] = int(row.get("pid") or 0)
    out: list[dict[str, Any]] = []
    for group in groups.values():
        sample = list(group.get("command_samples") or [])
        out.append(
            {
                "agent_id": str(group.get("agent_id") or "").strip(),
                "display_name": str(group.get("display_name") or group.get("agent_id") or "").strip(),
                "pid": int(group.get("pid") or 0),
                "task_summary": sample[0] if sample else "live repo-linked process activity",
                "state": str(group.get("state") or "unregistered"),
                "confidence": str(group.get("confidence") or "low"),
                "source_signals": list(group.get("source_signals") or []),
                "warnings": list(group.get("warnings") or []),
                "command": sample[0] if sample else "",
                "last_activity_at": str(group.get("last_activity_at") or ""),
                "process_pids": list(group.get("process_pids") or []),
                "evidence": sample,
                "process_family": str(group.get("process_family") or ""),
            }
        )
    return out


def _list_repo_services(repo_root: Path) -> list[dict[str, Any]]:
    services: dict[str, dict[str, Any]] = {}
    for row in _query_process_records(repo_root):
        role = str(row.get("role") or "")
        if role not in {"service", "tool"}:
            continue
        if not bool(row.get("repo_related")):
            continue
        key = (
            "thomas-ui"
            if "run-ui" in str(row.get("command") or "").lower()
            else "thomas-server"
            if "thomas.server" in str(row.get("command") or "").lower()
            else role
        )
        item = services.setdefault(
            key, {"service_id": key, "display_name": key.replace("-", " ").title(), "pids": [], "commands": []}
        )
        item["pids"] = _dedupe([*list(item.get("pids") or []), str(int(row.get("pid") or 0))])
        snippet = _short_command(str(row.get("command") or ""))
        if snippet:
            item["commands"] = _dedupe([*list(item.get("commands") or []), snippet])[:5]
    return sorted(services.values(), key=lambda row: str(row.get("service_id") or ""))


def _path_activity(repo_root: Path, relpath: str, *, now: datetime) -> dict[str, Any]:
    normalized = _normalize_scope([relpath])[0]
    full = repo_root / normalized
    modified_at = ""
    age_seconds: int | None = None
    exists = full.exists()
    if exists:
        try:
            stamp = datetime.fromtimestamp(full.stat().st_mtime, tz=timezone.utc)
            modified_at = _to_iso(stamp)
            age_seconds = max(0, int((now - stamp).total_seconds()))
        except OSError:
            modified_at = ""
            age_seconds = None
    return {
        "path": normalized,
        "modified_at": modified_at,
        "age_seconds": age_seconds,
        "exists": exists,
        "recent": age_seconds is not None
        and age_seconds <= _env_int("THOMAS_AGENT_PRESENCE_RECENT_SECONDS", DEFAULT_RECENT_ACTIVITY_SECONDS),
    }


def _collect_recent_file_activity(repo_root: Path, dirty_paths: Sequence[str]) -> list[dict[str, Any]]:
    now = _now()
    rows = [
        _path_activity(repo_root, path, now=now) for path in dirty_paths if path and not _is_noise_activity_path(path)
    ]
    rows.sort(
        key=lambda row: (
            (row.get("age_seconds") is None),
            int(row.get("age_seconds") or 10**9),
            str(row.get("path") or ""),
        )
    )
    return rows


def _base_row(repo_root: Path, key: str) -> dict[str, Any]:
    return {
        "session_id": "",
        "agent_id": key,
        "display_name": key,
        "repo_root": str(repo_root),
        "pid": 0,
        "launcher": "",
        "task_summary": "",
        "scope": [],
        "claim_status": "",
        "folder_claims": [],
        "started_at": "",
        "last_heartbeat_at": "",
        "last_activity_at": "",
        "state": "declared",
        "confidence": "medium",
        "source_signals": [],
        "warnings": [],
        "command": "",
        "recent_paths": [],
        "activity_count": 0,
        "process_pids": [],
        "evidence": [],
    }


def _merge_row(target: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    for key in (
        "session_id",
        "agent_id",
        "display_name",
        "launcher",
        "task_summary",
        "claim_status",
        "started_at",
        "command",
    ):
        value = str(patch.get(key) or "").strip()
        if value and not str(target.get(key) or "").strip():
            target[key] = value
    if _safe_int(patch.get("pid"), 0) and not _safe_int(target.get("pid"), 0):
        target["pid"] = _safe_int(patch.get("pid"), 0)
    for key in ("last_heartbeat_at", "last_activity_at"):
        value = str(patch.get(key) or "").strip()
        if value:
            target[key] = value
    target["scope"] = _dedupe([*list(target.get("scope") or []), *_normalize_scope(patch.get("scope"))])
    target["folder_claims"] = [*list(target.get("folder_claims") or []), *list(patch.get("folder_claims") or [])]
    target["source_signals"] = _dedupe(
        [*list(target.get("source_signals") or []), *list(patch.get("source_signals") or [])]
    )
    target["warnings"] = _dedupe([*list(target.get("warnings") or []), *_coerce_warning_list(patch.get("warnings"))])
    target["recent_paths"] = _dedupe(
        [
            *list(target.get("recent_paths") or []),
            *[str(item) for item in list(patch.get("recent_paths") or []) if str(item).strip()],
        ]
    )[:8]
    target["process_pids"] = _dedupe(
        [
            *list(target.get("process_pids") or []),
            *[str(item) for item in list(patch.get("process_pids") or []) if str(item).strip()],
        ]
    )
    target["evidence"] = _dedupe(
        [
            *list(target.get("evidence") or []),
            *[str(item) for item in list(patch.get("evidence") or []) if str(item).strip()],
        ]
    )[:8]
    target["activity_count"] = max(
        _safe_int(target.get("activity_count"), 0), _safe_int(patch.get("activity_count"), 0)
    )
    state_rank = {"active": 5, "alive": 4, "unregistered": 3, "declared": 2, "stale": 1}
    confidence_rank = {"high": 3, "medium": 2, "low": 1}
    patch_state = str(patch.get("state") or target.get("state") or "declared")
    patch_confidence = str(patch.get("confidence") or target.get("confidence") or "medium")
    if state_rank.get(patch_state, 0) >= state_rank.get(str(target.get("state") or ""), 0):
        target["state"] = patch_state
    if confidence_rank.get(patch_confidence, 0) >= confidence_rank.get(str(target.get("confidence") or ""), 0):
        target["confidence"] = patch_confidence
    return target


def _legacy_process_patch(proc: dict[str, Any]) -> dict[str, Any]:
    return {
        "agent_id": f"process:{_safe_int(proc.get('pid'), 0)}",
        "display_name": str(proc.get("name") or proc.get("agent_hint") or "unregistered-agent"),
        "pid": _safe_int(proc.get("pid"), 0),
        "task_summary": _short_command(str(proc.get("command") or "")),
        "state": "unregistered",
        "confidence": "low",
        "source_signals": ["process"],
        "warnings": [f"Unregistered process '{proc.get('name') or proc.get('agent_hint')}' references this repo."],
        "command": str(proc.get("command") or "").strip(),
        "last_activity_at": _to_iso(_now()),
        "evidence": [_short_command(str(proc.get("command") or ""))],
    }


def collect_presence(
    *, repo_root: str | Path | None = None, workboard_path: str | Path | None = None
) -> dict[str, Any]:
    repo = resolve_repo_root(repo_root)
    board = Path(workboard_path).resolve() if workboard_path else default_workboard_path(repo)
    agents: dict[str, dict[str, Any]] = {}
    for session in _collect_sessions(repo):
        key = str(session.get("agent_id") or session.get("session_id") or f"session:{uuid.uuid4()}")
        agents[key] = _merge_row(_base_row(repo, key), session)
    workboard_claims = _parse_workboard_claims(board)
    for claim in workboard_claims:
        key = str(claim.get("agent_id") or f"claim:{len(agents)}")
        agents[key] = _merge_row(agents.get(key, _base_row(repo, key)), claim)
    for claim in _parse_folder_claims(repo):
        key = str(claim.get("agent_id") or claim.get("session_id") or f"folder:{claim.get('claim_id') or len(agents)}")
        patch = {
            "agent_id": claim.get("agent_id") or key,
            "session_id": claim.get("session_id") or "",
            "scope": list(claim.get("paths") or []),
            "task_summary": claim.get("note") or "",
            "folder_claims": [claim],
            "claim_status": "folder-claim",
            "state": "alive",
            "confidence": "medium",
            "source_signals": ["folder_claim"],
            "last_heartbeat_at": claim.get("last_heartbeat_at") or "",
        }
        agents[key] = _merge_row(agents.get(key, _base_row(repo, key)), patch)
    for proc in _list_processes(repo):
        patch = proc if "agent_id" in proc else _legacy_process_patch(proc)
        key = str(patch.get("agent_id") or f"process:{len(agents)}")
        agents[key] = _merge_row(agents.get(key, _base_row(repo, key)), patch)
    dirty_paths = _git_dirty_paths(repo)
    activity = _collect_recent_file_activity(repo, dirty_paths)
    rows = list(agents.values())
    global_presence = _global_agent_presence(repo)
    agent_presence_inference.apply_file_activity(rows, activity, global_presence)
    claimed = [
        scope
        for row in rows
        if str(row.get("state") or "") in {"active", "alive", "declared"}
        and str(row.get("confidence") or "") in {"high", "medium"}
        for scope in _normalize_scope(row.get("scope"))
    ]
    uncovered = [
        item for item in activity if not any(_paths_overlap(str(item.get("path") or ""), scope) for scope in claimed)
    ]
    if uncovered:
        key = "unregistered-worktree"
        agents[key] = _merge_row(
            agents.get(key, _base_row(repo, key)),
            {
                "agent_id": key,
                "display_name": "Unregistered Repo Activity",
                "task_summary": f"Dirty repo activity on {len(uncovered)} unclaimed path(s).",
                "scope": [str(item.get("path") or "") for item in uncovered[:20]],
                "recent_paths": [str(item.get("path") or "") for item in uncovered[:8]],
                "activity_count": len(uncovered),
                "state": "unregistered",
                "confidence": "low",
                "source_signals": ["git_worktree", "file_activity"],
                "warnings": ["Dirty worktree paths are not covered by any active registered scope."],
                "last_activity_at": next(
                    (
                        str(item.get("modified_at") or "")
                        for item in uncovered
                        if str(item.get("modified_at") or "").strip()
                    ),
                    _to_iso(_now()),
                ),
                "evidence": [str(item.get("path") or "") for item in uncovered[:5]],
            },
        )
        rows = list(agents.values())
    inferred_candidates, inferred_suppressed_now = agent_presence_inference.infer_claim_candidates(
        rows=rows,
        activity=activity,
        global_presence=global_presence,
        workboard_claims=workboard_claims,
    )
    rows = sorted(
        rows,
        key=lambda row: (
            {"high": 0, "medium": 1, "low": 2}.get(str(row.get("confidence") or ""), 3),
            {"active": 0, "alive": 1, "declared": 2, "unregistered": 3, "stale": 4}.get(str(row.get("state") or ""), 5),
            str(row.get("display_name") or row.get("agent_id") or ""),
        ),
    )
    warnings: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("state") or "") == "stale":
            warnings.append(
                {
                    "code": "stale_agent",
                    "agent_id": str(row.get("agent_id") or ""),
                    "message": f"Agent '{row.get('display_name') or row.get('agent_id')}' looks stale.",
                    "scope": list(row.get("scope") or []),
                }
            )
        for item in _coerce_warning_list(row.get("warnings")):
            warnings.append(
                {
                    "code": "presence_warning",
                    "agent_id": str(row.get("agent_id") or ""),
                    "message": item,
                    "scope": list(row.get("scope") or []),
                }
            )
    for i, left in enumerate(rows):
        left_scope = _normalize_scope(left.get("scope"))
        left_state = str(left.get("state") or "")
        left_agent = str(left.get("agent_id") or "")
        if left_state not in {"active", "alive", "declared", "unregistered"} or not left_scope:
            continue
        for right in rows[i + 1 :]:
            right_scope = _normalize_scope(right.get("scope"))
            right_state = str(right.get("state") or "")
            right_agent = str(right.get("agent_id") or "")
            if (
                right_state not in {"active", "alive", "declared", "unregistered"}
                or not right_scope
                or left_agent == right_agent
            ):
                continue
            if _scope_overlaps(left_scope, right_scope):
                conflicts.append(
                    {
                        "type": "scope_overlap",
                        "agents": [left_agent, right_agent],
                        "message": f"Scope overlap between '{left.get('display_name') or left_agent}' and '{right.get('display_name') or right_agent}'.",
                        "scope": _scope_sample(left_scope, right_scope),
                    }
                )
    inferred_state = agent_presence_inference._read_inferred_state(repo)
    payload = {
        "success": True,
        "repo_root": str(repo),
        "generated_at": _to_iso(_now()),
        "active_count": sum(
            1 for row in rows if str(row.get("state") or "") in {"active", "alive", "declared", "unregistered"}
        ),
        "agents": rows,
        "recent_activity": activity[:20],
        "services": _list_repo_services(repo),
        "warnings": warnings,
        "conflicts": conflicts,
        "inferred_candidates": inferred_candidates,
        "inferred_applied": list(inferred_state.get("inferred_applied") or []),
        "inferred_suppressed": [*list(inferred_state.get("inferred_suppressed") or []), *inferred_suppressed_now],
        "inferred_expired": list(inferred_state.get("inferred_expired") or []),
    }
    _write_json(summary_path(repo), payload)
    return payload


def _validate_override_reason(reason: str) -> str:
    token = str(reason or "").strip()
    if not token:
        raise ValueError("presence override reason is required when override is requested")
    if len(token) < OVERRIDE_REASON_MIN_LEN:
        raise ValueError(f"presence override reason must be at least {OVERRIDE_REASON_MIN_LEN} characters")
    if any(ch in token for ch in ("\n", "\r")):
        raise ValueError("presence override reason cannot contain newlines")
    return token


def _append_override_audit(
    *,
    repo_root: Path,
    purpose: str,
    actor_agent: str,
    requested_scope: Sequence[str],
    reason: str,
    gate_result: dict[str, Any],
) -> None:
    path = override_audit_log(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "action": "agent_presence_override",
        "timestamp_utc": _to_iso(_now()),
        "purpose": str(purpose or "").strip(),
        "actor_agent": str(actor_agent or "").strip(),
        "requested_scope": list(requested_scope),
        "reason": str(reason),
        "warnings": list(gate_result.get("warnings") or []),
        "conflicts": list(gate_result.get("conflicts") or []),
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def evaluate_soft_gate(
    *,
    purpose: str,
    repo_root: str | Path | None = None,
    workboard_path: str | Path | None = None,
    actor_agent: str | None = None,
    requested_scope: str | Sequence[str] | None = None,
    allow_override: bool = False,
    override_reason: str = "",
) -> dict[str, Any]:
    repo = resolve_repo_root(repo_root)
    actor = resolve_agent_id(actor_agent)
    scope = _normalize_scope(requested_scope)
    snapshot = collect_presence(repo_root=repo, workboard_path=workboard_path)
    warnings: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    for row in list(snapshot.get("agents") or []):
        agent_id = str(row.get("agent_id") or "").strip()
        if actor and agent_id.lower() == actor.lower():
            continue
        row_scope = _normalize_scope(row.get("scope"))
        row_state = str(row.get("state") or "")
        relevant = (
            not scope
            or (row_scope and _scope_overlaps(scope, row_scope))
            or (row_state == "unregistered" and not row_scope)
        )
        if not relevant:
            continue
        if row_state == "unregistered":
            warnings.append(
                {
                    "agent_id": agent_id,
                    "state": row_state,
                    "scope": row_scope,
                    "message": f"Unregistered activity detected from '{row.get('display_name') or agent_id}'.",
                }
            )
        elif not scope and row_state in {"active", "alive", "declared"}:
            conflicts.append(
                {
                    "agent_id": agent_id,
                    "state": row_state,
                    "scope": row_scope,
                    "message": f"Agent '{row.get('display_name') or agent_id}' is active in this repo.",
                }
            )
        elif scope and row_scope and _scope_overlaps(scope, row_scope) and row_state in {"active", "alive", "declared"}:
            conflicts.append(
                {
                    "agent_id": agent_id,
                    "state": row_state,
                    "scope": _scope_sample(scope, row_scope),
                    "message": f"Scope overlaps active agent '{row.get('display_name') or agent_id}'.",
                }
            )
        elif scope and row_scope and _scope_overlaps(scope, row_scope) and row_state == "stale":
            warnings.append(
                {
                    "agent_id": agent_id,
                    "state": row_state,
                    "scope": _scope_sample(scope, row_scope),
                    "message": f"Scope overlaps stale agent '{row.get('display_name') or agent_id}'.",
                }
            )
    needs_override = bool(warnings or conflicts)
    message = ""
    if needs_override:
        counts = []
        if conflicts:
            counts.append(f"{len(conflicts)} conflict(s)")
        if warnings:
            counts.append(f"{len(warnings)} warning(s)")
        detail = [
            str(item.get("message") or "")
            for item in [*conflicts[:2], *warnings[:2]]
            if str(item.get("message") or "").strip()
        ]
        message = "presence gate requires override: " + ", ".join(counts)
        if detail:
            message += ". " + " ".join(detail)
    result = {
        "ok": not needs_override,
        "needs_override": needs_override,
        "overridden": False,
        "purpose": str(purpose or "").strip(),
        "actor_agent": actor,
        "requested_scope": scope,
        "warnings": warnings,
        "conflicts": conflicts,
        "message": message,
        "snapshot": snapshot,
    }
    if not needs_override:
        return result
    if not allow_override:
        return result
    reason = _validate_override_reason(override_reason)
    _append_override_audit(
        repo_root=repo,
        purpose=str(purpose or "").strip(),
        actor_agent=actor,
        requested_scope=scope,
        reason=reason,
        gate_result=result,
    )
    result["ok"] = True
    result["overridden"] = True
    result["override_reason"] = reason
    return result
