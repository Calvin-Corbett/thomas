"""Atomic durable store for Work apps, job definitions, and scoped metadata."""

from __future__ import annotations

import copy
import json
import os
import secrets
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

from .connectors import installed_connector_ids
from .migration import SCHEMA_VERSION, migrate_legacy_work_state
from .store_automations import WorkAutomationMixin, validate_automation_definitions
from .store_common import _JOB_STATUSES, _SKILL_STATUSES, _clean_bool, _clean_object_list, _clean_settings
from .store_connectors import WorkConnectorBindingMixin
from .store_jobs import WorkJobMixin
from .store_skills import WorkSkillMixin
from .store_workflows import (
    WorkWorkflowMixin,
    normalize_workflow_memory,
    validate_workflow_automation_links,
    validate_workflow_memory,
)
from .validation import (
    WorkConflictError,
    WorkCorruptStateError,
    WorkNotFoundError,
    WorkValidationError,
    clean_artifact_reference,
    clean_credential_ref,
    clean_json_object,
    clean_string_list,
    clean_text,
    new_id,
    require_safe_id,
    utc_now_iso,
)

_T = TypeVar("_T")
_APP_STATUSES = {"onboarding", "active", "paused", "archived"}
_ACCOUNT_STATUSES = {"planned", "active", "needs_reconnect", "archived"}
_ONBOARDING_STATES = {"collecting", "ready", "blocked"}
_ONBOARDING_PHASES = ("goal_discovery", "workflow_mapping", "workflow_configuration", "ready")
_PROMOTION_STATES = {"job_private", "requested", "approved", "rejected"}


class WorkStore(WorkJobMixin, WorkWorkflowMixin, WorkConnectorBindingMixin, WorkSkillMixin, WorkAutomationMixin):
    """Single-process Work metadata store with fail-closed reads and atomic writes."""

    def __init__(
        self,
        root_path: str | Path,
        *,
        runtime_apps_root: str | Path | None = None,
        user_work_apps_path: str | Path | None = None,
        global_skills_root: str | Path | None = None,
    ) -> None:
        self.root_path = Path(root_path).expanduser().resolve()
        self.state_path = self.root_path / ".thomas" / "work" / "state.json"
        self._runtime_apps_root = Path(runtime_apps_root).expanduser().resolve() if runtime_apps_root else None
        self._user_work_apps_path = Path(user_work_apps_path).expanduser().resolve() if user_work_apps_path else None
        self.global_skills_root = (
            Path(global_skills_root).expanduser().resolve()
            if global_skills_root
            else self.root_path / ".thomas" / "skills"
        )
        self._lock = threading.RLock()
        self._state = self._load_or_initialize()

    @classmethod
    def from_config(cls, config: Any) -> WorkStore:
        root = Path(config.memory.root_path).expanduser().resolve()
        return cls(
            root,
            runtime_apps_root=root / ".thomas" / "workforce" / "apps",
            user_work_apps_path=Path.home() / ".thomas" / "freedom_transit" / "work_apps.json",
            global_skills_root=Path.home() / ".thomas" / "skills",
        )

    def _load_or_initialize(self) -> dict[str, Any]:
        if not self.state_path.exists():
            state = migrate_legacy_work_state(
                runtime_apps_root=self._runtime_apps_root,
                user_work_apps_path=self._user_work_apps_path,
            )
            self._validate_state(state)
            self._persist(state)
            return state
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WorkCorruptStateError("durable Work state could not be read safely") from exc
        changed = False
        if "global_skills" not in state:
            state["global_skills"] = {}
            changed = True
        for app in state.get("apps", {}).values() if isinstance(state.get("apps"), dict) else ():
            onboarding = app.get("onboarding") if isinstance(app, dict) else None
            if isinstance(onboarding, dict) and "phase" not in onboarding:
                onboarding["phase"] = "ready" if onboarding.get("state") == "ready" else "goal_discovery"
                changed = True
            for job in app.get("jobs", {}).values() if isinstance(app, dict) else ():
                if isinstance(job, dict) and "activity" not in job:
                    job["activity"] = []
                    changed = True
                expected_scope = f"work/{app.get('id', '')}/{job.get('id', '')}" if isinstance(job, dict) else ""
                if isinstance(job, dict) and "memory" not in job:
                    job["memory"] = {
                        "scope": expected_scope,
                        "summary": "",
                        "workflows": [],
                        "metadata": {},
                    }
                    changed = True
                elif isinstance(job, dict) and isinstance(job.get("memory"), dict):
                    if job["memory"].get("scope") != expected_scope:
                        job["memory"]["scope"] = expected_scope
                        changed = True
                if (
                    isinstance(job, dict)
                    and isinstance(job.get("memory"), dict)
                    and normalize_workflow_memory(job["memory"])
                ):
                    changed = True
        self._validate_state(state)
        if changed:
            self._persist(state)
        return state

    @staticmethod
    def _validate_state(state: Any) -> None:
        if not isinstance(state, dict):
            raise WorkCorruptStateError("durable Work state must be an object")
        if state.get("schema_version") != SCHEMA_VERSION:
            raise WorkCorruptStateError("unsupported durable Work state schema")
        if (
            not isinstance(state.get("apps"), dict)
            or not isinstance(state.get("connector_accounts"), dict)
            or not isinstance(state.get("global_skills"), dict)
        ):
            raise WorkCorruptStateError("durable Work state is missing required collections")
        migrations = state.get("migrations")
        if not isinstance(migrations, dict) or not isinstance(migrations.get("sources"), list):
            raise WorkCorruptStateError("durable Work migration receipts are invalid")
        if any(not isinstance(account, dict) for account in state["connector_accounts"].values()):
            raise WorkCorruptStateError("durable Work connector accounts are invalid")
        for app in state["apps"].values():
            if not isinstance(app, dict):
                raise WorkCorruptStateError("durable Work app entries are invalid")
            if not isinstance(app.get("onboarding"), dict) or not isinstance(app.get("dashboard"), dict):
                raise WorkCorruptStateError("durable Work app metadata is invalid")
            if app["onboarding"].get("phase") not in _ONBOARDING_PHASES:
                raise WorkCorruptStateError("durable Work onboarding phase is invalid")
            jobs = app.get("jobs")
            if not isinstance(jobs, dict):
                raise WorkCorruptStateError("durable Work job collection is invalid")
            for job_id, job in jobs.items():
                if not isinstance(job, dict):
                    raise WorkCorruptStateError("durable Work job entries are invalid")
                if not isinstance(job.get("history"), dict) or not isinstance(job.get("dashboard"), dict):
                    raise WorkCorruptStateError("durable Work job metadata is invalid")
                memory = job.get("memory")
                if not isinstance(memory, dict) or not isinstance(memory.get("workflows"), list):
                    raise WorkCorruptStateError("durable Work job memory is invalid")
                if memory.get("scope") != f"work/{app.get('id', '')}/{job_id}":
                    raise WorkCorruptStateError("durable Work job memory scope is invalid")
                validate_workflow_memory(memory)
                for key in ("connector_bindings", "private_skills", "automations", "activity"):
                    if not isinstance(job.get(key), list):
                        raise WorkCorruptStateError(f"durable Work job {key} are invalid")
                validate_automation_definitions(job)
                validate_workflow_automation_links(job)
        if any(not isinstance(skill, dict) for skill in state["global_skills"].values()):
            raise WorkCorruptStateError("durable Work global skills are invalid")

    def _persist(self, state: dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.state_path.with_name(f".{self.state_path.name}.{secrets.token_hex(6)}.tmp")
        try:
            with temp_path.open("x", encoding="utf-8", newline="\n") as handle:
                json.dump(state, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.state_path)
        except (OSError, TypeError, ValueError):
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def _mutate(self, operation: Callable[[dict[str, Any]], _T]) -> _T:
        with self._lock:
            candidate = copy.deepcopy(self._state)
            result = operation(candidate)
            candidate["updated_at"] = utc_now_iso()
            self._validate_state(candidate)
            self._persist(candidate)
            self._state = candidate
            return copy.deepcopy(result)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._state)

    @staticmethod
    def _app(state: dict[str, Any], app_id: str) -> dict[str, Any]:
        safe_id = require_safe_id(app_id, field="app_id")
        app = state["apps"].get(safe_id)
        if not isinstance(app, dict):
            raise WorkNotFoundError("work app not found")
        return app

    @classmethod
    def _job(cls, state: dict[str, Any], app_id: str, job_id: str) -> dict[str, Any]:
        app = cls._app(state, app_id)
        safe_id = require_safe_id(job_id, field="job_id")
        job = app.get("jobs", {}).get(safe_id)
        if not isinstance(job, dict):
            raise WorkNotFoundError("work job not found")
        return job

    @staticmethod
    def _append_activity(
        job: dict[str, Any],
        *,
        kind: str,
        state: str,
        summary: str,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        row = {
            "id": new_id("activity"),
            "type": kind,
            "state": state,
            "summary": summary,
            "details": dict(details or {}),
            "created_at": utc_now_iso(),
        }
        job["activity"].append(row)
        return row

    def list_apps(self, *, include_archived: bool = False) -> list[dict[str, Any]]:
        with self._lock:
            rows = [copy.deepcopy(row) for row in self._state["apps"].values() if isinstance(row, dict)]
        if not include_archived:
            rows = [row for row in rows if row.get("status") != "archived"]
        return sorted(rows, key=lambda row: (str(row.get("name") or "").lower(), str(row.get("id") or "")))

    def get_app(self, app_id: str) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._app(self._state, app_id))

    def create_app(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = clean_text(payload.get("name"), field="name", required=True, max_length=160)
        app_id = require_safe_id(payload.get("id"), field="id") if payload.get("id") else new_id("app")
        goal = clean_text(payload.get("goal"), field="goal")
        now = utc_now_iso()

        def operation(state: dict[str, Any]) -> dict[str, Any]:
            if app_id in state["apps"]:
                raise WorkConflictError("work app id already exists")
            app = {
                "id": app_id,
                "name": name,
                "goal": goal,
                "status": "onboarding" if not goal else "active",
                "created_at": now,
                "updated_at": now,
                "onboarding": {
                    "state": "collecting" if not goal else "ready",
                    "phase": "goal_discovery" if not goal else "ready",
                    "messages": [],
                    "fields": {},
                    "next_prompt": "",
                    "updated_at": now,
                },
                "dashboard": {"metrics": [], "sections": [], "artifacts": []},
                "memory": {"scope": f"work/{app_id}", "summary": "", "metadata": {}},
                "jobs": {},
                "metadata": clean_json_object(payload.get("metadata"), field="metadata"),
            }
            state["apps"][app_id] = app
            return app

        return self._mutate(operation)

    def update_app(self, app_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        def operation(state: dict[str, Any]) -> dict[str, Any]:
            app = self._app(state, app_id)
            if app.get("status") == "archived":
                raise WorkConflictError("archived work apps cannot be changed")
            if "name" in payload:
                app["name"] = clean_text(payload["name"], field="name", required=True, max_length=160)
            if "goal" in payload:
                app["goal"] = clean_text(payload["goal"], field="goal")
            if "status" in payload:
                status = clean_text(payload["status"], field="status").lower()
                if status not in _APP_STATUSES - {"archived"}:
                    raise WorkValidationError("status must be onboarding, active, or paused")
                app["status"] = status
            if "metadata" in payload:
                app["metadata"] = clean_json_object(payload["metadata"], field="metadata")
            app["updated_at"] = utc_now_iso()
            return app

        return self._mutate(operation)

    def archive_app(self, app_id: str) -> dict[str, Any]:
        def operation(state: dict[str, Any]) -> dict[str, Any]:
            app = self._app(state, app_id)
            app["status"] = "archived"
            app["updated_at"] = utc_now_iso()
            for job in app.get("jobs", {}).values():
                if isinstance(job, dict):
                    job["status"] = "archived"
                    job["updated_at"] = app["updated_at"]
            return app

        return self._mutate(operation)

    def append_onboarding_message(self, app_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        role = clean_text(payload.get("role"), field="role", required=True, max_length=20).lower()
        if role not in {"user", "thomas", "system"}:
            raise WorkValidationError("role must be user, thomas, or system")
        text = clean_text(payload.get("text"), field="text", required=True, max_length=12_000)

        def operation(state: dict[str, Any]) -> dict[str, Any]:
            app = self._app(state, app_id)
            if app.get("status") == "archived":
                raise WorkConflictError("archived work apps cannot be onboarded")
            message = {"id": new_id("message"), "role": role, "text": text, "created_at": utc_now_iso()}
            app["onboarding"]["messages"].append(message)
            app["onboarding"]["messages"] = app["onboarding"]["messages"][-200:]
            app["onboarding"]["updated_at"] = message["created_at"]
            app["updated_at"] = message["created_at"]
            return message

        return self._mutate(operation)

    def update_onboarding(self, app_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        def operation(state: dict[str, Any]) -> dict[str, Any]:
            app = self._app(state, app_id)
            onboarding = app["onboarding"]
            incoming_fields = clean_json_object(payload["fields"], field="fields") if "fields" in payload else {}
            effective_fields = {**onboarding["fields"], **incoming_fields}
            if "phase" in payload:
                phase = clean_text(payload["phase"], field="phase", required=True).lower()
                if phase not in _ONBOARDING_PHASES:
                    raise WorkValidationError(
                        "onboarding phase must be goal_discovery, workflow_mapping, workflow_configuration, or ready"
                    )
                current = str(onboarding.get("phase") or "goal_discovery")
                if _ONBOARDING_PHASES.index(phase) > _ONBOARDING_PHASES.index(current) + 1:
                    raise WorkConflictError(
                        "Work onboarding must define the goal before mapping and configuring workflows"
                    )
                confirmed_goal = str(effective_fields.get("confirmed_goal") or "").strip()
                if phase != "goal_discovery" and len(confirmed_goal) < 12:
                    raise WorkConflictError(
                        "Work onboarding needs an explicitly confirmed goal before workflow mapping"
                    )
                if phase in {"workflow_configuration", "ready"}:
                    workflow_count = effective_fields.get("workflow_count")
                    if (
                        isinstance(workflow_count, bool)
                        or not isinstance(workflow_count, int)
                        or workflow_count < 3
                        or workflow_count > 6
                        or not str(effective_fields.get("selected_workflow") or "").strip()
                    ):
                        raise WorkConflictError(
                            "Work onboarding needs a workflow map and explicit workflow selection before configuration"
                        )
                onboarding["phase"] = phase
            if "state" in payload:
                status = clean_text(payload["state"], field="state").lower()
                if status not in _ONBOARDING_STATES:
                    raise WorkValidationError("onboarding state must be collecting, ready, or blocked")
                if status == "ready" and onboarding.get("state") != "ready":
                    if str(onboarding.get("phase") or "goal_discovery") not in {
                        "workflow_configuration",
                        "ready",
                    }:
                        raise WorkConflictError("Work onboarding must map workflows and configure one before launch")
                    if effective_fields.get("selected_workflow_configured") is not True:
                        raise WorkConflictError(
                            "Work onboarding needs an answered configuration question for the selected workflow"
                        )
                    messages = onboarding.get("messages") or []
                    user_turns = sum(
                        1 for message in messages if isinstance(message, dict) and message.get("role") == "user"
                    )
                    thomas_turns = sum(
                        1 for message in messages if isinstance(message, dict) and message.get("role") == "thomas"
                    )
                    if user_turns < 4 or thomas_turns < 4:
                        raise WorkConflictError(
                            "Work onboarding needs four user answers and four Thomas follow-ups before launch"
                        )
                    selection_turn = effective_fields.get("selected_workflow_user_turn")
                    if (
                        isinstance(selection_turn, bool)
                        or not isinstance(selection_turn, int)
                        or selection_turn < 1
                        or user_turns <= selection_turn
                    ):
                        raise WorkConflictError(
                            "Work onboarding needs an answer after the selected workflow configuration begins"
                        )
                onboarding["state"] = status
                if status == "ready" and app.get("status") == "onboarding":
                    app["status"] = "active"
                if status == "ready":
                    onboarding["phase"] = "ready"
            if "fields" in payload:
                onboarding["fields"] = effective_fields
            if "next_prompt" in payload:
                onboarding["next_prompt"] = clean_text(payload["next_prompt"], field="next_prompt")
            onboarding["updated_at"] = utc_now_iso()
            app["updated_at"] = onboarding["updated_at"]
            return onboarding

        return self._mutate(operation)

    def update_app_dashboard(self, app_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        def operation(state: dict[str, Any]) -> dict[str, Any]:
            app = self._app(state, app_id)
            dashboard = app["dashboard"]
            if "metrics" in payload:
                dashboard["metrics"] = _clean_object_list(payload["metrics"], field="metrics")
            if "sections" in payload:
                dashboard["sections"] = _clean_object_list(payload["sections"], field="sections")
            app["updated_at"] = utc_now_iso()
            return dashboard

        return self._mutate(operation)

    def add_app_artifact(self, app_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        title = clean_text(payload.get("title"), field="title", required=True, max_length=240)
        kind = require_safe_id(payload.get("kind") or "artifact", field="kind")
        reference = clean_artifact_reference(payload.get("reference"))

        def operation(state: dict[str, Any]) -> dict[str, Any]:
            app = self._app(state, app_id)
            artifact = {
                "id": new_id("artifact"),
                "title": title,
                "kind": kind,
                "reference": reference,
                "metadata": clean_json_object(payload.get("metadata"), field="metadata"),
                "created_at": utc_now_iso(),
            }
            app["dashboard"]["artifacts"].append(artifact)
            app["updated_at"] = artifact["created_at"]
            return artifact

        return self._mutate(operation)

    def list_accounts(self, *, provider: str = "", include_archived: bool = False) -> list[dict[str, Any]]:
        normalized_provider = require_safe_id(provider, field="provider") if provider else ""
        with self._lock:
            rows = [copy.deepcopy(row) for row in self._state["connector_accounts"].values() if isinstance(row, dict)]
        if normalized_provider:
            rows = [row for row in rows if row.get("provider") == normalized_provider]
        if not include_archived:
            rows = [row for row in rows if row.get("status") != "archived"]
        return sorted(rows, key=lambda row: (str(row.get("provider")), str(row.get("label")).lower()))

    def create_account(self, payload: dict[str, Any]) -> dict[str, Any]:
        provider = require_safe_id(payload.get("provider"), field="provider")
        if provider not in installed_connector_ids():
            raise WorkValidationError("provider is not an installed Work connector")
        account_id = require_safe_id(payload.get("id"), field="id") if payload.get("id") else new_id("account")
        label = clean_text(payload.get("label"), field="label", required=True, max_length=160)
        identity = clean_text(payload.get("identity"), field="identity", required=True, max_length=240)
        credential_ref = clean_credential_ref(payload.get("credential_ref"))
        now = utc_now_iso()

        def operation(state: dict[str, Any]) -> dict[str, Any]:
            if account_id in state["connector_accounts"]:
                raise WorkConflictError("connector account id already exists")
            account = {
                "id": account_id,
                "provider": provider,
                "label": label,
                "identity": identity,
                "credential_ref": credential_ref,
                "status": "active" if credential_ref else "planned",
                "metadata": clean_json_object(payload.get("metadata"), field="metadata"),
                "created_at": now,
                "updated_at": now,
            }
            state["connector_accounts"][account_id] = account
            return account

        return self._mutate(operation)

    def update_account(self, account_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        safe_id = require_safe_id(account_id, field="account_id")

        def operation(state: dict[str, Any]) -> dict[str, Any]:
            account = state["connector_accounts"].get(safe_id)
            if not isinstance(account, dict):
                raise WorkNotFoundError("connector account not found")
            for field, limit in (("label", 160), ("identity", 240)):
                if field in payload:
                    account[field] = clean_text(payload[field], field=field, required=True, max_length=limit)
            if "credential_ref" in payload:
                account["credential_ref"] = clean_credential_ref(payload["credential_ref"])
            if "status" in payload:
                status = clean_text(payload["status"], field="status").lower()
                if status not in _ACCOUNT_STATUSES:
                    raise WorkValidationError("invalid connector account status")
                account["status"] = status
            if "metadata" in payload:
                account["metadata"] = clean_json_object(payload["metadata"], field="metadata")
            account["updated_at"] = utc_now_iso()
            return account

        return self._mutate(operation)
