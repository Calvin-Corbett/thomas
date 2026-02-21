"""OpenAI-compatible batch helpers (xAI-first, provider-agnostic shape handling).

This module wraps REST batch endpoints such as:
- POST /v1/batches
- POST /v1/batches/{batch_id}/requests
- GET  /v1/batches/{batch_id}
- GET  /v1/batches/{batch_id}/requests
- GET  /v1/batches/{batch_id}/results

It is intentionally defensive because vendors can vary response envelopes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx

from thomas.core.config import ModelConfig


class BatchAPIError(RuntimeError):
    """Raised when a batch API request fails."""


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _root_obj(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    inner = payload.get("batch")
    if isinstance(inner, dict):
        return inner
    return payload


def extract_batch_id(payload: Dict[str, Any]) -> str:
    obj = _root_obj(payload)
    candidates = (
        obj.get("batch_id"),
        obj.get("batchId"),
        payload.get("batch_id"),
        payload.get("batchId"),
        payload.get("id"),
    )
    for candidate in candidates:
        text = str(candidate or "").strip()
        if text:
            return text
    return ""


def parse_batch_state(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Parse batch progress counters and completion state from loose payloads."""
    obj = _root_obj(payload)
    state = obj.get("state") if isinstance(obj.get("state"), dict) else {}
    status = str(
        obj.get("status")
        or payload.get("status")
        or ""
    ).strip().lower()

    num_requests = _to_int(
        state.get("num_requests")
        or state.get("numRequests")
        or obj.get("num_requests")
        or obj.get("numRequests"),
        0,
    )
    num_pending = _to_int(
        state.get("num_pending")
        or state.get("numPending")
        or obj.get("num_pending")
        or obj.get("numPending"),
        0,
    )
    num_success = _to_int(
        state.get("num_success")
        or state.get("numSuccess")
        or obj.get("num_success")
        or obj.get("numSuccess"),
        0,
    )
    num_error = _to_int(
        state.get("num_error")
        or state.get("numError")
        or obj.get("num_error")
        or obj.get("numError"),
        0,
    )
    num_cancelled = _to_int(
        state.get("num_cancelled")
        or state.get("numCancelled")
        or obj.get("num_cancelled")
        or obj.get("numCancelled"),
        0,
    )

    terminal_status = status in {
        "completed",
        "complete",
        "done",
        "succeeded",
        "success",
        "failed",
        "cancelled",
        "canceled",
        "expired",
    }
    counters_done = (num_requests > 0 and num_pending <= 0)
    done = bool(terminal_status or counters_done)
    if not status:
        if done:
            status = "completed"
        elif num_requests > 0:
            status = "running"
        else:
            status = "queued"

    return {
        "status": status,
        "done": bool(done),
        "num_requests": int(num_requests),
        "num_pending": int(num_pending),
        "num_success": int(num_success),
        "num_error": int(num_error),
        "num_cancelled": int(num_cancelled),
    }


def extract_batch_results(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    for key in ("results", "batch_results", "data"):
        val = payload.get(key)
        if isinstance(val, list):
            return [x for x in val if isinstance(x, dict)]
    inner = payload.get("list_batch_results_response")
    if isinstance(inner, dict):
        vals = inner.get("results")
        if isinstance(vals, list):
            return [x for x in vals if isinstance(x, dict)]
    return []


def extract_result_request_id(result: Dict[str, Any]) -> str:
    if not isinstance(result, dict):
        return ""
    return str(
        result.get("batch_request_id")
        or result.get("batchRequestId")
        or result.get("request_id")
        or result.get("id")
        or ""
    ).strip()


def extract_result_error(result: Dict[str, Any]) -> str:
    if not isinstance(result, dict):
        return ""
    err = result.get("error")
    if isinstance(err, dict):
        code = _to_int(err.get("code"), 0)
        msg = str(err.get("message") or "").strip()
        if code != 0 or msg:
            return msg or f"error code {code}"
    if isinstance(err, str):
        return err.strip()
    return ""


def _normalize_text_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                if str(item.get("type") or "") == "text":
                    parts.append(str(item.get("text") or ""))
                elif "content" in item and isinstance(item.get("content"), str):
                    parts.append(str(item.get("content") or ""))
        return "".join(parts).strip()
    return ""


def extract_result_text(result: Dict[str, Any]) -> str:
    """Extract assistant text from one batch result across common schemas."""
    if not isinstance(result, dict):
        return ""

    response_obj: Any = result.get("response")
    if isinstance(response_obj, dict) and isinstance(response_obj.get("completion_response"), dict):
        response_obj = response_obj.get("completion_response")
    if not isinstance(response_obj, dict):
        return ""

    # OpenAI-compatible choices payload.
    choices = response_obj.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0] if isinstance(choices[0], dict) else {}
        msg = first.get("message") if isinstance(first.get("message"), dict) else {}
        content = _normalize_text_content(msg.get("content"))
        if content:
            return content
        alt = _normalize_text_content(first.get("text"))
        if alt:
            return alt

    # Fallbacks used by some SDKs/providers.
    for key in ("output_text", "text", "content"):
        val = _normalize_text_content(response_obj.get(key))
        if val:
            return val
    return ""


def build_completion_request(
    *,
    model_cfg: ModelConfig,
    messages: List[Dict[str, Any]],
) -> Dict[str, Any]:
    req: Dict[str, Any] = {
        "model": str(model_cfg.model or ""),
        "messages": list(messages or []),
        "max_tokens": int(model_cfg.max_tokens or 4096),
        "temperature": float(model_cfg.temperature or 0.0),
    }
    top_p = float(model_cfg.top_p or 1.0)
    if top_p < 1.0:
        req["top_p"] = top_p
    return req


@dataclass
class BatchSubmission:
    batch_id: str
    request_id: str
    create_payload: Dict[str, Any]
    add_payload: Dict[str, Any]


class OpenAICompatBatchClient:
    """Small async client for openai-compatible batch endpoints."""

    def __init__(self, model_cfg: ModelConfig):
        self.model_cfg = model_cfg
        self._client: Optional[httpx.AsyncClient] = None

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is not None and not self._client.is_closed:
            return self._client
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if self.model_cfg.extra_headers:
            headers.update(self.model_cfg.extra_headers)
        if self.model_cfg.api_key:
            header_name = str(self.model_cfg.api_key_header or "Authorization")
            prefix = str(self.model_cfg.api_key_prefix or "")
            headers[header_name] = f"{prefix}{self.model_cfg.api_key}"
        self._client = httpx.AsyncClient(
            headers=headers,
            timeout=httpx.Timeout(
                connect=10.0,
                read=max(10.0, float(self.model_cfg.timeout_s or 120.0)),
                write=10.0,
                pool=10.0,
            ),
        )
        return self._client

    def _url(self, path: str) -> str:
        base = str(self.model_cfg.base_url or "").strip().rstrip("/")
        p = "/" + str(path or "").strip().lstrip("/")
        return base + p

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        client = await self._get_client()
        url = self._url(path)
        resp = await client.request(method=method.upper(), url=url, json=json_body, params=params)
        if resp.status_code >= 400:
            body = resp.text
            raise BatchAPIError(
                f"batch API {resp.status_code} at {path}: {body[:400]}"
            )
        if not resp.content:
            return {}
        ctype = str(resp.headers.get("content-type") or "").lower()
        if "application/json" in ctype:
            try:
                payload = resp.json()
                if isinstance(payload, dict):
                    return payload
            except Exception:
                pass
        try:
            payload = json.loads(resp.text)
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass
        return {}

    async def create_batch(self, *, name: str) -> Dict[str, Any]:
        return await self._request("POST", "/batches", json_body={"name": str(name or "thomas-batch").strip()})

    async def add_batch_requests(self, *, batch_id: str, batch_requests: List[Dict[str, Any]]) -> Dict[str, Any]:
        bid = str(batch_id or "").strip()
        if not bid:
            raise BatchAPIError("missing batch_id")
        body = {
            "batch_id": bid,
            "batch_requests": list(batch_requests or []),
        }
        return await self._request("POST", f"/batches/{bid}/requests", json_body=body)

    async def get_batch(self, *, batch_id: str) -> Dict[str, Any]:
        bid = str(batch_id or "").strip()
        if not bid:
            raise BatchAPIError("missing batch_id")
        return await self._request("GET", f"/batches/{bid}")

    async def list_batch_requests(
        self,
        *,
        batch_id: str,
        limit: int = 100,
        pagination_token: str = "",
    ) -> Dict[str, Any]:
        bid = str(batch_id or "").strip()
        if not bid:
            raise BatchAPIError("missing batch_id")
        params: Dict[str, Any] = {"limit": max(1, int(limit))}
        if pagination_token.strip():
            params["pagination_token"] = pagination_token.strip()
        return await self._request("GET", f"/batches/{bid}/requests", params=params)

    async def list_batch_results(
        self,
        *,
        batch_id: str,
        limit: int = 200,
        pagination_token: str = "",
    ) -> Dict[str, Any]:
        bid = str(batch_id or "").strip()
        if not bid:
            raise BatchAPIError("missing batch_id")
        params: Dict[str, Any] = {"limit": max(1, int(limit))}
        if pagination_token.strip():
            params["pagination_token"] = pagination_token.strip()
        return await self._request("GET", f"/batches/{bid}/results", params=params)

    async def create_and_add_chat_requests(
        self,
        *,
        batch_name: str,
        requests: List[Dict[str, Any]],
    ) -> BatchSubmission:
        create_payload = await self.create_batch(name=batch_name)
        batch_id = extract_batch_id(create_payload)
        if not batch_id:
            raise BatchAPIError("batch API create response missing batch_id")
        add_payload = await self.add_batch_requests(batch_id=batch_id, batch_requests=requests)
        request_id = ""
        if requests:
            request_id = str(requests[0].get("batch_request_id") or "").strip()
        return BatchSubmission(
            batch_id=batch_id,
            request_id=request_id,
            create_payload=create_payload,
            add_payload=add_payload,
        )
