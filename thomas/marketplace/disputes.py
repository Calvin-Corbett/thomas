"""Dispute resolution with evidence tracking and automated decisions."""

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from thomas.marketplace._exceptions import (
    DisputeException,
    DisputeNotFoundError,
    InvalidDisputeState,
)
from thomas.marketplace._types import (
    Dispute,
    DisputeStatus,
    DisputeType,
)


@dataclass
class DisputeEvidence:
    """Evidence submission in dispute."""

    id: str
    dispute_id: str
    submitted_by: str  # "buyer" or "seller"
    description: str
    attachments: list[str]
    submitted_at: datetime


@dataclass
class DisputeResolution:
    """Dispute resolution decision."""

    dispute_id: str
    decision: str  # "refund_buyer", "dismiss", "partial_refund"
    refund_amount: Decimal
    reason: str
    decided_at: datetime
    decided_by: str


class DisputeRulesEngine:
    """Automated dispute resolution rules."""

    SELLER_RESPONSE_DEADLINE_DAYS: int = 7

    @staticmethod
    def auto_resolve(dispute: Dispute) -> DisputeResolution | None:
        """Check if dispute qualifies for auto-resolution.

        Args:
            dispute: Dispute to evaluate.

        Returns:
            Resolution if auto-resolvable, None otherwise.
        """
        # Auto-refund if no seller response after 7 days
        if dispute.dispute_type == DisputeType.ITEM_NOT_RECEIVED:
            days_open = (datetime.utcnow() - dispute.created_at).days
            if days_open >= DisputeRulesEngine.SELLER_RESPONSE_DEADLINE_DAYS and not dispute.seller_evidence:
                return DisputeResolution(
                    dispute_id=dispute.id,
                    decision="refund_buyer",
                    refund_amount=Decimal("0"),  # Placeholder
                    reason="Auto-refund: Seller did not respond",
                    decided_at=datetime.utcnow(),
                    decided_by="system",
                )

        return None


class DisputeRegistry:
    """In-memory dispute resolution system."""

    def __init__(self) -> None:
        """Initialize dispute registry."""
        self._disputes: dict[str, Dispute] = {}
        self._order_disputes: dict[str, list[str]] = {}
        self._evidence: dict[str, list[DisputeEvidence]] = {}
        self._resolutions: dict[str, DisputeResolution] = {}

    def open_dispute(
        self,
        order_id: str,
        buyer_id: str,
        vendor_id: str,
        dispute_type: DisputeType,
        title: str,
        description: str,
    ) -> Dispute:
        """Open new dispute.

        Args:
            order_id: Order identifier.
            buyer_id: Buyer identifier.
            vendor_id: Vendor identifier.
            dispute_type: Type of dispute.
            title: Dispute title.
            description: Dispute description.

        Returns:
            Created dispute.
        """
        dispute_id = f"dispute_{uuid.uuid4().hex[:12]}"
        now = datetime.utcnow()

        dispute = Dispute(
            id=dispute_id,
            order_id=order_id,
            buyer_id=buyer_id,
            vendor_id=vendor_id,
            dispute_type=dispute_type,
            status=DisputeStatus.OPENED,
            title=title,
            description=description,
            created_at=now,
            updated_at=now,
        )

        self._disputes[dispute_id] = dispute
        if order_id not in self._order_disputes:
            self._order_disputes[order_id] = []
        self._order_disputes[order_id].append(dispute_id)

        return dispute

    def get_dispute(self, dispute_id: str) -> Dispute:
        """Get dispute by ID.

        Args:
            dispute_id: Dispute identifier.

        Returns:
            Dispute object.

        Raises:
            DisputeNotFoundError: If dispute not found.
        """
        dispute = self._disputes.get(dispute_id)
        if not dispute:
            raise DisputeNotFoundError(dispute_id)
        return dispute

    def submit_buyer_evidence(
        self,
        dispute_id: str,
        description: str,
        attachments: list[str] | None = None,
    ) -> DisputeEvidence:
        """Submit buyer evidence.

        Args:
            dispute_id: Dispute identifier.
            description: Evidence description.
            attachments: Evidence attachments (URLs).

        Returns:
            Evidence submission.

        Raises:
            DisputeNotFoundError: If dispute not found.
            InvalidDisputeState: If cannot submit evidence.
        """
        dispute = self.get_dispute(dispute_id)

        if dispute.status not in (DisputeStatus.OPENED, DisputeStatus.EVIDENCE_REVIEW):
            raise InvalidDisputeState(dispute_id, dispute.status.value)

        evidence_id = f"evid_{uuid.uuid4().hex[:12]}"
        evidence = DisputeEvidence(
            id=evidence_id,
            dispute_id=dispute_id,
            submitted_by="buyer",
            description=description,
            attachments=attachments or [],
            submitted_at=datetime.utcnow(),
        )

        if dispute_id not in self._evidence:
            self._evidence[dispute_id] = []

        self._evidence[dispute_id].append(evidence)
        dispute.buyer_evidence.append(
            {
                "id": evidence_id,
                "description": description,
                "attachments": attachments or [],
            }
        )

        # Transition to evidence review if opened
        if dispute.status == DisputeStatus.OPENED:
            dispute.status = DisputeStatus.EVIDENCE_REVIEW
            dispute.updated_at = datetime.utcnow()

        return evidence

    def submit_seller_evidence(
        self,
        dispute_id: str,
        description: str,
        attachments: list[str] | None = None,
    ) -> DisputeEvidence:
        """Submit seller evidence.

        Args:
            dispute_id: Dispute identifier.
            description: Evidence description.
            attachments: Evidence attachments (URLs).

        Returns:
            Evidence submission.

        Raises:
            DisputeNotFoundError: If dispute not found.
            InvalidDisputeState: If cannot submit evidence.
        """
        dispute = self.get_dispute(dispute_id)

        if dispute.status not in (DisputeStatus.OPENED, DisputeStatus.EVIDENCE_REVIEW):
            raise InvalidDisputeState(dispute_id, dispute.status.value)

        evidence_id = f"evid_{uuid.uuid4().hex[:12]}"
        evidence = DisputeEvidence(
            id=evidence_id,
            dispute_id=dispute_id,
            submitted_by="seller",
            description=description,
            attachments=attachments or [],
            submitted_at=datetime.utcnow(),
        )

        if dispute_id not in self._evidence:
            self._evidence[dispute_id] = []

        self._evidence[dispute_id].append(evidence)
        dispute.seller_evidence.append(
            {
                "id": evidence_id,
                "description": description,
                "attachments": attachments or [],
            }
        )

        # Transition to decision phase
        if dispute.status == DisputeStatus.EVIDENCE_REVIEW:
            dispute.status = DisputeStatus.DECISION
            dispute.updated_at = datetime.utcnow()

        return evidence

    def check_auto_resolution(self, dispute_id: str) -> DisputeResolution | None:
        """Check if dispute qualifies for auto-resolution.

        Args:
            dispute_id: Dispute identifier.

        Returns:
            Resolution if auto-resolvable, None otherwise.

        Raises:
            DisputeNotFoundError: If dispute not found.
        """
        dispute = self.get_dispute(dispute_id)
        return DisputeRulesEngine.auto_resolve(dispute)

    def resolve_dispute(
        self,
        dispute_id: str,
        decision: str,
        refund_amount: Decimal,
        reason: str,
        decided_by: str = "admin",
    ) -> tuple[Dispute, DisputeResolution]:
        """Resolve dispute with decision.

        Args:
            dispute_id: Dispute identifier.
            decision: Resolution decision.
            refund_amount: Refund to issue.
            reason: Decision reason.
            decided_by: Who made decision.

        Returns:
            Tuple of (updated dispute, resolution).

        Raises:
            DisputeNotFoundError: If dispute not found.
            InvalidDisputeState: If cannot resolve in current state.
        """
        dispute = self.get_dispute(dispute_id)

        if dispute.status != DisputeStatus.DECISION:
            raise InvalidDisputeState(dispute_id, dispute.status.value)

        resolution = DisputeResolution(
            dispute_id=dispute_id,
            decision=decision,
            refund_amount=refund_amount,
            reason=reason,
            decided_at=datetime.utcnow(),
            decided_by=decided_by,
        )

        self._resolutions[dispute_id] = resolution

        dispute.resolution = reason
        dispute.resolved_at = datetime.utcnow()
        dispute.status = DisputeStatus.CLOSED
        dispute.updated_at = datetime.utcnow()

        # Calculate fairness score
        dispute.fairness_score = self._calculate_fairness_score(dispute, decision)

        return dispute, resolution

    def appeal_dispute(self, dispute_id: str, appeal_reason: str) -> Dispute:
        """Appeal closed dispute.

        Args:
            dispute_id: Dispute identifier.
            appeal_reason: Reason for appeal.

        Returns:
            Updated dispute.

        Raises:
            DisputeNotFoundError: If dispute not found.
            InvalidDisputeState: If cannot appeal.
        """
        dispute = self.get_dispute(dispute_id)

        if dispute.status != DisputeStatus.CLOSED:
            raise InvalidDisputeState(dispute_id, dispute.status.value)

        if dispute.appeal_count >= 2:
            raise DisputeException("Maximum appeals reached")

        dispute.status = DisputeStatus.APPEAL
        dispute.appeal_count += 1
        dispute.updated_at = datetime.utcnow()

        return dispute

    @staticmethod
    def _calculate_fairness_score(dispute: Dispute, decision: str) -> Decimal:
        """Calculate fairness score of resolution (0-100).

        Based on evidence quality and decision alignment.

        Args:
            dispute: Dispute with evidence.
            decision: Resolution decision.

        Returns:
            Fairness score.
        """
        score = Decimal("50")  # Baseline

        # Evidence completeness
        total_evidence = len(dispute.buyer_evidence) + len(dispute.seller_evidence)
        if total_evidence >= 2:
            score += Decimal("25")
        elif total_evidence >= 1:
            score += Decimal("15")

        # Balanced evidence
        if len(dispute.buyer_evidence) > 0 and len(dispute.seller_evidence) > 0:
            score += Decimal("25")

        return min(score, Decimal("100"))

    def list_order_disputes(self, order_id: str) -> list[Dispute]:
        """List disputes for an order.

        Args:
            order_id: Order identifier.

        Returns:
            List of disputes.
        """
        dispute_ids = self._order_disputes.get(order_id, [])
        return [self._disputes[did] for did in dispute_ids if did in self._disputes]

    def list_vendor_disputes(self, vendor_id: str) -> list[Dispute]:
        """List disputes involving vendor.

        Args:
            vendor_id: Vendor identifier.

        Returns:
            List of disputes.
        """
        return [d for d in self._disputes.values() if d.vendor_id == vendor_id]

    def list_disputes_by_status(self, status: DisputeStatus) -> list[Dispute]:
        """List disputes by status.

        Args:
            status: Filter by dispute status.

        Returns:
            List of disputes.
        """
        return [d for d in self._disputes.values() if d.status == status]

    def get_dispute_resolution(self, dispute_id: str) -> DisputeResolution | None:
        """Get resolution for dispute.

        Args:
            dispute_id: Dispute identifier.

        Returns:
            Resolution if exists, None otherwise.
        """
        return self._resolutions.get(dispute_id)
