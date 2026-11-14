"""One place a model config gets its API key or ChatGPT sign-in token.

The server (``_model_cfg_with_secrets``) and the worker (``_embed_secrets``) each kept their own copy of this. They
agreed on the key lookup and the ChatGPT token, and differed in three small ways, recorded on ``embed_credentials``.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Any

log = logging.getLogger(__name__)


def _provider_of(cfg: Any) -> str:
    return str(getattr(cfg, "provider", "") or "").strip().lower().replace("-", "_")


def embed_credentials(
    model_cfg: Any,
    profile: str,
    secret_store: Any,
    *,
    profile_name_fallback: bool = False,
) -> Any:
    """A copy of ``model_cfg`` with its API key, or its ChatGPT token, embedded. ``None`` for no config.

    ``profile_name_fallback`` is the worker's rule: a config with no ``api_key_secret_name`` looks its key up under the
    profile name (then its own name), except ChatGPT, which signs in with a token. The server leaves it off.
    The two old copies also differed in what counted as "no store" (the server skipped any falsy store, the worker only
    ``None``) and in which errors the token read swallowed (the server also swallowed ``RuntimeError``). This keeps the
    server's on both, which is wider and harmless for the worker.
    """
    if not model_cfg:
        return None
    cfg_copy = dataclasses.replace(model_cfg)
    if not secret_store:
        return cfg_copy
    provider = _provider_of(cfg_copy)
    secret_name = str(getattr(cfg_copy, "api_key_secret_name", "") or "").strip()
    if not secret_name and profile_name_fallback and provider != "openai_codex":
        secret_name = str(profile or getattr(cfg_copy, "name", "") or "").strip()
    if secret_name:
        api_key = secret_store.get(secret_name)
        if api_key:
            cfg_copy.api_key = api_key
    if provider == "openai_codex":
        name = str(profile or getattr(cfg_copy, "name", "") or "chatgpt")
        try:
            from thomas.server.openai_codex_oauth import access_token_from_store, has_openai_codex_token

            access_token = access_token_from_store(secret_store, name)
            if access_token:
                cfg_copy.api_key = access_token
            cfg_copy._openai_codex_token_ready = bool(access_token or has_openai_codex_token(secret_store, name))
        except (AttributeError, ImportError, KeyError, OSError, RuntimeError, TypeError, ValueError) as e:
            log.debug("Failed to resolve ChatGPT OAuth token for %s: %s", name, e)
    return cfg_copy
