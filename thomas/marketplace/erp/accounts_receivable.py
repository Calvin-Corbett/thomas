"""
Accounts Receivable management.

Handles customer management, sales invoices, payment application,
credit memos, and revenue recognition.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from thomas.marketplace.erp._exceptions import (
    CustomerError,
    InvoiceError,
)
from thomas.marketplace.erp._types import (
    Customer,
    Invoice,
    InvoiceStatus,
    InvoiceType,
    LineItem,
    SalesOrder,
)


class AccountsReceivable:
    """
    Accounts Receivable management.

    Manages customer relationships, sales invoices, payment processing,
    and customer reporting.
    """

    def __init__(self) -> None:
        """Initialize accounts receivable."""
        self.customers: dict[str, Customer] = {}
        self.invoices: dict[str, Invoice] = {}
        self.sales_orders: dict[str, SalesOrder] = {}
        self.payments: dict[str, Decimal] = {}  # invoice_id -> paid_amount
        self.revenue_recognition: dict[str, dict[str, any]] = {}
        self.dunning_notices: list[dict[str, any]] = []
        self.customer_statements: dict[str, list[tuple[date, Decimal]]] = {}

    def create_customer(
        self,
        customer_id: str,
        name: str,
        contact_name: str = "",
        email: str = "",
        phone: str = "",
        credit_limit: Decimal = Decimal("0.00"),
    ) -> Customer:
        """
        Create a new customer.

        Args:
            customer_id: Unique customer identifier
            name: Customer name
            contact_name: Primary contact name
            email: Contact email
            phone: Contact phone
            credit_limit: Maximum credit available

        Returns:
            Created Customer object

        Raises:
            CustomerError: If customer already exists
        """
        if customer_id in self.customers:
            raise CustomerError(f"Customer {customer_id} already exists")

        customer = Customer(
            id=customer_id,
            name=name,
            contact_name=contact_name,
            email=email,
            phone=phone,
            credit_limit=credit_limit,
        )
        self.customers[customer_id] = customer
        return customer

    def get_customer(self, customer_id: str) -> Customer:
        """
        Retrieve a customer by ID.

        Args:
            customer_id: Customer identifier

        Returns:
            Customer object

        Raises:
            CustomerError: If customer not found
        """
        if customer_id not in self.customers:
            raise CustomerError(f"Customer {customer_id} not found")
        return self.customers[customer_id]

    def create_sales_invoice(
        self,
        invoice_id: str,
        customer_id: str,
        invoice_date: date,
        due_date: date,
        lines: list[LineItem],
        so_id: str | None = None,
    ) -> Invoice:
        """
        Create a sales invoice from sales order or direct invoice.

        Args:
            invoice_id: Unique invoice number
            customer_id: Customer identifier
            invoice_date: Invoice date
            due_date: Payment due date
            lines: Invoice line items
            so_id: Related sales order ID (optional)

        Returns:
            Created Invoice

        Raises:
            CustomerError: If customer not found
            InvoiceError: If invoice is invalid
        """
        if customer_id not in self.customers:
            raise CustomerError(f"Customer {customer_id} not found")

        if invoice_id in self.invoices:
            raise InvoiceError(f"Invoice {invoice_id} already exists")

        total = Decimal("0.00")
        for line in lines:
            total += line.get_amount()

        invoice = Invoice(
            id=invoice_id,
            invoice_type=InvoiceType.SALES_INVOICE,
            invoice_date=invoice_date,
            due_date=due_date,
            customer_id=customer_id,
            lines=lines,
            total=total,
            status=InvoiceStatus.SUBMITTED,
        )
        self.invoices[invoice_id] = invoice
        self.payments[invoice_id] = Decimal("0.00")

        return invoice

    def record_payment(
        self,
        invoice_id: str,
        amount: Decimal,
        payment_date: date,
        reference: str = "",
    ) -> Decimal:
        """
        Record a customer payment against an invoice.

        Args:
            invoice_id: Invoice identifier
            amount: Payment amount
            payment_date: Payment date
            reference: Check/transaction reference

        Returns:
            Remaining balance after payment

        Raises:
            InvoiceError: If invoice not found
        """
        if invoice_id not in self.invoices:
            raise InvoiceError(f"Invoice {invoice_id} not found")

        invoice = self.invoices[invoice_id]
        if invoice.status == InvoiceStatus.CANCELLED:
            raise InvoiceError(f"Cannot pay cancelled invoice {invoice_id}")

        invoice.paid_amount += amount

        if invoice.paid_amount >= invoice.total:
            invoice.status = InvoiceStatus.PAID
            remaining = Decimal("0.00")
        elif invoice.paid_amount > Decimal("0.00"):
            invoice.status = InvoiceStatus.PARTIALLY_PAID
            remaining = invoice.total - invoice.paid_amount
        else:
            remaining = invoice.total

        return remaining

    def apply_payment(
        self,
        customer_id: str,
        payment_amount: Decimal,
        payment_date: date,
        invoice_ids: list[str] | None = None,
    ) -> dict[str, Decimal]:
        """
        Apply customer payment to one or multiple invoices.

        Uses FIFO allocation if multiple invoices specified.

        Args:
            customer_id: Customer identifier
            payment_amount: Total payment amount
            payment_date: Payment date
            invoice_ids: Specific invoices to apply to (None = all outstanding)

        Returns:
            Map of invoice IDs to amounts applied

        Raises:
            CustomerError: If customer not found
        """
        if customer_id not in self.customers:
            raise CustomerError(f"Customer {customer_id} not found")

        allocation: dict[str, Decimal] = {}
        remaining = payment_amount

        if invoice_ids is None:
            invoice_ids = [
                inv.id
                for inv in self.invoices.values()
                if inv.customer_id == customer_id and inv.status not in (InvoiceStatus.PAID, InvoiceStatus.CANCELLED)
            ]
            invoice_ids.sort(key=lambda iid: self.invoices[iid].due_date)

        for invoice_id in invoice_ids:
            if invoice_id not in self.invoices:
                continue

            invoice = self.invoices[invoice_id]
            if invoice.customer_id != customer_id:
                continue

            invoice_due = invoice.total - invoice.paid_amount

            if remaining <= Decimal("0.00"):
                break

            if remaining >= invoice_due:
                applied = invoice_due
                remaining -= applied
            else:
                applied = remaining
                remaining = Decimal("0.00")

            allocation[invoice_id] = applied
            self.record_payment(invoice_id, applied, payment_date)

        return allocation

    def create_credit_memo(
        self,
        memo_id: str,
        customer_id: str,
        memo_date: date,
        original_invoice_id: str,
        amount: Decimal,
        reason: str = "",
    ) -> Invoice:
        """
        Create a credit memo (return/allowance).

        Args:
            memo_id: Unique memo number
            customer_id: Customer identifier
            memo_date: Memo date
            original_invoice_id: Original invoice being credited
            amount: Credit amount
            reason: Reason for credit

        Returns:
            Created credit memo Invoice

        Raises:
            CustomerError: If customer not found
            InvoiceError: If original invoice not found
        """
        if customer_id not in self.customers:
            raise CustomerError(f"Customer {customer_id} not found")

        if original_invoice_id not in self.invoices:
            raise InvoiceError(f"Original invoice {original_invoice_id} not found")

        memo = Invoice(
            id=memo_id,
            invoice_type=InvoiceType.CREDIT_MEMO,
            invoice_date=memo_date,
            due_date=memo_date,
            customer_id=customer_id,
            total=amount,
            paid_amount=Decimal("0.00"),
            status=InvoiceStatus.APPROVED,
            memo=reason,
        )
        self.invoices[memo_id] = memo
        self.payments[memo_id] = Decimal("0.00")

        original = self.invoices[original_invoice_id]
        original.paid_amount += amount

        if original.paid_amount >= original.total:
            original.status = InvoiceStatus.PAID
        elif original.paid_amount > Decimal("0.00"):
            original.status = InvoiceStatus.PARTIALLY_PAID

        return memo

    def aging_report(self, as_of_date: date) -> dict[str, dict[str, Decimal]]:
        """
        Generate accounts receivable aging report.

        Categorizes outstanding invoices by age: current, 30, 60, 90+ days.

        Args:
            as_of_date: Reporting date

        Returns:
            Map of customer IDs to aging buckets
        """
        aging: dict[str, dict[str, Decimal]] = {}

        for invoice_id, invoice in self.invoices.items():
            if invoice.invoice_type != InvoiceType.SALES_INVOICE:
                continue
            if invoice.status in (InvoiceStatus.PAID, InvoiceStatus.CANCELLED):
                continue

            customer_id = invoice.customer_id
            if customer_id not in aging:
                aging[customer_id] = {
                    "current": Decimal("0.00"),
                    "30_days": Decimal("0.00"),
                    "60_days": Decimal("0.00"),
                    "90_plus_days": Decimal("0.00"),
                    "total": Decimal("0.00"),
                }

            outstanding = invoice.total - invoice.paid_amount
            days_overdue = (as_of_date - invoice.due_date).days

            if days_overdue <= 0:
                aging[customer_id]["current"] += outstanding
            elif days_overdue <= 30:
                aging[customer_id]["30_days"] += outstanding
            elif days_overdue <= 60:
                aging[customer_id]["60_days"] += outstanding
            else:
                aging[customer_id]["90_plus_days"] += outstanding

            aging[customer_id]["total"] += outstanding

        return aging

    def generate_dunning_notice(
        self,
        customer_id: str,
        as_of_date: date,
        notice_level: int = 1,
    ) -> dict[str, any] | None:
        """
        Generate dunning notice (overdue payment reminder).

        Args:
            customer_id: Customer identifier
            as_of_date: Current date
            notice_level: Escalation level (1, 2, 3)

        Returns:
            Dunning notice details or None if no overdue balance

        Raises:
            CustomerError: If customer not found
        """
        if customer_id not in self.customers:
            raise CustomerError(f"Customer {customer_id} not found")

        customer = self.customers[customer_id]
        overdue_invoices: list[Invoice] = []
        total_overdue = Decimal("0.00")

        for invoice in self.invoices.values():
            if invoice.customer_id != customer_id:
                continue
            if invoice.invoice_type != InvoiceType.SALES_INVOICE:
                continue
            if invoice.status in (InvoiceStatus.PAID, InvoiceStatus.CANCELLED):
                continue

            if invoice.due_date < as_of_date:
                outstanding = invoice.total - invoice.paid_amount
                overdue_invoices.append(invoice)
                total_overdue += outstanding

        if total_overdue <= Decimal("0.00"):
            return None

        notice = {
            "id": f"DUNNING_{uuid4().hex[:8]}",
            "customer_id": customer_id,
            "customer_name": customer.name,
            "notice_date": as_of_date,
            "notice_level": notice_level,
            "invoices": [
                {
                    "invoice_id": inv.id,
                    "invoice_date": inv.invoice_date,
                    "due_date": inv.due_date,
                    "amount": inv.total - inv.paid_amount,
                }
                for inv in overdue_invoices
            ],
            "total_overdue": total_overdue,
            "generated_at": datetime.now(),
        }

        self.dunning_notices.append(notice)
        return notice

    def recognize_revenue(
        self,
        invoice_id: str,
        recognition_method: str,  # IMMEDIATE, RATABLY, MILESTONE
        start_date: date,
        end_date: date | None = None,
    ) -> list[tuple[date, Decimal]]:
        """
        Set up revenue recognition schedule.

        Args:
            invoice_id: Invoice identifier
            recognition_method: Recognition policy
            start_date: Recognition start date
            end_date: Recognition end date (for ratably method)

        Returns:
            List of (recognition_date, amount) tuples

        Raises:
            InvoiceError: If invoice not found
        """
        if invoice_id not in self.invoices:
            raise InvoiceError(f"Invoice {invoice_id} not found")

        invoice = self.invoices[invoice_id]
        schedule: list[tuple[date, Decimal]] = []

        if recognition_method == "IMMEDIATE":
            schedule.append((start_date, invoice.total))
        elif recognition_method == "RATABLY" and end_date:
            days = (end_date - start_date).days + 1
            daily_amount = invoice.total / Decimal(max(days, 1))

            current_date = start_date
            while current_date <= end_date:
                schedule.append((current_date, daily_amount))
                current_date += timedelta(days=1)

        self.revenue_recognition[invoice_id] = {
            "method": recognition_method,
            "schedule": schedule,
            "recognized_to_date": Decimal("0.00"),
            "created_at": datetime.now(),
        }

        return schedule

    def get_revenue_recognition_amount(
        self,
        invoice_id: str,
        as_of_date: date,
    ) -> Decimal:
        """
        Calculate recognized revenue up to a given date.

        Args:
            invoice_id: Invoice identifier
            as_of_date: Recognition cutoff date

        Returns:
            Recognized amount

        Raises:
            InvoiceError: If invoice not found
        """
        if invoice_id not in self.invoices:
            raise InvoiceError(f"Invoice {invoice_id} not found")

        if invoice_id not in self.revenue_recognition:
            return Decimal("0.00")

        schedule = self.revenue_recognition[invoice_id]["schedule"]
        recognized = Decimal("0.00")

        for rec_date, amount in schedule:
            if rec_date <= as_of_date:
                recognized += amount
            else:
                break

        return recognized

    def generate_customer_statement(
        self,
        customer_id: str,
        statement_date: date,
    ) -> dict[str, any]:
        """
        Generate customer statement (like bank statement).

        Args:
            customer_id: Customer identifier
            statement_date: Statement as-of date

        Returns:
            Statement details including balance and transactions

        Raises:
            CustomerError: If customer not found
        """
        if customer_id not in self.customers:
            raise CustomerError(f"Customer {customer_id} not found")

        customer = self.customers[customer_id]
        invoices: list[dict[str, any]] = []
        total_due = Decimal("0.00")

        for invoice in self.invoices.values():
            if invoice.customer_id != customer_id:
                continue
            if invoice.invoice_type != InvoiceType.SALES_INVOICE:
                continue
            if invoice.invoice_date > statement_date:
                continue

            outstanding = invoice.total - invoice.paid_amount
            if outstanding > Decimal("0.00"):
                invoices.append(
                    {
                        "invoice_id": invoice.id,
                        "invoice_date": invoice.invoice_date,
                        "due_date": invoice.due_date,
                        "amount": invoice.total,
                        "paid": invoice.paid_amount,
                        "outstanding": outstanding,
                    }
                )
                total_due += outstanding

        statement = {
            "statement_id": f"STMT_{uuid4().hex[:8]}",
            "customer_id": customer_id,
            "customer_name": customer.name,
            "statement_date": statement_date,
            "invoices": invoices,
            "total_due": total_due,
            "generated_at": datetime.now(),
        }

        if customer_id not in self.customer_statements:
            self.customer_statements[customer_id] = []

        self.customer_statements[customer_id].append((statement_date, total_due))

        return statement

    def get_customer_balance(self, customer_id: str) -> Decimal:
        """
        Get total outstanding balance for a customer.

        Args:
            customer_id: Customer identifier

        Returns:
            Total outstanding amount

        Raises:
            CustomerError: If customer not found
        """
        if customer_id not in self.customers:
            raise CustomerError(f"Customer {customer_id} not found")

        balance = Decimal("0.00")

        for invoice in self.invoices.values():
            if invoice.customer_id != customer_id:
                continue
            if invoice.invoice_type == InvoiceType.CREDIT_MEMO:
                balance -= invoice.total
            elif invoice.invoice_type == InvoiceType.SALES_INVOICE:
                balance += invoice.total - invoice.paid_amount

        return balance

    def get_overdue_invoices(self, customer_id: str | None = None) -> list[Invoice]:
        """
        Get list of overdue (past due date) invoices.

        Args:
            customer_id: Filter by customer (None for all)

        Returns:
            List of overdue invoices
        """
        today = date.today()
        overdue: list[Invoice] = []

        for invoice in self.invoices.values():
            if invoice.invoice_type != InvoiceType.SALES_INVOICE:
                continue
            if invoice.status in (InvoiceStatus.PAID, InvoiceStatus.CANCELLED):
                continue
            if customer_id and invoice.customer_id != customer_id:
                continue
            if invoice.due_date < today:
                overdue.append(invoice)

        return sorted(overdue, key=lambda i: i.due_date)
