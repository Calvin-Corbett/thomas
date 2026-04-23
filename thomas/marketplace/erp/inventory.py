"""
Inventory management.

Handles stock transactions, valuation, cycle counting,
and inventory analysis.
"""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from uuid import uuid4

from thomas.marketplace.erp._exceptions import InsufficientInventoryError
from thomas.marketplace.erp._types import InventoryItem, UnitOfMeasure


class TransactionType(Enum):
    """Inventory transaction types."""

    RECEIVE = "RECEIVE"
    ISSUE = "ISSUE"
    TRANSFER = "TRANSFER"
    ADJUSTMENT = "ADJUSTMENT"
    PRODUCTION = "PRODUCTION"
    SCRAP = "SCRAP"


class StockTransaction:
    """Single inventory transaction."""

    def __init__(
        self,
        transaction_id: str,
        sku: str,
        transaction_type: TransactionType,
        quantity: Decimal,
        transaction_date: date,
        reference: str = "",
        from_location: str | None = None,
        to_location: str | None = None,
        unit_cost: Decimal = Decimal("0.00"),
        lot_number: str | None = None,
        serial_number: str | None = None,
    ) -> None:
        """Initialize stock transaction."""
        self.transaction_id = transaction_id
        self.sku = sku
        self.transaction_type = transaction_type
        self.quantity = quantity
        self.transaction_date = transaction_date
        self.reference = reference
        self.from_location = from_location
        self.to_location = to_location
        self.unit_cost = unit_cost
        self.lot_number = lot_number
        self.serial_number = serial_number
        self.created_at = datetime.now()


class InventoryManager:
    """
    Inventory management with valuation methods.

    Supports FIFO, LIFO, and weighted average costing.
    """

    def __init__(self) -> None:
        """Initialize inventory manager."""
        self.items: dict[str, InventoryItem] = {}
        self.transactions: list[StockTransaction] = []
        self.transaction_index: dict[str, list[StockTransaction]] = {}
        self.fifo_queue: dict[str, list[tuple[Decimal, Decimal]]] = {}  # sku -> [(qty, cost)]
        self.weighted_average: dict[str, tuple[Decimal, Decimal]] = {}  # sku -> (qty, total_cost)
        self.lot_tracking: dict[str, list[dict[str, any]]] = {}
        self.serial_tracking: dict[str, list[dict[str, any]]] = {}
        self.cycle_counts: list[dict[str, any]] = []
        self.abc_analysis: dict[str, dict[str, Decimal]] = {}

    def create_item(
        self,
        sku: str,
        description: str,
        uom: UnitOfMeasure,
        cost_method: str,
        standard_cost: Decimal = Decimal("0.00"),
        min_quantity: Decimal = Decimal("0.00"),
        max_quantity: Decimal = Decimal("0.00"),
        reorder_quantity: Decimal = Decimal("0.00"),
        lot_tracking: bool = False,
        serial_tracking: bool = False,
    ) -> InventoryItem:
        """
        Create a new inventory item.

        Args:
            sku: Stock keeping unit
            description: Item description
            uom: Unit of measure
            cost_method: FIFO, LIFO, or WEIGHTED_AVERAGE
            standard_cost: Standard unit cost
            min_quantity: Reorder point
            max_quantity: Maximum stock level
            reorder_quantity: Preferred order quantity
            lot_tracking: Track lot/batch numbers
            serial_tracking: Track serial numbers

        Returns:
            Created InventoryItem

        Raises:
            ValueError: If item already exists
        """
        if sku in self.items:
            raise ValueError(f"Item {sku} already exists")

        item = InventoryItem(
            sku=sku,
            description=description,
            uom=uom,
            cost_method=cost_method,
            standard_cost=standard_cost,
            min_quantity=min_quantity,
            max_quantity=max_quantity,
            reorder_quantity=reorder_quantity,
            lot_tracking=lot_tracking,
            serial_tracking=serial_tracking,
        )
        self.items[sku] = item
        self.transaction_index[sku] = []
        self.fifo_queue[sku] = []
        self.weighted_average[sku] = (Decimal("0.00"), Decimal("0.00"))
        return item

    def receive_stock(
        self,
        sku: str,
        quantity: Decimal,
        unit_cost: Decimal,
        location: str = "DEFAULT",
        reference: str = "",
        lot_number: str | None = None,
    ) -> StockTransaction:
        """
        Record stock receipt.

        Args:
            sku: Item SKU
            quantity: Quantity received
            unit_cost: Unit cost
            location: Warehouse location
            reference: PO or receipt number
            lot_number: Lot/batch number if tracked

        Returns:
            Created StockTransaction

        Raises:
            ValueError: If item not found
        """
        if sku not in self.items:
            raise ValueError(f"Item {sku} not found")

        item = self.items[sku]
        transaction_id = f"RCV_{uuid4().hex[:8]}"

        transaction = StockTransaction(
            transaction_id=transaction_id,
            sku=sku,
            transaction_type=TransactionType.RECEIVE,
            quantity=quantity,
            transaction_date=date.today(),
            reference=reference,
            to_location=location,
            unit_cost=unit_cost,
            lot_number=lot_number,
        )

        self.transactions.append(transaction)
        self.transaction_index[sku].append(transaction)

        item.quantity_on_hand += quantity
        if location not in item.locations:
            item.locations[location] = Decimal("0.00")
        item.locations[location] += quantity

        self._update_fifo_queue(sku, quantity, unit_cost)
        self._update_weighted_average(sku, quantity, unit_cost)

        if lot_number:
            self._track_lot(sku, lot_number, quantity, unit_cost)

        return transaction

    def issue_stock(
        self,
        sku: str,
        quantity: Decimal,
        location: str = "DEFAULT",
        reference: str = "",
    ) -> StockTransaction:
        """
        Record stock issue/usage.

        Args:
            sku: Item SKU
            quantity: Quantity issued
            location: Warehouse location
            reference: SO or production order number

        Returns:
            Created StockTransaction

        Raises:
            ValueError: If item not found
            InsufficientInventoryError: If insufficient stock
        """
        if sku not in self.items:
            raise ValueError(f"Item {sku} not found")

        item = self.items[sku]
        available = item.quantity_on_hand - item.quantity_reserved

        if available < quantity:
            raise InsufficientInventoryError(f"Insufficient stock: need {quantity}, available {available}")

        transaction_id = f"ISS_{uuid4().hex[:8]}"

        transaction = StockTransaction(
            transaction_id=transaction_id,
            sku=sku,
            transaction_type=TransactionType.ISSUE,
            quantity=quantity,
            transaction_date=date.today(),
            reference=reference,
            from_location=location,
        )

        self.transactions.append(transaction)
        self.transaction_index[sku].append(transaction)

        item.quantity_on_hand -= quantity
        if location in item.locations:
            item.locations[location] -= quantity

        return transaction

    def transfer_stock(
        self,
        sku: str,
        quantity: Decimal,
        from_location: str,
        to_location: str,
        reference: str = "",
    ) -> StockTransaction:
        """
        Transfer stock between locations.

        Args:
            sku: Item SKU
            quantity: Quantity transferred
            from_location: Source location
            to_location: Destination location
            reference: Transfer reference

        Returns:
            Created StockTransaction

        Raises:
            ValueError: If item not found
            InsufficientInventoryError: If insufficient stock at source
        """
        if sku not in self.items:
            raise ValueError(f"Item {sku} not found")

        item = self.items[sku]

        if from_location not in item.locations or item.locations[from_location] < quantity:
            raise InsufficientInventoryError(f"Insufficient stock at {from_location}")

        transaction_id = f"TRN_{uuid4().hex[:8]}"

        transaction = StockTransaction(
            transaction_id=transaction_id,
            sku=sku,
            transaction_type=TransactionType.TRANSFER,
            quantity=quantity,
            transaction_date=date.today(),
            reference=reference,
            from_location=from_location,
            to_location=to_location,
        )

        self.transactions.append(transaction)
        self.transaction_index[sku].append(transaction)

        item.locations[from_location] -= quantity
        if to_location not in item.locations:
            item.locations[to_location] = Decimal("0.00")
        item.locations[to_location] += quantity

        return transaction

    def adjust_inventory(
        self,
        sku: str,
        quantity_adjustment: Decimal,
        reason: str = "",
        location: str = "DEFAULT",
    ) -> StockTransaction:
        """
        Adjust inventory for cycle count discrepancies or losses.

        Args:
            sku: Item SKU
            quantity_adjustment: Quantity to add (positive) or remove (negative)
            reason: Reason for adjustment
            location: Warehouse location

        Returns:
            Created StockTransaction

        Raises:
            ValueError: If item not found
        """
        if sku not in self.items:
            raise ValueError(f"Item {sku} not found")

        item = self.items[sku]
        transaction_id = f"ADJ_{uuid4().hex[:8]}"

        transaction = StockTransaction(
            transaction_id=transaction_id,
            sku=sku,
            transaction_type=TransactionType.ADJUSTMENT,
            quantity=abs(quantity_adjustment),
            transaction_date=date.today(),
            reference=reason,
            to_location=location if quantity_adjustment > 0 else None,
            from_location=location if quantity_adjustment < 0 else None,
        )

        self.transactions.append(transaction)
        self.transaction_index[sku].append(transaction)

        item.quantity_on_hand += quantity_adjustment
        if location not in item.locations:
            item.locations[location] = Decimal("0.00")
        item.locations[location] += quantity_adjustment

        return transaction

    def reserve_stock(self, sku: str, quantity: Decimal) -> None:
        """
        Reserve stock for pending orders.

        Args:
            sku: Item SKU
            quantity: Quantity to reserve

        Raises:
            ValueError: If item not found
            InsufficientInventoryError: If insufficient stock
        """
        if sku not in self.items:
            raise ValueError(f"Item {sku} not found")

        item = self.items[sku]
        available = item.quantity_on_hand - item.quantity_reserved

        if available < quantity:
            raise InsufficientInventoryError(f"Cannot reserve {quantity}: only {available} available")

        item.quantity_reserved += quantity
        item.quantity_available = item.quantity_on_hand - item.quantity_reserved

    def release_reservation(self, sku: str, quantity: Decimal) -> None:
        """
        Release stock reservation.

        Args:
            sku: Item SKU
            quantity: Quantity to release

        Raises:
            ValueError: If item not found
        """
        if sku not in self.items:
            raise ValueError(f"Item {sku} not found")

        item = self.items[sku]
        item.quantity_reserved = max(Decimal("0.00"), item.quantity_reserved - quantity)
        item.quantity_available = item.quantity_on_hand - item.quantity_reserved

    def get_inventory_valuation(self, sku: str) -> Decimal:
        """
        Calculate inventory valuation using item's cost method.

        Args:
            sku: Item SKU

        Returns:
            Total valuation amount

        Raises:
            ValueError: If item not found
        """
        if sku not in self.items:
            raise ValueError(f"Item {sku} not found")

        item = self.items[sku]
        method = item.cost_method.upper()

        if method == "FIFO":
            return self._calculate_fifo_value(sku)
        elif method == "LIFO":
            return self._calculate_lifo_value(sku)
        elif method == "WEIGHTED_AVERAGE":
            qty, total_cost = self.weighted_average[sku]
            return total_cost
        else:
            return Decimal("0.00")

    def _update_fifo_queue(
        self,
        sku: str,
        quantity: Decimal,
        unit_cost: Decimal,
    ) -> None:
        """Update FIFO queue with received items."""
        self.fifo_queue[sku].append((quantity, unit_cost))

    def _calculate_fifo_value(self, sku: str) -> Decimal:
        """Calculate inventory value using FIFO method."""
        item = self.items[sku]
        remaining_qty = item.quantity_on_hand
        total_value = Decimal("0.00")

        for batch_qty, batch_cost in self.fifo_queue[sku]:
            if remaining_qty <= Decimal("0.00"):
                break
            used_qty = min(batch_qty, remaining_qty)
            total_value += used_qty * batch_cost
            remaining_qty -= used_qty

        return total_value

    def _calculate_lifo_value(self, sku: str) -> Decimal:
        """Calculate inventory value using LIFO method."""
        item = self.items[sku]
        remaining_qty = item.quantity_on_hand
        total_value = Decimal("0.00")

        for batch_qty, batch_cost in reversed(self.fifo_queue[sku]):
            if remaining_qty <= Decimal("0.00"):
                break
            used_qty = min(batch_qty, remaining_qty)
            total_value += used_qty * batch_cost
            remaining_qty -= used_qty

        return total_value

    def _update_weighted_average(
        self,
        sku: str,
        quantity: Decimal,
        unit_cost: Decimal,
    ) -> None:
        """Update weighted average cost."""
        current_qty, current_cost = self.weighted_average[sku]
        new_qty = current_qty + quantity
        new_cost = current_cost + (quantity * unit_cost)
        self.weighted_average[sku] = (new_qty, new_cost)

    def _track_lot(
        self,
        sku: str,
        lot_number: str,
        quantity: Decimal,
        unit_cost: Decimal,
    ) -> None:
        """Track lot/batch information."""
        if sku not in self.lot_tracking:
            self.lot_tracking[sku] = []

        self.lot_tracking[sku].append(
            {
                "lot_number": lot_number,
                "quantity": quantity,
                "unit_cost": unit_cost,
                "received_at": datetime.now(),
            }
        )

    def cycle_count(
        self,
        location: str,
        counted_items: dict[str, Decimal],
    ) -> dict[str, tuple[Decimal, Decimal, Decimal]]:
        """
        Record cycle count results.

        Args:
            location: Warehouse location
            counted_items: Map of SKU to physical count

        Returns:
            Discrepancies: SKU -> (system_qty, counted_qty, variance)
        """
        discrepancies: dict[str, tuple[Decimal, Decimal, Decimal]] = {}
        count_id = f"CYCLE_{uuid4().hex[:8]}"

        for sku, counted_qty in counted_items.items():
            if sku not in self.items:
                continue

            item = self.items[sku]
            system_qty = item.locations.get(location, Decimal("0.00"))

            if system_qty != counted_qty:
                variance = counted_qty - system_qty
                discrepancies[sku] = (system_qty, counted_qty, variance)

                self.adjust_inventory(sku, variance, f"Cycle count {count_id}", location)

        self.cycle_counts.append(
            {
                "count_id": count_id,
                "location": location,
                "count_date": date.today(),
                "discrepancies": discrepancies,
                "counted_at": datetime.now(),
            }
        )

        return discrepancies

    def check_reorder_points(self) -> dict[str, dict[str, Decimal]]:
        """
        Check items below reorder point.

        Returns:
            Map of SKU to reorder info
        """
        reorder_needed: dict[str, dict[str, Decimal]] = {}

        for sku, item in self.items.items():
            if item.quantity_on_hand <= item.min_quantity:
                reorder_needed[sku] = {
                    "quantity_on_hand": item.quantity_on_hand,
                    "min_quantity": item.min_quantity,
                    "reorder_quantity": item.reorder_quantity,
                }

        return reorder_needed

    def abc_analysis(self) -> dict[str, list[str]]:
        """
        Perform ABC analysis based on inventory value.

        Returns:
            Map of categories (A, B, C) to SKU lists
        """
        valuations: dict[str, Decimal] = {}

        for sku in self.items:
            valuations[sku] = self.get_inventory_valuation(sku)

        sorted_items = sorted(
            valuations.items(),
            key=lambda x: x[1],
            reverse=True,
        )

        total_value = sum(v for _, v in sorted_items)
        cumulative = Decimal("0.00")
        analysis: dict[str, list[str]] = {"A": [], "B": [], "C": []}

        for sku, value in sorted_items:
            cumulative += value
            percentage = cumulative / total_value if total_value > 0 else Decimal("0.00")

            if percentage <= Decimal("0.80"):
                analysis["A"].append(sku)
            elif percentage <= Decimal("0.95"):
                analysis["B"].append(sku)
            else:
                analysis["C"].append(sku)

        self.abc_analysis = analysis
        return analysis

    def stock_movement_report(
        self,
        sku: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[StockTransaction]:
        """
        Generate stock movement report.

        Args:
            sku: Filter by SKU (None for all)
            start_date: Start date filter
            end_date: End date filter

        Returns:
            Matching transactions
        """
        results: list[StockTransaction] = []

        for transaction in self.transactions:
            if sku and transaction.sku != sku:
                continue
            if start_date and transaction.transaction_date < start_date:
                continue
            if end_date and transaction.transaction_date > end_date:
                continue

            results.append(transaction)

        return sorted(results, key=lambda t: t.transaction_date)
