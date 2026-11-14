"""Where each connection's current model list comes from.

One reader per kind of connection, all answering in the same shape, so the
catalog (thomas/models/catalog.py) merges them without knowing which is which.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from thomas.core.claude_plan import runs_on_claude_plan
from thomas.core.config import ModelConfig

TokenFn = Callable[[str], Awaitable[str]]

# Named by provider, not by having (or lacking) a base_url: Ollama and LM Studio
# profiles are local whatever host string they carry.
_LOCAL_PROVIDERS = frozenset({"ollama", "lmstudio", "lm_studio"})


@dataclass(frozen=True)
class ListedModel:
    id: str
    display_name: str = ""
    description: str = ""
    order: int = 1000
    hidden: bool = False
    retires_at: str = ""
    replacement: str = ""
    context_window: int | None = None


@dataclass(frozen=True)
class SourceAnswer:
    ok: bool
    source: str
    models: tuple[ListedModel, ...] = ()
    error: str = ""
    etag: str = ""
    not_modified: bool = False


def is_local_profile(provider: str, cfg: ModelConfig) -> bool:
    """A profile Thomas can ask without a key: a local runtime.

    Ollama and LM Studio are local by provider name whatever base_url they
    carry; anything else counts as local only when its base_url genuinely
    points at loopback, so a misconfigured cloud profile is never treated
    as free to ask.
    """
    if provider in _LOCAL_PROVIDERS:
        return True
    from thomas.models.protocol import is_loopback_base_url

    return is_loopback_base_url(str(getattr(cfg, "base_url", "") or ""))


# Kept for any existing caller still importing the old private name.
_is_local_profile = is_local_profile


async def list_profile_models(
    profile: str,
    cfg: ModelConfig,
    *,
    codex_token: TokenFn | None = None,
    previous_etag: str = "",
    timeout_s: float = 10.0,
) -> SourceAnswer:
    """Ask the right reader for *profile*'s current list."""
    provider = str(cfg.provider or "").strip().lower().replace("-", "_")
    if provider == "openai_codex":
        from thomas.models.sources.codex_signin import list_codex_models

        return await list_codex_models(profile, codex_token=codex_token, etag=previous_etag, timeout_s=timeout_s)
    if runs_on_claude_plan(provider, str(cfg.api_key or "")):
        # No key, so this profile is served by your Claude plan through the CLI —
        # in Chat as well as in Build since 2026-09-25. One predicate decides
        # that everywhere (thomas/core/claude_plan.py), so the list offered and
        # the transport that runs it can never disagree about who serves this
        # profile.
        from thomas.models.sources.claude_cli import list_claude_cli_models

        return list_claude_cli_models()
    if not is_local_profile(provider, cfg) and not str(cfg.api_key or "").strip():
        # A keyless cloud profile (OpenRouter, DeepInfra, ...) answers its whole
        # public catalog with no key at all -- hundreds of rows the picker would
        # show as unusable. Never ask; say why up front instead.
        return SourceAnswer(ok=False, source="provider", error=f"no API key for {profile}")
    from thomas.models.sources.generic import list_generic_models

    return await list_generic_models(cfg, timeout_s=timeout_s)
