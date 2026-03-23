"""Transaction management and closing operations."""

from datetime import date, timedelta
from decimal import Decimal

from thomas.marketplace.real_estate._exceptions import (
    TransactionNotFoundError,
    ValidationError,
)
from thomas.marketplace.real_estate._types import Offer, Transaction


class OfferManagement:
    """Offer submission and lifecycle management."""

    def __init__(self) -> None:
        """Initialize offer database."""
        self._offers: dict[str, Offer] = {}
        self._by_property: dict[str, list[str]] = {}

    def submit_offer(self, offer: Offer) -> None:
        """Submit a purchase offer.

        Args:
            offer: Offer instance to submit

        Raises:
            ValidationError: If offer data is invalid
            ValueError: If offer ID already exists
        """
        self._validate_offer(offer)
        if offer.offer_id in self._offers:
            raise ValueError(f"Offer {offer.offer_id} already exists")

        self._offers[offer.offer_id] = offer
        if offer.property_id not in self._by_property:
            self._by_property[offer.property_id] = []
        self._by_property[offer.property_id].append(offer.offer_id)

    def get_offer(self, offer_id: str) -> Offer:
        """Retrieve an offer.

        Args:
            offer_id: Offer identifier

        Returns:
            Offer instance

        Raises:
            ValueError: If offer not found
        """
        if offer_id not in self._offers:
            raise ValueError(f"Offer {offer_id} not found")
        return self._offers[offer_id]

    def counter_offer(self, offer_id: str, counter_price: Decimal) -> Offer:
        """Submit counter offer.

        Args:
            offer_id: Original offer ID
            counter_price: Counter offer price

        Returns:
            New counter offer

        Raises:
            ValueError: If original offer not found
        """
        original = self.get_offer(offer_id)
        if original.status not in ["submitted", "countered"]:
            raise ValueError(f"Cannot counter offer with status {original.status}")

        counter = Offer(
            offer_id=f"{offer_id}_counter",
            property_id=original.property_id,
            buyer_agent_id=original.buyer_agent_id,
            listing_agent_id=original.listing_agent_id,
            offer_price=counter_price,
            offer_date=date.today(),
            earnest_money=original.earnest_money,
            contingencies=original.contingencies.copy(),
            contingency_deadlines=original.contingency_deadlines.copy(),
            status="countered",
            closing_date=original.closing_date,
        )
        original.status = "countered"
        self._offers[counter.offer_id] = counter
        return counter

    def accept_offer(self, offer_id: str) -> None:
        """Accept an offer.

        Args:
            offer_id: Offer to accept

        Raises:
            ValueError: If offer cannot be accepted
        """
        offer = self.get_offer(offer_id)
        if offer.status not in ["submitted", "countered"]:
            raise ValueError(f"Cannot accept offer with status {offer.status}")
        offer.status = "accepted"

    def reject_offer(self, offer_id: str) -> None:
        """Reject an offer.

        Args:
            offer_id: Offer to reject
        """
        offer = self.get_offer(offer_id)
        offer.status = "rejected"

    def withdraw_offer(self, offer_id: str) -> None:
        """Withdraw an offer.

        Args:
            offer_id: Offer to withdraw
        """
        offer = self.get_offer(offer_id)
        offer.status = "withdrawn"

    def get_property_offers(self, property_id: str) -> list[Offer]:
        """Get all offers for a property.

        Args:
            property_id: Property identifier

        Returns:
            List of offers for property
        """
        offer_ids = self._by_property.get(property_id, [])
        return [self._offers[oid] for oid in offer_ids]

    @staticmethod
    def _validate_offer(offer: Offer) -> None:
        """Validate offer data.

        Args:
            offer: Offer to validate

        Raises:
            ValidationError: If validation fails
        """
        if not offer.offer_id:
            raise ValidationError("Offer ID required")
        if offer.offer_price < 0:
            raise ValidationError("Offer price must be non-negative")
        if offer.earnest_money < 0:
            raise ValidationError("Earnest money must be non-negative")
        if offer.offer_date > date.today():
            raise ValidationError("Offer date cannot be in future")


class ContingencyManagement:
    """Contingency tracking and deadline management."""

    COMMON_CONTINGENCIES = {
        "inspection": "Home inspection contingency",
        "financing": "Financing contingency",
        "appraisal": "Appraisal contingency",
        "title": "Title clearance contingency",
        "survey": "Survey contingency",
        "walkthrough": "Final walkthrough contingency",
    }

    @staticmethod
    def add_contingency(offer: Offer, contingency_type: str, deadline_days: int) -> None:
        """Add contingency to offer.

        Args:
            offer: Offer instance
            contingency_type: Type of contingency
            deadline_days: Days from today for deadline

        Raises:
            ValueError: If contingency type invalid
        """
        if contingency_type not in ContingencyManagement.COMMON_CONTINGENCIES:
            raise ValueError(f"Unknown contingency type: {contingency_type}")

        offer.contingencies.append(contingency_type)
        offer.contingency_deadlines[contingency_type] = date.today() + timedelta(days=deadline_days)

    @staticmethod
    def check_contingency_deadline(offer: Offer, contingency_type: str) -> bool:
        """Check if contingency deadline has passed.

        Args:
            offer: Offer instance
            contingency_type: Contingency type

        Returns:
            True if deadline has passed

        Raises:
            ValueError: If contingency not found
        """
        if contingency_type not in offer.contingency_deadlines:
            raise ValueError(f"Contingency {contingency_type} not found on offer")

        deadline = offer.contingency_deadlines[contingency_type]
        return date.today() > deadline

    @staticmethod
    def days_until_deadline(offer: Offer, contingency_type: str) -> int:
        """Get days remaining until contingency deadline.

        Args:
            offer: Offer instance
            contingency_type: Contingency type

        Returns:
            Days remaining (negative if past deadline)

        Raises:
            ValueError: If contingency not found
        """
        if contingency_type not in offer.contingency_deadlines:
            raise ValueError(f"Contingency {contingency_type} not found on offer")

        deadline = offer.contingency_deadlines[contingency_type]
        return (deadline - date.today()).days

    @staticmethod
    def remove_contingency(offer: Offer, contingency_type: str) -> None:
        """Remove contingency from offer.

        Args:
            offer: Offer instance
            contingency_type: Contingency type to remove

        Raises:
            ValueError: If contingency not found
        """
        if contingency_type not in offer.contingencies:
            raise ValueError(f"Contingency {contingency_type} not found")

        offer.contingencies.remove(contingency_type)
        if contingency_type in offer.contingency_deadlines:
            del offer.contingency_deadlines[contingency_type]


class ClosingChecklist:
    """Closing checklist and document tracking."""

    CHECKLIST_ITEMS = [
        "title_search",
        "title_insurance_quote",
        "homeowners_insurance",
        "appraisal_ordered",
        "inspection_completed",
        "financing_approved",
        "final_walkthrough",
        "closing_disclosure_received",
        "funds_wired",
        "documents_signed",
        "title_transferred",
        "keys_received",
    ]

    def __init__(self) -> None:
        """Initialize closing checklist."""
        self._checklists: dict[str, dict[str, bool]] = {}

    def create_checklist(self, transaction_id: str) -> None:
        """Create closing checklist for transaction.

        Args:
            transaction_id: Transaction identifier
        """
        self._checklists[transaction_id] = {item: False for item in self.CHECKLIST_ITEMS}

    def check_item(self, transaction_id: str, item: str) -> None:
        """Mark checklist item as complete.

        Args:
            transaction_id: Transaction identifier
            item: Item to check

        Raises:
            ValueError: If transaction or item not found
        """
        if transaction_id not in self._checklists:
            raise ValueError(f"Checklist not found for {transaction_id}")
        if item not in self._checklists[transaction_id]:
            raise ValueError(f"Unknown checklist item: {item}")

        self._checklists[transaction_id][item] = True

    def get_checklist(self, transaction_id: str) -> dict[str, bool]:
        """Get checklist status.

        Args:
            transaction_id: Transaction identifier

        Returns:
            Dictionary of item completion status
        """
        return self._checklists.get(transaction_id, {})

    def get_completion_percentage(self, transaction_id: str) -> float:
        """Get checklist completion percentage.

        Args:
            transaction_id: Transaction identifier

        Returns:
            Percentage complete (0-100)
        """
        checklist = self.get_checklist(transaction_id)
        if not checklist:
            return 0.0

        completed = sum(1 for v in checklist.values() if v)
        return (completed / len(checklist)) * 100


class CommissionCalculation:
    """Commission calculation and distribution."""

    @staticmethod
    def calculate_total_commission(purchase_price: Decimal, commission_rate: Decimal) -> Decimal:
        """Calculate total commission from purchase price.

        Args:
            purchase_price: Final purchase price
            commission_rate: Commission rate as decimal (e.g., 0.06 for 6%)

        Returns:
            Total commission amount
        """
        return purchase_price * commission_rate

    @staticmethod
    def split_commission(
        total_commission: Decimal,
        listing_split: Decimal,
        selling_split: Decimal,
    ) -> tuple[Decimal, Decimal]:
        """Split commission between listing and selling agents.

        Args:
            total_commission: Total commission
            listing_split: Listing agent percentage (e.g., 0.5 for 50%)
            selling_split: Selling agent percentage (e.g., 0.5 for 50%)

        Returns:
            Tuple of (listing_commission, selling_commission)
        """
        listing_comm = total_commission * listing_split
        selling_comm = total_commission * selling_split
        return (listing_comm, selling_comm)

    @staticmethod
    def calculate_broker_split(agent_commission: Decimal, broker_split: Decimal) -> Decimal:
        """Calculate broker's share of commission.

        Args:
            agent_commission: Agent's total commission
            broker_split: Broker's percentage (e.g., 0.5 for 50%)

        Returns:
            Broker's commission share
        """
        return agent_commission * broker_split

    @staticmethod
    def calculate_net_agent_commission(agent_commission: Decimal, broker_split: Decimal) -> Decimal:
        """Calculate agent's net commission after broker split.

        Args:
            agent_commission: Agent's total commission
            broker_split: Broker's percentage

        Returns:
            Agent's net commission
        """
        broker_share = CommissionCalculation.calculate_broker_split(agent_commission, broker_split)
        return agent_commission - broker_share


class ClosingCostEstimation:
    """Closing cost estimation and breakdown."""

    @staticmethod
    def estimate_title_insurance(purchase_price: Decimal) -> Decimal:
        """Estimate title insurance cost.

        Typically 0.5-1% of purchase price.

        Args:
            purchase_price: Purchase price

        Returns:
            Estimated title insurance cost
        """
        return purchase_price * Decimal("0.007")

    @staticmethod
    def estimate_transfer_tax(purchase_price: Decimal, tax_rate: Decimal) -> Decimal:
        """Estimate transfer/deed tax.

        Args:
            purchase_price: Purchase price
            tax_rate: Tax rate as decimal

        Returns:
            Estimated transfer tax
        """
        return purchase_price * tax_rate

    @staticmethod
    def estimate_recording_fees(num_documents: int = 3, fee_per_document: Decimal = Decimal("25")) -> Decimal:
        """Estimate recording fees.

        Args:
            num_documents: Number of documents to record (default 3)
            fee_per_document: Fee per document (default $25)

        Returns:
            Total recording fees
        """
        return Decimal(num_documents) * fee_per_document

    @staticmethod
    def estimate_total_closing_costs(
        purchase_price: Decimal,
        transfer_tax_rate: Decimal = Decimal("0"),
        lender_fees: Decimal = Decimal("1000"),
        other_costs: Decimal = Decimal("500"),
    ) -> Decimal:
        """Estimate total closing costs.

        Args:
            purchase_price: Purchase price
            transfer_tax_rate: Transfer tax rate
            lender_fees: Lender fees (default $1000)
            other_costs: Other costs (default $500)

        Returns:
            Total estimated closing costs
        """
        title = ClosingCostEstimation.estimate_title_insurance(purchase_price)
        transfer = ClosingCostEstimation.estimate_transfer_tax(purchase_price, transfer_tax_rate)
        recording = ClosingCostEstimation.estimate_recording_fees()

        return title + transfer + recording + lender_fees + other_costs

    @staticmethod
    def closing_costs_as_percentage(closing_costs: Decimal, purchase_price: Decimal) -> Decimal:
        """Calculate closing costs as percentage of purchase price.

        Args:
            closing_costs: Total closing costs
            purchase_price: Purchase price

        Returns:
            Percentage (e.g., 0.03 for 3%)
        """
        if purchase_price == 0:
            return Decimal("0")
        return closing_costs / purchase_price


class TransactionDatabase:
    """Transaction storage and retrieval."""

    def __init__(self) -> None:
        """Initialize transaction database."""
        self._transactions: dict[str, Transaction] = {}
        self._by_property: dict[str, list[str]] = {}

    def create(self, transaction: Transaction) -> None:
        """Create transaction record.

        Args:
            transaction: Transaction to create

        Raises:
            ValueError: If transaction already exists
        """
        if transaction.transaction_id in self._transactions:
            raise ValueError(f"Transaction {transaction.transaction_id} exists")

        self._transactions[transaction.transaction_id] = transaction
        if transaction.property_id not in self._by_property:
            self._by_property[transaction.property_id] = []
        self._by_property[transaction.property_id].append(transaction.transaction_id)

    def get_transaction(self, transaction_id: str) -> Transaction:
        """Retrieve transaction by ID.

        Args:
            transaction_id: Transaction identifier

        Returns:
            Transaction instance

        Raises:
            TransactionNotFoundError: If not found
        """
        if transaction_id not in self._transactions:
            raise TransactionNotFoundError(f"Transaction {transaction_id} not found")
        return self._transactions[transaction_id]

    def get_property_transactions(self, property_id: str) -> list[Transaction]:
        """Get all transactions for property.

        Args:
            property_id: Property identifier

        Returns:
            List of transactions
        """
        trans_ids = self._by_property.get(property_id, [])
        return [self._transactions[tid] for tid in trans_ids]

    def list_all(self) -> list[Transaction]:
        """Get all transactions.

        Returns:
            List of all transactions
        """
        return list(self._transactions.values())
