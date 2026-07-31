"""Validated settings contract for Forge Code dispatches.

Forge Code intentionally has a narrower capability envelope than general chat.
This module preserves every requested dial while separately reporting which
values the current executor applies, fixes to a safe value, or cannot honor.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

from thomas.core.file_access import file_access_spec, parse_file_access_level

# Wall-clock and repair budgets per token-economy dial — the single source of
# truth (forge_code_runner imports these). Real builds (games, web apps)
# regularly need >600s; a hard kill mid-build wastes the whole run and forces
# a from-scratch re-dispatch that costs more than letting it finish.
EXECUTION_TIMEOUTS_S = {"cheap": 600, "balanced": 1800, "max": 3600}
EXECUTION_MAX_FIX_ITERS = {"cheap": 1, "balanced": 2, "max": 3}


class ForgeCodeSettingsError(ValueError):
    """Raised when a Forge Code setting is malformed or unsupported."""


_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,119}$")
_REASONING = {"none", "low", "medium", "high", "xhigh", "max"}
_FILE_ACCESS = {"read_only", "workspace", "project", "pc", "full"}
_GUARDRAILS = {"open", "guarded", "fortress"}
_TOKEN_ECONOMY = {"cheap", "balanced", "max"}
_ENGINES = {"agent", "funnel"}
_GPT_CODE_CONTEXT_WINDOW = 200_000
_GPT_CODE_MAX_TOKENS = 16_384


def _choice(value: Any, *, default: str, allowed: set[str], name: str) -> str:
    normalized = str(value if value is not None else default).strip().lower()
    if normalized not in allowed:
        choices = ", ".join(sorted(allowed))
        raise ForgeCodeSettingsError(f"invalid {name}; expected one of: {choices}")
    return normalized


def _memory_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return True
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ForgeCodeSettingsError("invalid memory setting; expected a boolean")


def _autonomy_value(value: Any) -> int:
    try:
        autonomy = int(3 if value is None else value)
    except (TypeError, ValueError) as exc:
        raise ForgeCodeSettingsError("invalid autonomy_level; expected 1 through 4") from exc
    if autonomy not in {1, 2, 3, 4}:
        raise ForgeCodeSettingsError("invalid autonomy_level; expected 1 through 4")
    return autonomy


def _validated_model(value: Any, *, name: str) -> str:
    normalized = str(value or "").strip()
    if normalized and not _MODEL_ID.fullmatch(normalized):
        raise ForgeCodeSettingsError(f"invalid {name}")
    return normalized


@dataclass(frozen=True)
class ForgeCodeSettings:
    """One normalized Forge Code request and its honest capability report."""

    engine: str
    model: str
    model_id: str
    reasoning_effort: str
    autonomy_level: int
    file_access: str
    memory: bool
    guardrails: str
    token_economy: str
    family: str
    dispatch_model: str
    gpt_profile: str

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | None) -> ForgeCodeSettings:
        body = payload or {}
        engine = _choice(body.get("engine"), default="agent", allowed=_ENGINES, name="engine")
        # KNOWN TRAP, MEASURED 2026-07-31, deliberately not changed here.
        #
        # An unspecified model becomes `claude:sonnet`, and `family` is read off
        # that prefix, so the run dispatches to the CLAUDE CLI. That is fine when
        # the caller means it. It is confusing when the caller had nothing to
        # send:
        #
        #   the chat profile drifted to `local` with model_id ""
        #   -> the shell had no model to put in the payload
        #   -> this default made it claude:sonnet
        #   -> claude CLI, which was not logged in on this machine
        #   -> the run died with "Not logged in - Please run /login", exited 1,
        #      wrote nothing
        #
        # And the turn was labelled `qwen2.5-coder:7b`, the LOCAL profile's
        # configured model -- a model that had no part in the run. The report
        # names the profile's model while `family` decides the executor, and
        # nothing reconciles the two, so the owner is told a local qwen model
        # produced a failure that actually came from Claude.
        #
        # Two candidate fixes, both behaviour changes that deserve a decision
        # rather than a drive-by: refuse to invent a model when the caller sent
        # none (surfacing "no model selected" instead of silently choosing
        # Claude), or record the DISPATCHED model on the turn so the label
        # matches the executor. Left alone because picking one changes what runs.
        model = _validated_model(body.get("model") or "claude:sonnet", name="model")
        model_id = _validated_model(body.get("model_id"), name="model_id")
        reasoning = _choice(
            body.get("reasoning_effort", body.get("effort")),
            default="medium",
            allowed=_REASONING,
            name="reasoning_effort",
        )
        autonomy = _autonomy_value(body.get("autonomy_level"))
        file_access = _choice(body.get("file_access"), default="project", allowed=_FILE_ACCESS, name="file_access")
        memory = _memory_value(body.get("memory"))
        guardrails = _choice(
            body.get("thomas_guardrails", body.get("guardrails")),
            default="guarded",
            allowed=_GUARDRAILS,
            name="guardrails",
        )
        token_economy = _choice(
            body.get("token_economy"),
            default="balanced",
            allowed=_TOKEN_ECONOMY,
            name="token_economy",
        )

        lowered_model = model.lower()
        lowered_id = model_id.lower()
        gpt = lowered_id.startswith("gpt-") or lowered_model.startswith(("gpt-", "codex", "chatgpt", "openai_codex"))
        if gpt:
            exact_model = (
                model_id if lowered_id.startswith("gpt-") else (model if lowered_model.startswith("gpt-") else "")
            )
            return cls(
                engine,
                model,
                exact_model,
                reasoning,
                autonomy,
                file_access,
                memory,
                guardrails,
                token_economy,
                "gpt",
                "codex:gpt",
                "forgecode" if exact_model else "openai_codex",
            )

        variant = model_id or (model.split(":", 1)[1] if model.lower().startswith("claude:") else model)
        variant = variant or "sonnet"
        return cls(
            engine,
            model,
            model_id,
            reasoning,
            autonomy,
            file_access,
            memory,
            guardrails,
            token_economy,
            "claude",
            f"claude:{variant}",
            "",
        )

    def child_environment(self, base: dict[str, str] | None = None) -> dict[str, str]:
        """Return a child environment that applies an exact GPT model + effort.

        The temporary ``forgecode`` profile avoids mutating project config and is
        consumed only by the existing in-process AgentLoop dispatcher. Its profile
        name is an OAuth alias of ``openai_codex``, so it reuses the owner's
        existing ChatGPT connection without copying or exposing the token.
        """

        env = dict(base if base is not None else os.environ)
        if self.family == "gpt" and self.model_id:
            env["THOMAS_MODELS_FORGECODE_PROVIDER"] = "openai_codex"
            env["THOMAS_MODELS_FORGECODE_MODEL"] = self.model_id
            env["THOMAS_MODELS_FORGECODE_REASONING_EFFORT"] = self.reasoning_effort
            env["THOMAS_MODELS_FORGECODE_CONTEXT_WINDOW"] = str(_GPT_CODE_CONTEXT_WINDOW)
            env["THOMAS_MODELS_FORGECODE_MAX_TOKENS"] = str(_GPT_CODE_MAX_TOKENS)
        return env

    def requested(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "model": self.model,
            "model_id": self.model_id,
            "reasoning_effort": self.reasoning_effort,
            "autonomy_level": self.autonomy_level,
            "file_access": self.file_access,
            "memory": self.memory,
            "guardrails": self.guardrails,
            "token_economy": self.token_economy,
        }

    def execution_policy(self) -> dict[str, Any]:
        """Map every UI dial onto a bounded Forge executor behavior."""

        live_edit = self.autonomy_level >= 3 and self.file_access != "read_only"
        timeout = EXECUTION_TIMEOUTS_S[self.token_economy]
        max_fix_iters = EXECUTION_MAX_FIX_ITERS[self.token_economy]
        access_level = parse_file_access_level(self.file_access)
        guardrail_mode = {"open": "permissive", "guarded": "standard", "fortress": "strict"}[self.guardrails]
        return {
            "live_edit": live_edit,
            "history_enabled": self.memory,
            "allow_shell": bool(live_edit and self.guardrails == "open"),
            "timeout": timeout,
            "max_fix_iters": max_fix_iters,
            "sandbox_root": "selected_project",
            "file_access": self.file_access,
            "file_access_level": access_level,
            "guardrails": self.guardrails,
            "guardrail_mode": guardrail_mode,
        }

    def capability_report(self) -> dict[str, Any]:
        exact_gpt = self.family == "gpt" and bool(self.model_id)
        reasoning_status = "applied" if exact_gpt else "unsupported"
        reasoning_reason = (
            "applied to the isolated Forge GPT profile"
            if exact_gpt
            else "the current Claude executor does not expose a reasoning-effort control"
            if self.family == "claude"
            else "an exact GPT model_id is required to apply reasoning effort safely"
        )
        effective_model = self.model_id or self.dispatch_model
        policy = self.execution_policy()
        access_spec = file_access_spec(policy["file_access_level"])
        access_reason = {
            "read_only": "read-only planning is enforced; no filesystem writes are registered",
            "workspace": "writes are confined to the selected Code workspace",
            "project": "writes are confined to the selected project",
            "pc": "writes may reach the selected project and the user's home folders",
            "full": "writes may reach non-system paths; OS directories and Thomas runtime protections remain enforced",
        }[self.file_access]
        return {
            "requested": self.requested(),
            "effective": {
                "engine": self.engine,
                "model": effective_model,
                "reasoning_effort": self.reasoning_effort if reasoning_status == "applied" else None,
                "file_access": self.file_access,
                "file_access_level": policy["file_access_level"],
                "autonomy_level": self.autonomy_level,
                "memory": self.memory,
                "guardrails": self.guardrails,
                "token_economy": self.token_economy,
                "execution_policy": policy,
            },
            "support": {
                "engine": {"status": "applied"},
                "model": {
                    "status": "applied" if (self.family == "claude" or exact_gpt) else "configured_default",
                    "effective": effective_model,
                },
                "reasoning_effort": {"status": reasoning_status, "reason": reasoning_reason},
                "file_access": {
                    "status": "applied",
                    "effective": self.file_access,
                    "level": policy["file_access_level"],
                    "label": access_spec.name,
                    "reason": access_reason,
                },
                "autonomy_level": {
                    "status": "applied",
                    "effective": "edit_and_verify" if policy["live_edit"] else "plan_only",
                },
                "memory": {
                    "status": "applied",
                    "effective": "conversation_history" if self.memory else "off",
                },
                "guardrails": {
                    "status": "applied",
                    "effective": self.guardrails,
                    "mode": policy["guardrail_mode"],
                    "terminal": "enabled_in_selected_project" if policy["allow_shell"] else "engine_verification_only",
                },
                "token_economy": {
                    "status": "applied",
                    "effective": self.token_economy,
                    "timeout": policy["timeout"],
                    "max_fix_iters": policy["max_fix_iters"],
                },
            },
        }
