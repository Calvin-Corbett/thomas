"""
Payment processing and transaction management.

Implements payment request creation, validation, routing, fee calculation,
status tracking, idempotency management, and refund processing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from uuid import uuid4

from ._exceptions import FintechError
from ._types import Currency


class PaymentStatus(str, Enum):
    """Payment status."""

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REVERSED = "REVERSED"
    CANCELLED = "CANCELLED"


class FeeType(str, Enum):
    """Fee calculation type."""

    FLAT = "FLAT"
    PERCENTAGE = "PERCENTAGE"
    TIERED = "TIERED"


class PaymentMethod(str, Enum):
    """Payment method."""

    ACH = "ACH"
    WIRE = "WIRE"
    CARD = "CARD"
    BANK_TRANSFER = "BANK_TRANSFER"
    DIGITAL_WALLET = "DIGITAL_WALLET"


@dataclass
class FeeComponent:
    """
    Individual fee component.

    Attributes:
        type: Fee type (FLAT, PERCENTAGE, TIERED)
        amount: Flat fee amount or percentage/threshold for tiered
        description: Fee description
    """

    type: FeeType
    amount: Decimal
    description: str = ""


@dataclass
class PaymentRequest:
    """
    Payment request.

    Attributes:
        id: Payment request ID
        idempotency_key: Idempotency key for duplicate prevention
        from_account: Sender account ID
        to_account: Recipient account ID
        amount: Payment amount
        currency: Payment currency
        method: Payment method
        status: Current status
        fee_amount: Calculated fee
        net_amount: Amount after fees
        created_at: Creation timestamp
        scheduled_for: Scheduled execution time
        completed_at: Completion timestamp
        description: Payment description
        reference: Reference information
    """

    id: str
    idempotency_key: str
    from_account: str
    to_account: str
    amount: Decimal
    currency: Currency
    method: PaymentMethod
    status: PaymentStatus = PaymentStatus.PENDING
    fee_amount: Decimal = Decimal("0")
    net_amount: Decimal = Decimal("0")
    created_at: datetime = field(default_factory=datetime.utcnow)
    scheduled_for: datetime | None = None
    completed_at: datetime | None = None
    description: str = ""
    reference: str = ""

    def get_total_amount(self) -> Decimal:
        """Get total amount including fees."""
        return self.amount + self.fee_amount

    def is_pending(self) -> bool:
        """Check if payment is pending."""
        return self.status == PaymentStatus.PENDING

    def is_completed(self) -> bool:
        """Check if payment is completed."""
        return self.status == PaymentStatus.COMPLETED

    def is_reversible(self) -> bool:
        """Check if payment can be reversed."""
        return self.status in (
            PaymentStatus.COMPLETED,
            PaymentStatus.PROCESSING,
        )


@dataclass
class PaymentRefund:
    """
    Payment refund request.

    Attributes:
        id: Refund ID
        payment_id: Original payment ID
        amount: Refund amount
        reason: Refund reason
        status: Refund status
        created_at: Request timestamp
        processed_at: Processing timestamp
    """

    id: str
    payment_id: str
    amount: Decimal
    reason: str
    status: PaymentStatus = PaymentStatus.PENDING
    created_at: datetime = field(default_factory=datetime.utcnow)
    processed_at: datetime | None = None


class PaymentProcessor:
    """
    Process payments and manage payment lifecycle.

    Handles payment creation, validation, processing, and tracking.
    """

    def __init__(self) -> None:
        """Initialize payment processor."""
        self.payments: dict[str, PaymentRequest] = {}
        self.idempotency_cache: dict[str, str] = {}  # idempotency_key -> payment_id
        self.refunds: dict[str, PaymentRefund] = {}
        self.payment_counter = 0

    def create_payment(
        self,
        from_account: str,
        to_account: str,
        amount: Decimal,
        currency: Currency,
        method: PaymentMethod,
        idempotency_key: str | None = None,
        description: str = "",
        scheduled_for: datetime | None = None,
    ) -> PaymentRequest:
        """
        Create payment request.

        Args:
            from_account: Sender account
            to_account: Recipient account
            amount: Amount to pay
            currency: Payment currency
            method: Payment method
            idempotency_key: Idempotency key for duplicate prevention
            description: Payment description
            scheduled_for: Scheduled execution time

        Returns:
            Payment request

        Raises:
            FintechError: If payment creation fails
        """
        if idempotency_key is None:
            idempotency_key = str(uuid4())

        # Check for duplicate
        if idempotency_key in self.idempotency_cache:
            return self.payments[self.idempotency_cache[idempotency_key]]

        if amount <= 0:
            raise FintechError("Payment amount must be positive")

        if from_account == to_account:
            raise FintechError("Cannot send payment to same account")

        self.payment_counter += 1
        payment_id = f"PAY-{self.payment_counter:010d}"

        payment = PaymentRequest(
            id=payment_id,
            idempotency_key=idempotency_key,
            from_account=from_account,
            to_account=to_account,
            amount=amount,
            currency=currency,
            method=method,
            description=description,
            scheduled_for=scheduled_for,
        )

        self.payments[payment_id] = payment
        self.idempotency_cache[idempotency_key] = payment_id

        return payment

    def validate_payment(self, payment_id: str) -> bool:
        """
        Validate payment request.

        Args:
            payment_id: Payment ID

        Returns:
            True if valid

        Raises:
            FintechError: If validation fails
        """
        if payment_id not in self.payments:
            raise FintechError(f"Payment {payment_id} not found")

        payment = self.payments[payment_id]

        if payment.status != PaymentStatus.PENDING:
            raise FintechError(f"Payment {payment_id} is not pending")

        if payment.amount <= 0:
            raise FintechError("Payment amount must be positive")

        return True

    def calculate_fee(
        self,
        payment: PaymentRequest,
        fee_components: list[FeeComponent],
    ) -> Decimal:
        """
        Calculate total fee for payment.

        Args:
            payment: Payment request
            fee_components: Fee components to apply

        Returns:
            Total fee amount
        """
        total_fee = Decimal("0")

        for component in fee_components:
            if component.type == FeeType.FLAT:
                total_fee += component.amount
            elif component.type == FeeType.PERCENTAGE:
                percentage = component.amount / 100
                total_fee += payment.amount * percentage

        return total_fee

    def apply_fee(
        self,
        payment_id: str,
        fee_amount: Decimal,
    ) -> bool:
        """
        Apply fee to payment.

        Args:
            payment_id: Payment ID
            fee_amount: Fee amount

        Returns:
            True if fee applied
        """
        if payment_id not in self.payments:
            return False

        payment = self.payments[payment_id]
        payment.fee_amount = fee_amount
        payment.net_amount = payment.amount - fee_amount
        return True

    def process_payment(self, payment_id: str) -> bool:
        """
        Process payment.

        Args:
            payment_id: Payment ID

        Returns:
            True if processed

        Raises:
            FintechError: If processing fails
        """
        if payment_id not in self.payments:
            raise FintechError(f"Payment {payment_id} not found")

        payment = self.payments[payment_id]

        if not payment.is_pending():
            raise FintechError(f"Payment {payment_id} cannot be processed")

        payment.status = PaymentStatus.PROCESSING
        return True

    def complete_payment(
        self,
        payment_id: str,
        reference: str = "",
    ) -> bool:
        """
        Mark payment as completed.

        Args:
            payment_id: Payment ID
            reference: Transaction reference

        Returns:
            True if completed
        """
        if payment_id not in self.payments:
            return False

        payment = self.payments[payment_id]
        payment.status = PaymentStatus.COMPLETED
        payment.completed_at = datetime.utcnow()
        payment.reference = reference
        return True

    def fail_payment(self, payment_id: str, reason: str = "") -> bool:
        """
        Mark payment as failed.

        Args:
            payment_id: Payment ID
            reason: Failure reason

        Returns:
            True if failed
        """
        if payment_id not in self.payments:
            return False

        payment = self.payments[payment_id]
        payment.status = PaymentStatus.FAILED
        payment.description += f" [FAILED: {reason}]"
        return True

    def get_payment(self, payment_id: str) -> PaymentRequest | None:
        """Get payment by ID."""
        return self.payments.get(payment_id)

    def get_payment_by_idempotency(self, idempotency_key: str) -> PaymentRequest | None:
        """Get payment by idempotency key."""
        if idempotency_key not in self.idempotency_cache:
            return None
        payment_id = self.idempotency_cache[idempotency_key]
        return self.payments.get(payment_id)

    def get_account_payments(
        self,
        account_id: str,
        direction: str = "both",
    ) -> list[PaymentRequest]:
        """
        Get payments for account.

        Args:
            account_id: Account ID
            direction: "sent", "received", or "both"

        Returns:
            List of payments
        """
        payments = []

        for payment in self.payments.values():
            if (
                direction in ("both", "sent")
                and payment.from_account == account_id
                or direction in ("both", "received")
                and payment.to_account == account_id
            ):
                payments.append(payment)

        return payments


class RefundProcessor:
    """
    Process refunds for payments.

    Handles refund requests, validation, and processing.
    """

    def __init__(self, payment_processor: PaymentProcessor) -> None:
        """
        Initialize refund processor.

        Args:
            payment_processor: Payment processor instance
        """
        self.payment_processor = payment_processor
        self.refund_counter = 0

    def create_refund(
        self,
        payment_id: str,
        amount: Decimal | None = None,
        reason: str = "",
    ) -> PaymentRefund:
        """
        Create refund request.

        Args:
            payment_id: Original payment ID
            amount: Refund amount (None = full amount)
            reason: Refund reason

        Returns:
            Refund request

        Raises:
            FintechError: If refund creation fails
        """
        payment = self.payment_processor.get_payment(payment_id)
        if payment is None:
            raise FintechError(f"Payment {payment_id} not found")

        if not payment.is_reversible():
            raise FintechError(f"Payment {payment_id} cannot be refunded")

        if amount is None:
            amount = payment.net_amount
        elif amount > payment.net_amount:
            raise FintechError("Refund amount exceeds payment amount")

        self.refund_counter += 1
        refund_id = f"REF-{self.refund_counter:010d}"

        return PaymentRefund(
            id=refund_id,
            payment_id=payment_id,
            amount=amount,
            reason=reason,
        )

    def process_refund(self, refund: PaymentRefund) -> bool:
        """
        Process refund.

        Args:
            refund: Refund request

        Returns:
            True if processed
        """
        payment = self.payment_processor.get_payment(refund.payment_id)
        if payment is None:
            return False

        refund.status = PaymentStatus.PROCESSING
        return True

    def complete_refund(self, refund_id: str) -> bool:
        """
        Complete refund.

        Args:
            refund_id: Refund ID

        Returns:
            True if completed
        """
        if refund_id not in self.payment_processor.refunds:
            return False

        refund = self.payment_processor.refunds[refund_id]
        refund.status = PaymentStatus.COMPLETED
        refund.processed_at = datetime.utcnow()

        # Mark original payment as reversed
        payment = self.payment_processor.get_payment(refund.payment_id)
        if payment:
            payment.status = PaymentStatus.REVERSED

        return True
