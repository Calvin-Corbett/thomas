"""Native orchestration recipes and state for Thomas forge/evolve work.

This is the first in-process replacement for external Codex heartbeat threads:
Thomas can name a recurring recipe, inspect current repo/workboard/evolve state,
dedupe active workers, and produce a bounded dispatch plan without spawning a
new external council on every wakeup.
"""

from __future__ import annotations

import ctypes
import json
import os
import socket
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ACTIVE_WORKER_STATUSES = {"planned", "queued", "running", "blocked", "merge_ready", "awaiting_review"}
DEFAULT_RECIPE_ID = "senior-council-integration"
STATE_VERSION = 1


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def orchestration_root(project_root: Path) -> Path:
    return Path(project_root) / ".thomas" / "evolve" / "orchestration"


def state_path(project_root: Path) -> Path:
    return orchestration_root(project_root) / "state.json"


def _coerce_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)]


@dataclass
class OrchestrationLane:
    key: str
    title: str
    goal_prompt: str
    claim_scope: list[str]
    dedupe_key: str
    runner_hint: str = "evolve.dispatch"
    model_hint: str = "codex:gpt"
    stop_conditions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "goal_prompt": self.goal_prompt,
            "claim_scope": list(self.claim_scope),
            "dedupe_key": self.dedupe_key,
            "runner_hint": self.runner_hint,
            "model_hint": self.model_hint,
            "stop_conditions": list(self.stop_conditions),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> OrchestrationLane:
        return cls(
            key=str(payload.get("key") or "").strip(),
            title=str(payload.get("title") or "").strip(),
            goal_prompt=str(payload.get("goal_prompt") or "").strip(),
            claim_scope=_coerce_str_list(payload.get("claim_scope")),
            dedupe_key=str(payload.get("dedupe_key") or "").strip(),
            runner_hint=str(payload.get("runner_hint") or "evolve.dispatch").strip(),
            model_hint=str(payload.get("model_hint") or "codex:gpt").strip(),
            stop_conditions=_coerce_str_list(payload.get("stop_conditions")),
        )


@dataclass
class OrchestrationRecipe:
    id: str
    name: str
    trigger: str
    coordinator_goal: str
    max_active_workers: int
    dedupe_key: str
    claim_scope: list[str]
    lanes: list[OrchestrationLane]
    runner_hint: str = "native-orchestrator"
    model_hint: str = "codex:gpt"
    stop_conditions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "trigger": self.trigger,
            "coordinator_goal": self.coordinator_goal,
            "max_active_workers": int(self.max_active_workers),
            "dedupe_key": self.dedupe_key,
            "claim_scope": list(self.claim_scope),
            "runner_hint": self.runner_hint,
            "model_hint": self.model_hint,
            "stop_conditions": list(self.stop_conditions),
            "lanes": [lane.to_dict() for lane in self.lanes],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> OrchestrationRecipe:
        lanes = [OrchestrationLane.from_dict(item) for item in payload.get("lanes") or [] if isinstance(item, dict)]
        return cls(
            id=str(payload.get("id") or "").strip(),
            name=str(payload.get("name") or "").strip(),
            trigger=str(payload.get("trigger") or "").strip(),
            coordinator_goal=str(payload.get("coordinator_goal") or "").strip(),
            max_active_workers=max(1, int(payload.get("max_active_workers") or 1)),
            dedupe_key=str(payload.get("dedupe_key") or "").strip(),
            claim_scope=_coerce_str_list(payload.get("claim_scope")),
            runner_hint=str(payload.get("runner_hint") or "native-orchestrator").strip(),
            model_hint=str(payload.get("model_hint") or "codex:gpt").strip(),
            stop_conditions=_coerce_str_list(payload.get("stop_conditions")),
            lanes=lanes,
        )


@dataclass
class WorkerRecord:
    worker_id: str
    recipe_id: str
    run_id: str
    lane_key: str
    status: str
    dedupe_key: str
    title: str
    goal_prompt: str
    claim_scope: list[str]
    runner_hint: str
    model_hint: str
    created_at: str
    updated_at: str
    source: str = "native_orchestration"
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "worker_id": self.worker_id,
            "recipe_id": self.recipe_id,
            "run_id": self.run_id,
            "lane_key": self.lane_key,
            "status": self.status,
            "dedupe_key": self.dedupe_key,
            "title": self.title,
            "goal_prompt": self.goal_prompt,
            "claim_scope": list(self.claim_scope),
            "runner_hint": self.runner_hint,
            "model_hint": self.model_hint,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "source": self.source,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> WorkerRecord:
        return cls(
            worker_id=str(payload.get("worker_id") or "").strip(),
            recipe_id=str(payload.get("recipe_id") or "").strip(),
            run_id=str(payload.get("run_id") or "").strip(),
            lane_key=str(payload.get("lane_key") or "").strip(),
            status=str(payload.get("status") or "").strip(),
            dedupe_key=str(payload.get("dedupe_key") or "").strip(),
            title=str(payload.get("title") or "").strip(),
            goal_prompt=str(payload.get("goal_prompt") or "").strip(),
            claim_scope=_coerce_str_list(payload.get("claim_scope")),
            runner_hint=str(payload.get("runner_hint") or "").strip(),
            model_hint=str(payload.get("model_hint") or "").strip(),
            created_at=str(payload.get("created_at") or "").strip(),
            updated_at=str(payload.get("updated_at") or "").strip(),
            source=str(payload.get("source") or "native_orchestration").strip(),
            reason=str(payload.get("reason") or "").strip(),
        )


@dataclass
class OrchestrationRun:
    run_id: str
    recipe_id: str
    status: str
    workers: list[WorkerRecord]
    blocked_lanes: list[dict[str, Any]]
    merge_ready_lanes: list[dict[str, Any]]
    recommended_actions: list[str]
    created_at: str
    updated_at: str
    dry_run: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "recipe_id": self.recipe_id,
            "status": self.status,
            "workers": [worker.to_dict() for worker in self.workers],
            "blocked_lanes": list(self.blocked_lanes),
            "merge_ready_lanes": list(self.merge_ready_lanes),
            "recommended_actions": list(self.recommended_actions),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "dry_run": bool(self.dry_run),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> OrchestrationRun:
        workers = [WorkerRecord.from_dict(item) for item in payload.get("workers") or [] if isinstance(item, dict)]
        return cls(
            run_id=str(payload.get("run_id") or "").strip(),
            recipe_id=str(payload.get("recipe_id") or "").strip(),
            status=str(payload.get("status") or "unknown").strip(),
            workers=workers,
            blocked_lanes=list(payload.get("blocked_lanes") or []),
            merge_ready_lanes=list(payload.get("merge_ready_lanes") or []),
            recommended_actions=_coerce_str_list(payload.get("recommended_actions")),
            created_at=str(payload.get("created_at") or "").strip(),
            updated_at=str(payload.get("updated_at") or "").strip(),
            dry_run=bool(payload.get("dry_run")),
        )


@dataclass
class OrchestrationState:
    version: int = STATE_VERSION
    runs: list[OrchestrationRun] = field(default_factory=list)
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": int(self.version),
            "updated_at": self.updated_at,
            "runs": [run.to_dict() for run in self.runs],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> OrchestrationState:
        runs = [OrchestrationRun.from_dict(item) for item in payload.get("runs") or [] if isinstance(item, dict)]
        return cls(
            version=int(payload.get("version") or STATE_VERSION),
            updated_at=str(payload.get("updated_at") or ""),
            runs=runs,
        )


def built_in_recipes() -> dict[str, OrchestrationRecipe]:
    council = OrchestrationRecipe(
        id=DEFAULT_RECIPE_ID,
        name="Senior council integration pipeline",
        trigger="heartbeat:FREQ=MINUTELY;INTERVAL=5 or manual",
        coordinator_goal=(
            "Inspect repo, workboard, evolve-loop, and merge-readiness state once; plan only the smallest needed "
            "worker lanes; reuse or dedupe existing active workers before dispatching anything new."
        ),
        max_active_workers=3,
        dedupe_key="native-orchestration:senior-council",
        claim_scope=["thomas/forge/anvil", "thomas/cli/commands/evolve.py", ".thomas/evolve/orchestration"],
        runner_hint="native-orchestrator",
        model_hint="codex:gpt",
        stop_conditions=[
            "matching active worker exists",
            "worktree has broad dirty conflicts",
            "merge-ready lane requires human review",
            "verification evidence is missing",
        ],
        lanes=[
            OrchestrationLane(
                key="repo-council",
                title="Repo and workboard council scan",
                goal_prompt=(
                    "Inspect git status, active workboard claims, evolve-loop state, and recent sessions; report "
                    "blocked lanes, merge-ready lanes, and the smallest next action."
                ),
                claim_scope=["plans/thomas/WORKBOARD.md", ".thomas/evolve"],
                dedupe_key="native-orchestration:senior-council:repo-council",
                runner_hint="evolve.plan",
                model_hint="codex:gpt",
                stop_conditions=["workboard unavailable", "repo status unavailable"],
            ),
            OrchestrationLane(
                key="upgrade-worker",
                title="Focused upgrade worker",
                goal_prompt=(
                    "Implement exactly one high-leverage Thomas improvement selected by the council scan, claim a "
                    "narrow scope, run focused verification, and leave unrelated dirty files untouched."
                ),
                claim_scope=["thomas", "tests"],
                dedupe_key="native-orchestration:senior-council:upgrade-worker",
                runner_hint="evolve.dispatch",
                model_hint="codex:gpt",
                stop_conditions=["matching upgrade worker active", "max active workers reached"],
            ),
            OrchestrationLane(
                key="integration-review",
                title="Integration and merge decision",
                goal_prompt=(
                    "Review merge-ready evolve sessions and worker outputs, require verification evidence, then "
                    "recommend promote, hold, or reject without pushing public origin/main."
                ),
                claim_scope=[".thomas/evolve", "CHANGELOG.md", "tests"],
                dedupe_key="native-orchestration:senior-council:integration-review",
                runner_hint="evolve.loop-status",
                model_hint="codex:gpt",
                stop_conditions=["no merge-ready lane", "critical risk requires explicit approval"],
            ),
        ],
    )
    return {council.id: council}


def list_recipes() -> list[OrchestrationRecipe]:
    return list(built_in_recipes().values())


def get_recipe(recipe_id: str = DEFAULT_RECIPE_ID) -> OrchestrationRecipe:
    recipes = built_in_recipes()
    key = str(recipe_id or DEFAULT_RECIPE_ID).strip()
    try:
        return recipes[key]
    except KeyError as exc:
        raise RuntimeError(f"unknown orchestration recipe: {key}") from exc


def load_state(project_root: Path) -> OrchestrationState:
    path = state_path(project_root)
    if not path.exists():
        return OrchestrationState()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return OrchestrationState()
    return OrchestrationState.from_dict(payload if isinstance(payload, dict) else {})


def save_state(project_root: Path, state: OrchestrationState) -> Path:
    state.updated_at = utc_now_iso()
    path = state_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def active_workers(state: OrchestrationState, *, recipe_id: str | None = None) -> list[WorkerRecord]:
    workers: list[WorkerRecord] = []
    for run in state.runs:
        for worker in run.workers:
            if recipe_id and worker.recipe_id != recipe_id:
                continue
            if worker.status in ACTIVE_WORKER_STATUSES:
                workers.append(worker)
    return workers


def _parse_workboard_fields(line: str) -> dict[str, str]:
    text = line.strip()
    if text.startswith("- "):
        text = text[2:].strip()
    fields: dict[str, str] = {}
    for part in text.split(";"):
        key, sep, value = part.partition("=")
        if sep:
            fields[key.strip()] = value.strip()
    return fields


def read_workboard_active(project_root: Path) -> list[dict[str, str]]:
    path = Path(project_root) / "plans" / "thomas" / "WORKBOARD.md"
    if not path.exists():
        return []
    rows: list[dict[str, str]] = []
    section = ""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        if line.startswith("## "):
            section = line[3:].strip()
            continue
        if section not in {"Agent Claims", "Active Tasks"} or not line.lstrip().startswith("- "):
            continue
        fields = _parse_workboard_fields(line)
        if fields:
            fields["section"] = section
            rows.append(fields)
    return rows


def _git_dirty_paths(project_root: Path) -> list[str]:
    try:
        proc = subprocess.run(
            ["git", "-C", str(project_root), "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=20,
            encoding="utf-8",
            errors="replace",
        )
    except Exception:  # noqa: BLE001 - status is advisory for planning
        return []
    paths: list[str] = []
    for raw in (proc.stdout or "").splitlines():
        if not raw.strip():
            continue
        path = raw[3:].strip()
        if " -> " in path:
            path = path.rsplit(" -> ", 1)[-1].strip()
        if path:
            paths.append(path.replace("\\", "/"))
    return paths


def _scope_contains(scope: list[str], path: str) -> bool:
    normalized = path.replace("\\", "/")
    for raw in scope:
        item = raw.replace("\\", "/").strip().rstrip("/")
        if not item:
            continue
        if item == "." or normalized == item or normalized.startswith(item + "/"):
            return True
    return False


def broad_dirty_conflicts(recipe: OrchestrationRecipe, dirty_paths: list[str]) -> list[str]:
    allowed = list(recipe.claim_scope)
    for lane in recipe.lanes:
        allowed.extend(lane.claim_scope)
    return [path for path in dirty_paths if not _scope_contains(allowed, path)]


def _matching_workboard_rows(rows: list[dict[str, str]], dedupe_key: str) -> list[dict[str, str]]:
    matches: list[dict[str, str]] = []
    needle = dedupe_key.lower()
    for row in rows:
        haystack = " ".join(str(value) for value in row.values()).lower()
        if needle and needle in haystack:
            matches.append(row)
    return matches


def _read_evolve_loop_state(project_root: Path) -> dict[str, Any]:
    path = Path(project_root) / ".thomas" / "evolve" / "loop" / "state.json"
    if not path.exists():
        return {"status": "idle"}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"status": "unknown"}
    return payload if isinstance(payload, dict) else {"status": "unknown"}


def _parse_utc(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _coerce_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _local_hostname() -> str:
    return socket.gethostname().split(".")[0].lower()


def _is_local_claim_host(hostname: str) -> bool:
    host = str(hostname or "").strip().split(".")[0].lower()
    return not host or host == _local_hostname()


def _pid_alive(pid: int | None, *, hostname: str = "") -> bool | None:
    if pid is None or not _is_local_claim_host(hostname):
        return None
    if os.name == "nt":
        process_query_limited_information = 0x1000
        still_active = 259
        handle = ctypes.windll.kernel32.OpenProcess(process_query_limited_information, False, int(pid))
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if not ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return None
            return int(exit_code.value) == still_active
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _read_active_folder_claims(project_root: Path, *, now: datetime | None = None) -> list[dict[str, Any]]:
    path = Path(project_root) / "runtime" / "coordination" / "active_folders.json"
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    raw_claims = payload.get("claims") if isinstance(payload, dict) else []
    if not isinstance(raw_claims, list):
        return []
    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    claims: list[dict[str, Any]] = []
    for item in raw_claims:
        if not isinstance(item, dict):
            continue
        expires_at = str(item.get("expires_at") or "").strip()
        expires = _parse_utc(expires_at)
        paths = _coerce_str_list(item.get("paths"))
        pid = _coerce_int(item.get("pid"))
        hostname = str(item.get("hostname") or "").strip()
        owner_alive = _pid_alive(pid, hostname=hostname)
        stale = bool(expires is not None and expires <= now_utc)
        dead_owner = owner_alive is False
        claims.append(
            {
                "agent_id": str(item.get("agent_id") or "").strip(),
                "claim_id": str(item.get("claim_id") or "").strip(),
                "paths": paths,
                "note": str(item.get("note") or "").strip(),
                "pid": pid,
                "hostname": hostname,
                "session_id": str(item.get("session_id") or "").strip(),
                "started_at": str(item.get("started_at") or "").strip(),
                "last_heartbeat_at": str(item.get("last_heartbeat_at") or "").strip(),
                "expires_at": expires_at,
                "owner_alive": owner_alive,
                "stale": stale,
                "dead_owner": dead_owner,
                "needs_cleanup": bool(stale or dead_owner),
            }
        )
    claims.sort(
        key=lambda claim: (
            bool(claim.get("needs_cleanup")),
            bool(claim.get("dead_owner")),
            str(claim.get("agent_id") or ""),
        ),
        reverse=True,
    )
    return claims


def _merge_ready_sessions(project_root: Path, *, limit: int = 12) -> list[dict[str, Any]]:
    sessions_root = Path(project_root) / ".thomas" / "evolve" / "sessions"
    if not sessions_root.exists():
        return []
    rows: list[dict[str, Any]] = []
    for path in sessions_root.glob("*/session.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(payload, dict):
            continue
        status = str(payload.get("status") or "").strip()
        if payload.get("promotable") or status == "ready":
            rows.append(
                {
                    "session_id": str(payload.get("session_id") or path.parent.name),
                    "status": status,
                    "promotable": bool(payload.get("promotable")),
                    "changed_count": int((payload.get("delta") or {}).get("changed_count") or 0)
                    if isinstance(payload.get("delta"), dict)
                    else 0,
                    "diff_path": str(payload.get("diff_path") or ""),
                }
            )
    rows.sort(key=lambda item: str(item.get("session_id") or ""), reverse=True)
    return rows[:limit]


def collect_repo_signals(project_root: Path, recipe: OrchestrationRecipe) -> dict[str, Any]:
    dirty_paths = _git_dirty_paths(project_root)
    workboard_rows = read_workboard_active(project_root)
    active_folder_claims = _read_active_folder_claims(project_root)
    return {
        "dirty_paths": dirty_paths,
        "broad_dirty_conflicts": broad_dirty_conflicts(recipe, dirty_paths),
        "workboard_active": workboard_rows,
        "active_folder_claims": active_folder_claims,
        "stale_active_folder_claims": [claim for claim in active_folder_claims if claim.get("stale")],
        "dead_owner_active_folder_claims": [claim for claim in active_folder_claims if claim.get("dead_owner")],
        "evolve_loop": _read_evolve_loop_state(project_root),
        "merge_ready_lanes": _merge_ready_sessions(project_root),
    }


def plan_orchestration_run(
    project_root: Path,
    *,
    recipe_id: str = DEFAULT_RECIPE_ID,
    state: OrchestrationState | None = None,
    signals: dict[str, Any] | None = None,
) -> OrchestrationRun:
    recipe = get_recipe(recipe_id)
    state = state or load_state(project_root)
    signals = signals or collect_repo_signals(project_root, recipe)
    existing_workers = active_workers(state, recipe_id=recipe.id)
    workboard_rows = list(signals.get("workboard_active") or [])
    dirty_conflicts = [str(path) for path in (signals.get("broad_dirty_conflicts") or [])]
    merge_ready = list(signals.get("merge_ready_lanes") or [])
    stale_folder_claims = list(signals.get("stale_active_folder_claims") or [])
    dead_owner_claims = list(signals.get("dead_owner_active_folder_claims") or [])
    now = utc_now_iso()
    run_id = f"orch-{uuid.uuid4().hex[:10]}"
    workers: list[WorkerRecord] = []
    blocked: list[dict[str, Any]] = []
    recommendations: list[str] = []
    active_count = len(existing_workers)

    if dirty_conflicts:
        recommendations.append("hold live dispatch until unrelated dirty paths are resolved or explicitly coordinated")
    if stale_folder_claims:
        recommendations.append("clear stale active-folder leases before dispatching more workers")
    if dead_owner_claims:
        recommendations.append("clear dead-owner active-folder leases or route a coordinator handoff before dispatch")
    if merge_ready:
        recommendations.append("review merge-ready evolve sessions before spawning more upgrade workers")

    for lane in recipe.lanes:
        duplicate = next((worker for worker in existing_workers if worker.dedupe_key == lane.dedupe_key), None)
        matching_workboard = _matching_workboard_rows(workboard_rows, lane.dedupe_key)
        if duplicate is not None:
            workers.append(
                WorkerRecord(
                    worker_id=duplicate.worker_id,
                    recipe_id=recipe.id,
                    run_id=run_id,
                    lane_key=lane.key,
                    status="deduped",
                    dedupe_key=lane.dedupe_key,
                    title=lane.title,
                    goal_prompt=lane.goal_prompt,
                    claim_scope=list(lane.claim_scope),
                    runner_hint=lane.runner_hint,
                    model_hint=lane.model_hint,
                    created_at=now,
                    updated_at=now,
                    source="native_orchestration",
                    reason=f"active native worker already owns {duplicate.worker_id}",
                )
            )
            recommendations.append(f"reuse active worker {duplicate.worker_id} for lane {lane.key}")
            continue
        if matching_workboard:
            workers.append(
                WorkerRecord(
                    worker_id=f"workboard:{matching_workboard[0].get('agent') or matching_workboard[0].get('task_id')}",
                    recipe_id=recipe.id,
                    run_id=run_id,
                    lane_key=lane.key,
                    status="deduped",
                    dedupe_key=lane.dedupe_key,
                    title=lane.title,
                    goal_prompt=lane.goal_prompt,
                    claim_scope=list(lane.claim_scope),
                    runner_hint=lane.runner_hint,
                    model_hint=lane.model_hint,
                    created_at=now,
                    updated_at=now,
                    source="workboard",
                    reason="matching workboard lane is already active",
                )
            )
            recommendations.append(f"reuse active workboard lane for {lane.key}")
            continue
        if active_count >= recipe.max_active_workers:
            blocked.append(
                {
                    "lane_key": lane.key,
                    "title": lane.title,
                    "reason": f"max active workers reached ({recipe.max_active_workers})",
                    "dedupe_key": lane.dedupe_key,
                }
            )
            continue
        if dirty_conflicts and lane.key != "repo-council":
            blocked.append(
                {
                    "lane_key": lane.key,
                    "title": lane.title,
                    "reason": "broad dirty worktree conflict",
                    "dirty_paths": dirty_conflicts[:20],
                    "dedupe_key": lane.dedupe_key,
                }
            )
            continue
        active_count += 1
        workers.append(
            WorkerRecord(
                worker_id=f"{lane.key}-{uuid.uuid4().hex[:8]}",
                recipe_id=recipe.id,
                run_id=run_id,
                lane_key=lane.key,
                status="planned",
                dedupe_key=lane.dedupe_key,
                title=lane.title,
                goal_prompt=lane.goal_prompt,
                claim_scope=list(lane.claim_scope),
                runner_hint=lane.runner_hint,
                model_hint=lane.model_hint,
                created_at=now,
                updated_at=now,
            )
        )

    if not recommendations:
        recommendations.append("dispatch planned lanes through existing evolve/dispatch machinery")
    status = "blocked" if blocked and not workers else "planned"
    return OrchestrationRun(
        run_id=run_id,
        recipe_id=recipe.id,
        status=status,
        workers=workers,
        blocked_lanes=blocked,
        merge_ready_lanes=merge_ready,
        recommended_actions=recommendations,
        created_at=now,
        updated_at=now,
        dry_run=True,
    )


def start_orchestration_run(
    project_root: Path,
    *,
    recipe_id: str = DEFAULT_RECIPE_ID,
    dry_run: bool = False,
) -> OrchestrationRun:
    state = load_state(project_root)
    planned = plan_orchestration_run(project_root, recipe_id=recipe_id, state=state)
    planned.dry_run = bool(dry_run)
    if dry_run:
        return planned
    planned.status = "running" if any(worker.status == "planned" for worker in planned.workers) else planned.status
    state.runs.insert(0, planned)
    state.runs = state.runs[:80]
    save_state(project_root, state)
    return planned


def status_payload(project_root: Path) -> dict[str, Any]:
    state = load_state(project_root)
    recipes = [recipe.to_dict() for recipe in list_recipes()]
    workers = [worker.to_dict() for worker in active_workers(state)]
    runs = [run.to_dict() for run in state.runs[:20]]
    active_folder_claims = _read_active_folder_claims(project_root)
    return {
        "ok": True,
        "state_path": str(state_path(project_root)),
        "recipes": recipes,
        "active_workers": workers,
        "active_worker_count": len(workers),
        "active_folder_claims": active_folder_claims,
        "active_folder_claim_count": len(active_folder_claims),
        "stale_active_folder_claim_count": sum(1 for claim in active_folder_claims if claim.get("stale")),
        "dead_owner_active_folder_claim_count": sum(1 for claim in active_folder_claims if claim.get("dead_owner")),
        "cleanup_needed_active_folder_claim_count": sum(
            1 for claim in active_folder_claims if claim.get("needs_cleanup")
        ),
        "runs": runs,
        "run_count": len(state.runs),
        "updated_at": state.updated_at,
    }
