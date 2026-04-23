"""
Tests for billing engine module.
"""

from datetime import datetime, timedelta

import pytest

from thomas.marketplace.telecom._types import CallRecord, Subscriber
from thomas.marketplace.telecom.billing import (
    BillingEngine,
    CDRMediation,
    InterconnectSettlement,
    InvoiceGenerator,
    RevenueAssurance,
    TariffPlan,
)


class TestTariffPlan:
    """Test tariff plan."""

    def test_create_tariff_plan(self) -> None:
        """Test creating tariff plan."""
        plan = TariffPlan(
            name="Standard",
            voice_rate_per_minute={"local": 0.05, "national": 0.10},
            data_rate_per_gb=0.50,
            sms_rate_per_sms=0.02,
            monthly_base_fee=20.0,
        )
        assert plan.name == "Standard"
        assert plan.monthly_base_fee == 20.0

    def test_voice_charge_calculation(self) -> None:
        """Test voice charge calculation."""
        plan = TariffPlan(name="Test")
        charge = plan.calculate_voice_charge(
            duration_minutes=10.0,
            call_type="local",
            time_of_day="peak",
        )
        assert charge > 0

    def test_data_charge_with_tiers(self) -> None:
        """Test data charge with volume tiers."""
        plan = TariffPlan(
            name="Test",
            volume_tiers=[(10, 0.10), (100, 0.08), (1000, 0.05)],
        )
        charge = plan.calculate_data_charge(data_gb=15.0)
        assert charge > 0

    def test_sms_charge(self) -> None:
        """Test SMS charge."""
        plan = TariffPlan(name="Test", sms_rate_per_sms=0.05)
        charge = plan.calculate_sms_charge(sms_count=10)
        assert charge == 0.5

    def test_monthly_charge_calculation(self) -> None:
        """Test total monthly charge."""
        plan = TariffPlan(
            name="Test",
            monthly_base_fee=20.0,
            voice_rate_per_minute={"local": 0.05},
            data_rate_per_gb=0.50,
            sms_rate_per_sms=0.05,
        )
        charge = plan.calculate_monthly_charge(
            voice_minutes=100.0,
            data_gb=2.0,
            sms_count=50,
        )
        assert charge >= 20.0


class TestBillingEngine:
    """Test billing engine."""

    def test_add_tariff(self) -> None:
        """Test adding tariff."""
        engine = BillingEngine()
        plan = TariffPlan(name="Standard")
        engine.add_tariff(plan)
        assert "Standard" in engine.tariffs

    def test_assign_tariff(self) -> None:
        """Test assigning tariff to subscriber."""
        engine = BillingEngine()
        plan = TariffPlan(name="Standard")
        engine.add_tariff(plan)

        subscriber = Subscriber(
            msisdn="1234567890",
            imsi="310410123456789",
            imei="990000862471854",
        )
        engine.subscribers["1234567890"] = subscriber

        success = engine.assign_tariff("1234567890", "Standard")
        assert success is True

    def test_process_cdr_voice(self) -> None:
        """Test CDR processing for voice call."""
        engine = BillingEngine()
        plan = TariffPlan(name="Standard")
        engine.add_tariff(plan)

        cdr = CallRecord(
            msisdn="1234567890",
            destination="9876543210",
            duration_seconds=600,
            call_type="voice",
            roaming=False,
        )

        charge = engine.process_cdr(cdr)
        assert charge >= 0

    def test_process_cdr_roaming(self) -> None:
        """Test CDR processing with roaming."""
        engine = BillingEngine()
        plan = TariffPlan(name="Standard")
        engine.add_tariff(plan)

        cdr1 = CallRecord(
            msisdn="1234567890",
            destination="9876543210",
            duration_seconds=600,
            call_type="voice",
            roaming=False,
        )

        cdr2 = CallRecord(
            msisdn="1234567890",
            destination="9876543210",
            duration_seconds=600,
            call_type="voice",
            roaming=True,
        )

        charge_domestic = engine.process_cdr(cdr1)
        charge_roaming = engine.process_cdr(cdr2)

        assert charge_roaming > charge_domestic

    def test_charge_subscriber_postpaid(self) -> None:
        """Test charging postpaid subscriber."""
        engine = BillingEngine()
        subscriber = Subscriber(
            msisdn="1234567890",
            imsi="310410123456789",
            imei="990000862471854",
            plan_type="postpaid",
            balance_credits=0.0,
        )
        engine.subscribers["1234567890"] = subscriber

        success = engine.charge_subscriber("1234567890", 10.0, "Voice call")
        assert success is True
        assert subscriber.balance_credits == -10.0

    def test_charge_subscriber_prepaid(self) -> None:
        """Test charging prepaid subscriber."""
        engine = BillingEngine()
        subscriber = Subscriber(
            msisdn="1234567890",
            imsi="310410123456789",
            imei="990000862471854",
            plan_type="prepaid",
            balance_credits=100.0,
        )
        engine.subscribers["1234567890"] = subscriber

        success = engine.charge_subscriber("1234567890", 10.0, "Voice call")
        assert success is True
        assert subscriber.balance_credits == 90.0

    def test_charge_prepaid_insufficient_balance(self) -> None:
        """Test charging prepaid with insufficient balance."""
        engine = BillingEngine()
        subscriber = Subscriber(
            msisdn="1234567890",
            imsi="310410123456789",
            imei="990000862471854",
            plan_type="prepaid",
            balance_credits=5.0,
        )
        engine.subscribers["1234567890"] = subscriber

        success = engine.charge_subscriber("1234567890", 10.0, "Voice call")
        assert success is False

    def test_credit_limit_check(self) -> None:
        """Test credit limit checking."""
        engine = BillingEngine()

        prepaid_subscriber = Subscriber(
            msisdn="1111111111",
            imsi="310410111111111",
            imei="990000111111111",
            plan_type="prepaid",
            balance_credits=10.0,
        )
        engine.subscribers["1111111111"] = prepaid_subscriber

        postpaid_subscriber = Subscriber(
            msisdn="2222222222",
            imsi="310410222222222",
            imei="990000222222222",
            plan_type="postpaid",
            balance_credits=-200.0,
        )
        engine.subscribers["2222222222"] = postpaid_subscriber

        assert engine.check_credit_limit("1111111111") is True
        assert engine.check_credit_limit("2222222222") is False


class TestInvoiceGenerator:
    """Test invoice generation."""

    def test_generate_invoice(self) -> None:
        """Test invoice generation."""
        engine = BillingEngine()
        plan = TariffPlan(name="Standard", monthly_base_fee=20.0)
        engine.add_tariff(plan)

        subscriber = Subscriber(
            msisdn="1234567890",
            imsi="310410123456789",
            imei="990000862471854",
            name="John Doe",
        )
        engine.subscribers["1234567890"] = subscriber
        engine.assign_tariff("1234567890", "Standard")

        generator = InvoiceGenerator(billing_engine=engine)
        period_start = datetime.now() - timedelta(days=30)
        period_end = datetime.now()

        invoice = generator.generate_invoice("1234567890", period_start, period_end)

        assert invoice is not None
        assert invoice["msisdn"] == "1234567890"
        assert invoice["total"] >= 20.0

    def test_mark_invoice_paid(self) -> None:
        """Test marking invoice as paid."""
        engine = BillingEngine()
        plan = TariffPlan(name="Standard")
        engine.add_tariff(plan)

        subscriber = Subscriber(
            msisdn="1234567890",
            imsi="310410123456789",
            imei="990000862471854",
        )
        engine.subscribers["1234567890"] = subscriber
        engine.assign_tariff("1234567890", "Standard")

        generator = InvoiceGenerator(billing_engine=engine)
        invoice = generator.generate_invoice(
            "1234567890",
            datetime.now() - timedelta(days=30),
            datetime.now(),
        )

        assert invoice is not None
        success = generator.mark_invoice_paid(invoice["invoice_id"])
        assert success is True


class TestCDRMediation:
    """Test CDR mediation."""

    def test_add_cdr(self) -> None:
        """Test adding CDR."""
        mediation = CDRMediation()
        cdr = CallRecord(
            msisdn="1234567890",
            destination="9876543210",
            duration_seconds=120,
        )
        mediation.add_cdr(cdr)
        assert cdr in mediation.cdrs

    def test_validate_cdr(self) -> None:
        """Test CDR validation."""
        mediation = CDRMediation()
        valid_cdr = CallRecord(
            msisdn="1234567890",
            destination="9876543210",
            duration_seconds=120,
            call_type="voice",
        )
        assert mediation.validate_cdr(valid_cdr) is True

        invalid_cdr = CallRecord(
            msisdn="123",
            destination="9876543210",
            duration_seconds=120,
            call_type="voice",
        )
        assert mediation.validate_cdr(invalid_cdr) is False

    def test_detect_duplicates(self) -> None:
        """Test duplicate detection."""
        mediation = CDRMediation()
        cdr1 = CallRecord(
            msisdn="1234567890",
            destination="9876543210",
            start_time=datetime.now(),
            duration_seconds=120,
        )
        cdr2 = CallRecord(
            msisdn="1234567890",
            destination="9876543210",
            start_time=datetime.now(),
            duration_seconds=120,
        )
        mediation.add_cdr(cdr1)
        mediation.add_cdr(cdr2)

        duplicates = mediation.detect_duplicate_cdrs()
        assert len(duplicates) > 0

    def test_mediate_cdrs(self) -> None:
        """Test CDR mediation."""
        mediation = CDRMediation()
        cdr = CallRecord(
            msisdn="1234567890",
            destination="9876543210",
            duration_seconds=120,
            call_type="voice",
        )
        mediation.add_cdr(cdr)

        valid_cdrs = mediation.mediate_cdrs()
        assert len(valid_cdrs) >= 1


class TestRevenueAssurance:
    """Test revenue assurance."""

    def test_calculate_revenue(self) -> None:
        """Test revenue calculation."""
        ra = RevenueAssurance()

        cdr1 = CallRecord(
            msisdn="1234567890",
            destination="9876543210",
            duration_seconds=600,
            cost_currency=5.0,
        )
        cdr2 = CallRecord(
            msisdn="1111111111",
            destination="9876543210",
            duration_seconds=300,
            cost_currency=2.5,
        )

        revenue = ra.calculate_revenue_from_cdrs([cdr1, cdr2])
        assert revenue == 7.5


class TestInterconnectSettlement:
    """Test interconnect settlement."""

    def test_add_partner(self) -> None:
        """Test adding partner operator."""
        settlement = InterconnectSettlement()
        settlement.add_partner("OP2", "Operator 2")
        assert "OP2" in settlement.partner_operators

    def test_set_interconnect_rate(self) -> None:
        """Test setting interconnect rate."""
        settlement = InterconnectSettlement()
        settlement.add_partner("OP2", "Operator 2")
        settlement.set_interconnect_rate("OP2", 0.10)
        assert settlement.interconnect_rates["OP2"] == 0.10

    def test_calculate_interconnect_charge(self) -> None:
        """Test interconnect charge calculation."""
        settlement = InterconnectSettlement()
        settlement.add_partner("OP2", "Operator 2")
        settlement.set_interconnect_rate("OP2", 0.10)

        charge = settlement.calculate_interconnect_charge("OP2", 100.0)
        assert charge == 10.0

    def test_record_settlement(self) -> None:
        """Test settlement recording."""
        settlement = InterconnectSettlement()
        settlement.add_partner("OP2", "Operator 2")

        settlement.record_settlement("OP2", 100.0)
        assert settlement.settlement_accounts["OP2"] == 100.0

        settlement.record_settlement("OP2", -50.0)
        assert settlement.settlement_accounts["OP2"] == 50.0


if __name__ == "__main__":
    pytest.main([__file__])
