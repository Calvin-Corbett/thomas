"""Shared, fail-closed runtime policy for every Thomas chat execution path.

Settings are server authority.  A request may narrow a saved policy (for
example by disabling network access for one turn), but it must never widen it.
The resolved object is immutable so foreground specialists, inline actions,
and background workers all receive the same decision.
"""

from __future__ import annotations

import ipaddress
from dataclasses import asdict, dataclass, replace
from typing import Any
from urllib.parse import urlparse

from thomas.core.autonomy import clamp_autonomy_level
from thomas.server.chat_tool_policy import (
    PolicyToolRegistryView,
    ToolRuntimePolicy,
    canonical_tool_name,
    tool_policy_from_payload,
)


class ChatRuntimePolicyError(RuntimeError):
    """Raised when saved chat policy cannot be loaded safely."""


def _csv_lines(value: Any, *, lower: bool = False) -> tuple[str, ...]:
    text = str(value or "").replace("\r", "\n")
    values = tuple(item.strip() for item in text.replace("\n", ",").split(",") if item.strip())
    return tuple(item.casefold() for item in values) if lower else values


def _autonomy_level(value: Any, *, default: int) -> int:
    text = str(value or "").strip().upper()
    if text.startswith("L"):
        text = text[1:]
    return clamp_autonomy_level(text, default=default)


def _companion_request(payload: dict[str, Any]) -> bool:
    values = (str(payload.get(key) or "").strip().casefold() for key in ("channel", "source", "client", "surface"))
    return any("companion" in value or "infinite" in value for value in values)


def model_endpoint_is_local(model_cfg: Any) -> bool:
    provider = str(getattr(model_cfg, "provider", "") or "").strip().casefold().replace("-", "_")
    endpoint = str(getattr(model_cfg, "base_url", "") or "").strip()
    if not endpoint:
        return provider in {"local", "ollama", "llama_cpp", "lmstudio", "lm_studio"}
    host = str(urlparse(endpoint).hostname or "").strip().casefold()
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@dataclass(frozen=True)
class ModelRuntimePolicy:
    temperature: float
    top_p: float
    max_output_tokens: int
    reasoning_effort: str
    frequency_penalty: float
    presence_penalty: float
    deterministic_seed: int | None
    json_mode: bool
    stop_sequences: tuple[str, ...]
    max_retries: int
    retry_backoff_s: float
    failover_enabled: bool
    failover_on_auth_error: bool
    failover_cooldown_s: int
    failover_profiles: tuple[str, ...]

    @property
    def request_overrides(self) -> dict[str, Any]:
        overrides: dict[str, Any] = {
            "frequency_penalty": self.frequency_penalty,
            "presence_penalty": self.presence_penalty,
            "json_mode": self.json_mode,
        }
        if self.deterministic_seed is not None:
            overrides["seed"] = self.deterministic_seed
        if self.stop_sequences:
            overrides["stop"] = list(self.stop_sequences)
        return overrides

    def apply(self, model_cfg: Any, *, model_id: str = "", reasoning_effort: str = "") -> Any:
        updates = {
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_output_tokens,
            "reasoning_effort": reasoning_effort or self.reasoning_effort,
        }
        if model_id:
            updates["model"] = model_id
        supported = {key: value for key, value in updates.items() if hasattr(model_cfg, key)}
        return replace(model_cfg, **supported) if supported else model_cfg


@dataclass(frozen=True)
class MemoryRuntimePolicy:
    enabled: bool
    include_thread: bool
    include_global: bool
    include_profile: bool
    pins_only: bool
    retrieval_top_k: int
    decay_half_life_hours: float
    context_budget: int
    pinned_context: str


@dataclass(frozen=True)
class QualityRuntimePolicy:
    enforce: bool
    require_verification_for_coding: bool
    require_tests_for_code_edits: bool
    require_monolith_guard_for_coding: bool
    max_agent_iterations: int


@dataclass(frozen=True)
class CostRuntimePolicy:
    session_token_budget: int
    daily_token_budget: int
    throttle_on_budget: bool


@dataclass(frozen=True)
class ResolvedChatRuntimePolicy:
    profile: str
    model_id: str
    autonomy_level: int
    mode: str
    token_economy: str
    system_prompt: str
    profile_type: str
    review_depth: str
    non_coder_profile: bool
    local_only: bool
    model: ModelRuntimePolicy
    tools: ToolRuntimePolicy
    memory: MemoryRuntimePolicy
    quality: QualityRuntimePolicy
    cost: CostRuntimePolicy

    def assert_profile_allowed(self, config: Any, profile: str | None = None) -> None:
        selected = str(profile or self.profile or "").strip()
        if not self.local_only:
            return
        models = getattr(config, "models", {}) or {}
        model_cfg = models.get(selected)
        if model_cfg is None or not model_endpoint_is_local(model_cfg):
            raise PermissionError("local_only_mode blocks non-local model endpoints")

    def filter_failovers(self, config: Any, fallback_cfgs: list[Any]) -> list[Any]:
        configured = list(fallback_cfgs or [])
        if self.model.failover_profiles:
            configured = []
            for profile in self.model.failover_profiles:
                if profile == self.profile or profile not in getattr(config, "models", {}):
                    continue
                configured.append(config.get_model(profile))
        if self.local_only:
            configured = [item for item in configured if model_endpoint_is_local(item)]
        return configured

    def instruction_context(self) -> str:
        instructions: list[str] = []
        if self.system_prompt:
            instructions.append(self.system_prompt)
        if self.memory.enabled and self.memory.pinned_context:
            instructions.append(f"Pinned user context:\n{self.memory.pinned_context}")
        if self.profile_type == "non_coder":
            instructions.append(
                "Use plain language, explain consequential choices, and verify the result before presenting it."
            )
        if self.review_depth == "technical":
            instructions.append("Use technical review depth and report concrete evidence and failure modes.")
        elif self.review_depth == "simple":
            instructions.append("Keep review explanations simple while preserving the underlying verification rigor.")
        return "\n\n".join(item.strip() for item in instructions if item.strip())

    def worker_payload(self) -> dict[str, Any]:
        return {
            "local_only": self.local_only,
            "model": asdict(self.model),
            "tools": asdict(self.tools),
            "memory": asdict(self.memory),
            "quality": asdict(self.quality),
            "cost": asdict(self.cost),
            "profile_type": self.profile_type,
            "review_depth": self.review_depth,
            "system_instructions": self.instruction_context(),
        }
