"""The models slot: where every part of Thomas gets a model client.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md (slots). A slot is one thing the whole program
shares, filled by one provider, and a row may add to it but never replace it.

``Models.open`` builds the same ``LLMClient`` the call site built before and nothing more, so moving a site onto the slot
changes no behaviour. Any process can use it (``from thomas.core.llm_slot import models``): there is no kernel and no
server in the way, which is why the slot lives here and not on the kernel alone. The kernel carries the same object
under ``LLM`` for rows that ask for it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any, Protocol, runtime_checkable

from thomas.core import llm_adapters

#: ``(config, profile) -> config`` with its key embedded. Same shape as the Codex resolver in ``codex_auth``.
CredentialResolver = Callable[[Any, str], Any]


@runtime_checkable
class ModelClient(Protocol):
    """What callers may touch on a client. ``LLMClient`` satisfies it, and a test proves that."""

    config: Any
    session_usage: Any

    def stream_chat(self, messages: Any, tools: Any = None, *, turn_user_content: Any = None) -> AsyncIterator[Any]: ...

    async def chat(self, messages: Any, tools: Any = None) -> dict[str, Any]: ...

    async def close(self) -> None: ...

    def reset_runtime_trace(self) -> None: ...

    def runtime_trace(self) -> dict[str, Any]: ...

    def set_budget_scope(self, scope: Any) -> Any: ...


# Process-wide, like the Codex resolver. Tests build many apps, so each registration returns its undo and the newest one
# still registered answers.
_resolvers: list[CredentialResolver] = []


class Models:
    def open(self, config: Any, /, *, default: Any = None, **options: Any) -> ModelClient:
        """``LLMClient(config, **options)`` and nothing more.

        ``default`` is the caller's own name for the class, so a test that patches that name still reaches the patch,
        as ``build_agent_loop`` does. Without it the class is looked up here at call time.
        """
        if default is None:
            from thomas.core import llm_client

            default = llm_client.LLMClient
        return default(config, **options)

    def profile(
        self,
        app_config: Any,
        name: str | None = None,
        /,
        *,
        default: Any = None,
        failover_enabled: bool | None = None,
        **options: Any,
    ) -> ModelClient:
        """A named profile with its credentials and its failover chain.

        ``failover_enabled=None`` means what chat means by it: ``failover.enabled`` and ``chat_auto_failover``. A caller
        that has always read only ``failover.enabled`` passes that value, so its behaviour does not change by accident.
        Keyword options win over what is worked out here.
        """
        profile = str(name or getattr(app_config, "default_model", "") or "").strip()
        model_cfg = self._resolved(app_config.get_model(profile or None), profile)
        failover = app_config.failover
        if failover_enabled is None:
            failover_enabled = bool(failover.enabled and getattr(failover, "chat_auto_failover", False))
        chain = app_config.failover_chain(profile)
        settings: dict[str, Any] = {
            "fallback_configs": [self._resolved(cfg, str(getattr(cfg, "name", "") or "")) for cfg in chain],
            "failover_enabled": bool(failover_enabled),
            "failover_cooldown_s": failover.cooldown_seconds,
            "failover_on_auth_error": failover.fallback_on_auth_error,
        }
        settings.update(options)
        return self.open(model_cfg, default=default, **settings)

    @asynccontextmanager
    async def session(self, config: Any, /, **options: Any) -> AsyncIterator[ModelClient]:
        """``open``, then ``close`` on the way out: for the one-shot sites that leave a client open today."""
        client = self.open(config, **options)
        try:
            yield client
        finally:
            await client.close()

    def credentials(self, resolve: CredentialResolver) -> Callable[[], None]:
        """Register ``(config, profile) -> config`` with its key embedded, and return the undo."""
        if not callable(resolve):
            raise TypeError("a credentials resolver must be callable")
        _resolvers.append(resolve)

        def undo() -> None:
            if resolve in _resolvers:
                _resolvers.remove(resolve)

        return undo

    def adapter(self, provider: str, stream: llm_adapters.ProviderStream) -> Callable[[], None]:
        """Add a provider's stream. Returns the undo, for ``ctx.effect``."""
        return llm_adapters.register(provider, stream)

    def adapter_for(self, provider: str) -> llm_adapters.ProviderStream | None:
        """The stream a row registered for *provider* right now, or None when the built-in providers answer."""
        return llm_adapters.lookup(provider)

    @staticmethod
    def _resolved(cfg: Any, profile: str) -> Any:
        if cfg is None or not _resolvers:
            return cfg
        return _resolvers[-1](cfg, profile)


_models = Models()


def models() -> Models:
    return _models
