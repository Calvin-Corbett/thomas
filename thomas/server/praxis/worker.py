"""Server-owned read/review/verify agents for one Build run."""

from __future__ import annotations

import math
import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from thomas.core.file_access import READ_ONLY
from thomas.server.app_keys import APP_CONFIG, APP_SECRETS
from thomas.server.chat_runtime_policy_model import model_endpoint_is_local
from thomas.server.model_runtime_receipt import validate_model_runtime_receipt
from thomas.server.worker_runtime import run_agent_worker_events

_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_CREDENTIAL_ID = re.compile(r"^[a-z0-9_]+(?::[0-9a-f]{20})?$")
_QUOTA_KINDS = frozenset({"clean", "transient", "quota", "other"})
_QUOTA_REASONS = frozenset({"provider_quota", "long_reset", "429_streak", "rate_limit"})
_SAFE_SELECTION_ERRORS = frozenset(
    {
        "invalid Build child model choice",
        "Build child model profile is not configured",
        "invalid Build child model ID",
        "Build child model account is not connected",
    }
)


def _selected_model(
    app: Any, default_profile: str, default_model: str, choice: dict[str, Any] | None
) -> tuple[str, str, Any]:
    if choice is not None and (not isinstance(choice, dict) or set(choice) - {"profile", "model_id"}):
        raise ValueError("invalid Build child model choice")
    profile = str((choice or {}).get("profile") or default_profile).strip()
    cfg = app[APP_CONFIG]
    model_cfg = cfg.models.get(profile)
    if model_cfg is None:
        raise ValueError("Build child model profile is not configured")
    inherited_model = default_model if profile == default_profile else model_cfg.model
    model_id = str((choice or {}).get("model_id") or inherited_model or model_cfg.model).strip()
    if not _MODEL_ID.fullmatch(model_id):
        raise ValueError("invalid Build child model ID")
    provider = str(getattr(model_cfg, "provider", "") or "").strip().lower().replace("-", "_")
    secrets = app.get(APP_SECRETS)
    if provider == "openai_codex":
        from thomas.server.openai_codex_oauth import has_openai_codex_token

        connected = has_openai_codex_token(secrets, profile)
    elif model_endpoint_is_local(model_cfg):
        connected = True
    else:
        secret_name = str(getattr(model_cfg, "api_key_secret_name", "") or "").strip()
        connected = bool(getattr(model_cfg, "api_key", "")) or bool(
            secrets is not None and (secrets.has(secret_name) if secret_name else secrets.has(profile))
        )
    if not connected:
        raise ValueError("Build child model account is not connected")
    return profile, model_id, model_cfg


def _strict_model_policy(model_cfg: Any) -> dict[str, Any]:
    """Pin this child to one account; provider failover must not substitute it."""
    return {
        "temperature": float(getattr(model_cfg, "temperature", 0.1)),
        "top_p": float(getattr(model_cfg, "top_p", 0.95)),
        "max_output_tokens": int(getattr(model_cfg, "max_tokens", 4096)),
        "reasoning_effort": str(getattr(model_cfg, "reasoning_effort", "") or ""),
        "frequency_penalty": 0.0,
        "presence_penalty": 0.0,
        "deterministic_seed": None,
        "json_mode": False,
        "stop_sequences": (),
        "max_retries": 1,
        "retry_backoff_s": 0.0,
        "failover_enabled": False,
        "failover_on_auth_error": False,
        "failover_cooldown_s": 0,
        "failover_profiles": (),
    }


def build_read_child_runner(app: Any, project: Path, *, model_id: str, run_id: str, profile: str = "openai_codex"):
    async def run(
        child_id: str, kind: str, title: str, brief: str, model_choice: dict[str, Any] | None = None
    ) -> AsyncIterator[dict[str, Any]]:
        try:
            chosen_profile, chosen_model, model_cfg = _selected_model(app, profile, model_id, model_choice)
        except (KeyError, ValueError, TypeError, AttributeError) as exc:
            message = str(exc)
            yield {
                "type": "error",
                "error": message if message in _SAFE_SELECTION_ERRORS else "Build child model selection is unavailable",
                "retryable": False,
            }
            return
        instructions = (
            f"You are a {kind} agent in a larger Build run. Work on the assigned brief and report evidence. "
            "You have read-only project access. Do not claim that you edited or tested files unless a tool did so."
        )
        receipt_seen = False
        async for event in run_agent_worker_events(
            app,
            prompt=brief,
            instructions=instructions,
            work_dir=project,
            profile=chosen_profile,
            model_id=chosen_model,
            role=None,
            execution_id=f"{run_id}:{child_id}",
            autonomy_level=3,
            file_access=READ_ONLY,
            tools_enabled=True,
            can_spawn=False,
            runtime_policy={"model": _strict_model_policy(model_cfg)},
        ):
            if event.get("type") == "model_runtime":
                receipt = validate_model_runtime_receipt(
                    event.get("runtime"),
                    requested_profile=chosen_profile,
                    requested_model_id=chosen_model,
                )
                if receipt is None:
                    yield {
                        "type": "error",
                        "error": "Build child model receipt did not match its selection",
                        "retryable": False,
                    }
                    return
                receipt_seen = True
                event = {"type": "model_runtime", "runtime": receipt, "model_used": receipt["active"]["model"]}
            elif event.get("type") == "done" and not receipt_seen:
                yield {
                    "type": "error",
                    "error": "Build child completed without a verified model receipt",
                    "retryable": False,
                }
                return
            elif event.get("type") == "error":
                # Provider exceptions may contain authentication headers or
                # endpoint query strings. Keep retry/quota evidence, not prose.
                status = event.get("provider_status")
                safe_status = status if isinstance(status, int) and 100 <= status <= 599 else None
                quota = event.get("quota") if isinstance(event.get("quota"), dict) else {}
                credential = event.get("provider_credential")
                safe_credential = (
                    credential if isinstance(credential, str) and _CREDENTIAL_ID.fullmatch(credential) else ""
                )
                safe_quota = {}
                kind_value = quota.get("kind")
                reason_value = quota.get("reason")
                retry_at = quota.get("retry_at")
                if isinstance(kind_value, str) and kind_value in _QUOTA_KINDS:
                    safe_quota["kind"] = kind_value
                if isinstance(reason_value, str) and reason_value in _QUOTA_REASONS:
                    safe_quota["reason"] = reason_value
                if isinstance(retry_at, (int, float)) and math.isfinite(retry_at):
                    safe_quota["retry_at"] = retry_at
                event = {
                    "type": "error",
                    "error": (
                        "Build child provider HTTP 401: "
                        + (
                            "live Codex login revoked or invalidated"
                            if "the live codex login was revoked or invalidated"
                            in str(event.get("error") or "").lower()
                            else "live Codex login expired"
                            if "the live codex login was expired" in str(event.get("error") or "").lower()
                            else "live Codex login rejected during token refresh"
                            if "token refresh failed with http 401" in str(event.get("error") or "").lower()
                            else "live Codex login also held the rejected stored token"
                            if "live codex login still contains the rejected stored token"
                            in str(event.get("error") or "").lower()
                            else "different stored token revoked or invalidated"
                            if "different stored token was also rejected" in str(event.get("error") or "").lower()
                            and "revoked or invalidated" in str(event.get("error") or "").lower()
                            else "different stored token expired"
                            if "different stored token was also rejected" in str(event.get("error") or "").lower()
                            and "expired" in str(event.get("error") or "").lower()
                            else "different stored token rejected"
                            if "different stored token was also rejected" in str(event.get("error") or "").lower()
                            else "access token revoked or invalidated"
                            if "revoked or invalidated" in str(event.get("error") or "").lower()
                            else "access token expired"
                            if "expired" in str(event.get("error") or "").lower()
                            else "access token rejected"
                        )
                        if safe_status == 401
                        else f"Build child provider HTTP {safe_status}"
                        if safe_status
                        else "Build child provider request failed"
                    ),
                    "retryable": safe_status != 401 and bool(event.get("retryable")),
                    "provider_status": safe_status,
                    "provider_credential": safe_credential,
                    "quota": safe_quota,
                }
            yield event

    return run
