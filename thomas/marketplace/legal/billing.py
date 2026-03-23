"""Billing and time tracking module for legal practice operations."""

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from thomas.marketplace.legal._exceptions import InsufficientFundsError
from thomas.marketplace.legal._types import (
    BillingStatus,
    Invoice,
    TimeEntry,
    Trust,
)

logger = logging.getLogger(__name__)


class TimeTracker:
    """Manages time entries in 6-minute increments for billing."""

    def __init__(self) -> None:
        """Initialize the time tracker."""
        self.time_entries: dict[str, TimeEntry] = {}
        self.attorney_rates: dict[str, Decimal] = {}

    def add_time_entry(
        self,
        attorney_id: str,
        case_id: str,
        date_worked: date,
        hours: Decimal,
        description: str,
        activity_type: str = "general",
        billable: bool = True,
    ) -> TimeEntry:
        """Add a time entry (hours in 0.1 hour/6-minute increments).

        Hours must be in increments of 0.1 (6 minutes).
        """
        # Validate 6-minute increment
        remainder = (hours * 10) % 1
        if remainder != 0:
            raise ValueError(f"Hours must be in 6-minute increments. Got {hours}")

        entry_id = str(uuid4())
        entry = TimeEntry(
            entry_id=entry_id,
            attorney_id=attorney_id,
            case_id=case_id,
            date=date_worked,
            hours=hours,
            description=description,
            activity_type=activity_type,
            billable=billable,
        )

        if not entry.validate_increment():
            raise ValueError("Invalid time increment")

        self.time_entries[entry_id] = entry
        logger.info(f"Added {hours} hours for {attorney_id} on case {case_id}")
        return entry

    def set_attorney_rate(self, attorney_id: str, rate: Decimal) -> None:
        """Set hourly billing rate for an attorney."""
        self.attorney_rates[attorney_id] = rate
        logger.info(f"Set rate for {attorney_id} to ${rate}/hour")

    def get_attorney_rate(self, attorney_id: str) -> Decimal:
        """Get hourly billing rate for an attorney."""
        return self.attorney_rates.get(attorney_id, Decimal("0.00"))

    def get_time_entries_by_case(
        self,
        case_id: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[TimeEntry]:
        """Get time entries for a case in a date range."""
        entries = [e for e in self.time_entries.values() if e.case_id == case_id]

        if start_date:
            entries = [e for e in entries if e.date >= start_date]
        if end_date:
            entries = [e for e in entries if e.date <= end_date]

        return sorted(entries, key=lambda e: e.date)

    def get_time_entries_by_attorney(
        self,
        attorney_id: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[TimeEntry]:
        """Get time entries for an attorney in a date range."""
        entries = [e for e in self.time_entries.values() if e.attorney_id == attorney_id]

        if start_date:
            entries = [e for e in entries if e.date >= start_date]
        if end_date:
            entries = [e for e in entries if e.date <= end_date]

        return sorted(entries, key=lambda e: e.date)

    def calculate_billable_hours(
        self,
        case_id: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> Decimal:
        """Calculate total billable hours for a case."""
        entries = self.get_time_entries_by_case(case_id, start_date, end_date)
        return sum((e.hours for e in entries if e.billable), Decimal("0.00"))

    def calculate_attorney_billable_hours(
        self,
        attorney_id: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> Decimal:
        """Calculate billable hours for an attorney."""
        entries = self.get_time_entries_by_attorney(attorney_id, start_date, end_date)
        return sum((e.hours for e in entries if e.billable), Decimal("0.00"))


class BillingManager:
    """Manages invoicing, trust accounts, and billing compliance."""

    # Standard OCG (Outside Counsel Guidelines) limits
    OCG_LIMITS = {
        "partner": Decimal("350.00"),
        "counsel": Decimal("300.00"),
        "associate": Decimal("250.00"),
        "junior_associate": Decimal("150.00"),
    }

    def __init__(self, time_tracker: TimeTracker) -> None:
        """Initialize the billing manager."""
        self.invoices: dict[str, Invoice] = {}
        self.trusts: dict[str, Trust] = {}
        self.time_tracker = time_tracker
        self.write_offs: list[dict] = []

    def create_invoice(
        self,
        client_id: str,
        case_id: str | None = None,
        invoice_date: date | None = None,
        due_date: date | None = None,
    ) -> Invoice:
        """Create a new invoice."""
        invoice_id = str(uuid4())
        today = date.today()
        invoice = Invoice(
            invoice_id=invoice_id,
            client_id=client_id,
            case_id=case_id,
            status=BillingStatus.DRAFT,
            invoice_date=invoice_date or today,
            due_date=due_date or today + timedelta(days=30),
            amount_due=Decimal("0.00"),
        )

        self.invoices[invoice_id] = invoice
        logger.info(f"Created invoice {invoice_id} for client {client_id}")
        return invoice

    def add_line_item(
        self,
        invoice_id: str,
        description: str,
        amount: Decimal,
        attorney_id: str | None = None,
        hours: Decimal | None = None,
        rate: Decimal | None = None,
    ) -> Invoice:
        """Add a line item to an invoice."""
        if invoice_id not in self.invoices:
            raise ValueError(f"Invoice {invoice_id} not found")

        invoice = self.invoices[invoice_id]
        if invoice.status != BillingStatus.DRAFT:
            raise ValueError(f"Cannot modify {invoice.status.value} invoice")

        line_item = {
            "description": description,
            "amount": amount,
            "attorney_id": attorney_id,
            "hours": hours,
            "rate": rate,
            "created_at": datetime.now(),
        }

        invoice.line_items.append(line_item)
        invoice.amount_due += amount

        logger.info(f"Added line item to invoice {invoice_id}: ${amount}")
        return invoice

    def populate_invoice_from_case(
        self,
        invoice_id: str,
        case_id: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> Invoice:
        """Populate invoice with time entries from a case (LEDES format)."""
        if invoice_id not in self.invoices:
            raise ValueError(f"Invoice {invoice_id} not found")

        invoice = self.invoices[invoice_id]
        if invoice.status != BillingStatus.DRAFT:
            raise ValueError(f"Cannot modify {invoice.status.value} invoice")

        # Get all time entries for case
        entries = self.time_tracker.get_time_entries_by_case(case_id, start_date, end_date)

        # Group by attorney
        by_attorney: dict[str, list] = {}
        for entry in entries:
            if entry.attorney_id not in by_attorney:
                by_attorney[entry.attorney_id] = []
            by_attorney[entry.attorney_id].append(entry)

        # Add line items for each attorney
        total = Decimal("0.00")
        for attorney_id, atty_entries in by_attorney.items():
            total_hours = sum((e.hours for e in atty_entries if e.billable), Decimal("0.00"))
            if total_hours > 0:
                rate = self.time_tracker.get_attorney_rate(attorney_id)
                amount = total_hours * rate

                self.add_line_item(
                    invoice_id,
                    f"Legal services - {attorney_id} ({total_hours} hours @ ${rate}/hr)",
                    amount,
                    attorney_id=attorney_id,
                    hours=total_hours,
                    rate=rate,
                )
                total += amount

        invoice.amount_due = total
        logger.info(f"Populated invoice {invoice_id} from case {case_id}")
        return invoice

    def finalize_invoice(
        self,
        invoice_id: str,
        ocg_check: bool = True,
    ) -> Invoice:
        """Finalize invoice for sending (OCG compliance check)."""
        if invoice_id not in self.invoices:
            raise ValueError(f"Invoice {invoice_id} not found")

        invoice = self.invoices[invoice_id]

        # OCG compliance check
        if ocg_check:
            self._check_ocg_compliance(invoice)

        invoice.status = BillingStatus.SENT
        invoice.modified_at = datetime.now()

        logger.info(f"Finalized invoice {invoice_id}")
        return invoice

    def record_payment(
        self,
        invoice_id: str,
        amount_paid: Decimal,
    ) -> Invoice:
        """Record a payment against an invoice."""
        if invoice_id not in self.invoices:
            raise ValueError(f"Invoice {invoice_id} not found")

        invoice = self.invoices[invoice_id]
        invoice.amount_paid += amount_paid

        if invoice.amount_paid >= invoice.amount_due:
            invoice.status = BillingStatus.PAID
        else:
            invoice.status = BillingStatus.SENT

        logger.info(f"Recorded ${amount_paid} payment on invoice {invoice_id}")
        return invoice

    def write_off_invoice(
        self,
        invoice_id: str,
        reason: str,
        write_off_amount: Decimal,
    ) -> Invoice:
        """Write off an invoice or portion of an invoice."""
        if invoice_id not in self.invoices:
            raise ValueError(f"Invoice {invoice_id} not found")

        invoice = self.invoices[invoice_id]
        invoice.amount_due -= write_off_amount
        invoice.status = BillingStatus.WRITTEN_OFF

        self.write_offs.append(
            {
                "invoice_id": invoice_id,
                "reason": reason,
                "amount": write_off_amount,
                "date": datetime.now(),
            }
        )

        logger.info(f"Wrote off ${write_off_amount} on invoice {invoice_id}: {reason}")
        return invoice

    def create_trust_account(
        self,
        firm_id: str,
        account_number: str,
        bank_name: str,
    ) -> Trust:
        """Create a trust account for client funds (IOLTA)."""
        trust_id = str(uuid4())
        trust = Trust(
            trust_id=trust_id,
            firm_id=firm_id,
            account_number=account_number,
            bank_name=bank_name,
        )

        self.trusts[trust_id] = trust
        logger.info(f"Created trust account {trust_id} with {bank_name}")
        return trust

    def deposit_to_trust(
        self,
        trust_id: str,
        client_id: str,
        amount: Decimal,
        description: str,
    ) -> Trust:
        """Deposit client funds to trust account."""
        if trust_id not in self.trusts:
            raise ValueError(f"Trust account {trust_id} not found")

        trust = self.trusts[trust_id]
        trust.balance += amount
        trust.transactions.append(
            {
                "type": "deposit",
                "client_id": client_id,
                "amount": amount,
                "description": description,
                "date": datetime.now(),
            }
        )

        logger.info(f"Deposited ${amount} to trust {trust_id}")
        return trust

    def withdraw_from_trust(
        self,
        trust_id: str,
        client_id: str,
        amount: Decimal,
        description: str,
    ) -> Trust:
        """Withdraw from trust account (fees, disbursements)."""
        if trust_id not in self.trusts:
            raise ValueError(f"Trust account {trust_id} not found")

        trust = self.trusts[trust_id]
        if trust.balance < amount:
            raise InsufficientFundsError(f"Trust balance ${trust.balance} < withdrawal ${amount}")

        trust.balance -= amount
        trust.transactions.append(
            {
                "type": "withdrawal",
                "client_id": client_id,
                "amount": amount,
                "description": description,
                "date": datetime.now(),
            }
        )

        logger.info(f"Withdrew ${amount} from trust {trust_id}")
        return trust

    def calculate_realization_rate(
        self,
        invoice_id: str,
    ) -> Decimal:
        """Calculate realization rate: (collected) / (billed)."""
        if invoice_id not in self.invoices:
            raise ValueError(f"Invoice {invoice_id} not found")

        invoice = self.invoices[invoice_id]
        if invoice.amount_due == 0:
            return Decimal("1.00")

        return invoice.amount_paid / invoice.amount_due

    def calculate_collection_rate(
        self,
        client_id: str,
    ) -> Decimal:
        """Calculate collection rate for a client."""
        client_invoices = [i for i in self.invoices.values() if i.client_id == client_id]

        if not client_invoices:
            return Decimal("1.00")

        total_billed = sum(i.amount_due for i in client_invoices)
        total_collected = sum(i.amount_paid for i in client_invoices)

        if total_billed == 0:
            return Decimal("1.00")

        return total_collected / total_billed

    def _check_ocg_compliance(self, invoice: Invoice) -> None:
        """Check invoice rates against OCG guidelines."""
        for line in invoice.line_items:
            if line.get("rate"):
                rate = line["rate"]
                # Log warnings for rates exceeding OCG limits
                for level, limit in self.OCG_LIMITS.items():
                    if rate > limit:
                        logger.warning(
                            f"Invoice {invoice.invoice_id} rate ${rate} " f"exceeds OCG limit ${limit} for {level}"
                        )
