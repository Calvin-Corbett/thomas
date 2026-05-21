"""Travel expense management with policy compliance and reporting."""

from datetime import datetime
from decimal import Decimal

from thomas.travel._exceptions import ExpenseError
from thomas.travel._types import Currency, Expense, ExpenseStatus, TravelPolicy


class ExpenseCategorizer:
    """Categorize travel expenses."""

    # Standard categories and typical amounts
    CATEGORIES = {
        "transportation": {
            "description": "Flights, trains, buses, taxis",
            "typical_limit": Decimal("5000"),
        },
        "lodging": {
            "description": "Hotels, accommodations",
            "typical_limit": Decimal("250"),  # Per night
        },
        "meals": {
            "description": "Breakfast, lunch, dinner",
            "typical_limit": Decimal("75"),  # Daily
        },
        "entertainment": {
            "description": "Activities, attractions",
            "typical_limit": Decimal("100"),
        },
        "miscellaneous": {
            "description": "Other travel expenses",
            "typical_limit": Decimal("200"),
        },
    }

    @classmethod
    def categorize_expense(cls, description: str) -> str:
        """
        Categorize expense based on description.

        Args:
            description: Expense description

        Returns:
            Category code
        """
        description_lower = description.lower()

        # Determine category from keywords
        if any(word in description_lower for word in ["flight", "airline", "taxi", "uber", "lyft", "train", "bus"]):
            return "transportation"

        if any(word in description_lower for word in ["hotel", "motel", "room", "accommodation"]):
            return "lodging"

        if any(
            word in description_lower
            for word in ["restaurant", "café", "coffee", "lunch", "dinner", "breakfast", "meal"]
        ):
            return "meals"

        if any(word in description_lower for word in ["movie", "theater", "show", "museum", "tour", "activity"]):
            return "entertainment"

        return "miscellaneous"

    @classmethod
    def get_category_limit(cls, category: str) -> Decimal:
        """
        Get typical limit for category.

        Args:
            category: Category code

        Returns:
            Typical limit amount
        """
        return cls.CATEGORIES.get(category, {}).get("typical_limit", Decimal("100"))


class ReceiptTracker:
    """Track and validate expense receipts."""

    def __init__(self) -> None:
        """Initialize receipt tracker."""
        self._receipts: dict[str, dict] = {}

    def attach_receipt(
        self,
        expense_id: str,
        receipt_url: str,
        receipt_amount: Decimal,
        receipt_date: datetime,
    ) -> dict[str, any]:
        """
        Attach receipt to expense.

        Args:
            expense_id: Expense identifier
            receipt_url: URL to receipt image/document
            receipt_amount: Amount on receipt
            receipt_date: Receipt date

        Returns:
            Receipt record

        Raises:
            ExpenseError: If receipt invalid
        """
        if not receipt_url:
            raise ExpenseError("Receipt URL required")

        receipt = {
            "expense_id": expense_id,
            "receipt_url": receipt_url,
            "receipt_amount": receipt_amount,
            "receipt_date": receipt_date,
            "attachment_date": datetime.utcnow(),
            "verified": False,
        }

        self._receipts[expense_id] = receipt
        return receipt

    def get_receipt(self, expense_id: str) -> dict | None:
        """
        Get receipt for expense.

        Args:
            expense_id: Expense identifier

        Returns:
            Receipt record, or None
        """
        return self._receipts.get(expense_id)

    def verify_receipt(self, expense_id: str) -> bool:
        """
        Mark receipt as verified.

        Args:
            expense_id: Expense identifier

        Returns:
            True if verified
        """
        if expense_id in self._receipts:
            self._receipts[expense_id]["verified"] = True
            return True
        return False


class PerDiemCalculator:
    """Calculate per diem allowances by location."""

    # GSA standard per diem rates (simplified by region)
    FEDERAL_PER_DIEM = {
        "domestic_high": Decimal("75"),  # High-cost areas
        "domestic_standard": Decimal("50"),  # Standard areas
        "international_high": Decimal("100"),  # Expensive countries
        "international_standard": Decimal("75"),  # Standard countries
    }

    # Location classifications
    HIGH_COST_AREAS = ["San Francisco", "New York", "Washington", "Boston", "Los Angeles"]
    EXPENSIVE_COUNTRIES = ["Switzerland", "Norway", "Denmark", "Japan", "Singapore"]

    def __init__(self) -> None:
        """Initialize per diem calculator."""
        self._custom_rates: dict[str, Decimal] = {}

    def set_custom_rate(self, location: str, daily_rate: Decimal) -> None:
        """
        Set custom per diem rate for location.

        Args:
            location: Location name
            daily_rate: Daily allowance
        """
        self._custom_rates[location] = daily_rate

    def get_per_diem_rate(
        self,
        location: str,
        is_international: bool = False,
    ) -> Decimal:
        """
        Get per diem rate for location.

        Args:
            location: Location name
            is_international: Whether international location

        Returns:
            Daily per diem allowance
        """
        # Check custom rate first
        if location in self._custom_rates:
            return self._custom_rates[location]

        # Check GSA standard rates
        if is_international:
            if any(country in location for country in self.EXPENSIVE_COUNTRIES):
                return self.FEDERAL_PER_DIEM["international_high"]
            return self.FEDERAL_PER_DIEM["international_standard"]
        else:
            if any(city in location for city in self.HIGH_COST_AREAS):
                return self.FEDERAL_PER_DIEM["domestic_high"]
            return self.FEDERAL_PER_DIEM["domestic_standard"]

    def calculate_per_diem(
        self,
        location: str,
        num_days: int,
        is_international: bool = False,
    ) -> Decimal:
        """
        Calculate total per diem allowance.

        Args:
            location: Location name
            num_days: Number of days
            is_international: Whether international

        Returns:
            Total per diem allowance
        """
        daily_rate = self.get_per_diem_rate(location, is_international)
        return daily_rate * Decimal(num_days)


class PolicyComplianceChecker:
    """Check expenses against travel policy."""

    def __init__(self, policy: TravelPolicy | None = None) -> None:
        """
        Initialize compliance checker.

        Args:
            policy: Travel policy
        """
        self.policy = policy

    def check_expense_compliance(self, expense: Expense) -> tuple[bool, list[str]]:
        """
        Check if expense complies with policy.

        Args:
            expense: Expense to check

        Returns:
            Tuple of (is_compliant, list of violations)

        Raises:
            ExpenseError: If policy not set
        """
        if not self.policy:
            raise ExpenseError("Travel policy not configured")

        violations = []

        # Check category limits
        if expense.category == "lodging":
            if expense.amount > self.policy.max_daily_hotel_rate:
                violations.append(
                    f"Hotel rate ${expense.amount} exceeds policy limit ${self.policy.max_daily_hotel_rate}"
                )

        if expense.category == "meals":
            if expense.amount > self.policy.max_daily_meal_allowance:
                violations.append(
                    f"Meal expense ${expense.amount} exceeds daily limit ${self.policy.max_daily_meal_allowance}"
                )

        if expense.category == "transportation":
            if expense.amount > self.policy.max_ground_transportation:
                violations.append(
                    f"Ground transportation ${expense.amount} exceeds limit ${self.policy.max_ground_transportation}"
                )

        # Check receipt requirement
        if expense.amount > self.policy.requires_receipt_above and not expense.receipt_url:
            violations.append(f"Receipt required for expenses over ${self.policy.requires_receipt_above}")

        is_compliant = len(violations) == 0
        expense.policy_compliant = is_compliant

        return is_compliant, violations

    def flag_for_approval(self, expense: Expense) -> bool:
        """
        Check if expense requires manager approval.

        Args:
            expense: Expense to check

        Returns:
            True if approval required
        """
        if not self.policy:
            return False

        return expense.amount > self.policy.requires_manager_approval_above


class ExpenseReportGenerator:
    """Generate expense reports."""

    def __init__(self) -> None:
        """Initialize report generator."""
        self._reports: dict[str, dict] = {}

    def create_report(
        self,
        report_id: str,
        trip_id: str,
        employee_name: str,
        expenses: list[Expense],
    ) -> dict[str, any]:
        """
        Create expense report from expenses.

        Args:
            report_id: Report identifier
            trip_id: Trip identifier
            employee_name: Employee name
            expenses: List of expenses

        Returns:
            Expense report

        Raises:
            ExpenseError: If no expenses provided
        """
        if not expenses:
            raise ExpenseError("At least one expense required")

        # Calculate totals by category
        category_totals: dict[str, Decimal] = {}
        total_amount = Decimal("0")
        total_reimbursable = Decimal("0")

        for expense in expenses:
            category_totals[expense.category] = category_totals.get(expense.category, Decimal("0")) + expense.amount
            total_amount += expense.amount

            if expense.policy_compliant:
                total_reimbursable += expense.amount

        report = {
            "report_id": report_id,
            "trip_id": trip_id,
            "employee_name": employee_name,
            "created_date": datetime.utcnow(),
            "status": ExpenseStatus.SUBMITTED,
            "expenses": expenses,
            "category_totals": category_totals,
            "total_amount": total_amount,
            "total_reimbursable": total_reimbursable,
            "non_compliant_amount": total_amount - total_reimbursable,
            "approved_date": None,
            "reimbursement_date": None,
        }

        self._reports[report_id] = report
        return report

    def get_report(self, report_id: str) -> dict | None:
        """
        Get expense report.

        Args:
            report_id: Report identifier

        Returns:
            Report, or None
        """
        return self._reports.get(report_id)


class ApprovalWorkflow:
    """Manage expense approval workflow."""

    def __init__(self) -> None:
        """Initialize approval workflow."""
        self._approvals: dict[str, dict] = {}

    def submit_for_approval(
        self,
        report_id: str,
        manager_id: str,
    ) -> dict[str, any]:
        """
        Submit report for manager approval.

        Args:
            report_id: Report identifier
            manager_id: Manager identifier

        Returns:
            Approval record
        """
        approval = {
            "report_id": report_id,
            "manager_id": manager_id,
            "submission_date": datetime.utcnow(),
            "status": ExpenseStatus.SUBMITTED,
            "approval_date": None,
            "approval_notes": None,
        }

        self._approvals[report_id] = approval
        return approval

    def approve_report(
        self,
        report_id: str,
        approval_notes: str = "",
    ) -> dict[str, any]:
        """
        Approve expense report.

        Args:
            report_id: Report identifier
            approval_notes: Approval notes

        Returns:
            Updated approval record
        """
        if report_id not in self._approvals:
            raise ExpenseError(f"Approval not found for {report_id}")

        approval = self._approvals[report_id]
        approval["status"] = ExpenseStatus.APPROVED
        approval["approval_date"] = datetime.utcnow()
        approval["approval_notes"] = approval_notes
        return approval

    def reject_report(
        self,
        report_id: str,
        rejection_reason: str,
    ) -> dict[str, any]:
        """
        Reject expense report.

        Args:
            report_id: Report identifier
            rejection_reason: Reason for rejection

        Returns:
            Updated approval record
        """
        if report_id not in self._approvals:
            raise ExpenseError(f"Approval not found for {report_id}")

        approval = self._approvals[report_id]
        approval["status"] = ExpenseStatus.REJECTED
        approval["rejection_date"] = datetime.utcnow()
        approval["rejection_reason"] = rejection_reason
        return approval


class MileageCalculator:
    """Calculate mileage reimbursement."""

    # IRS standard mileage rates (as of 2025)
    MILEAGE_RATES = {
        "business": Decimal("0.67"),
        "medical": Decimal("0.21"),
        "charitable": Decimal("0.14"),
    }

    def calculate_mileage_reimbursement(
        self,
        miles: float,
        purpose: str = "business",
    ) -> Decimal:
        """
        Calculate mileage reimbursement.

        Args:
            miles: Miles driven
            purpose: Purpose of travel

        Returns:
            Reimbursement amount
        """
        rate = self.MILEAGE_RATES.get(purpose, self.MILEAGE_RATES["business"])
        return Decimal(miles) * rate

    def add_mileage_expense(
        self,
        origin: str,
        destination: str,
        miles: float,
        purpose: str = "business",
    ) -> Decimal:
        """
        Create mileage expense.

        Args:
            origin: Trip origin
            destination: Trip destination
            miles: Miles driven
            purpose: Purpose of travel

        Returns:
            Reimbursement amount
        """
        return self.calculate_mileage_reimbursement(miles, purpose)


class CurrencyExpenseConversion:
    """Convert international expenses to home currency."""

    def __init__(self) -> None:
        """Initialize currency converter."""
        self._exchange_rates: dict[Currency, Decimal] = {}
        self._load_default_rates()

    def _load_default_rates(self) -> None:
        """Load default exchange rates to USD."""
        self._exchange_rates = {
            Currency.USD: Decimal("1.0"),
            Currency.EUR: Decimal("1.09"),
            Currency.GBP: Decimal("1.27"),
            Currency.JPY: Decimal("0.0065"),
            Currency.AUD: Decimal("0.64"),
            Currency.CAD: Decimal("0.72"),
        }

    def set_exchange_rate(self, currency: Currency, rate: Decimal) -> None:
        """
        Set exchange rate to USD.

        Args:
            currency: Currency
            rate: Exchange rate to USD
        """
        self._exchange_rates[currency] = rate

    def convert_to_usd(
        self,
        amount: Decimal,
        currency: Currency,
    ) -> Decimal:
        """
        Convert expense to USD.

        Args:
            amount: Expense amount
            currency: Expense currency

        Returns:
            Amount in USD
        """
        rate = self._exchange_rates.get(currency, Decimal("1.0"))
        return amount * rate

    def convert_expense(
        self,
        expense: Expense,
        target_currency: Currency = Currency.USD,
    ) -> Decimal:
        """
        Convert expense to target currency.

        Args:
            expense: Expense object
            target_currency: Target currency

        Returns:
            Converted amount
        """
        if expense.currency == target_currency:
            return expense.amount

        # Convert to USD first if needed
        usd_amount = self.convert_to_usd(expense.amount, expense.currency)

        # Then convert to target
        if target_currency == Currency.USD:
            return usd_amount

        # For other currencies, use inverse rate
        rate = self._exchange_rates.get(target_currency, Decimal("1.0"))
        return usd_amount / rate
