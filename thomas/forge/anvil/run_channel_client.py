"""Build-runner client for the server-owned Praxis child channel."""

from __future__ import annotations

import ipaddress
import os
from typing import Any
from urllib.parse import urlsplit

import httpx

# `delete` removes files in the run's own project folder; the server confines every path.
_ACTIONS = frozenset(
    {"spawn", "wait", "status", "stop_child", "heartbeat", "admit_builder", "report_builder", "delete"}
)


class RunChannelClient:
    def __init__(self, *, base_url: str, run_id: str, token: str) -> None:
        url = urlsplit(base_url)
        try:
            host = ipaddress.ip_address(url.hostname or "")
        except ValueError as exc:
            raise ValueError("run channel must be loopback") from exc
        if url.scheme != "http" or not host.is_loopback or not run_id or not token:
            raise ValueError("run channel requires loopback HTTP and a run identity")
        self.base_url = base_url.rstrip("/")
        self.run_id = run_id
        self.token = token

    @classmethod
    def from_environment(cls) -> RunChannelClient | None:
        base = os.environ.get("THOMAS_RUN_CHANNEL_URL", "")
        run_id = os.environ.get("THOMAS_CODE_RUN_ID", "")
        token = os.environ.get("THOMAS_RUN_CHANNEL_TOKEN", "")
        return cls(base_url=base, run_id=run_id, token=token) if base and run_id and token else None

    async def call(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        if action not in _ACTIONS:
            raise ValueError("unsupported run-channel action")
        timeout = max(10.0, min(310.0, float(payload.get("timeout") or 0) + 10.0))
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{self.base_url}/api/praxis/run/{self.run_id}/{action}",
                json=payload,
                headers={"X-Thomas-Run-Token": self.token},
            )
            if response.is_error:
                try:
                    refusal = response.json()
                except ValueError:
                    refusal = {}
                reason = (
                    str(refusal.get("error") or "HTTP " + str(response.status_code))
                    if isinstance(refusal, dict)
                    else "HTTP " + str(response.status_code)
                )
                raise RuntimeError(f"run channel {action} refused: {reason[:500]}")
            result = response.json()
        if not isinstance(result, dict) or not result.get("ok"):
            raise RuntimeError(str(result.get("error") if isinstance(result, dict) else "run channel failed"))
        return result
