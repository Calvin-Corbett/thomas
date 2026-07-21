"""Ticket-system integration with bidirectional status sync (Jira/Linear-style).

Public surface:

* :class:`~thomas.integrations.tickets.provider.TicketProvider` -- provider protocol.
* :class:`~thomas.integrations.tickets.provider.LinearProvider` -- real Linear
  GraphQL adapter (credential-gated; token from ``LINEAR_API_KEY`` or injected).
* :class:`~thomas.integrations.tickets.provider.FakeProvider` -- hermetic test double.
* :class:`~thomas.integrations.tickets.sync_engine.BidirectionalSyncEngine` --
  intake + two-way, idempotent, conflict-aware status sync.
"""

from __future__ import annotations

from thomas.integrations.tickets.provider import (
    FakeProvider,
    LinearProvider,
    TicketProvider,
    TicketProviderError,
)
from thomas.integrations.tickets.sync_engine import (
    BidirectionalSyncEngine,
    CanonicalStatus,
    Conflict,
    SyncRecord,
    SyncResult,
    WorkItem,
    normalize_assignment,
)

__all__ = [
    "BidirectionalSyncEngine",
    "CanonicalStatus",
    "Conflict",
    "FakeProvider",
    "LinearProvider",
    "SyncRecord",
    "SyncResult",
    "TicketProvider",
    "TicketProviderError",
    "WorkItem",
    "normalize_assignment",
]
