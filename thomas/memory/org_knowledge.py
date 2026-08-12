"""Team / org shared knowledge (CAP-110).

An :class:`OrgKnowledgeStore` where knowledge items are **org-scoped** (visible
to the members of an org), can be **shared across different users** (one user's
item can be made org-visible so a *different* user sees it), and where promotion
from *personal* to *org* scope passes through a **reviewed promotion gate**.

Three guarantees, each independently testable:

1. **Org scoping** -- an item at ``org`` scope is visible to every member of its
   org and to nobody outside it. A user who is not a member of the org sees
   nothing from that org.

2. **Different-user sharing** -- a user may :meth:`share_to_org` an item they
   authored, flipping it to ``org`` scope so that a *different* member of the
   same org can then see it. Sharing your own item is a voluntary, self-service
   contribution and does not require review.

3. **Reviewed promotion gate** -- :meth:`propose_promotion` records a *pending*
   proposal to elevate a personal item to org scope. While pending the item
   stays personal (author-only). An **authorized reviewer** of the org may
   :meth:`approve_promotion` (item becomes org-visible) or
   :meth:`reject_promotion` (item stays personal). A non-reviewer cannot decide
   a proposal.

Sharing and promotion are two intentionally distinct paths into org scope:
sharing is the author volunteering their own knowledge; the promotion gate is
governance for elevating knowledge into the reviewed org corpus.

The store persists durably to a JSON file (atomic writes) and is fully
deterministic: ids are monotonic counters and timestamps come from an injected
clock, so a reload reproduces exactly what was written.

This module lives in the ``memory`` tier and depends only on the standard
library (``memory`` may import ``core``/``library`` but needs neither here).

Storage path resolution order:
    1. explicit ``path=`` argument to :class:`OrgKnowledgeStore`
    2. ``THOMAS_ORG_KNOWLEDGE_PATH`` environment variable (used by tests)
    3. ``~/.thomas/org_knowledge.json``
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable

__all__ = [
    "KnowledgeItem",
    "PromotionProposal",
    "OrgKnowledgeStore",
    "OrgKnowledgeError",
    "OrgNotFoundError",
    "ItemNotFoundError",
    "ProposalNotFoundError",
    "NotAuthorizedError",
    "PromotionStateError",
    "SCOPE_PERSONAL",
    "SCOPE_ORG",
]

_ENV_PATH_VAR = "THOMAS_ORG_KNOWLEDGE_PATH"
_STATE_VERSION = 1

SCOPE_PERSONAL = "personal"
SCOPE_ORG = "org"

# origins record *how* an item reached org scope (or that it is still personal)
_ORIGIN_PERSONAL = "personal"
_ORIGIN_SHARED = "shared"
_ORIGIN_PROMOTED = "promoted"

_STATUS_PENDING = "pending"
_STATUS_APPROVED = "approved"
_STATUS_REJECTED = "rejected"


class OrgKnowledgeError(Exception):
    """Base class for org-knowledge errors."""


class OrgNotFoundError(KeyError):
    """Raised when an operation targets an org that does not exist."""


class ItemNotFoundError(KeyError):
    """Raised when an operation targets an unknown knowledge item."""


class ProposalNotFoundError(KeyError):
    """Raised when an operation targets an unknown promotion proposal."""


class NotAuthorizedError(PermissionError):
    """Raised when a user attempts an action they are not authorized for."""


class PromotionStateError(OrgKnowledgeError):
    """Raised when a promotion action is invalid for the item/proposal state."""


@dataclass(frozen=True)
class KnowledgeItem:
    """An immutable knowledge item owned by a user within an org context."""

    item_id: str
    org_id: str
    author_user_id: str
    content: str
    scope: str  # SCOPE_PERSONAL | SCOPE_ORG
    origin: str  # _ORIGIN_PERSONAL | _ORIGIN_SHARED | _ORIGIN_PROMOTED
    created_at: float
    updated_at: float

    @property
    def is_org_visible(self) -> bool:
        return self.scope == SCOPE_ORG

    def to_payload(self) -> dict[str, Any]:
        return {
            "author_user_id": self.author_user_id,
            "content": self.content,
            "created_at": self.created_at,
            "item_id": self.item_id,
            "org_id": self.org_id,
            "origin": self.origin,
            "scope": self.scope,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> KnowledgeItem:
        return cls(
            item_id=str(payload["item_id"]),
            org_id=str(payload["org_id"]),
            author_user_id=str(payload["author_user_id"]),
            content=str(payload["content"]),
            scope=str(payload["scope"]),
            origin=str(payload["origin"]),
            created_at=float(payload["created_at"]),
            updated_at=float(payload["updated_at"]),
        )


@dataclass(frozen=True)
class PromotionProposal:
    """A reviewed proposal to promote a personal item to org scope."""

    proposal_id: str
    item_id: str
    org_id: str
    proposer_user_id: str
    status: str  # _STATUS_PENDING | _STATUS_APPROVED | _STATUS_REJECTED
    reason: str
    reviewer_user_id: str | None
    created_at: float
    decided_at: float | None

    @property
    def is_pending(self) -> bool:
        return self.status == _STATUS_PENDING

    @property
    def is_approved(self) -> bool:
        return self.status == _STATUS_APPROVED

    @property
    def is_rejected(self) -> bool:
        return self.status == _STATUS_REJECTED

    def to_payload(self) -> dict[str, Any]:
        return {
            "created_at": self.created_at,
            "decided_at": self.decided_at,
            "item_id": self.item_id,
            "org_id": self.org_id,
            "proposal_id": self.proposal_id,
            "proposer_user_id": self.proposer_user_id,
            "reason": self.reason,
            "reviewer_user_id": self.reviewer_user_id,
            "status": self.status,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> PromotionProposal:
        decided = payload.get("decided_at")
        reviewer = payload.get("reviewer_user_id")
        return cls(
            proposal_id=str(payload["proposal_id"]),
            item_id=str(payload["item_id"]),
            org_id=str(payload["org_id"]),
            proposer_user_id=str(payload["proposer_user_id"]),
            status=str(payload["status"]),
            reason=str(payload.get("reason") or ""),
            reviewer_user_id=None if reviewer is None else str(reviewer),
            created_at=float(payload["created_at"]),
            decided_at=None if decided is None else float(decided),
        )


class OrgKnowledgeStore:
    """Durable, deterministic org-scoped knowledge store with a review gate."""

    def __init__(
        self,
        path: str | os.PathLike[str] | None = None,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._path = self._resolve_path(path)
        self._clock = clock if clock is not None else time.time
        # org_id -> {"members": set[str], "reviewers": set[str]}
        self._orgs: dict[str, dict[str, set[str]]] = {}
        self._items: dict[str, KnowledgeItem] = {}
        self._proposals: dict[str, PromotionProposal] = {}
        self._counters: dict[str, int] = {"item": 0, "proposal": 0}
        self._load()

    # -- path / persistence -------------------------------------------------

    @staticmethod
    def _resolve_path(path: str | os.PathLike[str] | None) -> Path:
        if path is not None:
            return Path(os.fspath(path))
        env = os.environ.get(_ENV_PATH_VAR)
        if env:
            return Path(env)
        return Path.home() / ".thomas" / "org_knowledge.json"

    def _load(self) -> None:
        if not self._path.exists():
            return
        raw = self._path.read_text(encoding="utf-8")
        if not raw.strip():
            return
        state = json.loads(raw)
        self._counters = {
            "item": int(state.get("counters", {}).get("item", 0)),
            "proposal": int(state.get("counters", {}).get("proposal", 0)),
        }
        for org_id, rec in (state.get("orgs") or {}).items():
            self._orgs[str(org_id)] = {
                "members": {str(m) for m in rec.get("members") or ()},
                "reviewers": {str(r) for r in rec.get("reviewers") or ()},
            }
        for item_id, payload in (state.get("items") or {}).items():
            self._items[str(item_id)] = KnowledgeItem.from_payload(payload)
        for proposal_id, payload in (state.get("proposals") or {}).items():
            self._proposals[str(proposal_id)] = PromotionProposal.from_payload(payload)

    def _serialize(self) -> dict[str, Any]:
        return {
            "version": _STATE_VERSION,
            "counters": dict(self._counters),
            "orgs": {
                org_id: {
                    "members": sorted(rec["members"]),
                    "reviewers": sorted(rec["reviewers"]),
                }
                for org_id, rec in sorted(self._orgs.items())
            },
            "items": {item_id: self._items[item_id].to_payload() for item_id in sorted(self._items)},
            "proposals": {
                proposal_id: self._proposals[proposal_id].to_payload() for proposal_id in sorted(self._proposals)
            },
        }

    def _save(self) -> None:
        text = json.dumps(self._serialize(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_name(self._path.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, self._path)

    def _next_id(self, kind: str) -> str:
        self._counters[kind] = self._counters.get(kind, 0) + 1
        return f"{kind}-{self._counters[kind]}"

    # -- org / membership ---------------------------------------------------

    def ensure_org(self, org_id: str) -> None:
        if not org_id:
            raise ValueError("org_id must be a non-empty string")
        if org_id not in self._orgs:
            self._orgs[org_id] = {"members": set(), "reviewers": set()}
            self._save()

    def _require_org(self, org_id: str) -> dict[str, set[str]]:
        rec = self._orgs.get(org_id)
        if rec is None:
            raise OrgNotFoundError(org_id)
        return rec

    def add_member(self, org_id: str, user_id: str) -> None:
        self.ensure_org(org_id)
        self._orgs[org_id]["members"].add(user_id)
        self._save()

    def add_reviewer(self, org_id: str, user_id: str) -> None:
        """Authorize ``user_id`` to decide promotions (also makes them a member)."""

        self.ensure_org(org_id)
        self._orgs[org_id]["members"].add(user_id)
        self._orgs[org_id]["reviewers"].add(user_id)
        self._save()

    def is_member(self, org_id: str, user_id: str) -> bool:
        rec = self._orgs.get(org_id)
        return rec is not None and user_id in rec["members"]

    def is_reviewer(self, org_id: str, user_id: str) -> bool:
        rec = self._orgs.get(org_id)
        return rec is not None and user_id in rec["reviewers"]

    def members(self, org_id: str) -> list[str]:
        return sorted(self._require_org(org_id)["members"])

    def reviewers(self, org_id: str) -> list[str]:
        return sorted(self._require_org(org_id)["reviewers"])

    # -- item creation ------------------------------------------------------

    def add_personal(self, org_id: str, user_id: str, content: str) -> KnowledgeItem:
        """Create a personal item owned by ``user_id`` within ``org_id``.

        The author is registered as a member of the org. The item is visible
        only to its author until it is shared or promoted.
        """

        if not user_id:
            raise ValueError("user_id must be a non-empty string")
        self.add_member(org_id, user_id)
        now = float(self._clock())
        item = KnowledgeItem(
            item_id=self._next_id("item"),
            org_id=org_id,
            author_user_id=user_id,
            content=content,
            scope=SCOPE_PERSONAL,
            origin=_ORIGIN_PERSONAL,
            created_at=now,
            updated_at=now,
        )
        self._items[item.item_id] = item
        self._save()
        return item

    def get_item(self, item_id: str) -> KnowledgeItem:
        item = self._items.get(item_id)
        if item is None:
            raise ItemNotFoundError(item_id)
        return item

    # -- different-user sharing --------------------------------------------

    def share_to_org(self, item_id: str, actor_user_id: str) -> KnowledgeItem:
        """Share the author's own item to the org so other members can see it.

        Only the item's author may share it. Sharing flips the item to ``org``
        scope immediately -- it is a voluntary self-service contribution and
        does not go through the review gate.
        """

        item = self.get_item(item_id)
        if actor_user_id != item.author_user_id:
            raise NotAuthorizedError(f"user {actor_user_id!r} may not share item owned by {item.author_user_id!r}")
        if item.scope == SCOPE_ORG:
            return item
        updated = replace(
            item,
            scope=SCOPE_ORG,
            origin=_ORIGIN_SHARED,
            updated_at=float(self._clock()),
        )
        self._items[item_id] = updated
        self._save()
        return updated

    # -- reviewed promotion gate -------------------------------------------

    def propose_promotion(self, item_id: str, proposer_user_id: str, reason: str = "") -> PromotionProposal:
        """Record a *pending* proposal to promote a personal item to org scope.

        The item stays personal (author-only) while the proposal is pending.
        Raises :class:`PromotionStateError` if the item is already org-visible
        or already has an open (pending) proposal.
        """

        item = self.get_item(item_id)
        if not proposer_user_id:
            raise ValueError("proposer_user_id must be a non-empty string")
        if item.scope == SCOPE_ORG:
            raise PromotionStateError(f"item {item_id!r} is already org-visible")
        if self._pending_for_item(item_id) is not None:
            raise PromotionStateError(f"item {item_id!r} already has a pending promotion proposal")
        proposal = PromotionProposal(
            proposal_id=self._next_id("proposal"),
            item_id=item_id,
            org_id=item.org_id,
            proposer_user_id=proposer_user_id,
            status=_STATUS_PENDING,
            reason=reason,
            reviewer_user_id=None,
            created_at=float(self._clock()),
            decided_at=None,
        )
        self._proposals[proposal.proposal_id] = proposal
        self._save()
        return proposal

    def get_proposal(self, proposal_id: str) -> PromotionProposal:
        proposal = self._proposals.get(proposal_id)
        if proposal is None:
            raise ProposalNotFoundError(proposal_id)
        return proposal

    def approve_promotion(self, proposal_id: str, reviewer_user_id: str) -> PromotionProposal:
        """Approve a pending proposal; the item becomes org-visible.

        Only an authorized reviewer of the item's org may approve.
        """

        proposal = self._decide(proposal_id, reviewer_user_id, _STATUS_APPROVED, reason=None)
        item = self.get_item(proposal.item_id)
        promoted = replace(
            item,
            scope=SCOPE_ORG,
            origin=_ORIGIN_PROMOTED,
            updated_at=float(self._clock()),
        )
        self._items[item.item_id] = promoted
        self._save()
        return proposal

    def reject_promotion(self, proposal_id: str, reviewer_user_id: str, reason: str = "") -> PromotionProposal:
        """Reject a pending proposal; the item stays personal.

        Only an authorized reviewer of the item's org may reject.
        """

        proposal = self._decide(proposal_id, reviewer_user_id, _STATUS_REJECTED, reason=reason)
        self._save()
        return proposal

    def _decide(
        self,
        proposal_id: str,
        reviewer_user_id: str,
        status: str,
        *,
        reason: str | None,
    ) -> PromotionProposal:
        proposal = self.get_proposal(proposal_id)
        if not proposal.is_pending:
            raise PromotionStateError(f"proposal {proposal_id!r} is already {proposal.status}; cannot set to {status}")
        if not self.is_reviewer(proposal.org_id, reviewer_user_id):
            raise NotAuthorizedError(
                f"user {reviewer_user_id!r} is not an authorized reviewer of org {proposal.org_id!r}"
            )
        decided = replace(
            proposal,
            status=status,
            reviewer_user_id=reviewer_user_id,
            reason=reason if reason is not None else proposal.reason,
            decided_at=float(self._clock()),
        )
        self._proposals[proposal_id] = decided
        return decided

    def _pending_for_item(self, item_id: str) -> PromotionProposal | None:
        for proposal in self._proposals.values():
            if proposal.item_id == item_id and proposal.is_pending:
                return proposal
        return None

    def pending_proposals(self, org_id: str) -> list[PromotionProposal]:
        return sorted(
            (p for p in self._proposals.values() if p.org_id == org_id and p.is_pending),
            key=lambda p: p.proposal_id,
        )

    # -- visibility ---------------------------------------------------------

    def can_see(self, user_id: str, item: KnowledgeItem) -> bool:
        """Whether ``user_id`` may see ``item``.

        Org-scoped items are visible to any member of their org; personal items
        are visible only to their author.
        """

        if item.scope == SCOPE_ORG:
            return self.is_member(item.org_id, user_id)
        return item.author_user_id == user_id

    def visible_items(self, org_id: str, user_id: str) -> list[KnowledgeItem]:
        """Every item in ``org_id`` that ``user_id`` may see, ordered by id.

        A non-member sees nothing from the org. A member sees all org-scoped
        items plus their own personal items.
        """

        visible = [item for item in self._items.values() if item.org_id == org_id and self.can_see(user_id, item)]
        return sorted(visible, key=lambda i: i.item_id)

    def org_items(self, org_id: str) -> list[KnowledgeItem]:
        """Every org-scoped (shared/promoted) item in ``org_id``, ordered by id."""

        return sorted(
            (i for i in self._items.values() if i.org_id == org_id and i.scope == SCOPE_ORG),
            key=lambda i: i.item_id,
        )
