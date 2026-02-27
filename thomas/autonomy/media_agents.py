from __future__ import annotations

import base64
import mimetypes
from collections.abc import Iterable
from pathlib import Path
from typing import Any

try:
    import httpx
except ImportError:
    from thomas._vendor import httpx_shim as httpx  # type: ignore[assignment]

from thomas.core.config import ModelConfig

_RETRYABLE = {408, 409, 425, 429, 500, 502, 503, 504}


class MediaAgentError(RuntimeError):
    pass


class MediaAgentTransientError(MediaAgentError):
    pass


def _join_url(base_url: str, path: str) -> str:
    base = str(base_url or "").strip().rstrip("/")
    if not base:
        raise MediaAgentError("missing model base_url")
    p = str(path or "").strip()
    if not p:
        raise MediaAgentError("missing endpoint path")
    if not p.startswith("/"):
        p = "/" + p
    return base + p


def _norm_paths(raw: Any, *, default_paths: Iterable[str]) -> list[str]:
    out: list[str] = []
    if isinstance(raw, str):
        raw = [x.strip() for x in raw.split(",") if x.strip()]
    if isinstance(raw, list):
        for item in raw:
            p = str(item or "").strip()
            if not p:
                continue
            if not p.startswith("/"):
                p = "/" + p
            if p not in out:
                out.append(p)
    for p in default_paths:
        pp = str(p or "").strip()
        if not pp:
            continue
        if not pp.startswith("/"):
            pp = "/" + pp
        if pp not in out:
            out.append(pp)
    return out


def _auth_headers(cfg: ModelConfig) -> dict[str, str]:
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if cfg.extra_headers:
        headers.update(cfg.extra_headers)
    if cfg.api_key:
        if cfg.provider == "anthropic":
            headers["x-api-key"] = cfg.api_key
            headers.setdefault("anthropic-version", "2023-06-01")
        else:
            header_name = cfg.api_key_header or "Authorization"
            prefix = cfg.api_key_prefix or ""
            headers[header_name] = f"{prefix}{cfg.api_key}"
    return headers


def _extract_text(payload: dict[str, Any]) -> str:
    candidates = [
        payload.get("text"),
        payload.get("transcript"),
        payload.get("output_text"),
        payload.get("content"),
    ]
    for value in candidates:
        if isinstance(value, str) and value.strip():
            return value.strip()
    nested = payload.get("data")
    if isinstance(nested, dict):
        return _extract_text(nested)
    return ""


def _extract_video_meta(payload: dict[str, Any]) -> tuple[str, str, str]:
    status = ""
    video_id = ""
    video_url = ""

    if isinstance(payload.get("status"), str):
        status = str(payload.get("status") or "").strip()

    for key in ("id", "video_id", "job_id"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            video_id = value.strip()
            break

    for key in ("url", "video_url", "output_url"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            video_url = value.strip()
            break

    data = payload.get("data")
    if isinstance(data, dict):
        d_status, d_id, d_url = _extract_video_meta(data)
        status = status or d_status
        video_id = video_id or d_id
        video_url = video_url or d_url
    elif isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict):
            d_status, d_id, d_url = _extract_video_meta(first)
            status = status or d_status
            video_id = video_id or d_id
            video_url = video_url or d_url

    return status, video_id, video_url


class OpenAICompatMediaClient:
    """Small media client for OpenAI-compatible providers."""

    def __init__(self, cfg: ModelConfig):
        self.cfg = cfg
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers=_auth_headers(self.cfg),
                timeout=httpx.Timeout(
                    connect=10.0,
                    read=max(30.0, float(self.cfg.timeout_s or 120.0)),
                    write=30.0,
                    pool=10.0,
                ),
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    async def _request(
        self,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        files: Any = None,
    ) -> httpx.Response:
        client = await self._get_client()
        url = _join_url(self.cfg.base_url, path)
        try:
            resp = await client.request(
                method.upper(),
                url,
                json=json_body,
                data=data,
                files=files,
                params=(self.cfg.query or None),
            )
        except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError, OSError) as e:
            raise MediaAgentTransientError(f"{type(e).__name__}: {e}")
        except httpx.HTTPError as e:
            raise MediaAgentTransientError(f"{type(e).__name__}: {e}")
        return resp

    @staticmethod
    def _ensure_success(resp: httpx.Response) -> None:
        if 200 <= int(resp.status_code) < 300:
            return
        body = ""
        try:
            body = resp.text or ""
        except (OSError, FileNotFoundError):
            body = ""
        msg = f"HTTP {resp.status_code}: {body[:500]}"
        if int(resp.status_code) in _RETRYABLE:
            raise MediaAgentTransientError(msg)
        raise MediaAgentError(msg)

    async def _request_json(
        self,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        files: Any = None,
    ) -> dict[str, Any]:
        resp = await self._request(method=method, path=path, json_body=json_body, data=data, files=files)
        self._ensure_success(resp)
        try:
            payload = resp.json()
        except (ValueError, TypeError):
            text = ""
            try:
                text = resp.text or ""
            except Exception:  # REVIEWED: async context
                text = ""
            if text.strip():
                return {"text": text}
            return {}
        if isinstance(payload, dict):
            return payload
        if isinstance(payload, list):
            return {"data": payload}
        return {}

    async def generate_video(
        self,
        *,
        prompt: str,
        model: str | None = None,
        endpoint_paths: Any | None = None,
        image_url: str | None = None,
        duration_seconds: int | None = None,
        size: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        paths = _norm_paths(endpoint_paths, default_paths=["/videos/generations", "/videos"])
        if not paths:
            raise MediaAgentError("video generation endpoint path is missing")

        body: dict[str, Any] = {
            "model": str(model or self.cfg.model or "").strip(),
            "prompt": str(prompt or "").strip(),
        }
        if not body["model"]:
            raise MediaAgentError("video generation requires model id")
        if not body["prompt"]:
            raise MediaAgentError("video generation requires prompt")
        if isinstance(image_url, str) and image_url.strip():
            body["image_url"] = image_url.strip()
        if duration_seconds is not None:
            body["duration_seconds"] = int(duration_seconds)
        if isinstance(size, str) and size.strip():
            body["size"] = size.strip()
        if isinstance(extra, dict):
            body.update(extra)

        last_err: Exception | None = None
        for path in paths:
            try:
                payload = await self._request_json(method="POST", path=path, json_body=body)
                payload["_endpoint_path"] = path
                return payload
            except MediaAgentError as e:
                last_err = e
                # Keep trying fallback endpoints only for obvious "route missing" errors.
                if "HTTP 404" in str(e) or "HTTP 405" in str(e):
                    continue
                raise
        if last_err is not None:
            raise last_err
        raise MediaAgentError("video generation failed without endpoint response")

    async def transcribe_audio(
        self,
        *,
        audio_path: str,
        model: str | None = None,
        endpoint_path: str = "/audio/transcriptions",
        language: str | None = None,
        prompt: str | None = None,
        response_format: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ap = Path(str(audio_path or "").strip()).expanduser()
        if not ap.exists() or not ap.is_file():
            raise MediaAgentError(f"audio file not found: {ap}")

        fields: dict[str, str] = {
            "model": str(model or self.cfg.model or "").strip(),
        }
        if not fields["model"]:
            raise MediaAgentError("speech transcription requires model id")
        if isinstance(language, str) and language.strip():
            fields["language"] = language.strip()
        if isinstance(prompt, str) and prompt.strip():
            fields["prompt"] = prompt.strip()
        if isinstance(response_format, str) and response_format.strip():
            fields["response_format"] = response_format.strip()
        if isinstance(extra, dict):
            for k, v in extra.items():
                if v is None:
                    continue
                fields[str(k)] = str(v)

        mime = mimetypes.guess_type(ap.name)[0] or "application/octet-stream"
        with ap.open("rb") as f:
            files = {"file": (ap.name, f, mime)}
            payload = await self._request_json(
                method="POST",
                path=endpoint_path,
                data=fields,
                files=files,
            )
        payload.setdefault("text", _extract_text(payload))
        payload["_endpoint_path"] = endpoint_path
        payload["_audio_path"] = str(ap)
        return payload

    async def synthesize_speech(
        self,
        *,
        text: str,
        voice: str = "alloy",
        model: str | None = None,
        endpoint_path: str = "/audio/speech",
        audio_format: str = "mp3",
        speed: float | None = None,
        output_path: Path | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": str(model or self.cfg.model or "").strip(),
            "input": str(text or "").strip(),
            "voice": str(voice or "alloy").strip() or "alloy",
        }
        if not body["model"]:
            raise MediaAgentError("speech synthesis requires model id")
        if not body["input"]:
            raise MediaAgentError("speech synthesis requires text input")
        if isinstance(audio_format, str) and audio_format.strip():
            body["format"] = audio_format.strip()
        if speed is not None:
            body["speed"] = float(speed)
        if isinstance(extra, dict):
            body.update(extra)

        resp = await self._request(method="POST", path=endpoint_path, json_body=body)
        self._ensure_success(resp)

        content_type = str(resp.headers.get("content-type") or "").strip().lower()
        raw_bytes = bytes(resp.content or b"")
        payload: dict[str, Any] = {}

        if "json" in content_type:
            try:
                j = resp.json()
            except (ValueError, TypeError):
                j = {}
            if isinstance(j, dict):
                payload.update(j)
                # Common schema used by some providers.
                b64 = j.get("audio_base64") or j.get("audio")
                if isinstance(b64, str) and b64:
                    try:
                        raw_bytes = base64.b64decode(b64)
                    except (ValueError, TypeError):
                        raw_bytes = b""
            elif isinstance(j, list):
                payload["data"] = j

        written_path = ""
        if output_path is not None and raw_bytes:
            op = Path(output_path).expanduser()
            op.parent.mkdir(parents=True, exist_ok=True)
            op.write_bytes(raw_bytes)
            written_path = str(op.resolve())

        payload.update(
            {
                "_endpoint_path": endpoint_path,
                "content_type": content_type or "application/octet-stream",
                "size_bytes": len(raw_bytes),
                "output_path": written_path,
            }
        )
        return payload


__all__ = [
    "MediaAgentError",
    "MediaAgentTransientError",
    "OpenAICompatMediaClient",
    "_extract_text",
    "_extract_video_meta",
]
