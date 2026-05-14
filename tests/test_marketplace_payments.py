"""Tests for payment processing module."""

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from thomas.marketplace._exceptions import (
    InsufficientFunds,
    PaymentFailed,
)
from thomas.marketplace._types import (
    CommissionTier,
    PaymentStatus,
)
from thomas.marketplace.payments import (
    CommissionCalculator,
    EscrowManager,
    PaymentGatewayAdapter,
    PaymentProcessor,
)


class TestPaymentGatewayAdapter:
    """Test payment gateway operations."""

    def test_charge_valid_amount(self) -> None:
        """Test charging valid amount."""
        gateway = PaymentGatewayAdapter()

        txn_id = gateway.charge(Decimal("99.99"), "USD", "Order #123")

        assert txn_id.startswith("txn_")
        assert txn_id in gateway._transactions

    def test_charge_invalid_amount(self) -> None:
        """Test charging invalid amount."""
        gateway = PaymentGatewayAdapter()

        with pytest.raises(PaymentFailed):
            gateway.charge(Decimal("0"), "USD")

    def test_charge_insufficient_funds(self) -> None:
        """Test charge with insufficient funds."""
        gateway = PaymentGatewayAdapter()

        with pytest.raises(InsufficientFunds):
            gateway.charge(Decimal("50000"), "USD")

    def test_capture_authorization(self) -> None:
        """Test capturing authorized payment."""
        gateway = PaymentGatewayAdapter()

        txn_id = gateway.charge(Decimal("99.99"), "USD")
        capture_id = gateway.capture(txn_id)

        assert capture_id.startswith("cap_")

    def test_capture_nonexistent_transaction(self) -> None:
        """Test capturing nonexistent transaction."""
        gateway = PaymentGatewayAdapter()

        with pytest.raises(PaymentFailed):
            gateway.capture("txn_nonexistent")

    def test_refund_captured_payment(self) -> None:
        """Test refunding captured payment."""
        gateway = PaymentGatewayAdapter()

        txn_id = gateway.charge(Decimal("99.99"), "USD")
        gateway.capture(txn_id)
        refund_id = gateway.refund(txn_id)

        assert refund_id.startswith("refund_")

    def test_partial_refund(self) -> None:
        """Test partial refund."""
        gateway = PaymentGatewayAdapter()

        txn_id = gateway.charge(Decimal("100.00"), "USD")
        gateway.capture(txn_id)
        refund_id = gateway.refund(txn_id, Decimal("50.00"))

        assert refund_id.startswith("refund_")

    def test_refund_exceeds_amount(self) -> None:
        """Test refund exceeding original amount."""
        gateway = PaymentGatewayAdapter()

        txn_id = gateway.charge(Decimal("100.00"), "USD")
        gateway.capture(txn_id)

        with pytest.raises(PaymentFailed):
            gateway.refund(txn_id, Decimal("150.00"))


class TestEscrowManager:
    """Test escrow operations."""

    def test_hold_payment(self) -> None:
        """Test holding payment in escrow."""
        escrow = EscrowManager()

        escrow_id = escrow.hold_payment("order_1", Decimal("99.99"))

        assert escrow_id.startswith("escrow_")
        assert escrow_id in escrow._escrows

    def test_release_escrow(self) -> None:
        """Test releasing escrow."""
        escrow = EscrowManager()

        escrow_id = escrow.hold_payment("order_1", Decimal("99.99"))
        amount = escrow.release_escrow(escrow_id)

        assert amount == Decimal("99.99")
        assert escrow._escrows[escrow_id]["status"] == "released"

    def test_auto_release_expired(self) -> None:
        """Test auto-releasing expired escrows."""
        escrow = EscrowManager()

        escrow_id = escrow.hold_payment("order_1", Decimal("99.99"), hold_days=0)

        released = escrow.auto_release_expired()

        assert len(released) == 1
        assert released[0][0] == escrow_id
        assert released[0][1] == Decimal("99.99")


class TestCommissionCalculator:
    """Test commission calculation."""

    def test_calculate_commission_tier1(self) -> None:
        """Test commission for tier 1."""
        calc = CommissionCalculator()

        commission = calc.calculate_commission(
            "vendor_1",
            Decimal("1000.00"),
            CommissionTier.TIER_1,
        )

        # Default tier 1 is 15%
        assert commission == Decimal("150.00")

    def test_calculate_commission_tier4(self) -> None:
        """Test commission for tier 4 is lower."""
        calc = CommissionCalculator()

        comm1 = calc.calculate_commission(
            "vendor_1",
            Decimal("1000.00"),
            CommissionTier.TIER_1,
        )

        comm4 = calc.calculate_commission(
            "vendor_1",
            Decimal("1000.00"),
            CommissionTier.TIER_4,
        )

        assert comm4 < comm1


class TestPaymentProcessor:
    """Test payment processing."""

    def test_process_payment(self) -> None:
        """Test processing payment."""
        processor = PaymentProcessor()

        payment = processor.process_payment(
            order_id="order_1",
            amount=Decimal("99.99"),
            currency="USD",
        )

        assert payment.status == PaymentStatus.CAPTURED
        assert payment.amount == Decimal("99.99")

    def test_process_payment_with_escrow(self) -> None:
        """Test processing payment with escrow."""
        processor = PaymentProcessor()

        payment = processor.process_payment(
            order_id="order_1",
            amount=Decimal("99.99"),
            use_escrow=True,
        )

        assert payment.is_escrow

    def test_process_payment_without_escrow(self) -> None:
        """Test processing payment without escrow."""
        processor = PaymentProcessor()

        payment = processor.process_payment(
            order_id="order_1",
            amount=Decimal("99.99"),
            use_escrow=False,
        )

        assert not payment.is_escrow

    def test_refund_payment(self) -> None:
        """Test refunding payment."""
        processor = PaymentProcessor()

        payment = processor.process_payment(
            order_id="order_1",
            amount=Decimal("99.99"),
        )

        refunded = processor.refund_payment(payment.id)
        assert refunded.status == PaymentStatus.REFUNDED

    def test_partial_refund(self) -> None:
        """Test partial refund."""
        processor = PaymentProcessor()

        payment = processor.process_payment(
            order_id="order_1",
            amount=Decimal("100.00"),
        )

        refunded = processor.refund_payment(payment.id, Decimal("50.00"))
        assert refunded.refund_amount == Decimal("50.00")

    def test_calculate_split_payment(self) -> None:
        """Test calculating split payment."""
        processor = PaymentProcessor()

        split = processor.calculate_split_payment(
            order_amount=Decimal("1000.00"),
            commission_tier=CommissionTier.TIER_1,
            vendor_id="vendor_1",
        )

        assert split.platform_fee > Decimal("0")
        assert split.vendor_amount < Decimal("1000.00")
        assert split.platform_fee + split.vendor_amount == Decimal("1000.00")

    def test_create_payout_batch(self) -> None:
        """Test creating payout batch."""
        processor = PaymentProcessor()

        payouts = {
            "vendor_1": Decimal("500.00"),
            "vendor_2": Decimal("300.00"),
        }

        batch = processor.create_payout_batch(
            period_start=datetime.utcnow(),
            period_end=datetime.utcnow() + timedelta(days=30),
            vendor_payouts=payouts,
        )

        assert batch.id.startswith("batch_")
        assert batch.total_amount == Decimal("800.00")
        assert len(batch.vendor_payouts) == 2

    def test_list_order_payments(self) -> None:
        """Test listing payments for order."""
        processor = PaymentProcessor()

        processor.process_payment("order_1", Decimal("99.99"))
        processor.process_payment("order_1", Decimal("50.00"))
        processor.process_payment("order_2", Decimal("75.00"))

        order1_payments = processor.list_order_payments("order_1")
        assert len(order1_payments) == 2

        order2_payments = processor.list_order_payments("order_2")
        assert len(order2_payments) == 1
