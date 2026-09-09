"""Duck-typed budget hooks used by provider transports without server imports."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class _BoundBudgetAttempt:
    scope: Any
    lease: Any
    output_cap: int


class LLMBudgetMixin:
    """Attach one request-scoped budget authority to physical provider attempts."""

    _budget_scope: Any = None

    def set_budget_scope(self, scope: Any) -> Any:
        previous = getattr(self, "_budget_scope", None)
        self._budget_scope = scope
        return previous

    async def begin_budget_attempt(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> Any:
        scope = getattr(self, "_budget_scope", None)
        if scope is None:
            return None
        start = asyncio.create_task(
            scope.begin_attempt(
                client=self,
                messages=messages,
                tools=tools,
                configured_max_tokens=max(1, int(getattr(self.config, "max_tokens", 0) or 1)),
            )
        )
        try:
            lease = await asyncio.shield(start)
        except asyncio.CancelledError:
            lease = await start
            await scope.abort_attempt(lease)
            raise
        return _BoundBudgetAttempt(scope=scope, lease=lease, output_cap=int(lease.output_cap))

    async def finish_budget_attempt(self, lease: Any) -> None:
        if lease is None:
            return
        settlement = asyncio.create_task(lease.scope.finish_attempt(client=self, lease=lease.lease))
        try:
            await asyncio.shield(settlement)
        except asyncio.CancelledError:
            await settlement
            raise

    async def abort_budget_attempt(self, lease: Any) -> None:
        if lease is not None:
            await lease.scope.abort_attempt(lease.lease)


__all__ = ["LLMBudgetMixin"]
