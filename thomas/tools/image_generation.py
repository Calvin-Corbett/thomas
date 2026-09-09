"""Real image generation as a first-class tool.

``image.generate`` turns a text prompt into PNG file(s) in the task workspace
using whichever image-capable credential is actually configured:

1. An OpenAI **API key** (``openai`` model profile / Settings > Models /
   ``OPENAI_API_KEY``) -> ``POST {base}/images/generations`` with ``gpt-image-1``.
2. A Google Gemini API key (``gemini`` profile / ``GEMINI_API_KEY`` /
   ``GOOGLE_API_KEY``) -> ``generateContent`` on ``gemini-2.5-flash-image``.

The ChatGPT-subscription OAuth token (provider ``openai_codex``) is
deliberately NOT a candidate. Verified live 2026-08-06: that token against
``https://api.openai.com/v1/images/generations`` returns HTTP 401
"Missing scopes: api.model.images.request" -- OpenAI scopes the subscription
token to the Codex Responses backend only. Being signed in with ChatGPT does
not grant image generation, and this tool never pretends otherwise.

The tool is always registered so the model can see it and relay the honest
remedy when no credential works; unavailability is a clear error at call time,
never a silent absence and never a fake image (same contract as the
email/calendar tools in ``thomas.server.tool_extensions``).
"""

from __future__ import annotations

import base64
import binascii
import logging
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from thomas.tools.base import Tool, ToolResult

log = logging.getLogger(__name__)

OPENAI_IMAGE_MODEL = "gpt-image-1"
GEMINI_IMAGE_MODEL = "gemini-2.5-flash-image"
GEMINI_API_ROOT = "https://generativelanguage.googleapis.com/v1beta"

NO_CREDENTIAL_REMEDY = (
    "Image generation is not available yet: no image-capable API key is configured. "
    "The ChatGPT sign-in Thomas uses for chat cannot generate images -- OpenAI scopes that "
    "subscription token to the Codex API only (verified 2026-08-06: HTTP 401, missing scope "
    "api.model.images.request). To enable images, add an OpenAI API key to the 'openai' model "
    "profile in Settings > Models (or set OPENAI_API_KEY), or add a Google Gemini API key to "
    "the 'gemini' profile (or set GEMINI_API_KEY / GOOGLE_API_KEY)."
)

# Exact-size -> Gemini aspect-ratio hints (Gemini takes ratios, not pixel sizes).
_GEMINI_ASPECT_RATIOS = {
    "1024x1024": "1:1",
    "1536x1024": "3:2",
    "1024x1536": "2:3",
    "1792x1024": "16:9",
    "1024x1792": "9:16",
    "1920x1080": "16:9",
    "1080x1920": "9:16",
}

_MAX_COUNT = 4
_DEFAULT_SIZE = "1024x1024"


class ImageProviderError(RuntimeError):
    """A provider was tried with a real credential and refused or failed."""


@dataclass
class _Candidate:
    provider: str  # "openai" | "gemini"
    api_key: str
    base_url: str = ""


async def _default_http_post(
    url: str,
    headers: dict[str, str],
    json_body: dict[str, Any],
    timeout_s: float,
) -> tuple[int, Any]:
    try:
        import httpx
    except ImportError:  # pragma: no cover - vendored fallback mirrors openai_codex_oauth
        from thomas._vendor import httpx_shim as httpx  # type: ignore[assignment]
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        resp = await client.post(url, headers=headers, json=json_body)
        try:
            body: Any = resp.json()
        except (ValueError, TypeError):
            body = resp.text
        return int(resp.status_code), body


def _upstream_error_text(status: int, body: Any) -> str:
    detail = ""
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            detail = str(err.get("message") or "")
        elif err:
            detail = str(err)
    if not detail:
        detail = str(body)[:300]
    return f"HTTP {status}: {detail}"


def _slug(prompt: str, max_len: int = 32) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", prompt.lower()).strip("-")
    return slug[:max_len].rstrip("-") or "image"


class ImageGenerateTool(Tool):
    """Generate PNG image(s) from a text prompt into the workspace."""

    name = "image.generate"
    category = "media"
    description = (
        "Generate image(s) from a text prompt and save them as PNG files in the task "
        "workspace. Uses a configured OpenAI API key (gpt-image-1) or Google Gemini API key "
        "(gemini-2.5-flash-image). If neither key is configured, the result explains exactly "
        "which credential is missing and where to add it -- relay that explanation to the "
        "user; never pretend an image was created."
    )
    parameters = {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "What the image should show, in plain language.",
            },
            "size": {
                "type": "string",
                "description": (
                    "Optional size, e.g. '1024x1024' (default), '1536x1024', '1024x1536'. "
                    "Gemini treats this as an aspect-ratio hint."
                ),
            },
            "count": {
                "type": "integer",
                "description": f"How many images to generate (1-{_MAX_COUNT}, default 1).",
            },
        },
        "required": ["prompt"],
    }

    def __init__(
        self,
        workspace: Path | str,
        *,
        model_configs: Mapping[str, Any] | None = None,
        env: Mapping[str, str] | None = None,
        secret_reader: Callable[[str], str | None] | None = None,
        http_post: Callable[..., Any] | None = None,
        timeout_s: float = 180.0,
    ) -> None:
        self._workspace = Path(workspace)
        self._model_configs = dict(model_configs or {})
        self._env = env  # None -> live os.environ at call time
        self._secret_reader = secret_reader
        self._http_post = http_post or _default_http_post
        self._timeout_s = float(timeout_s)

    # ----- credential discovery -----

    def _env_get(self, key: str) -> str:
        if self._env is not None:
            return str(self._env.get(key) or "").strip()
        import os

        return str(os.environ.get(key) or "").strip()

    def _secret_get(self, profile: str) -> str:
        if self._secret_reader is None:
            return ""
        try:
            return str(self._secret_reader(profile) or "").strip()
        except (AttributeError, KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
            # Named, not broad: an unreadable secret store degrades to "no key
            # from Settings" (config/env still get their chance) and is logged;
            # a bug in the reader still surfaces.
            log.debug("image.generate: secret lookup for %s failed: %s", profile, exc)
            return ""

    def _profile_key(self, profile: str) -> tuple[str, str]:
        cfg = self._model_configs.get(profile)
        if cfg is None:
            return "", ""
        return (
            str(getattr(cfg, "api_key", "") or "").strip(),
            str(getattr(cfg, "base_url", "") or "").strip(),
        )

    def _candidates(self) -> list[_Candidate]:
        out: list[_Candidate] = []

        cfg_key, base_url = self._profile_key("openai")
        openai_key = self._secret_get("openai") or cfg_key or self._env_get("OPENAI_API_KEY")
        if openai_key:
            out.append(
                _Candidate(
                    provider="openai",
                    api_key=openai_key,
                    base_url=base_url or "https://api.openai.com/v1",
                )
            )

        cfg_key, _ = self._profile_key("gemini")
        gemini_key = (
            self._secret_get("gemini")
            or cfg_key
            or self._env_get("GEMINI_API_KEY")
            or self._env_get("GOOGLE_API_KEY")
        )
        if gemini_key:
            out.append(_Candidate(provider="gemini", api_key=gemini_key))

        return out

    # ----- generation -----

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        prompt = str(args.get("prompt") or "").strip()
        if not prompt:
            return ToolResult(ok=False, error="prompt is required")
        size = str(args.get("size") or _DEFAULT_SIZE).strip().lower() or _DEFAULT_SIZE
        try:
            count = int(args.get("count") or 1)
        except (TypeError, ValueError):
            count = 1
        count = max(1, min(_MAX_COUNT, count))

        candidates = self._candidates()
        if not candidates:
            return ToolResult(ok=False, error=NO_CREDENTIAL_REMEDY)

        failures: list[str] = []
        for candidate in candidates:
            try:
                if candidate.provider == "openai":
                    images = await self._generate_openai(candidate, prompt, size, count)
                    model_used = OPENAI_IMAGE_MODEL
                else:
                    images = await self._generate_gemini(candidate, prompt, size, count)
                    model_used = GEMINI_IMAGE_MODEL
            except ImageProviderError as exc:
                failures.append(f"{candidate.provider}: {exc}")
                continue
            files = self._write_files(images, prompt)
            noun = "image" if len(files) == 1 else f"{len(files)} images"
            description = f'Generated {noun} ({size}) for "{prompt}" via {model_used}.'
            return ToolResult(
                ok=True,
                data={
                    "files": files,
                    "description": description,
                    "provider": candidate.provider,
                    "model": model_used,
                },
            )

        return ToolResult(
            ok=False,
            error=(
                "Image generation failed with every configured credential. "
                + " | ".join(failures)
                + " Fix the failing key (Settings > Models) or add a working one: "
                "OpenAI API key ('openai' profile / OPENAI_API_KEY) or Gemini API key "
                "('gemini' profile / GEMINI_API_KEY)."
            ),
        )

    async def _generate_openai(
        self, candidate: _Candidate, prompt: str, size: str, count: int
    ) -> list[bytes]:
        url = candidate.base_url.rstrip("/") + "/images/generations"
        status, body = await self._http_post(
            url,
            {
                "Authorization": f"Bearer {candidate.api_key}",
                "Content-Type": "application/json",
            },
            {"model": OPENAI_IMAGE_MODEL, "prompt": prompt, "n": count, "size": size},
            self._timeout_s,
        )
        if status != 200:
            raise ImageProviderError(_upstream_error_text(status, body))
        entries = body.get("data") if isinstance(body, dict) else None
        images: list[bytes] = []
        for entry in entries or []:
            b64 = entry.get("b64_json") if isinstance(entry, dict) else None
            if b64:
                try:
                    images.append(base64.b64decode(b64))
                except (ValueError, binascii.Error) as exc:
                    raise ImageProviderError(f"response contained undecodable image data: {exc}") from exc
        if not images:
            raise ImageProviderError(f"HTTP 200 but no image data in response: {str(body)[:200]}")
        return images

    async def _generate_gemini(
        self, candidate: _Candidate, prompt: str, size: str, count: int
    ) -> list[bytes]:
        url = f"{GEMINI_API_ROOT}/models/{GEMINI_IMAGE_MODEL}:generateContent"
        generation_config: dict[str, Any] = {"responseModalities": ["TEXT", "IMAGE"]}
        aspect_ratio = _GEMINI_ASPECT_RATIOS.get(size)
        if aspect_ratio:
            generation_config["imageConfig"] = {"aspectRatio": aspect_ratio}
        images: list[bytes] = []
        for _ in range(count):
            status, body = await self._http_post(
                url,
                {"x-goog-api-key": candidate.api_key, "Content-Type": "application/json"},
                {
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": generation_config,
                },
                self._timeout_s,
            )
            if status != 200:
                raise ImageProviderError(_upstream_error_text(status, body))
            images.extend(self._gemini_image_parts(body))
        if not images:
            raise ImageProviderError("HTTP 200 but the response contained no image data")
        return images

    @staticmethod
    def _gemini_image_parts(body: Any) -> list[bytes]:
        images: list[bytes] = []
        candidates = body.get("candidates") if isinstance(body, dict) else None
        for cand in candidates or []:
            content = cand.get("content") if isinstance(cand, dict) else None
            parts = content.get("parts") if isinstance(content, dict) else None
            for part in parts or []:
                inline = {}
                if isinstance(part, dict):
                    inline = part.get("inlineData") or part.get("inline_data") or {}
                data = inline.get("data") if isinstance(inline, dict) else None
                if data:
                    try:
                        images.append(base64.b64decode(data))
                    except (ValueError, binascii.Error) as exc:
                        raise ImageProviderError(
                            f"response contained undecodable image data: {exc}"
                        ) from exc
        return images

    def _write_files(self, images: list[bytes], prompt: str) -> list[str]:
        self._workspace.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        slug = _slug(prompt)
        files: list[str] = []
        for index, blob in enumerate(images, start=1):
            suffix = "" if len(images) == 1 else f"-{index}"
            path = self._workspace / f"{slug}-{stamp}{suffix}.png"
            counter = 1
            while path.exists():
                path = self._workspace / f"{slug}-{stamp}{suffix}-{counter}.png"
                counter += 1
            path.write_bytes(blob)
            files.append(str(path.resolve()))
        return files


def register_image_generation_tools(
    registry: Any,
    config: Any = None,
    workspace: Path | str | None = None,
    *,
    secret_reader: Callable[[str], str | None] | None = None,
) -> None:
    """Register ``image.generate`` bound to ``workspace``.

    ``config`` supplies model-profile API keys (``config.models``);
    ``secret_reader`` (server layer only) supplies Settings-saved keys.
    The tool is registered unconditionally -- honest unavailability is a
    call-time error, never a missing tool.
    """
    target = workspace
    if target is None:
        tools_cfg = getattr(config, "tools", None)
        target = getattr(tools_cfg, "sandbox_path", None) or Path.cwd()
    registry.register(
        ImageGenerateTool(
            Path(target),
            model_configs=getattr(config, "models", None) or {},
            secret_reader=secret_reader,
        )
    )
