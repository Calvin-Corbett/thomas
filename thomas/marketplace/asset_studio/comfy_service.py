from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import urllib.parse
import urllib.request
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from . import connector_shims

DEFAULT_SERVER_URL = "http://127.0.0.1:8188"


def _safe_string(value: Any) -> str:
    return str(value or "").strip()


def _safe_float(value: Any, *, default: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except ImportError:
        parsed = float(default)
    return max(float(minimum), min(float(maximum), float(parsed)))


def _normalize_server_url(value: str) -> str:
    raw = _safe_string(value) or DEFAULT_SERVER_URL
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return DEFAULT_SERVER_URL
    return raw.rstrip("/")


def _json_get(url: str, *, timeout_s: float) -> Any:
    request = urllib.request.Request(url, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        payload = response.read().decode("utf-8", errors="replace")
    return json.loads(payload)


class ComfyStudioService:
    def __init__(
        self,
        *,
        default_server_url: str = DEFAULT_SERVER_URL,
        boot_command: str = "",
        boot_cwd: str = "",
    ) -> None:
        self.default_server_url = _normalize_server_url(default_server_url)
        self.default_boot_command = _safe_string(boot_command) or _safe_string(
            os.environ.get("THOMAS_COMFYUI_BOOT_CMD")
        )
        self.default_boot_cwd = _safe_string(boot_cwd) or _safe_string(os.environ.get("THOMAS_COMFYUI_BOOT_CWD"))
        self._process: asyncio.subprocess.Process | None = None
        self._process_command = ""
        self._process_cwd = ""
        self._boot_guard = asyncio.Lock()

    def _process_snapshot(self) -> dict[str, Any]:
        process = self._process
        return {
            "managed": process is not None,
            "managed_alive": bool(process is not None and process.returncode is None),
            "managed_pid": int(process.pid) if process is not None and process.pid else 0,
            "managed_command": self._process_command,
            "managed_cwd": self._process_cwd,
            "managed_exit_code": (None if process is None or process.returncode is None else int(process.returncode)),
        }

    @staticmethod
    def _status_sync(server_url: str, timeout_s: float) -> dict[str, Any]:
        timeout = _safe_float(timeout_s, default=2.0, minimum=0.5, maximum=20.0)
        queue_payload: Any = None
        stats_payload: Any = None
        last_error = ""

        try:
            queue_payload = _json_get(f"{server_url}/queue", timeout_s=timeout)
        except Exception as exc:
            last_error = str(exc)

        try:
            stats_payload = _json_get(f"{server_url}/system_stats", timeout_s=timeout)
        except Exception as exc:
            if not last_error:
                last_error = str(exc)

        running = isinstance(queue_payload, Mapping) or isinstance(stats_payload, Mapping)
        queue_running = 0
        queue_pending = 0
        python_version = ""
        if isinstance(queue_payload, Mapping):
            queue_running = len(queue_payload.get("queue_running") or [])
            queue_pending = len(queue_payload.get("queue_pending") or [])
        if isinstance(stats_payload, Mapping):
            system = stats_payload.get("system")
            if isinstance(system, Mapping):
                python_version = _safe_string(system.get("python_version"))

        return {
            "server_url": server_url,
            "running": bool(running),
            "queue_running": int(queue_running),
            "queue_pending": int(queue_pending),
            "python_version": python_version,
            "error": "" if running else _safe_string(last_error),
        }

    async def status(
        self,
        *,
        server_url: str = "",
        timeout_s: float = 2.0,
    ) -> dict[str, Any]:
        normalized = _normalize_server_url(server_url or self.default_server_url)
        snapshot = await asyncio.to_thread(self._status_sync, normalized, float(timeout_s))
        snapshot.update(self._process_snapshot())
        return snapshot

    async def boot(
        self,
        *,
        server_url: str = "",
        command: str = "",
        cwd: str = "",
        wait_timeout_s: float = 20.0,
    ) -> dict[str, Any]:
        normalized_server = _normalize_server_url(server_url or self.default_server_url)
        timeout = _safe_float(wait_timeout_s, default=20.0, minimum=1.0, maximum=180.0)
        initial = await self.status(server_url=normalized_server, timeout_s=min(2.0, timeout))
        if bool(initial.get("running")):
            return {
                **initial,
                "ready": True,
                "already_running": True,
                "launched": False,
                "can_boot": True,
            }

        launch_command = _safe_string(command) or self.default_boot_command
        launch_cwd = _safe_string(cwd) or self.default_boot_cwd
        if not launch_command:
            return {
                **initial,
                "ready": False,
                "already_running": False,
                "launched": False,
                "can_boot": False,
                "error": (
                    "ComfyUI is offline and no boot command is configured. "
                    "Set THOMAS_COMFYUI_BOOT_CMD or pass command in the boot payload."
                ),
            }

        resolved_cwd = ""
        if launch_cwd:
            candidate = Path(launch_cwd).expanduser().resolve()
            if candidate.exists() and candidate.is_dir():
                resolved_cwd = str(candidate)

        async with self._boot_guard:
            process = self._process
            if process is None or process.returncode is not None:
                self._process = await asyncio.create_subprocess_shell(
                    launch_command,
                    cwd=resolved_cwd or None,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                self._process_command = launch_command
                self._process_cwd = resolved_cwd

        deadline = asyncio.get_running_loop().time() + float(timeout)
        latest = await self.status(server_url=normalized_server, timeout_s=min(2.0, timeout))
        while not bool(latest.get("running")) and asyncio.get_running_loop().time() < deadline:
            process = self._process
            if process is not None and process.returncode is not None:
                break
            await asyncio.sleep(0.4)
            latest = await self.status(server_url=normalized_server, timeout_s=min(2.0, timeout))

        return {
            **latest,
            "ready": bool(latest.get("running")),
            "already_running": False,
            "launched": True,
            "can_boot": True,
            "boot_timeout_s": float(timeout),
        }

    async def shutdown(
        self,
        *,
        server_url: str = "",
        wait_timeout_s: float = 8.0,
    ) -> dict[str, Any]:
        timeout = _safe_float(wait_timeout_s, default=8.0, minimum=1.0, maximum=60.0)
        normalized_server = _normalize_server_url(server_url or self.default_server_url)
        terminated = False
        killed = False
        exit_code: int | None = None

        process = self._process
        if process is not None and process.returncode is None:
            with contextlib.suppress(Exception):
                process.terminate()
                terminated = True
                await asyncio.wait_for(process.wait(), timeout=timeout)
            if process.returncode is None:
                with contextlib.suppress(Exception):
                    process.kill()
                    killed = True
                    await asyncio.wait_for(process.wait(), timeout=timeout)
            if process.returncode is not None:
                exit_code = int(process.returncode)

        self._process = None
        self._process_command = ""
        self._process_cwd = ""
        status = await self.status(server_url=normalized_server, timeout_s=2.0)
        return {
            **status,
            "terminated": bool(terminated),
            "killed": bool(killed),
            "exit_code": exit_code,
        }

    async def queue_prompt(
        self,
        *,
        server_url: str = "",
        workflow_json: str = "",
        workflow_file: str = "",
        client_id: str = "",
        timeout_s: float = 30.0,
        output: str = "",
    ) -> dict[str, Any]:
        args = argparse.Namespace(
            server_url=_normalize_server_url(server_url or self.default_server_url),
            workflow_json=_safe_string(workflow_json),
            workflow_file=_safe_string(workflow_file),
            client_id=_safe_string(client_id),
            timeout_s=float(_safe_float(timeout_s, default=30.0, minimum=1.0, maximum=180.0)),
            output=_safe_string(output),
        )
        return await asyncio.to_thread(connector_shims.comfyui_queue_prompt, args)

    async def get_history(
        self,
        *,
        server_url: str = "",
        prompt_id: str,
        timeout_s: float = 20.0,
        output: str = "",
    ) -> dict[str, Any]:
        args = argparse.Namespace(
            server_url=_normalize_server_url(server_url or self.default_server_url),
            prompt_id=_safe_string(prompt_id),
            timeout_s=float(_safe_float(timeout_s, default=20.0, minimum=1.0, maximum=120.0)),
            output=_safe_string(output),
        )
        return await asyncio.to_thread(connector_shims.comfyui_get_history, args)

    async def get_outputs(
        self,
        *,
        server_url: str = "",
        prompt_id: str,
        timeout_s: float = 20.0,
    ) -> dict[str, Any]:
        history_response = await self.get_history(
            server_url=server_url,
            prompt_id=prompt_id,
            timeout_s=timeout_s,
            output="",
        )
        normalized_server = _normalize_server_url(server_url or history_response.get("server_url") or "")
        history = history_response.get("history")
        outputs = history.get("outputs") if isinstance(history, Mapping) else None
        images: list[dict[str, Any]] = []
        if isinstance(outputs, Mapping):
            for node_id, node_payload in outputs.items():
                if not isinstance(node_payload, Mapping):
                    continue
                node_images = node_payload.get("images")
                if not isinstance(node_images, list):
                    continue
                for index, row in enumerate(node_images):
                    if not isinstance(row, Mapping):
                        continue
                    filename = _safe_string(row.get("filename"))
                    if not filename:
                        continue
                    subfolder = _safe_string(row.get("subfolder"))
                    image_type = _safe_string(row.get("type")) or "output"
                    query = [("filename", filename), ("type", image_type)]
                    if subfolder:
                        query.append(("subfolder", subfolder))
                    url = f"{normalized_server}/view?{urllib.parse.urlencode(query)}"
                    images.append(
                        {
                            "node_id": _safe_string(node_id),
                            "index": int(index),
                            "filename": filename,
                            "subfolder": subfolder,
                            "type": image_type,
                            "url": url,
                        }
                    )
        return {
            "ok": True,
            "provider": "comfyui",
            "server_url": normalized_server,
            "prompt_id": _safe_string(prompt_id),
            "status": history_response.get("status"),
            "count": len(images),
            "images": images,
            "history": history if isinstance(history, Mapping) else {},
        }

    async def close(self) -> None:
        with contextlib.suppress(Exception):
            await self.shutdown(wait_timeout_s=3.0)
