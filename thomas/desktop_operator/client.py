from __future__ import annotations

from typing import Any

import httpx

from .contracts import DesktopOperatorError


class DesktopOperatorClient:
    def __init__(self, *, base_url: str, token: str, timeout_s: float = 10.0) -> None:
        self.base_url = str(base_url).rstrip("/")
        self.token = str(token)
        self.timeout_s = float(timeout_s)

    def health(self) -> dict[str, Any]:
        response = httpx.get(f"{self.base_url}/health", timeout=self.timeout_s)
        response.raise_for_status()
        return response.json()

    def status(self) -> dict[str, Any]:
        return self._post_or_get("/status", None, use_get=True)

    def call(self, endpoint: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._post_or_get(endpoint, payload or {}, use_get=False)

    def _post_or_get(self, endpoint: str, payload: dict[str, Any] | None, *, use_get: bool) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.token}"}
        if use_get:
            response = httpx.get(f"{self.base_url}{endpoint}", headers=headers, timeout=self.timeout_s)
        else:
            response = httpx.post(
                f"{self.base_url}{endpoint}", headers=headers, json=payload or {}, timeout=self.timeout_s
            )
        try:
            body = response.json()
        except Exception:  # noqa: BLE001
            response.raise_for_status()
            raise
        if not response.is_success or not bool(body.get("ok")):
            error = body.get("error") if isinstance(body, dict) else None
            if isinstance(error, dict):
                raise DesktopOperatorError(
                    str(error.get("code") or "external_failure"),
                    str(error.get("message") or "Desktop helper request failed."),
                    details=error.get("details") if isinstance(error.get("details"), dict) else {},
                )
            response.raise_for_status()
        data = body.get("data")
        return data if isinstance(data, dict) else {"value": data}
