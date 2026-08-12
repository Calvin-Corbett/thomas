"""Per-provider-call enforcement for saved Chat token budgets."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

from thomas.server.chat_budget_ledger import ChatBudgetExceeded, ChatBudgetLedger, ChatBudgetTicket


def _usage_total(client: Any) -> int:
    usage = getattr(client, "session_usage", None)
    prompt = max(0, int(getattr(usage, "prompt_tokens", 0) or 0))
    completion = max(0, int(getattr(usage, "completion_tokens", 0) or 0))
    return max(prompt + completion, max(0, int(getattr(usage, "total_tokens", 0) or 0)))


def conservative_input_bound(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
) -> int:
    """Upper-bound text/tool tokens using canonical UTF-8 bytes plus framing."""
    payload = json.dumps(
        {"messages": messages, "tools": tools or []},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    ).encode("utf-8")
    remote_images = 0
    for message in messages:
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or str(block.get("type") or "") not in {"image_url", "input_image"}:
                continue
            raw_image = block.get("image_url")
            image_url = str(raw_image.get("url") if isinstance(raw_image, dict) else raw_image or "").strip()
            if image_url.startswith(("http://", "https://")):
                remote_images += 1
    framing = 64 + (16 * len(messages)) + (64 * len(tools or ())) + (32_768 * remote_images)
    return max(1, len(payload) + framing)


@dataclass(frozen=True)
class ChatBudgetLease:
    ticket: ChatBudgetTicket
    output_cap: int
    usage_before: int


@dataclass
class ChatBudgetScope:
    ledger: ChatBudgetLedger
    user_id: str
    session_id: str
    session_budget: int
    daily_budget: int
    throttle: bool
    prior_session_tokens: int = 0
    charged_tokens: int = field(default=0, init=False)

    async def _reserve(self, *, estimated_tokens: int, prior_session_tokens: int = 0) -> ChatBudgetTicket:
        reservation = asyncio.create_task(
            self.ledger.reserve(
                user_id=self.user_id,
                session_id=self.session_id,
                prior_session_tokens=prior_session_tokens,
                session_budget=self.session_budget,
                daily_budget=self.daily_budget,
                throttle=self.throttle,
                estimated_tokens=estimated_tokens,
            )
        )
        try:
            return await asyncio.shield(reservation)
        except asyncio.CancelledError:
            ticket = await reservation
            await self.ledger.release(ticket)
            raise

    async def preflight(self) -> None:
        ticket = await self._reserve(estimated_tokens=1, prior_session_tokens=self.prior_session_tokens)
        await self.ledger.release(ticket)

    async def begin_attempt(
        self,
        *,
        client: Any,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        configured_max_tokens: int,
    ) -> ChatBudgetLease:
        input_bound = conservative_input_bound(messages, tools)
        output_limit = max(1, int(configured_max_tokens or 1))
        ticket = await self._reserve(estimated_tokens=input_bound + output_limit)
        if ticket.hard_limit:
            remaining_output = ticket.reserved_tokens - input_bound
            if remaining_output < 1:
                await self.ledger.release(ticket)
                raise ChatBudgetExceeded("Token budget cannot fit this request context")
            output_limit = min(output_limit, remaining_output)
        return ChatBudgetLease(ticket=ticket, output_cap=output_limit, usage_before=_usage_total(client))

    async def finish_attempt(self, *, client: Any, lease: ChatBudgetLease) -> None:
        usage_delta = max(0, _usage_total(client) - lease.usage_before)
        actual = usage_delta or lease.ticket.reserved_tokens
        try:
            await self.ledger.settle(lease.ticket, actual)
        except ChatBudgetExceeded:
            self.charged_tokens += actual
            raise
        self.charged_tokens += actual

    async def abort_attempt(self, lease: ChatBudgetLease) -> None:
        await self.ledger.release(lease.ticket)

    async def reconcile_unscoped_usage(self, actual_tokens: int) -> None:
        missing = max(0, int(actual_tokens or 0) - self.charged_tokens)
        if not missing:
            return
        ticket = await self._reserve(
            estimated_tokens=missing,
            prior_session_tokens=self.prior_session_tokens,
        )
        try:
            await self.ledger.settle(ticket, missing)
        except ChatBudgetExceeded:
            self.charged_tokens += missing
            raise
        self.charged_tokens += missing


def scope_from_runtime_policy(
    ledger: ChatBudgetLedger,
    runtime_policy: dict[str, Any],
    *,
    user_id: str,
    session_id: str,
    prior_session_tokens: int = 0,
) -> ChatBudgetScope:
    cost = dict(runtime_policy.get("cost") or {})
    return ChatBudgetScope(
        ledger=ledger,
        user_id=str(user_id or "default"),
        session_id=str(session_id or "default"),
        session_budget=int(cost.get("session_token_budget") or 0),
        daily_budget=int(cost.get("daily_token_budget") or 0),
        throttle=bool(cost.get("throttle_on_budget", False)),
        prior_session_tokens=max(0, int(prior_session_tokens or 0)),
    )


__all__ = [
    "ChatBudgetLease",
    "ChatBudgetScope",
    "conservative_input_bound",
    "scope_from_runtime_policy",
]
