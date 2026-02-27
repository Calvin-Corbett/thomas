from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import urllib.parse
import urllib.request
import uuid
from collections.abc import Mapping
from typing import Any

from .contracts import ConnectorCatalog, default_connector_catalog
from .job_store import AssetStudioJobStore
from .runtime_common import (
    COMPLETION_WEBHOOK_KEY,
    TERMINAL_STATES,
    _now_iso,
    _safe_int,
    _safe_string,
)
from .runtime_template_ops import AssetStudioRuntimeTemplateMixin


class AssetStudioRuntime(AssetStudioRuntimeTemplateMixin):
    def __init__(
        self,
        *,
        store: AssetStudioJobStore,
        catalog: ConnectorCatalog | None = None,
    ):
        self.store = store
        self.catalog = catalog or default_connector_catalog()
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._task_guard = asyncio.Lock()

    async def list_connectors(self, *, include_detection: bool = True) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for connector in self.catalog.list():
            payload = connector.to_dict()
            if include_detection:
                payload["detection"] = connector.detect()
            rows.append(payload)
        return rows

    async def detect_connector(self, connector_id: str) -> dict[str, Any]:
        connector = self.catalog.get(connector_id)
        if connector is None:
            raise KeyError(f"unknown connector '{connector_id}'")
        return connector.detect()

    async def preview_job(
        self,
        *,
        connector_id: str,
        action_id: str,
        payload: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        connector = self.catalog.get(connector_id)
        if connector is None:
            raise KeyError(f"unknown connector '{connector_id}'")
        action = connector.action_by_id(action_id)
        if action is None:
            raise ValueError(f"unknown action '{action_id}' for connector '{connector_id}'")

        body = dict(payload or {})
        detection = connector.detect()
        command: list[str] = []
        can_run = False
        error_text = ""
        try:
            command = connector.build_command(action.id, body)
            can_run = True
        except Exception as exc:
            error_text = str(exc)

        return {
            "connector_id": connector.id,
            "connector_label": connector.label,
            "action_id": action.id,
            "action_label": action.label,
            "can_run": bool(can_run),
            "error": error_text,
            "command": command,
            "payload_fields": list(action.payload_fields),
            "payload": body,
            "detection": detection,
        }

    async def create_job(
        self,
        *,
        connector_id: str,
        action_id: str,
        payload: Mapping[str, Any] | None = None,
        template_id: str = "",
    ) -> dict[str, Any]:
        connector = self.catalog.get(connector_id)
        if connector is None:
            raise KeyError(f"unknown connector '{connector_id}'")
        action = connector.action_by_id(action_id)
        if action is None:
            raise ValueError(f"unknown action '{action_id}' for connector '{connector_id}'")

        body = dict(payload or {})
        job_id = f"job_{uuid.uuid4().hex[:16]}"
        job = await self.store.create_job(
            job_id=job_id,
            connector_id=connector.id,
            action_id=action.id,
            payload=body,
            template_id=_safe_string(template_id),
        )
        await self.store.add_event(
            job_id=job_id,
            kind="queued",
            message=f"{connector.label}::{action.label} queued.",
            data={"connector_id": connector.id, "action_id": action.id},
        )
        async with self._task_guard:
            self._tasks[job_id] = asyncio.create_task(
                self._run_job(job_id=job_id, connector_id=connector.id, action_id=action.id, payload=body)
            )
        return job

    async def create_jobs_batch(
        self,
        rows: list[Mapping[str, Any]],
    ) -> dict[str, Any]:
        accepted: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        for idx, row in enumerate(rows):
            if not isinstance(row, Mapping):
                errors.append({"index": idx, "error": "row must be a JSON object"})
                continue
            connector_id = _safe_string(row.get("connector_id"))
            action_id = _safe_string(row.get("action_id"))
            payload = row.get("payload")
            if not connector_id:
                errors.append({"index": idx, "error": "missing connector_id"})
                continue
            if not action_id:
                errors.append({"index": idx, "error": "missing action_id"})
                continue
            if payload is None:
                payload = {}
            if not isinstance(payload, Mapping):
                errors.append({"index": idx, "error": "payload must be an object"})
                continue
            try:
                job = await self.create_job(
                    connector_id=connector_id,
                    action_id=action_id,
                    payload=dict(payload),
                )
                accepted.append({"index": idx, "job": job})
            except Exception as exc:
                errors.append({"index": idx, "error": f"{type(exc).__name__}: {exc}"})
        return {
            "submitted": len(accepted),
            "failed": len(errors),
            "jobs": accepted,
            "errors": errors,
        }

    async def _run_job(self, *, job_id: str, connector_id: str, action_id: str, payload: Mapping[str, Any]) -> None:
        connector = self.catalog.get(connector_id)
        if connector is None:
            await self.store.set_terminal(
                job_id,
                status="failed",
                error=f"connector '{connector_id}' is no longer available",
                artifact={},
            )
            await self._emit_completion_webhook(job_id=job_id, status="failed")
            return
        try:
            command = connector.build_command(action_id, payload)
            await self.store.set_running(job_id, command=command)
            await self.store.add_event(
                job_id=job_id,
                kind="running",
                message=f"Running: {' '.join(command)}",
                data={"command": command},
            )
            timeout_s = max(3, min(7200, _safe_int(payload.get("timeout_s"), 300)))
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            self._processes[job_id] = process
            stdout_task = asyncio.create_task(self._pump_stream(job_id, process.stdout, kind="stdout"))
            stderr_task = asyncio.create_task(self._pump_stream(job_id, process.stderr, kind="stderr"))
            try:
                exit_code = await asyncio.wait_for(process.wait(), timeout=timeout_s)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                await self.store.add_event(
                    job_id=job_id,
                    kind="error",
                    message=f"Job timed out after {timeout_s}s.",
                    data={"timeout_s": timeout_s},
                )
                await self.store.set_terminal(
                    job_id,
                    status="failed",
                    exit_code=124,
                    error=f"timed out after {timeout_s}s",
                    artifact={"command": command},
                )
                await self._emit_completion_webhook(job_id=job_id, status="failed")
                return
            finally:
                await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)

            status = "done" if int(exit_code) == 0 else "failed"
            await self.store.set_terminal(
                job_id,
                status=status,
                exit_code=int(exit_code),
                error="" if status == "done" else f"process exited with {exit_code}",
                artifact={"command": command},
            )
            await self.store.add_event(
                job_id=job_id,
                kind=status,
                message=f"Job completed with exit code {exit_code}.",
                data={"exit_code": int(exit_code), "command": command},
            )
            await self._emit_completion_webhook(job_id=job_id, status=status)
        except asyncio.CancelledError:
            await self.store.set_terminal(
                job_id,
                status="cancelled",
                exit_code=130,
                error="cancelled",
                artifact={},
            )
            await self.store.add_event(job_id=job_id, kind="cancelled", message="Job cancelled.", data={})
            await self._emit_completion_webhook(job_id=job_id, status="cancelled")
            raise
        except Exception as exc:
            await self.store.set_terminal(
                job_id,
                status="failed",
                exit_code=1,
                error=str(exc),
                artifact={},
            )
            await self.store.add_event(
                job_id=job_id,
                kind="error",
                message=f"Job failed: {exc}",
                data={},
            )
            await self._emit_completion_webhook(job_id=job_id, status="failed")
        finally:
            self._processes.pop(job_id, None)
            async with self._task_guard:
                self._tasks.pop(job_id, None)

    async def _pump_stream(
        self,
        job_id: str,
        stream: asyncio.StreamReader | None,
        *,
        kind: str,
    ) -> None:
        if stream is None:
            return
        while not stream.at_eof():
            try:
                line = await stream.readline()
            except (OSError, FileNotFoundError):
                break
            if not line:
                break
            text = line.decode("utf-8", errors="replace").rstrip()
            if not text:
                continue
            await self.store.add_event(job_id=job_id, kind=kind, message=text[:1000], data={})

    async def get_job(self, job_id: str) -> dict[str, Any] | None:
        return await self.store.get_job(job_id)

    async def list_jobs(self, *, limit: int = 100, status: str = "") -> list[dict[str, Any]]:
        return await self.store.list_jobs(limit=limit, status=status)

    async def list_events(self, job_id: str, *, after_seq: int = 0, limit: int = 200) -> list[dict[str, Any]]:
        return await self.store.list_events(job_id, after_seq=after_seq, limit=limit)

    async def wait_for_job(
        self,
        job_id: str,
        *,
        timeout_s: int = 30,
        poll_interval_s: float = 0.1,
    ) -> dict[str, Any] | None:
        timeout = max(1, min(600, _safe_int(timeout_s, 30)))
        try:
            poll = float(poll_interval_s)
        except (ValueError, TypeError):
            poll = 0.1
        poll = max(0.05, min(2.0, poll))
        loop = asyncio.get_running_loop()
        deadline = loop.time() + float(timeout)

        current = await self.get_job(job_id)
        while current is not None:
            status = _safe_string(current.get("status")).lower()
            if status in TERMINAL_STATES:
                return current
            if loop.time() >= deadline:
                return current
            await asyncio.sleep(poll)
            current = await self.get_job(job_id)
        return None

    @staticmethod
    def _public_webhook_config(config: Mapping[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(config, Mapping):
            return None
        return {
            "webhook_key": _safe_string(config.get("webhook_key")),
            "url": _safe_string(config.get("url")),
            "enabled": bool(config.get("enabled")),
            "timeout_s": max(1, min(30, _safe_int(config.get("timeout_s"), 5))),
            "has_secret": bool(_safe_string(config.get("secret"))),
            "created_at": _safe_string(config.get("created_at")),
            "updated_at": _safe_string(config.get("updated_at")),
        }

    @staticmethod
    def _public_template_webhook_config(config: Mapping[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(config, Mapping):
            return None
        return {
            "template_id": _safe_string(config.get("template_id")),
            "url": _safe_string(config.get("url")),
            "enabled": bool(config.get("enabled")),
            "timeout_s": max(1, min(30, _safe_int(config.get("timeout_s"), 5))),
            "has_secret": bool(_safe_string(config.get("secret"))),
            "created_at": _safe_string(config.get("created_at")),
            "updated_at": _safe_string(config.get("updated_at")),
        }

    @staticmethod
    def _validated_webhook_url(url: str) -> str:
        normalized = _safe_string(url)
        if not normalized:
            raise ValueError("url is required")
        parsed = urllib.parse.urlparse(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("url must be a valid http(s) endpoint")
        return normalized

    async def configure_completion_webhook(
        self,
        *,
        url: str,
        secret: str = "",
        enabled: bool = True,
        timeout_s: int = 5,
    ) -> dict[str, Any]:
        normalized_url = self._validated_webhook_url(url)
        config = await self.store.upsert_webhook_config(
            webhook_key=COMPLETION_WEBHOOK_KEY,
            url=normalized_url,
            secret=_safe_string(secret),
            enabled=bool(enabled),
            timeout_s=max(1, min(30, _safe_int(timeout_s, 5))),
        )
        return self._public_webhook_config(config) or {}

    async def get_completion_webhook(self) -> dict[str, Any] | None:
        config = await self.store.get_webhook_config(COMPLETION_WEBHOOK_KEY)
        return self._public_webhook_config(config)

    async def clear_completion_webhook(self) -> bool:
        return await self.store.delete_webhook_config(COMPLETION_WEBHOOK_KEY)

    async def configure_template_webhook(
        self,
        *,
        template_id: str,
        url: str,
        secret: str = "",
        enabled: bool = True,
        timeout_s: int = 5,
    ) -> dict[str, Any]:
        tid = _safe_string(template_id)
        template = await self.get_template(tid)
        if template is None:
            raise KeyError(f"unknown template '{tid}'")
        normalized_url = self._validated_webhook_url(url)
        config = await self.store.upsert_template_webhook_config(
            template_id=tid,
            url=normalized_url,
            secret=_safe_string(secret),
            enabled=bool(enabled),
            timeout_s=max(1, min(30, _safe_int(timeout_s, 5))),
        )
        return self._public_template_webhook_config(config) or {}

    async def get_template_webhook(self, template_id: str) -> dict[str, Any] | None:
        tid = _safe_string(template_id)
        template = await self.get_template(tid)
        if template is None:
            raise KeyError(f"unknown template '{tid}'")
        config = await self.store.get_template_webhook_config(tid)
        return self._public_template_webhook_config(config)

    async def clear_template_webhook(self, template_id: str) -> bool:
        tid = _safe_string(template_id)
        template = await self.get_template(tid)
        if template is None:
            raise KeyError(f"unknown template '{tid}'")
        return await self.store.delete_template_webhook_config(tid)

    @staticmethod
    def _post_completion_webhook(
        *,
        url: str,
        secret: str,
        timeout_s: int,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        raw = json.dumps(dict(payload), ensure_ascii=True).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "X-Thomas-Event": "asset_studio.job.completed",
        }
        key = _safe_string(secret)
        if key:
            digest = hmac.new(key.encode("utf-8"), raw, hashlib.sha256).hexdigest()
            headers["X-Thomas-Signature"] = f"sha256={digest}"

        request = urllib.request.Request(
            url=_safe_string(url),
            data=raw,
            headers=headers,
            method="POST",
        )
        timeout = max(1, min(30, _safe_int(timeout_s, 5)))
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = getattr(response, "status", None)
            if status is None:
                status = _safe_int(response.getcode(), 200)
            body = response.read(4096)
        return {
            "status_code": int(status),
            "response_size": len(body or b""),
        }

    async def _emit_completion_webhook(self, *, job_id: str, status: str) -> None:
        current = await self.get_job(job_id)
        if not isinstance(current, Mapping):
            return

        template_id = _safe_string(current.get("template_id"))
        config: Mapping[str, Any] | None = None
        if template_id:
            template_config = await self.store.get_template_webhook_config(template_id)
            if isinstance(template_config, Mapping):
                if not bool(template_config.get("enabled")):
                    return
                config = template_config

        if config is None:
            global_config = await self.store.get_webhook_config(COMPLETION_WEBHOOK_KEY)
            if not isinstance(global_config, Mapping) or not bool(global_config.get("enabled")):
                return
            config = global_config

        endpoint = _safe_string(config.get("url"))
        timeout_s = max(1, min(30, _safe_int(config.get("timeout_s"), 5)))
        payload = {
            "event": "asset_studio.job.completed",
            "sent_at": _now_iso(),
            "job": dict(current),
            "status": _safe_string(status),
        }
        max_attempts = 3
        backoff_s = 0.2
        last_error = ""
        for attempt in range(1, max_attempts + 1):
            try:
                result = await asyncio.to_thread(
                    self._post_completion_webhook,
                    url=endpoint,
                    secret=_safe_string(config.get("secret")),
                    timeout_s=timeout_s,
                    payload=payload,
                )
                status_code = int(result.get("status_code") or 0)
                if status_code < 200 or status_code >= 300:
                    raise RuntimeError(f"unexpected webhook status {status_code}")
                await self.store.add_event(
                    job_id=job_id,
                    kind="webhook_ok",
                    message=f"Completion webhook delivered ({status_code}) on attempt {attempt}.",
                    data={
                        "url": endpoint,
                        "status_code": status_code,
                        "attempt": attempt,
                        "attempts": max_attempts,
                    },
                )
                return
            except Exception as exc:
                last_error = str(exc)
                if attempt >= max_attempts:
                    break
                await self.store.add_event(
                    job_id=job_id,
                    kind="webhook_retry",
                    message=f"Completion webhook attempt {attempt} failed; retrying.",
                    data={
                        "url": endpoint,
                        "attempt": attempt,
                        "attempts": max_attempts,
                    },
                )
                await asyncio.sleep(backoff_s)
                backoff_s = min(backoff_s * 2.0, 2.0)
        await self.store.add_event(
            job_id=job_id,
            kind="webhook_error",
            message=f"Completion webhook failed after {max_attempts} attempts: {last_error}",
            data={"url": endpoint, "attempts": max_attempts},
        )
