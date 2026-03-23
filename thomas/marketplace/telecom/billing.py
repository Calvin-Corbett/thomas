"""
Billing engine for telecommunications networks.

Handles CDR processing, real-time charging, tariff plan management, invoice
generation, revenue assurance, and interconnect settlement.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

from thomas.marketplace.telecom._types import CallRecord, Subscriber


class ChargeType(Enum):
    """Types of charges."""

    VOICE = "voice"
    DATA = "data"
    SMS = "sms"
    ROAMING = "roaming"
    INTERCONNECT = "interconnect"


class InvoiceStatus(Enum):
    """Invoice status."""

    DRAFT = "draft"
    ISSUED = "issued"
    PAID = "paid"
    OVERDUE = "overdue"


@dataclass
class CDRMediation:
    """CDR mediation and processing."""

    cdrs: list[CallRecord] = field(default_factory=list)
    processed_cdr_ids: set = field(default_factory=set)
    discarded_cdrs: list[CallRecord] = field(default_factory=list)

    def add_cdr(self, cdr: CallRecord) -> None:
        """
        Add CDR for processing.

        Args:
            cdr: CallRecord to add
        """
        self.cdrs.append(cdr)

    def detect_duplicate_cdrs(self) -> list[tuple[CallRecord, CallRecord]]:
        """
        Detect duplicate CDRs.

        Returns:
            List of duplicate pairs
        """
        duplicates = []
        for i, cdr1 in enumerate(self.cdrs):
            for cdr2 in self.cdrs[i + 1 :]:
                if (
                    cdr1.msisdn == cdr2.msisdn
                    and cdr1.destination == cdr2.destination
                    and abs((cdr1.start_time - cdr2.start_time).total_seconds()) < 5
                    and abs(cdr1.duration_seconds - cdr2.duration_seconds) < 1
                ):
                    duplicates.append((cdr1, cdr2))

        return duplicates

    def validate_cdr(self, cdr: CallRecord) -> bool:
        """
        Validate CDR integrity.

        Args:
            cdr: CallRecord to validate

        Returns:
            True if valid
        """
        if not cdr.msisdn or len(cdr.msisdn) < 7:
            return False

        if cdr.end_time and cdr.start_time > cdr.end_time:
            return False

        if cdr.duration_seconds < 0:
            return False

        if cdr.call_type not in ["voice", "sms", "data"]:
            return False

        return True

    def mediate_cdrs(self) -> list[CallRecord]:
        """
        Process and validate all CDRs.

        Returns:
            List of valid CDRs
        """
        valid_cdrs = []

        duplicates = self.detect_duplicate_cdrs()
        duplicate_ids = set()
        for dup1, dup2 in duplicates:
            duplicate_ids.add(dup1.id)
            self.discarded_cdrs.append(dup1)

        for cdr in self.cdrs:
            if cdr.id in duplicate_ids:
                continue

            if self.validate_cdr(cdr):
                valid_cdrs.append(cdr)
                self.processed_cdr_ids.add(cdr.id)
            else:
                self.discarded_cdrs.append(cdr)

        return valid_cdrs


@dataclass
class TariffPlan:
    """Tariff plan definition."""

    name: str
    voice_rate_per_minute: dict[str, float] = field(default_factory=dict)
    data_rate_per_gb: float = 0.0
    sms_rate_per_sms: float = 0.0
    time_of_day_multiplier: dict[str, float] = field(default_factory=dict)
    zone_rates: dict[str, float] = field(default_factory=dict)
    volume_tiers: list[tuple[float, float]] = field(default_factory=list)
    monthly_base_fee: float = 0.0

    def __post_init__(self) -> None:
        if not self.voice_rate_per_minute:
            self.voice_rate_per_minute = {"local": 0.05, "national": 0.10, "international": 0.50}

        if not self.time_of_day_multiplier:
            self.time_of_day_multiplier = {
                "peak": 1.5,
                "off_peak": 0.5,
                "night": 0.2,
            }

        if not self.zone_rates:
            self.zone_rates = {"zone1": 0.5, "zone2": 1.0, "zone3": 1.5}

        if not self.volume_tiers:
            self.volume_tiers = [(10, 0.10), (100, 0.08), (1000, 0.05)]

    def calculate_voice_charge(
        self,
        duration_minutes: float,
        call_type: str = "local",
        time_of_day: str = "peak",
    ) -> float:
        """
        Calculate voice charge.

        Args:
            duration_minutes: Duration in minutes
            call_type: Type of call (local, national, international)
            time_of_day: Time of day (peak, off_peak, night)

        Returns:
            Charge in currency units
        """
        base_rate = self.voice_rate_per_minute.get(call_type, 0.10)
        time_multiplier = self.time_of_day_multiplier.get(time_of_day, 1.0)
        return duration_minutes * base_rate * time_multiplier

    def calculate_data_charge(self, data_gb: float) -> float:
        """
        Calculate data charge with volume tiers.

        Args:
            data_gb: Data usage in GB

        Returns:
            Charge in currency units
        """
        charge = 0.0
        remaining_gb = data_gb

        for tier_gb, tier_rate in sorted(self.volume_tiers):
            if remaining_gb <= 0:
                break

            tier_usage = min(remaining_gb, tier_gb)
            charge += tier_usage * tier_rate
            remaining_gb -= tier_usage

        return charge

    def calculate_sms_charge(self, sms_count: int) -> float:
        """
        Calculate SMS charge.

        Args:
            sms_count: Number of SMS messages

        Returns:
            Charge in currency units
        """
        return sms_count * self.sms_rate_per_sms

    def calculate_monthly_charge(
        self,
        voice_minutes: float,
        data_gb: float,
        sms_count: int,
    ) -> float:
        """
        Calculate total monthly charge.

        Args:
            voice_minutes: Voice usage in minutes
            data_gb: Data usage in GB
            sms_count: SMS count

        Returns:
            Total charge in currency units
        """
        voice_charge = self.calculate_voice_charge(voice_minutes)
        data_charge = self.calculate_data_charge(data_gb)
        sms_charge = self.calculate_sms_charge(sms_count)

        return self.monthly_base_fee + voice_charge + data_charge + sms_charge


@dataclass
class BillingEngine:
    """Real-time charging and billing engine."""

    subscribers: dict[str, Subscriber] = field(default_factory=dict)
    tariffs: dict[str, TariffPlan] = field(default_factory=dict)
    subscriber_tariffs: dict[str, str] = field(default_factory=dict)
    pending_charges: dict[str, float] = field(default_factory=dict)
    balance_updates: list[tuple[str, float, str]] = field(default_factory=list)

    def add_tariff(self, tariff: TariffPlan) -> None:
        """
        Add tariff plan.

        Args:
            tariff: TariffPlan to add
        """
        self.tariffs[tariff.name] = tariff

    def assign_tariff(self, msisdn: str, tariff_name: str) -> bool:
        """
        Assign tariff to subscriber.

        Args:
            msisdn: Phone number
            tariff_name: Tariff name

        Returns:
            True if successful
        """
        if tariff_name not in self.tariffs:
            return False

        self.subscriber_tariffs[msisdn] = tariff_name
        return True

    def process_cdr(self, cdr: CallRecord) -> float:
        """
        Process CDR and calculate charge.

        Args:
            cdr: CallRecord to process

        Returns:
            Charge amount
        """
        tariff_name = self.subscriber_tariffs.get(cdr.msisdn)
        if not tariff_name or tariff_name not in self.tariffs:
            tariff_name = list(self.tariffs.keys())[0] if self.tariffs else None
            if not tariff_name:
                return 0.0

        tariff = self.tariffs[tariff_name]
        charge = 0.0

        if cdr.call_type == "voice":
            duration_minutes = cdr.duration_seconds / 60.0
            call_type = "international" if cdr.roaming else "national"
            time_of_day = "peak"
            charge = tariff.calculate_voice_charge(duration_minutes, call_type, time_of_day)

        elif cdr.call_type == "data":
            charge = tariff.calculate_data_charge(cdr.data_volume_mb / 1024.0)

        elif cdr.call_type == "sms":
            charge = tariff.calculate_sms_charge(1)

        if cdr.roaming:
            charge *= 1.5

        cdr.cost_currency = charge
        return charge

    def charge_subscriber(self, msisdn: str, amount: float, reason: str) -> bool:
        """
        Charge subscriber account.

        Args:
            msisdn: Phone number
            amount: Amount to charge
            reason: Reason for charge

        Returns:
            True if successful
        """
        subscriber = self.subscribers.get(msisdn)
        if not subscriber:
            return False

        if subscriber.plan_type == "prepaid":
            if subscriber.balance_credits < amount:
                return False
            subscriber.balance_credits -= amount
        else:
            subscriber.balance_credits -= amount

        self.balance_updates.append((msisdn, -amount, reason))
        self.pending_charges[msisdn] = self.pending_charges.get(msisdn, 0.0) + amount

        return True

    def check_credit_limit(self, msisdn: str) -> bool:
        """
        Check if subscriber has credit limit exceeded.

        Args:
            msisdn: Phone number

        Returns:
            True if balance is positive or acceptable
        """
        subscriber = self.subscribers.get(msisdn)
        if not subscriber:
            return False

        if subscriber.plan_type == "prepaid":
            return subscriber.balance_credits > 0.0
        else:
            return subscriber.balance_credits > -100.0


@dataclass
class InvoiceGenerator:
    """Generate invoices for subscribers."""

    billing_engine: BillingEngine = field(default_factory=BillingEngine)
    invoices: dict[str, dict] = field(default_factory=dict)

    def generate_invoice(
        self,
        msisdn: str,
        period_start: datetime,
        period_end: datetime,
    ) -> dict | None:
        """
        Generate invoice for period.

        Args:
            msisdn: Phone number
            period_start: Period start date
            period_end: Period end date

        Returns:
            Invoice dict or None
        """
        subscriber = self.billing_engine.subscribers.get(msisdn)
        if not subscriber:
            return None

        tariff_name = self.billing_engine.subscriber_tariffs.get(msisdn)
        if not tariff_name:
            return None

        tariff = self.billing_engine.tariffs[tariff_name]

        invoice = {
            "invoice_id": f"INV-{msisdn}-{datetime.now().strftime('%Y%m%d')}",
            "msisdn": msisdn,
            "subscriber_name": subscriber.name,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "issued_date": datetime.now().isoformat(),
            "due_date": (datetime.now() + timedelta(days=30)).isoformat(),
            "tariff_name": tariff_name,
            "status": "issued",
            "line_items": [
                {
                    "description": "Base Fee",
                    "amount": tariff.monthly_base_fee,
                    "quantity": 1,
                }
            ],
            "subtotal": tariff.monthly_base_fee,
            "tax_percent": 10.0,
            "tax_amount": 0.0,
            "total": 0.0,
        }

        tax_amount = invoice["subtotal"] * (invoice["tax_percent"] / 100.0)
        invoice["tax_amount"] = tax_amount
        invoice["total"] = invoice["subtotal"] + tax_amount

        invoice_id = invoice["invoice_id"]
        self.invoices[invoice_id] = invoice

        return invoice

    def mark_invoice_paid(self, invoice_id: str) -> bool:
        """
        Mark invoice as paid.

        Args:
            invoice_id: Invoice ID

        Returns:
            True if successful
        """
        if invoice_id not in self.invoices:
            return False

        self.invoices[invoice_id]["status"] = "paid"
        return True

    def get_invoices_for_subscriber(self, msisdn: str) -> list[dict]:
        """
        Get all invoices for subscriber.

        Args:
            msisdn: Phone number

        Returns:
            List of invoices
        """
        return [inv for inv in self.invoices.values() if inv["msisdn"] == msisdn]


@dataclass
class RevenueAssurance:
    """Revenue assurance and fraud detection."""

    processed_cdrs: dict[str, CallRecord] = field(default_factory=dict)
    gaps: list[tuple[datetime, datetime]] = field(default_factory=list)

    def detect_gaps(
        self, start_time: datetime, end_time: datetime, expected_count: int
    ) -> list[tuple[datetime, datetime]]:
        """
        Detect gaps in CDR records.

        Args:
            start_time: Period start
            end_time: Period end
            expected_count: Expected number of CDRs

        Returns:
            List of gap periods
        """
        actual_count = len(self.processed_cdrs)
        if actual_count < expected_count:
            gap_duration = (end_time - start_time) / (expected_count - actual_count)
            gaps = []

            current_time = start_time
            for i in range(expected_count - actual_count):
                gap_end = current_time + gap_duration
                gaps.append((current_time, gap_end))
                current_time = gap_end

            self.gaps.extend(gaps)
            return gaps

        return []

    def detect_duplicate_cdrs(self, cdrs: list[CallRecord]) -> list[tuple[str, str]]:
        """
        Detect duplicate CDRs.

        Args:
            cdrs: List of CDRs

        Returns:
            List of duplicate CDR pairs
        """
        duplicates = []
        seen = {}

        for cdr in cdrs:
            key = (cdr.msisdn, cdr.destination, cdr.start_time, cdr.duration_seconds)
            if key in seen:
                duplicates.append((seen[key].id, cdr.id))
            else:
                seen[key] = cdr

        return duplicates

    def calculate_revenue_from_cdrs(self, cdrs: list[CallRecord]) -> float:
        """
        Calculate total revenue from CDRs.

        Args:
            cdrs: List of CDRs

        Returns:
            Total revenue
        """
        return sum(cdr.cost_currency for cdr in cdrs)


@dataclass
class InterconnectSettlement:
    """Manage interconnect billing and settlement."""

    partner_operators: dict[str, str] = field(default_factory=dict)
    interconnect_rates: dict[str, float] = field(default_factory=dict)
    settlement_accounts: dict[str, float] = field(default_factory=dict)

    def add_partner(self, operator_id: str, operator_name: str) -> None:
        """
        Add partner operator.

        Args:
            operator_id: Operator ID
            operator_name: Operator name
        """
        self.partner_operators[operator_id] = operator_name
        self.settlement_accounts[operator_id] = 0.0

    def set_interconnect_rate(self, operator_id: str, rate_per_minute: float) -> None:
        """
        Set interconnect rate.

        Args:
            operator_id: Operator ID
            rate_per_minute: Rate per minute in currency
        """
        self.interconnect_rates[operator_id] = rate_per_minute

    def calculate_interconnect_charge(self, operator_id: str, duration_minutes: float) -> float:
        """
        Calculate interconnect charge.

        Args:
            operator_id: Operator ID
            duration_minutes: Call duration in minutes

        Returns:
            Charge amount
        """
        rate = self.interconnect_rates.get(operator_id, 0.0)
        return duration_minutes * rate

    def record_settlement(self, operator_id: str, amount: float) -> None:
        """
        Record settlement with operator.

        Args:
            operator_id: Operator ID
            amount: Amount (positive = credit, negative = debit)
        """
        if operator_id in self.settlement_accounts:
            self.settlement_accounts[operator_id] += amount


__all__ = [
    "BillingEngine",
    "TariffPlan",
    "InvoiceGenerator",
    "RevenueAssurance",
    "InterconnectSettlement",
    "CDRMediation",
    "ChargeType",
    "InvoiceStatus",
]
