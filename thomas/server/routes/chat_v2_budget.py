"""Chat V2 helpers for one per-provider-call token budget authority."""

from __future__ import annotations

from typing import Any

from thomas.server.chat_budget_ledger import ChatBudgetLedger
from thomas.server.chat_budget_scope import ChatBudgetScope, scope_from_runtime_policy
from thomas.server.routes.chat_v2_keys import APP_CHAT_BUDGET_LEDGER


async def prepare_chat_turn_budget(
    app: Any,
    *,
    runtime_policy: Any,
    user_id: str,
    session_id: str,
    prior_session_tokens: int,
) -> tuple[ChatBudgetLedger, ChatBudgetScope, dict[str, Any]]:
    ledger: ChatBudgetLedger = app[APP_CHAT_BUDGET_LEDGER]
    worker_policy = runtime_policy.worker_payload()
    worker_policy["budget_context"] = {
        "ledger_path": str(ledger.path),
        "user_id": user_id,
        "session_id": session_id,
    }
    scope = scope_from_runtime_policy(
        ledger,
        worker_policy,
        user_id=user_id,
        session_id=session_id,
        prior_session_tokens=prior_session_tokens,
    )
    await scope.preflight()
    return ledger, scope, worker_policy


async def sync_chat_turn_budget(
    ledger: ChatBudgetLedger,
    *,
    scope: ChatBudgetScope,
    usage: dict[str, Any],
    user_id: str,
    session_id: str,
    meta: Any,
    session_store: Any,
    conversation: Any,
    temporary: bool,
) -> None:
    await scope.reconcile_unscoped_usage(int(usage.get("total_tokens", 0) or 0))
    totals = await ledger.snapshot(user_id=user_id, session_id=session_id)
    meta.token_spend = totals.session_tokens
    if not temporary:
        await session_store.save(session_id, conversation, meta, force=True)


__all__ = ["prepare_chat_turn_budget", "sync_chat_turn_budget"]
