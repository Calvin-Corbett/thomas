"""Model onboarding protocol helpers and compatibility probes."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
from dataclasses import dataclass, replace
from typing import Any
from urllib.parse import urlparse

from thomas.core.config import ModelConfig
from thomas.core.llm import LLMClient, LLMError
from thomas.models.discovery import ModelsHandshake, handshake_models_async

log = logging.getLogger(__name__)

_TOOL_SMOKE_NAME = "thomas_smoke_echo"
_TOOL_SMOKE_SPEC = [
    {
        "type": "function",
        "function": {
            "name": _TOOL_SMOKE_NAME,
            "description": "Echo a short message used for a tool-calling smoke test.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {"type": "string"},
                },
                "required": ["message"],
                "additionalProperties": False,
            },
        },
    }
]
_TOOL_SMOKE_MESSAGES = [
    {
        "role": "system",
        "content": (
            "You are running a tool-calling smoke test. " f"You must call the '{_TOOL_SMOKE_NAME}' tool exactly once."
        ),
    },
    {
        "role": "user",
        "content": "Call the smoke-test tool now with message='ok'. Do not answer in plain text.",
    },
]


@dataclass(frozen=True)
class ToolSmokeResult:
    """Result of a synthetic tool-calling probe."""

    ok: bool
    status: str  # ok | skipped | no_tool_call | invalid_tool | invalid_args | error
    error: str | None = None
    tool_name: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": bool(self.ok),
            "status": str(self.status),
            "error": str(self.error) if self.error else None,
            "tool_name": str(self.tool_name),
        }


@dataclass(frozen=True)
class ModelValidationReport:
    """Combined profile validation report used by onboarding checks."""

    profile: str
    provider: str
    handshake: ModelsHandshake
    tool_smoke: ToolSmokeResult
    ok: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": str(self.profile),
            "provider": str(self.provider),
            "ok": bool(self.ok),
            "handshake": self.handshake.to_dict(),
            "tool_smoke": self.tool_smoke.to_dict(),
        }


def _is_loopback_host(host: str) -> bool:
    h = str(host or "").strip().lower()
    if not h:
        return False
    if h in ("localhost", "127.0.0.1", "::1"):
        return True
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return False
    return bool(ip.is_loopback)


def is_loopback_base_url(base_url: str) -> bool:
    """Return True when base_url points to localhost/loopback."""
    try:
        u = urlparse(str(base_url or "").strip())
    except (ValueError, TypeError):
        return False
    return _is_loopback_host(u.hostname or "")


def profile_prefers_always_tools(cfg: ModelConfig) -> bool:
    """Whether this profile should keep tools exposed in auto policy."""
    provider = str(cfg.provider or "").strip().lower()
    if provider in ("anthropic", "codex"):
        return True
    if provider == "openai_compat":
        return not is_loopback_base_url(cfg.base_url)
    return False


async def run_tool_smoke_async(
    cfg: ModelConfig,
    *,
    timeout_s: float = 20.0,
) -> ToolSmokeResult:
    """Run a synthetic tool-call probe against one profile."""
    provider = str(cfg.provider or "").strip().lower()
    if provider == "codex":
        return ToolSmokeResult(
            ok=True,
            status="skipped",
            error="Codex tool execution is handled by the app-server bridge.",
        )

    llm_cfg = replace(
        cfg,
        temperature=0.0,
        max_tokens=max(64, min(int(cfg.max_tokens or 256), 256)),
        timeout_s=max(float(cfg.timeout_s or 1.0), float(timeout_s)),
    )
    llm = LLMClient(llm_cfg)
    try:
        result = await asyncio.wait_for(
            llm.chat(_TOOL_SMOKE_MESSAGES, tools=_TOOL_SMOKE_SPEC),
            timeout=float(timeout_s),
        )
    except asyncio.TimeoutError:
        return ToolSmokeResult(ok=False, status="error", error=f"tool smoke timed out after {timeout_s:.1f}s")
    except LLMError as e:
        msg = str(e).strip() or "LLM error"
        return ToolSmokeResult(ok=False, status="error", error=msg)
    except Exception as e:
        return ToolSmokeResult(ok=False, status="error", error=f"{type(e).__name__}: {e}")
    finally:
        try:
            await llm.close()
        except (ConnectionError, TimeoutError):
            log.debug("Failed to close LLM client after tool smoke for %s", cfg.name, exc_info=True)

    calls = result.get("tool_calls") or []
    if not isinstance(calls, list) or not calls:
        text = str(result.get("text") or "").strip()
        hint = f"model returned text instead: {text[:220]!r}" if text else "no tool calls returned"
        return ToolSmokeResult(ok=False, status="no_tool_call", error=hint)

    first = calls[0] if isinstance(calls[0], dict) else {}
    name = str(first.get("name") or "").strip()
    if name != _TOOL_SMOKE_NAME:
        return ToolSmokeResult(
            ok=False,
            status="invalid_tool",
            error=f"expected tool '{_TOOL_SMOKE_NAME}', got '{name or '(empty)'}'",
            tool_name=name,
        )

    args_raw = first.get("arguments", "")
    try:
        if isinstance(args_raw, str):
            parsed = json.loads(args_raw) if args_raw.strip() else {}
        elif isinstance(args_raw, dict):
            parsed = args_raw
        else:
            parsed = json.loads(str(args_raw)) if str(args_raw).strip() else {}
    except Exception as e:
        return ToolSmokeResult(
            ok=False,
            status="invalid_args",
            error=f"tool arguments were not valid JSON: {type(e).__name__}: {e}",
            tool_name=name,
        )

    if not isinstance(parsed, dict):
        return ToolSmokeResult(
            ok=False,
            status="invalid_args",
            error=f"tool arguments should be an object, got {type(parsed).__name__}",
            tool_name=name,
        )

    return ToolSmokeResult(ok=True, status="ok", tool_name=name)


async def validate_model_profile_async(
    cfg: ModelConfig,
    *,
    handshake_timeout_s: float = 3.0,
    tool_timeout_s: float = 20.0,
    run_tool_smoke: bool = True,
) -> ModelValidationReport:
    """Validate one configured profile for onboarding readiness."""
    handshake = await handshake_models_async(cfg, timeout_s=float(handshake_timeout_s))

    tool_smoke = ToolSmokeResult(ok=True, status="skipped", error="tool smoke disabled")
    if run_tool_smoke:
        if handshake.status in ("auth_error", "offline", "error"):
            tool_smoke = ToolSmokeResult(
                ok=False,
                status="error",
                error=f"skipped due handshake status '{handshake.status}'",
            )
        else:
            tool_smoke = await run_tool_smoke_async(cfg, timeout_s=float(tool_timeout_s))

    handshake_ok = handshake.status in ("ok", "unsupported")
    overall_ok = handshake_ok and bool(tool_smoke.ok)

    return ModelValidationReport(
        profile=str(cfg.name),
        provider=str(cfg.provider),
        handshake=handshake,
        tool_smoke=tool_smoke,
        ok=overall_ok,
    )
