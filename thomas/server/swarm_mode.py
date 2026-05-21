"""Compatibility shim for legacy swarm-mode import paths.

The swarm implementation moved, but tests and integration code still patch
`thomas.server.swarm_mode.SwarmOrchestrator` and
`thomas.server.swarm_mode.handle_swarm_chat`.
"""

from __future__ import annotations

from typing import Any

try:
    from thomas.agent.swarm import SwarmOrchestrator as SwarmOrchestrator
except Exception:  # pragma: no cover - defensive fallback for partial installs

    class SwarmOrchestrator:  # type: ignore[no-redef]
        """Fallback placeholder when swarm runtime dependencies are unavailable."""

        def __init__(self, *_args: Any, **_kwargs: Any) -> None:  # noqa: D401
            raise RuntimeError("SwarmOrchestrator is unavailable in this runtime")


async def handle_swarm_chat(*_args: Any, **_kwargs: Any):
    """Legacy entrypoint retained for monkeypatch compatibility in tests."""
    raise RuntimeError("handle_swarm_chat implementation moved; patch this symbol in tests")


__all__ = ["SwarmOrchestrator", "handle_swarm_chat"]
