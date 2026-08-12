"""Transactional session and daily token budgets shared by every model call."""

from __future__ import annotations

import asyncio
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from .chat_budget_store import (
    ChatBudgetError,
    ChatBudgetExceeded,
    ChatBudgetStore,
    ChatBudgetTicket,
    ChatBudgetTotals,
)


class ChatBudgetLedger(ChatBudgetStore):
    """SQLite-backed ledger with cross-process reservations and atomic settlement."""

    def _reserve_sync(
        self,
        *,
        user_id: str,
        session_id: str,
        prior_session_tokens: int,
        session_budget: int,
        daily_budget: int,
        throttle: bool,
        estimated_tokens: int,
    ) -> ChatBudgetTicket:
        conn = self._connect_checked()
        now = time.time()
        user_key = str(user_id or "default")
        session_key = str(session_id or "default")
        requested = max(1, int(estimated_tokens or 1))
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM reservations WHERE expires_at <= ?", (now,))
            session_used = self._scalar(
                conn,
                "SELECT tokens FROM session_usage WHERE user_id=? AND session_id=?",
                (user_key, session_key),
            )
            session_used = max(session_used, max(0, int(prior_session_tokens or 0)))
            conn.execute(
                "INSERT INTO session_usage(user_id, session_id, tokens) VALUES(?, ?, ?) "
                "ON CONFLICT(user_id, session_id) DO UPDATE SET tokens=MAX(tokens, excluded.tokens)",
                (user_key, session_key, session_used),
            )
            daily_used = self._scalar(
                conn,
                "SELECT tokens FROM daily_usage WHERE day=? AND user_id=?",
                (self._today(), user_key),
            )
            reserve_tokens = requested
            if throttle:
                session_reserved = self._scalar(
                    conn,
                    "SELECT COALESCE(SUM(reserved_tokens), 0) FROM reservations "
                    "WHERE user_id=? AND session_id=? AND hard_limit=1",
                    (user_key, session_key),
                )
                daily_reserved = self._scalar(
                    conn,
                    "SELECT COALESCE(SUM(reserved_tokens), 0) FROM reservations WHERE user_id=? AND hard_limit=1",
                    (user_key,),
                )
                available: list[int] = []
                if session_budget > 0:
                    available.append(max(0, int(session_budget) - session_used - session_reserved))
                if daily_budget > 0:
                    available.append(max(0, int(daily_budget) - daily_used - daily_reserved))
                if available and min(available) <= 0:
                    raise ChatBudgetExceeded("Token budget exceeded")
                if available:
                    reserve_tokens = min(requested, *available)
            ticket = ChatBudgetTicket(
                ticket_id=uuid.uuid4().hex,
                user_id=user_key,
                session_id=session_key,
                reserved_tokens=reserve_tokens,
                hard_limit=bool(throttle),
            )
            conn.execute(
                "INSERT INTO reservations(ticket_id, user_id, session_id, reserved_tokens, hard_limit, expires_at) "
                "VALUES(?, ?, ?, ?, ?, ?)",
                (
                    ticket.ticket_id,
                    ticket.user_id,
                    ticket.session_id,
                    ticket.reserved_tokens,
                    int(ticket.hard_limit),
                    now + self._LEASE_SECONDS,
                ),
            )
            conn.commit()
            return ticket
        except ChatBudgetExceeded:
            conn.rollback()
            raise
        except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
            conn.rollback()
            raise ChatBudgetError("Token budget ledger is unavailable") from exc
        finally:
            conn.close()

    async def reserve(self, **kwargs: Any) -> ChatBudgetTicket:
        transaction = asyncio.create_task(asyncio.to_thread(self._reserve_sync, **kwargs))
        try:
            return await asyncio.shield(transaction)
        except asyncio.CancelledError:
            ticket = await transaction
            cleanup = asyncio.create_task(asyncio.to_thread(self._release_sync, ticket))
            await asyncio.shield(cleanup)
            raise

    def _settle_sync(self, ticket: ChatBudgetTicket, actual_tokens: int) -> ChatBudgetTotals:
        conn = self._connect_checked()
        actual = max(0, int(actual_tokens or 0))
        overrun = 0
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT user_id, session_id, reserved_tokens, hard_limit FROM reservations WHERE ticket_id=?",
                (ticket.ticket_id,),
            ).fetchone()
            if row is None:
                settled = conn.execute(
                    "SELECT user_id, session_id, overrun_tokens FROM settlements WHERE ticket_id=?",
                    (ticket.ticket_id,),
                ).fetchone()
                if settled is None:
                    raise ChatBudgetError("Token budget reservation is no longer active")
                user_key, session_key = str(settled[0]), str(settled[1])
                overrun = max(0, int(settled[2] or 0))
            else:
                user_key, session_key = str(row[0]), str(row[1])
                reserved, hard_limit = max(0, int(row[2] or 0)), bool(row[3])
                if user_key != ticket.user_id or session_key != ticket.session_id:
                    raise ChatBudgetError("Token budget reservation identity mismatch")
                overrun = max(0, actual - reserved) if hard_limit else 0
                conn.execute("DELETE FROM reservations WHERE ticket_id=?", (ticket.ticket_id,))
                conn.execute(
                    "INSERT INTO settlements(ticket_id, user_id, session_id, actual_tokens, overrun_tokens, settled_at) "
                    "VALUES(?, ?, ?, ?, ?, ?)",
                    (ticket.ticket_id, user_key, session_key, actual, overrun, time.time()),
                )
                conn.execute(
                    "INSERT INTO session_usage(user_id, session_id, tokens) VALUES(?, ?, ?) "
                    "ON CONFLICT(user_id, session_id) DO UPDATE SET tokens=tokens+excluded.tokens",
                    (user_key, session_key, actual),
                )
                conn.execute(
                    "INSERT INTO daily_usage(day, user_id, tokens) VALUES(?, ?, ?) "
                    "ON CONFLICT(day, user_id) DO UPDATE SET tokens=tokens+excluded.tokens",
                    (self._today(), user_key, actual),
                )
            totals = ChatBudgetTotals(
                session_tokens=self._scalar(
                    conn,
                    "SELECT tokens FROM session_usage WHERE user_id=? AND session_id=?",
                    (user_key, session_key),
                ),
                daily_tokens=self._scalar(
                    conn,
                    "SELECT tokens FROM daily_usage WHERE day=? AND user_id=?",
                    (self._today(), user_key),
                ),
            )
            conn.commit()
        except ChatBudgetError:
            conn.rollback()
            raise
        except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
            conn.rollback()
            raise ChatBudgetError("Token budget ledger could not be saved") from exc
        finally:
            conn.close()
        if overrun:
            raise ChatBudgetExceeded(f"Provider exceeded its reserved token allowance by {overrun} tokens")
        return totals

    async def settle(self, ticket: ChatBudgetTicket, actual_tokens: int) -> ChatBudgetTotals:
        transaction = asyncio.create_task(asyncio.to_thread(self._settle_sync, ticket, actual_tokens))
        try:
            return await asyncio.shield(transaction)
        except asyncio.CancelledError:
            await transaction
            raise

    def _release_sync(self, ticket: ChatBudgetTicket) -> None:
        conn = self._connect_checked()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM reservations WHERE ticket_id=?", (ticket.ticket_id,))
            conn.commit()
        except sqlite3.Error as exc:
            conn.rollback()
            raise ChatBudgetError("Token budget reservation could not be released") from exc
        finally:
            conn.close()

    async def release(self, ticket: ChatBudgetTicket) -> None:
        await asyncio.to_thread(self._release_sync, ticket)

    def _snapshot_sync(self, *, user_id: str, session_id: str) -> ChatBudgetTotals:
        conn = self._connect_checked()
        try:
            return ChatBudgetTotals(
                session_tokens=self._scalar(
                    conn,
                    "SELECT tokens FROM session_usage WHERE user_id=? AND session_id=?",
                    (str(user_id or "default"), str(session_id or "default")),
                ),
                daily_tokens=self._scalar(
                    conn,
                    "SELECT tokens FROM daily_usage WHERE day=? AND user_id=?",
                    (self._today(), str(user_id or "default")),
                ),
            )
        except sqlite3.Error as exc:
            raise ChatBudgetError("Token budget ledger is unavailable") from exc
        finally:
            conn.close()

    async def snapshot(self, *, user_id: str, session_id: str) -> ChatBudgetTotals:
        return await asyncio.to_thread(self._snapshot_sync, user_id=user_id, session_id=session_id)


_LEDGERS: dict[Path, ChatBudgetLedger] = {}
_LEDGERS_LOCK = threading.Lock()


def get_chat_budget_ledger(path: str | Path) -> ChatBudgetLedger:
    resolved = Path(path).resolve()
    with _LEDGERS_LOCK:
        ledger = _LEDGERS.get(resolved)
        if ledger is None:
            ledger = ChatBudgetLedger(resolved)
            _LEDGERS[resolved] = ledger
        return ledger


def budget_context(runtime_policy: dict[str, Any] | None) -> dict[str, Any]:
    return dict((runtime_policy or {}).get("budget_context") or {})


__all__ = [
    "ChatBudgetError",
    "ChatBudgetExceeded",
    "ChatBudgetLedger",
    "ChatBudgetTicket",
    "ChatBudgetTotals",
    "budget_context",
    "get_chat_budget_ledger",
]
