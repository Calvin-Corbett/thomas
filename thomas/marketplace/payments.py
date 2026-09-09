"""Payment processing with escrow, commission calculations, and split payments."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from thomas.marketplace._exceptions import (
    InsufficientFunds,
    PaymentException,
    PaymentFailed,
)
from thomas.marketplace._types import (
    Commission,
    CommissionTier,
    Payment,
    PaymentStatus,
)


@dataclass
class PaymentSplit:
    """Payment split between platform and vendor."""

    platform_fee: Decimal
    vendor_amount: Decimal
    commission_rate: Decimal
    commission_tier: CommissionTier


@dataclass
class PayoutBatch:
    """Batch payout to vendors."""

    id: str
    period_start: datetime
    period_end: datetime
    vendor_payouts: dict[str, Decimal] = field(default_factory=dict)
    total_amount: Decimal = Decimal("0")
    status: str = "pending"
    created_at: datetime = field(default_factory=datetime.utcnow)
    processed_at: datetime | None = None


class PaymentGatewayAdapter:
    """Abstract payment gateway for processing charges and refunds."""

    def __init__(self) -> None:
        """Initialize payment gateway."""
        self._transactions: dict[str, dict] = {}

    def charge(self, amount: Decimal, currency: str, description: str = "") -> str:
        """Process payment charge.

        Args:
            amount: Amount to charge.
            currency: Currency code.
            description: Payment description.

        Returns:
            Transaction ID.

        Raises:
            PaymentFailed: If charge fails.
            InsufficientFunds: If insufficient funds.
        """
        if amount <= Decimal("0"):
            raise PaymentFailed("", "Invalid amount")

        txn_id = f"txn_{uuid.uuid4().hex[:12]}"

        # Simulate gateway processing
        if amount > Decimal("10000"):
            raise InsufficientFunds()

        self._transactions[txn_id] = {
            "amount": amount,
            "currency": currency,
            "type": "charge",
            "status": "authorized",
            "created_at": datetime.utcnow(),
        }

        return txn_id

    def capture(self, txn_id: str) -> str:
        """Capture previously authorized payment.

        Args:
            txn_id: Transaction ID from charge.

        Returns:
            Capture ID.

        Raises:
            PaymentFailed: If capture fails.
        """
        if txn_id not in self._transactions:
            raise PaymentFailed(txn_id, "Transaction not found")

        txn = self._transactions[txn_id]
        if txn["status"] != "authorized":
            raise PaymentFailed(txn_id, "Transaction not authorized")

        txn["status"] = "captured"
        capture_id = f"cap_{uuid.uuid4().hex[:12]}"

        return capture_id

    def refund(self, txn_id: str, amount: Decimal | None = None) -> str:
        """Refund payment (full or partial).

        Args:
            txn_id: Transaction ID.
            amount: Amount to refund (None for full).

        Returns:
            Refund ID.

        Raises:
            PaymentFailed: If refund fails.
        """
        if txn_id not in self._transactions:
            raise PaymentFailed(txn_id, "Transaction not found")

        txn = self._transactions[txn_id]
        if txn["status"] not in ("captured", "refunded"):
            raise PaymentFailed(txn_id, "Transaction cannot be refunded")

        refund_amount = amount or txn["amount"]
        if refund_amount > txn["amount"]:
            raise PaymentFailed(txn_id, "Refund exceeds original amount")

        refund_id = f"refund_{uuid.uuid4().hex[:12]}"
        txn["status"] = "refunded"
        txn["refund_amount"] = refund_amount

        return refund_id


class EscrowManager:
    """Hold payments in escrow until delivery confirmed."""

    def __init__(self) -> None:
        """Initialize escrow manager."""
        self._escrows: dict[str, dict] = {}

    def hold_payment(self, order_id: str, amount: Decimal, hold_days: int = 14) -> str:
        """Hold payment in escrow until delivery confirmed.

        Args:
            order_id: Order identifier.
            amount: Amount to hold.
            hold_days: Days to hold before auto-release.

        Returns:
            Escrow ID.
        """
        escrow_id = f"escrow_{uuid.uuid4().hex[:12]}"

        self._escrows[escrow_id] = {
            "order_id": order_id,
            "amount": amount,
            "status": "held",
            "created_at": datetime.utcnow(),
            "release_at": datetime.utcnow() + timedelta(days=hold_days),
            "released_at": None,
        }

        return escrow_id

    def release_escrow(self, escrow_id: str) -> Decimal:
        """Release held payment to vendor.

        Args:
            escrow_id: Escrow ID.

        Returns:
            Released amount.

        Raises:
            PaymentException: If escrow not found.
        """
        if escrow_id not in self._escrows:
            raise PaymentException(f"Escrow not found: {escrow_id}")

        escrow = self._escrows[escrow_id]
        if escrow["status"] != "held":
            raise PaymentException(f"Escrow already released: {escrow_id}")

        escrow["status"] = "released"
        escrow["released_at"] = datetime.utcnow()

        return escrow["amount"]

    def auto_release_expired(self) -> list[tuple[str, Decimal]]:
        """Release all escrows that expired.

        Returns:
            List of (escrow_id, amount) released.
        """
        released = []
        now = datetime.utcnow()

        for escrow_id, escrow in self._escrows.items():
            if escrow["status"] == "held" and escrow["release_at"] <= now:
                escrow["status"] = "released"
                escrow["released_at"] = now
                released.append((escrow_id, escrow["amount"]))

        return released


class CommissionCalculator:
    """Calculate commissions with tier-based rates."""

    def __init__(self) -> None:
        """Initialize commission calculator."""
        self._commission_schedules: dict[str, list[Commission]] = {}

    def set_commission_schedule(self, vendor_id: str, commissions: list[Commission]) -> None:
        """Set commission schedule for vendor.

        Args:
            vendor_id: Vendor identifier.
            commissions: List of commission tiers.
        """
        self._commission_schedules[vendor_id] = commissions

    def calculate_commission(self, vendor_id: str, amount: Decimal, tier: CommissionTier) -> Decimal:
        """Calculate commission for transaction.

        Args:
            vendor_id: Vendor identifier.
            amount: Transaction amount.
            tier: Commission tier.

        Returns:
            Commission amount.
        """
        commissions = self._commission_schedules.get(vendor_id, [])

        # Find applicable commission for tier
        commission = None
        for comm in commissions:
            if comm.tier == tier:
                now = datetime.utcnow()
                if comm.effective_from <= now and (comm.effective_to is None or comm.effective_to > now):
                    commission = comm
                    break

        if not commission:
            # Default commission
            default_rate = self._get_default_rate(tier)
            return amount * default_rate / Decimal("100")

        return commission.calculate(amount)

    @staticmethod
    def _get_default_rate(tier: CommissionTier) -> Decimal:
        """Get default commission rate for tier.

        Args:
            tier: Commission tier.

        Returns:
            Commission percentage.
        """
        rates: dict[CommissionTier, Decimal] = {
            CommissionTier.TIER_1: Decimal("15"),
            CommissionTier.TIER_2: Decimal("12"),
            CommissionTier.TIER_3: Decimal("10"),
            CommissionTier.TIER_4: Decimal("8"),
        }
        return rates.get(tier, Decimal("15"))


class PaymentProcessor:
    """Process payments, split between platform and vendor."""

    def __init__(self) -> None:
        """Initialize payment processor."""
        self._payments: dict[str, Payment] = {}
        self._gateway = PaymentGatewayAdapter()
        self._escrow = EscrowManager()
        self._commission_calc = CommissionCalculator()

    def process_payment(
        self,
        order_id: str,
        amount: Decimal,
        currency: str = "USD",
        use_escrow: bool = True,
    ) -> Payment:
        """Process payment for order.

        Args:
            order_id: Order identifier.
            amount: Total amount.
            currency: Currency code.
            use_escrow: Whether to use escrow.

        Returns:
            Payment object.

        Raises:
            PaymentFailed: If payment fails.
        """
        payment_id = f"payment_{uuid.uuid4().hex[:12]}"

        try:
            txn_id = self._gateway.charge(amount, currency, f"Order {order_id}")
        except (PaymentFailed, InsufficientFunds):
            payment = Payment(
                id=payment_id,
                order_id=order_id,
                amount=amount,
                currency=currency,
                status=PaymentStatus.FAILED,
                gateway_id="",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            self._payments[payment_id] = payment
            raise

        # Capture payment
        try:
            self._gateway.capture(txn_id)
        except PaymentFailed:
            raise

        # Hold in escrow if specified
        if use_escrow:
            self._escrow.hold_payment(order_id, amount)

        payment = Payment(
            id=payment_id,
            order_id=order_id,
            amount=amount,
            currency=currency,
            status=PaymentStatus.CAPTURED,
            gateway_id=txn_id,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            is_escrow=use_escrow,
        )

        self._payments[payment_id] = payment
        return payment

    def calculate_split_payment(
        self,
        order_amount: Decimal,
        commission_tier: CommissionTier,
        vendor_id: str,
    ) -> PaymentSplit:
        """Calculate platform fee and vendor payout.

        Args:
            order_amount: Order total amount.
            commission_tier: Vendor commission tier.
            vendor_id: Vendor identifier.

        Returns:
            Payment split breakdown.
        """
        commission = self._commission_calc.calculate_commission(vendor_id, order_amount, commission_tier)
        vendor_amount = order_amount - commission

        return PaymentSplit(
            platform_fee=commission,
            vendor_amount=vendor_amount,
            commission_rate=commission / order_amount * Decimal("100") if order_amount > 0 else Decimal("0"),
            commission_tier=commission_tier,
        )

    def refund_payment(self, payment_id: str, amount: Decimal | None = None) -> Payment:
        """Refund payment (full or partial).

        Args:
            payment_id: Payment identifier.
            amount: Refund amount (None for full).

        Returns:
            Updated payment.

        Raises:
            PaymentException: If refund fails.
        """
        if payment_id not in self._payments:
            raise PaymentException(f"Payment not found: {payment_id}")

        payment = self._payments[payment_id]
        refund_amount = amount or payment.amount

        try:
            self._gateway.refund(payment.gateway_id, refund_amount)
        except PaymentFailed as e:
            raise PaymentException(str(e))

        payment.refund_amount = refund_amount
        payment.status = PaymentStatus.REFUNDED
        payment.updated_at = datetime.utcnow()

        return payment

    def create_payout_batch(
        self,
        period_start: datetime,
        period_end: datetime,
        vendor_payouts: dict[str, Decimal],
    ) -> PayoutBatch:
        """Create batch payout to vendors.

        Args:
            period_start: Period start date.
            period_end: Period end date.
            vendor_payouts: Vendor ID to payout amount mapping.

        Returns:
            Payout batch.
        """
        total = sum(vendor_payouts.values())

        batch = PayoutBatch(
            id=f"batch_{uuid.uuid4().hex[:12]}",
            period_start=period_start,
            period_end=period_end,
            vendor_payouts=vendor_payouts,
            total_amount=total,
        )

        return batch

    def get_payment(self, payment_id: str) -> Payment:
        """Get payment by ID.

        Args:
            payment_id: Payment identifier.

        Returns:
            Payment object.

        Raises:
            PaymentException: If payment not found.
        """
        if payment_id not in self._payments:
            raise PaymentException(f"Payment not found: {payment_id}")

        return self._payments[payment_id]

    def list_order_payments(self, order_id: str) -> list[Payment]:
        """List all payments for an order.

        Args:
            order_id: Order identifier.

        Returns:
            List of payments.
        """
        return [p for p in self._payments.values() if p.order_id == order_id]
