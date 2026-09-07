"""Registers a ChatGPT/Codex access-token resolver for headless Thomas runs.

The Codex transport takes its bearer token from ``ModelConfig.api_key`` and
only falls back to ``thomas.core.codex_auth.resolve_access_token`` when that is
empty (``thomas/core/llm_streaming.py:336-338``). No resolver is registered
outside the HTTP server, so a bare ``thomas chat`` on the ``openai_codex``
provider fails with "ChatGPT OAuth is not connected".

This module supplies that resolver. Install it into a benchmark container as
``sitecustomize.py`` on ``PYTHONPATH`` so it loads before the CLI starts, and
leave ``api_key`` unset so the fallback is actually reached.

It deliberately holds **only an access token**, never a refresh token. The
refresh grant rotates: an exchange can return a new refresh token and invalidate
the one presented. Refreshing inside a per-trial container would strand each
rotation in a container that is then destroyed, so the next trial would present
an invalidated token and every later trial would fail. The host-side broker in
``agent.py`` therefore does the refreshing and injects a fresh access token per
trial.

That also keeps the longer-lived secret off the task environment -- but only
because the adapter reads it from the host process environment and *refuses* it
when passed with Harbor's ``--ae``. Values given to ``--ae`` are applied to every
``exec`` as a scoped overlay and handed to the container, so passing the refresh
token that way would put it in front of an agent running as root with a shell and
open egress. The access token injected here is short-lived by design, and is
scrubbed from the published artifacts after the run.
"""

from __future__ import annotations

import os

ACCESS_TOKEN_ENV = "THOMAS_CODEX_ACCESS_TOKEN"


async def resolve_access_token(profile: str | None = None) -> str:
    """Return the access token injected for this trial."""
    token = os.environ.get(ACCESS_TOKEN_ENV, "").strip()
    if not token:
        raise RuntimeError(
            f"{ACCESS_TOKEN_ENV} is unset; the harness adapter did not inject a "
            "Codex access token for this trial."
        )
    return token


def install() -> bool:
    """Register the resolver. Returns False if Thomas is not importable yet."""
    try:
        from thomas.core.codex_auth import register_access_token_resolver
    except Exception:
        return False
    register_access_token_resolver(resolve_access_token)
    return True


# Runs on interpreter startup when installed as sitecustomize.py.
install()
