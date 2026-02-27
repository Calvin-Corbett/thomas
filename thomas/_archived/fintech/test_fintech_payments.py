"""
Tests for payment processing.

Tests for payment creation, validation, fee calculation, status tracking,
idempotency, and refund processing.
"""

from decimal import Decimal

import pytest
from _exceptions import FintechError
from _types import Currency
from payments import (
    FeeComponent,
    FeeType,
    PaymentMethod,
    PaymentProcessor,
    PaymentStatus,
    RefundProcessor,
)


class TestPaymentProcessor:
    """Test payment processing."""

    def setup_method(self):
        """Set up test fixtures."""
        self.processor = PaymentProcessor()

    def test_create_payment(self):
        """Test payment creation."""
        payment = self.processor.create_payment(
            from_account="ACC001",
            to_account="ACC002",
            amount=Decimal("100.00"),
            currency=Currency.USD,
            method=PaymentMethod.ACH,
            description="Test payment",
        )

        assert payment.from_account == "ACC001"
        assert payment.to_account == "ACC002"
        assert payment.amount == Decimal("100.00")
        assert payment.status == PaymentStatus.PENDING

    def test_idempotency(self):
        """Test idempotency key prevents duplicates."""
        idempotency_key = "IDEMPOTENT-001"

        payment1 = self.processor.create_payment(
            from_account="ACC001",
            to_account="ACC002",
            amount=Decimal("100.00"),
            currency=Currency.USD,
            method=PaymentMethod.ACH,
            idempotency_key=idempotency_key,
        )

        payment2 = self.processor.create_payment(
            from_account="ACC001",
            to_account="ACC002",
            amount=Decimal("100.00"),
            currency=Currency.USD,
            method=PaymentMethod.ACH,
            idempotency_key=idempotency_key,
        )

        # Should return same payment
        assert payment1.id == payment2.id

    def test_payment_validation(self):
        """Test payment validation."""
        payment = self.processor.create_payment(
            from_account="ACC001",
            to_account="ACC002",
            amount=Decimal("100.00"),
            currency=Currency.USD,
            method=PaymentMethod.ACH,
        )

        assert self.processor.validate_payment(payment.id) is True

    def test_validate_nonexistent_payment(self):
        """Test validation of non-existent payment."""
        with pytest.raises(FintechError):
            self.processor.validate_payment("NONEXISTENT")

    def test_same_account_payment(self):
        """Test that payments to same account are rejected."""
        with pytest.raises(FintechError):
            self.processor.create_payment(
                from_account="ACC001",
                to_account="ACC001",
                amount=Decimal("100.00"),
                currency=Currency.USD,
                method=PaymentMethod.ACH,
            )

    def test_zero_amount_payment(self):
        """Test that zero amount payments are rejected."""
        with pytest.raises(FintechError):
            self.processor.create_payment(
                from_account="ACC001",
                to_account="ACC002",
                amount=Decimal("0"),
                currency=Currency.USD,
                method=PaymentMethod.ACH,
            )

    def test_apply_flat_fee(self):
        """Test applying flat fee."""
        payment = self.processor.create_payment(
            from_account="ACC001",
            to_account="ACC002",
            amount=Decimal("100.00"),
            currency=Currency.USD,
            method=PaymentMethod.ACH,
        )

        self.processor.apply_fee(payment.id, Decimal("2.50"))

        assert payment.fee_amount == Decimal("2.50")
        assert payment.net_amount == Decimal("97.50")

    def test_calculate_percentage_fee(self):
        """Test percentage fee calculation."""
        payment = self.processor.create_payment(
            from_account="ACC001",
            to_account="ACC002",
            amount=Decimal("1000.00"),
            currency=Currency.USD,
            method=PaymentMethod.ACH,
        )

        fees = [
            FeeComponent(
                type=FeeType.PERCENTAGE,
                amount=Decimal("1"),
                description="1% fee",
            )
        ]

        fee = self.processor.calculate_fee(payment, fees)

        assert fee == Decimal("10.00")

    def test_process_payment(self):
        """Test payment processing."""
        payment = self.processor.create_payment(
            from_account="ACC001",
            to_account="ACC002",
            amount=Decimal("100.00"),
            currency=Currency.USD,
            method=PaymentMethod.ACH,
        )

        self.processor.process_payment(payment.id)

        assert payment.status == PaymentStatus.PROCESSING

    def test_complete_payment(self):
        """Test completing payment."""
        payment = self.processor.create_payment(
            from_account="ACC001",
            to_account="ACC002",
            amount=Decimal("100.00"),
            currency=Currency.USD,
            method=PaymentMethod.ACH,
        )

        self.processor.process_payment(payment.id)
        self.processor.complete_payment(payment.id, reference="TXN-123")

        assert payment.status == PaymentStatus.COMPLETED
        assert payment.reference == "TXN-123"
        assert payment.completed_at is not None

    def test_fail_payment(self):
        """Test payment failure."""
        payment = self.processor.create_payment(
            from_account="ACC001",
            to_account="ACC002",
            amount=Decimal("100.00"),
            currency=Currency.USD,
            method=PaymentMethod.ACH,
        )

        self.processor.fail_payment(payment.id, reason="Insufficient funds")

        assert payment.status == PaymentStatus.FAILED

    def test_get_account_payments(self):
        """Test retrieving account payments."""
        payment1 = self.processor.create_payment(
            from_account="ACC001",
            to_account="ACC002",
            amount=Decimal("100.00"),
            currency=Currency.USD,
            method=PaymentMethod.ACH,
        )

        payment2 = self.processor.create_payment(
            from_account="ACC003",
            to_account="ACC001",
            amount=Decimal("50.00"),
            currency=Currency.USD,
            method=PaymentMethod.ACH,
        )

        sent = self.processor.get_account_payments("ACC001", "sent")
        received = self.processor.get_account_payments("ACC001", "received")

        assert len(sent) == 1
        assert len(received) == 1

    def test_get_payment_by_idempotency(self):
        """Test retrieving payment by idempotency key."""
        idempotency_key = "UNIQUE-KEY"

        payment = self.processor.create_payment(
            from_account="ACC001",
            to_account="ACC002",
            amount=Decimal("100.00"),
            currency=Currency.USD,
            method=PaymentMethod.ACH,
            idempotency_key=idempotency_key,
        )

        retrieved = self.processor.get_payment_by_idempotency(idempotency_key)

        assert retrieved.id == payment.id


class TestRefundProcessor:
    """Test refund processing."""

    def setup_method(self):
        """Set up test fixtures."""
        self.payment_processor = PaymentProcessor()
        self.refund_processor = RefundProcessor(self.payment_processor)

    def test_create_refund(self):
        """Test refund creation."""
        payment = self.payment_processor.create_payment(
            from_account="ACC001",
            to_account="ACC002",
            amount=Decimal("100.00"),
            currency=Currency.USD,
            method=PaymentMethod.ACH,
        )

        self.payment_processor.process_payment(payment.id)
        self.payment_processor.complete_payment(payment.id)

        refund = self.refund_processor.create_refund(
            payment.id,
            reason="Customer request",
        )

        assert refund.payment_id == payment.id
        assert refund.amount == payment.net_amount

    def test_partial_refund(self):
        """Test partial refund."""
        payment = self.payment_processor.create_payment(
            from_account="ACC001",
            to_account="ACC002",
            amount=Decimal("100.00"),
            currency=Currency.USD,
            method=PaymentMethod.ACH,
        )

        self.payment_processor.process_payment(payment.id)
        self.payment_processor.complete_payment(payment.id)

        refund = self.refund_processor.create_refund(
            payment.id,
            amount=Decimal("50.00"),
            reason="Partial refund",
        )

        assert refund.amount == Decimal("50.00")

    def test_refund_exceeds_payment(self):
        """Test that refund cannot exceed payment."""
        payment = self.payment_processor.create_payment(
            from_account="ACC001",
            to_account="ACC002",
            amount=Decimal("100.00"),
            currency=Currency.USD,
            method=PaymentMethod.ACH,
        )

        self.payment_processor.process_payment(payment.id)
        self.payment_processor.complete_payment(payment.id)

        with pytest.raises(FintechError):
            self.refund_processor.create_refund(
                payment.id,
                amount=Decimal("200.00"),
            )

    def test_refund_pending_payment(self):
        """Test that pending payments cannot be refunded."""
        payment = self.payment_processor.create_payment(
            from_account="ACC001",
            to_account="ACC002",
            amount=Decimal("100.00"),
            currency=Currency.USD,
            method=PaymentMethod.ACH,
        )

        with pytest.raises(FintechError):
            self.refund_processor.create_refund(payment.id)

    def test_process_refund(self):
        """Test refund processing."""
        payment = self.payment_processor.create_payment(
            from_account="ACC001",
            to_account="ACC002",
            amount=Decimal("100.00"),
            currency=Currency.USD,
            method=PaymentMethod.ACH,
        )

        self.payment_processor.process_payment(payment.id)
        self.payment_processor.complete_payment(payment.id)

        refund = self.refund_processor.create_refund(payment.id)
        self.refund_processor.process_refund(refund)

        assert refund.status == PaymentStatus.PROCESSING

    def test_complete_refund(self):
        """Test completing refund."""
        payment = self.payment_processor.create_payment(
            from_account="ACC001",
            to_account="ACC002",
            amount=Decimal("100.00"),
            currency=Currency.USD,
            method=PaymentMethod.ACH,
        )

        self.payment_processor.process_payment(payment.id)
        self.payment_processor.complete_payment(payment.id)

        refund = self.refund_processor.create_refund(payment.id)
        self.refund_processor.process_refund(refund)
        self.refund_processor.complete_refund(refund.id)

        assert refund.status == PaymentStatus.COMPLETED
        assert refund.processed_at is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
