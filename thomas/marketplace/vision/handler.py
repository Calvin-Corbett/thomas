from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import httpx
except ImportError:
    from thomas._vendor import httpx_shim as httpx  # type: ignore[assignment]

from .ocr_fallback import extract_text_from_images

UPLOAD_TOKEN_PREFIX = "thomas-upload://"
_IMAGE_TOKEN_RE = re.compile(r"(?:thomas-upload://)([0-9a-fA-F]{32,128})")

_DEFAULT_VISION_HINTS = ("gpt-4o", "gpt-4.1", "gpt-4-vision", "o1", "o3", "o4", "claude-")


def extract_image_ids(text: str) -> list[str]:
    """Extract image IDs embedded in message text as `thomas-upload://<id>`."""
    if not text:
        return []
    return [m.group(1) for m in _IMAGE_TOKEN_RE.finditer(text)]


def _load_model_caps() -> dict:
    raw = os.getenv("THOMAS_MODEL_CAPS_JSON", "").strip()
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def model_supports_vision(active_model: str) -> bool:
    """Vision capability gate.

    Priority:
      1) THOMAS_MODEL_CAPS_JSON mapping
      2) THOMAS_VISION_MODEL_HINTS comma list
      3) built-in heuristics
    """
    if not active_model:
        return False

    caps = _load_model_caps()
    if isinstance(caps, dict) and active_model in caps:
        try:
            return bool(caps[active_model].get("vision", False))
        except json.JSONDecodeError:
            pass

    hints = os.getenv("THOMAS_VISION_MODEL_HINTS", "").strip()
    tokens = tuple(t.strip().lower() for t in hints.split(",") if t.strip()) if hints else _DEFAULT_VISION_HINTS
    m = active_model.lower()
    return any(tok in m for tok in tokens)


def provider_for_model(active_model: str) -> str:
    """Infer provider from model name or caps mapping."""
    m = (active_model or "").strip()

    caps = _load_model_caps()
    if isinstance(caps, dict) and m in caps:
        prov = (caps[m].get("provider") or "").strip().lower()
        if prov in ("openai", "anthropic"):
            return prov

    ml = m.lower()
    if ml.startswith("claude"):
        return "anthropic"
    if ml.startswith(("gpt", "o1", "o3", "o4")) or "gpt" in ml:
        return "openai"
    raise ValueError(f"Unknown provider for model: {active_model!r}")


def _guess_mime(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    if mime:
        return mime
    ext = path.suffix.lower()
    if ext in (".jpg", ".jpeg"):
        return "image/jpeg"
    if ext == ".png":
        return "image/png"
    if ext == ".webp":
        return "image/webp"
    if ext == ".gif":
        return "image/gif"
    return "application/octet-stream"


def _read_image_b64(image_path: Path) -> tuple[str, str]:
    data = image_path.read_bytes()
    media_type = _guess_mime(image_path)
    return media_type, base64.b64encode(data).decode("ascii")


def _openai_style() -> str:
    style = os.getenv("THOMAS_OPENAI_API_STYLE", "responses").strip().lower()
    return "chat_completions" if style in ("chat", "chat_completions", "completions") else "responses"


def _openai_image_detail() -> str:
    d = os.getenv("THOMAS_OPENAI_IMAGE_DETAIL", "auto").strip().lower()
    return d if d in ("auto", "low", "high") else "auto"


def build_openai_payload(prompt: str, image_paths: Sequence[Path], model: str, *, max_tokens: int) -> dict[str, Any]:
    """Build OpenAI payload using either Responses API or Chat Completions.

    - Chat Completions: content parts include {"type":"image_url","image_url":{"url":...,"detail":...}}
    - Responses: content parts include {"type":"input_image","image_url":...} and {"type":"input_text","text":...}

    Docs: citeturn2view3turn2view2
    """
    detail = _openai_image_detail()
    style = _openai_style()

    if style == "chat_completions":
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt or ""}]
        for p in image_paths:
            media_type, b64 = _read_image_b64(p)
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{media_type};base64,{b64}",
                        "detail": detail,
                    },
                }
            )
        return {"model": model, "messages": [{"role": "user", "content": content}], "max_tokens": max_tokens}

    # Responses API (default)
    content2: list[dict[str, Any]] = [{"type": "input_text", "text": prompt or ""}]
    for p in image_paths:
        media_type, b64 = _read_image_b64(p)
        part = {"type": "input_image", "image_url": f"data:{media_type};base64,{b64}"}
        # Some models accept `detail`; safe to include only when explicitly set.
        if detail != "auto":
            part["detail"] = detail
        content2.append(part)
    return {
        "model": model,
        "input": [{"role": "user", "content": content2}],
        "max_output_tokens": max_tokens,
    }


def build_anthropic_payload(prompt: str, image_paths: Sequence[Path], model: str, *, max_tokens: int) -> dict[str, Any]:
    """Anthropic Messages API payload with base64 image blocks."""
    blocks: list[dict[str, Any]] = []
    for p in image_paths:
        media_type, b64 = _read_image_b64(p)
        blocks.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": b64,
                },
            }
        )
    blocks.append({"type": "text", "text": prompt or ""})
    return {"model": model, "max_tokens": max_tokens, "messages": [{"role": "user", "content": blocks}]}


def _inject_ocr_text(prompt: str, ocr_texts: Sequence[str]) -> str:
    joined = "\n\n".join(f"[image {i + 1}]\n{t.strip()}" for i, t in enumerate(ocr_texts) if t and t.strip())
    if not joined:
        joined = "(No OCR text could be extracted from the attached image(s).)"
    base = (prompt or "").rstrip()
    if base:
        base += "\n\n"
    return base + "OCR_EXTRACT_FROM_IMAGES:\n" + joined + "\n"


def _text_only_payload(provider: str, model: str, prompt: str, max_tokens: int) -> dict[str, Any]:
    if provider == "openai":
        # Match selected OpenAI style
        if _openai_style() == "chat_completions":
            return {"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens}
        return {"model": model, "input": prompt, "max_output_tokens": max_tokens}

    if provider == "anthropic":
        return {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}],
        }
    return {"model": model, "prompt": prompt, "max_tokens": max_tokens}


@dataclass
class ProviderRequest:
    provider: str  # "openai" | "anthropic"
    model: str
    payload: dict[str, Any]
    used_ocr_fallback: bool = False
    ocr_text: str | None = None


async def build_provider_request(
    prompt: str,
    image_paths: Sequence[Path],
    active_model: str,
    *,
    max_tokens: int = 1024,
) -> ProviderRequest:
    """Build a provider-ready request with vision or OCR fallback."""
    provider = provider_for_model(active_model)

    # No images => text only
    if not image_paths:
        return ProviderRequest(
            provider=provider,
            model=active_model,
            payload=_text_only_payload(provider, active_model, prompt, max_tokens),
        )

    # Vision path
    if model_supports_vision(active_model):
        if provider == "openai":
            payload = build_openai_payload(prompt, image_paths, active_model, max_tokens=max_tokens)
            return ProviderRequest(provider="openai", model=active_model, payload=payload, used_ocr_fallback=False)
        if provider == "anthropic":
            payload = build_anthropic_payload(prompt, image_paths, active_model, max_tokens=max_tokens)
            return ProviderRequest(provider="anthropic", model=active_model, payload=payload, used_ocr_fallback=False)

    # OCR fallback path
    ocr_texts = extract_text_from_images(image_paths)
    augmented = _inject_ocr_text(prompt, ocr_texts)
    return ProviderRequest(
        provider=provider,
        model=active_model,
        payload=_text_only_payload(provider, active_model, augmented, max_tokens),
        used_ocr_fallback=True,
        ocr_text=augmented,
    )


async def call_provider(req: ProviderRequest, *, timeout_s: float = 60.0) -> str:
    """Optional minimal HTTP caller (use your existing provider layer if you have one)."""
    if req.provider == "openai":
        # Choose endpoint based on style
        if _openai_style() == "chat_completions":
            return await _call_openai("/v1/chat/completions", req.payload, timeout_s=timeout_s, parse="chat")
        return await _call_openai("/v1/responses", req.payload, timeout_s=timeout_s, parse="responses")
    if req.provider == "anthropic":
        return await _call_anthropic(req.payload, timeout_s=timeout_s)
    raise ValueError(f"Unsupported provider: {req.provider}")


async def _call_openai(path: str, payload: dict[str, Any], *, timeout_s: float, parse: str) -> str:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com").rstrip("/")
    url = f"{base_url}{path}"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=timeout_s) as client:
        r = await client.post(url, headers=headers, json=payload)
        r.raise_for_status()
        data = r.json()

    if parse == "chat":
        return data["choices"][0]["message"]["content"]
    # responses
    # Newer Responses API provides output_text convenience; otherwise parse output blocks.
    if "output_text" in data and isinstance(data["output_text"], str):
        return data["output_text"]
    # Fallback parse
    parts = []
    for item in data.get("output", []):
        for c in item.get("content", []):
            if c.get("type") in ("output_text", "text") and "text" in c:
                parts.append(c["text"])
    return "".join(parts).strip()


async def _call_anthropic(payload: dict[str, Any], *, timeout_s: float) -> str:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    base_url = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/")
    url = f"{base_url}/v1/messages"

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    async with httpx.AsyncClient(timeout=timeout_s) as client:
        r = await client.post(url, headers=headers, json=payload)
        r.raise_for_status()
        data = r.json()

    parts = []
    for block in data.get("content", []):
        if block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "".join(parts).strip()
