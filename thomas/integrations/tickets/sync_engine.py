"""Bidirectional ticket <-> PR/work status synchronization.

The :class:`BidirectionalSyncEngine` does three things:

1. **Intake** -- takes a ticket *assignment* (a Linear-style ticket payload, or a
   GitHub issue payload) and normalizes it into a :class:`WorkItem`. GitHub-shaped
   payloads are routed through
   :func:`thomas.integrations.github_automation.normalize_issue_to_task` so we
   reuse the existing normalizer rather than duplicating it.

2. **Bidirectional status sync** -- a ticket state change propagates to the
   PR/work side, and a PR/work state change propagates back to the ticket (via
   :meth:`TicketProvider.set_ticket_state`). Mapping is done through a single,
   documented canonical status vocabulary (see ``TICKET_TO_CANONICAL`` /
   ``PR_TO_CANONICAL``).

3. **Conflict-aware application** -- writes are idempotent (a re-observed state is
   a no-op, so no duplicate provider writes), and when both sides diverge since
   the last sync the engine resolves last-writer-wins **and records a
   :class:`Conflict`** rather than silently clobbering.

State map (documented, canonical vocabulary in ``CanonicalStatus``):

    ticket "Backlog"/"Todo"      <-> canonical TODO         <-> PR "open"
    ticket "In Progress"         <-> canonical IN_PROGRESS  <-> PR "in_progress"
    ticket "In Review"           <-> canonical IN_REVIEW    <-> PR "in_review"
    ticket "Done"                <-> canonical DONE         <-> PR "merged"
    ticket "Canceled"            <-> canonical CANCELED     <-> PR "closed"
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final

from thomas.integrations.github_automation import normalize_issue_to_task
from thomas.integrations.tickets.provider import TicketProvider


class CanonicalStatus:
    """Canonical status vocabulary shared by the ticket and PR/work sides."""

    TODO: Final = "todo"
    IN_PROGRESS: Final = "in_progress"
    IN_REVIEW: Final = "in_review"
    DONE: Final = "done"
    CANCELED: Final = "canceled"

    ALL: Final = frozenset({TODO, IN_PROGRESS, IN_REVIEW, DONE, CANCELED})


# --- documented state maps -------------------------------------------------

TICKET_TO_CANONICAL: Final[dict[str, str]] = {
    "backlog": CanonicalStatus.TODO,
    "todo": CanonicalStatus.TODO,
    "to do": CanonicalStatus.TODO,
    "unstarted": CanonicalStatus.TODO,
    "in progress": CanonicalStatus.IN_PROGRESS,
    "started": CanonicalStatus.IN_PROGRESS,
    "doing": CanonicalStatus.IN_PROGRESS,
    "in review": CanonicalStatus.IN_REVIEW,
    "in-review": CanonicalStatus.IN_REVIEW,
    "review": CanonicalStatus.IN_REVIEW,
    "done": CanonicalStatus.DONE,
    "completed": CanonicalStatus.DONE,
    "closed": CanonicalStatus.DONE,
    "canceled": CanonicalStatus.CANCELED,
    "cancelled": CanonicalStatus.CANCELED,
    "duplicate": CanonicalStatus.CANCELED,
}

CANONICAL_TO_TICKET: Final[dict[str, str]] = {
    CanonicalStatus.TODO: "Todo",
    CanonicalStatus.IN_PROGRESS: "In Progress",
    CanonicalStatus.IN_REVIEW: "In Review",
    CanonicalStatus.DONE: "Done",
    CanonicalStatus.CANCELED: "Canceled",
}

PR_TO_CANONICAL: Final[dict[str, str]] = {
    "open": CanonicalStatus.IN_PROGRESS,
    "draft": CanonicalStatus.IN_PROGRESS,
    "in_progress": CanonicalStatus.IN_PROGRESS,
    "reopened": CanonicalStatus.IN_PROGRESS,
    "review": CanonicalStatus.IN_REVIEW,
    "in_review": CanonicalStatus.IN_REVIEW,
    "review_requested": CanonicalStatus.IN_REVIEW,
    "merged": CanonicalStatus.DONE,
    "closed": CanonicalStatus.CANCELED,
}

CANONICAL_TO_PR: Final[dict[str, str]] = {
    CanonicalStatus.TODO: "open",
    CanonicalStatus.IN_PROGRESS: "in_progress",
    CanonicalStatus.IN_REVIEW: "in_review",
    CanonicalStatus.DONE: "merged",
    CanonicalStatus.CANCELED: "closed",
}


def _safe_string(value: Any) -> str:
    return str(value or "").strip()


def ticket_state_to_canonical(state_name: str) -> str:
    """Map a ticket workflow-state name to a canonical status."""
    return TICKET_TO_CANONICAL.get(_safe_string(state_name).lower(), CanonicalStatus.TODO)


def pr_state_to_canonical(pr_state: str) -> str:
    """Map a PR/work state to a canonical status."""
    return PR_TO_CANONICAL.get(_safe_string(pr_state).lower(), CanonicalStatus.IN_PROGRESS)


def canonical_to_ticket_state(canonical: str) -> str:
    return CANONICAL_TO_TICKET.get(canonical, "Todo")


def canonical_to_pr_state(canonical: str) -> str:
    return CANONICAL_TO_PR.get(canonical, "open")


# --- data model ------------------------------------------------------------


@dataclass
class WorkItem:
    """Normalized work item produced from a ticket assignment."""

    key: str
    source: str
    source_id: str
    title: str
    assignee: str
    status: str
    description: str = ""
    url: str = ""
    ticket_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "source": self.source,
            "source_id": self.source_id,
            "title": self.title,
            "assignee": self.assignee,
            "status": self.status,
            "description": self.description,
            "url": self.url,
            "ticket_id": self.ticket_id,
        }


@dataclass
class SyncRecord:
    """Engine's last-known reconciled state for a work item."""

    key: str
    ticket_id: str
    ticket_canonical: str
    pr_canonical: str
    last_writer: str = "intake"
    revision: int = 0


@dataclass(frozen=True)
class Conflict:
    """A recorded divergent-change conflict (never a silent clobber)."""

    key: str
    ticket_canonical: str
    pr_canonical: str
    winner: str
    resolved_canonical: str
    revision: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "ticket_canonical": self.ticket_canonical,
            "pr_canonical": self.pr_canonical,
            "winner": self.winner,
            "resolved_canonical": self.resolved_canonical,
            "revision": self.revision,
        }


@dataclass
class SyncResult:
    """Outcome of a sync operation."""

    key: str
    applied: bool
    direction: str
    canonical: str
    ticket_state: str = ""
    pr_state: str = ""
    conflict: Conflict | None = field(default=None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "applied": self.applied,
            "direction": self.direction,
            "canonical": self.canonical,
            "ticket_state": self.ticket_state,
            "pr_state": self.pr_state,
            "conflict": self.conflict.to_dict() if self.conflict else None,
        }


def _looks_like_github_issue(payload: Mapping[str, Any]) -> bool:
    if "identifier" in payload or isinstance(payload.get("state"), Mapping):
        return False
    if "number" in payload or "html_url" in payload or "repository" in payload:
        return True
    return False


def normalize_assignment(payload: Mapping[str, Any]) -> WorkItem:
    """Normalize a ticket assignment (Linear ticket or GitHub issue) to a WorkItem.

    GitHub-shaped payloads reuse
    :func:`thomas.integrations.github_automation.normalize_issue_to_task`.
    """
    if not isinstance(payload, Mapping):
        raise TypeError("assignment payload must be a mapping")

    if _looks_like_github_issue(payload):
        task = normalize_issue_to_task(payload)
        assignees = task.get("assignees") or []
        assignee = _safe_string(assignees[0]) if assignees else ""
        canonical = CanonicalStatus.DONE if task.get("status") == "done" else CanonicalStatus.TODO
        return WorkItem(
            key=_safe_string(task.get("source_id")) or f"gh#{task.get('issue_number')}",
            source="github_issue",
            source_id=_safe_string(task.get("source_id")),
            title=_safe_string(task.get("title")),
            assignee=assignee,
            status=canonical,
            description=_safe_string(task.get("description")),
            url=_safe_string(task.get("url")),
            ticket_id="",
        )

    # Linear-style ticket payload.
    ticket_id = _safe_string(payload.get("id")) or _safe_string(payload.get("identifier"))
    identifier = _safe_string(payload.get("identifier")) or ticket_id
    if not ticket_id:
        raise ValueError("ticket assignment requires an 'id' or 'identifier'")

    assignee_field = payload.get("assignee")
    assignee = ""
    if isinstance(assignee_field, Mapping):
        assignee = _safe_string(assignee_field.get("name")) or _safe_string(assignee_field.get("email"))
    elif assignee_field is not None:
        assignee = _safe_string(assignee_field)
    if not assignee:
        raise ValueError("ticket has no assignee; not an assignment")

    state_field = payload.get("state")
    state_name = ""
    if isinstance(state_field, Mapping):
        state_name = _safe_string(state_field.get("name"))
    else:
        state_name = _safe_string(state_field)

    return WorkItem(
        key=identifier,
        source="linear",
        source_id=identifier,
        title=_safe_string(payload.get("title")),
        assignee=assignee,
        status=ticket_state_to_canonical(state_name),
        description=_safe_string(payload.get("description")),
        url=_safe_string(payload.get("url")),
        ticket_id=ticket_id,
    )


class BidirectionalSyncEngine:
    """Idempotent, conflict-aware ticket <-> PR/work status synchronizer."""

    def __init__(self, provider: TicketProvider) -> None:
        self._provider = provider
        self._records: dict[str, SyncRecord] = {}
        self._items: dict[str, WorkItem] = {}
        self._conflicts: list[Conflict] = []

    @property
    def conflicts(self) -> list[Conflict]:
        return list(self._conflicts)

    def work_item(self, key: str) -> WorkItem:
        return self._items[_safe_string(key)]

    def record(self, key: str) -> SyncRecord:
        return self._records[_safe_string(key)]

    def intake_assignment(self, payload: Mapping[str, Any]) -> WorkItem:
        """Normalize an assignment into a WorkItem and start tracking it."""
        item = normalize_assignment(payload)
        self._items[item.key] = item
        self._records[item.key] = SyncRecord(
            key=item.key,
            ticket_id=item.ticket_id,
            ticket_canonical=item.status,
            pr_canonical=item.status,
            last_writer="intake",
            revision=0,
        )
        return item

    def _require_record(self, key: str) -> SyncRecord:
        norm = _safe_string(key)
        if norm not in self._records:
            raise KeyError(f"Unknown work item {key!r}; intake_assignment first.")
        return self._records[norm]

    def sync_from_ticket(self, key: str, ticket_state: str) -> SyncResult:
        """Propagate a ticket state change to the PR/work side."""
        record = self._require_record(key)
        canonical = ticket_state_to_canonical(ticket_state)
        if record.ticket_canonical == canonical and record.pr_canonical == canonical:
            # Idempotent: nothing diverged, no write.
            return SyncResult(
                key=record.key,
                applied=False,
                direction="ticket->pr",
                canonical=canonical,
                ticket_state=canonical_to_ticket_state(canonical),
                pr_state=canonical_to_pr_state(canonical),
            )
        record.ticket_canonical = canonical
        record.pr_canonical = canonical
        record.last_writer = "ticket"
        record.revision += 1
        if record.key in self._items:
            self._items[record.key].status = canonical
        return SyncResult(
            key=record.key,
            applied=True,
            direction="ticket->pr",
            canonical=canonical,
            ticket_state=canonical_to_ticket_state(canonical),
            pr_state=canonical_to_pr_state(canonical),
        )

    def sync_from_pr(self, key: str, pr_state: str) -> SyncResult:
        """Propagate a PR/work state change back to the ticket side."""
        record = self._require_record(key)
        canonical = pr_state_to_canonical(pr_state)
        if record.ticket_canonical == canonical and record.pr_canonical == canonical:
            return SyncResult(
                key=record.key,
                applied=False,
                direction="pr->ticket",
                canonical=canonical,
                ticket_state=canonical_to_ticket_state(canonical),
                pr_state=canonical_to_pr_state(canonical),
            )
        ticket_state = canonical_to_ticket_state(canonical)
        if record.ticket_id:
            self._provider.set_ticket_state(record.ticket_id, ticket_state)
        record.pr_canonical = canonical
        record.ticket_canonical = canonical
        record.last_writer = "pr"
        record.revision += 1
        if record.key in self._items:
            self._items[record.key].status = canonical
        return SyncResult(
            key=record.key,
            applied=True,
            direction="pr->ticket",
            canonical=canonical,
            ticket_state=ticket_state,
            pr_state=canonical_to_pr_state(canonical),
        )

    def reconcile(
        self,
        key: str,
        *,
        ticket_state: str,
        pr_state: str,
        ticket_updated_at: float,
        pr_updated_at: float,
    ) -> SyncResult:
        """Reconcile simultaneously-observed ticket and PR states.

        If both sides diverged from the last sync to *different* canonical
        statuses, resolve last-writer-wins (by timestamp) and record a
        :class:`Conflict`. If only one side changed, behave like the matching
        one-way sync.
        """
        record = self._require_record(key)
        ticket_canonical = ticket_state_to_canonical(ticket_state)
        pr_canonical = pr_state_to_canonical(pr_state)
        ticket_changed = ticket_canonical != record.ticket_canonical
        pr_changed = pr_canonical != record.pr_canonical

        if ticket_changed and pr_changed and ticket_canonical != pr_canonical:
            winner = "ticket" if float(ticket_updated_at) >= float(pr_updated_at) else "pr"
            resolved = ticket_canonical if winner == "ticket" else pr_canonical
            record.revision += 1
            conflict = Conflict(
                key=record.key,
                ticket_canonical=ticket_canonical,
                pr_canonical=pr_canonical,
                winner=winner,
                resolved_canonical=resolved,
                revision=record.revision,
            )
            self._conflicts.append(conflict)
            # Apply the winner to both sides; if the ticket lost, write the
            # resolved state back to the ticket provider (not a silent clobber).
            if winner == "pr" and record.ticket_id:
                self._provider.set_ticket_state(record.ticket_id, canonical_to_ticket_state(resolved))
            record.ticket_canonical = resolved
            record.pr_canonical = resolved
            record.last_writer = winner
            if record.key in self._items:
                self._items[record.key].status = resolved
            return SyncResult(
                key=record.key,
                applied=True,
                direction="conflict",
                canonical=resolved,
                ticket_state=canonical_to_ticket_state(resolved),
                pr_state=canonical_to_pr_state(resolved),
                conflict=conflict,
            )

        if ticket_changed:
            return self.sync_from_ticket(key, ticket_state)
        if pr_changed:
            return self.sync_from_pr(key, pr_state)
        return SyncResult(
            key=record.key,
            applied=False,
            direction="noop",
            canonical=record.ticket_canonical,
            ticket_state=canonical_to_ticket_state(record.ticket_canonical),
            pr_state=canonical_to_pr_state(record.pr_canonical),
        )


__all__ = [
    "CANONICAL_TO_PR",
    "CANONICAL_TO_TICKET",
    "PR_TO_CANONICAL",
    "TICKET_TO_CANONICAL",
    "BidirectionalSyncEngine",
    "CanonicalStatus",
    "Conflict",
    "SyncRecord",
    "SyncResult",
    "WorkItem",
    "canonical_to_pr_state",
    "canonical_to_ticket_state",
    "normalize_assignment",
    "pr_state_to_canonical",
    "ticket_state_to_canonical",
]
