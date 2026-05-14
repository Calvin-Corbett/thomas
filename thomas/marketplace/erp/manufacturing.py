"""
Manufacturing management.

Handles bill of materials, production orders, MRP,
and work-in-progress tracking.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from thomas.marketplace.erp._exceptions import ManufacturingError
from thomas.marketplace.erp._types import (
    BOM,
    BOMLine,
    ProductionOrder,
    PRStatus,
)


class Routing:
    """Production routing (work center sequence)."""

    def __init__(
        self,
        routing_id: str,
        product_sku: str,
        operations: list[dict[str, any]],
    ) -> None:
        """Initialize routing."""
        self.routing_id = routing_id
        self.product_sku = product_sku
        self.operations = operations  # [{work_center, sequence, run_time, setup_time}, ...]
        self.created_at = datetime.now()


class WorkCenterOperation:
    """Work performed at a work center."""

    def __init__(
        self,
        operation_id: str,
        production_order_id: str,
        work_center_id: str,
        sequence: int,
        operation_date: date,
        quantity_started: Decimal,
        quantity_completed: Decimal = Decimal("0.00"),
        run_time_minutes: int = 0,
        setup_time_minutes: int = 0,
    ) -> None:
        """Initialize work center operation."""
        self.operation_id = operation_id
        self.production_order_id = production_order_id
        self.work_center_id = work_center_id
        self.sequence = sequence
        self.operation_date = operation_date
        self.quantity_started = quantity_started
        self.quantity_completed = quantity_completed
        self.run_time_minutes = run_time_minutes
        self.setup_time_minutes = setup_time_minutes
        self.status = "PENDING"
        self.created_at = datetime.now()


class ManufacturingManager:
    """
    Manufacturing management with BOM, MRP, and production planning.
    """

    def __init__(self) -> None:
        """Initialize manufacturing manager."""
        self.boms: dict[str, BOM] = {}
        self.production_orders: dict[str, ProductionOrder] = {}
        self.routings: dict[str, Routing] = {}
        self.work_center_operations: list[WorkCenterOperation] = []
        self.planned_orders: dict[str, dict[str, Decimal]] = {}  # sku -> {planned_qty, planned_date}
        self.bom_explosions: dict[str, dict[str, Decimal]] = {}
        self.work_in_progress: dict[str, dict[str, Decimal]] = {}  # production_order_id -> {sku: qty}

    def create_bom(
        self,
        bom_id: str,
        finished_sku: str,
        lines: list[BOMLine],
        effective_date: date = None,
    ) -> BOM:
        """
        Create a bill of materials.

        Args:
            bom_id: Unique BOM identifier
            finished_sku: Finished product SKU
            lines: Component lines with quantities and costs
            effective_date: When BOM becomes active

        Returns:
            Created BOM

        Raises:
            ManufacturingError: If BOM already exists
        """
        if bom_id in self.boms:
            raise ManufacturingError(f"BOM {bom_id} already exists")

        if effective_date is None:
            effective_date = date.today()

        bom = BOM(
            id=bom_id,
            finished_sku=finished_sku,
            lines=lines,
            effective_date=effective_date,
        )

        self.boms[bom_id] = bom
        return bom

    def explode_bom(
        self,
        finished_sku: str,
        quantity: Decimal,
        bom_id: str | None = None,
    ) -> dict[str, Decimal]:
        """
        Explode BOM to get component requirements.

        Handles multi-level BOMs recursively.

        Args:
            finished_sku: Finished product SKU
            quantity: Quantity to produce
            bom_id: Specific BOM version (uses latest if None)

        Returns:
            Map of component SKU to total quantity required

        Raises:
            ManufacturingError: If BOM not found
        """
        requirements: dict[str, Decimal] = {}

        if bom_id is None:
            bom = self._get_active_bom(finished_sku)
        else:
            if bom_id not in self.boms:
                raise ManufacturingError(f"BOM {bom_id} not found")
            bom = self.boms[bom_id]

        if bom is None:
            raise ManufacturingError(f"No BOM found for {finished_sku}")

        for line in bom.lines:
            required_qty = quantity * line.quantity * (Decimal("1.00") + (line.scrap_percent / Decimal("100.00")))

            if line.sku not in requirements:
                requirements[line.sku] = Decimal("0.00")
            requirements[line.sku] += required_qty

            sub_bom = self._get_active_bom(line.sku)
            if sub_bom:
                sub_requirements = self.explode_bom(line.sku, required_qty, sub_bom.id)
                for sub_sku, sub_qty in sub_requirements.items():
                    if sub_sku not in requirements:
                        requirements[sub_sku] = Decimal("0.00")
                    requirements[sub_sku] += sub_qty

        return requirements

    def create_production_order(
        self,
        pr_id: str,
        bom_id: str,
        finished_sku: str,
        quantity_ordered: Decimal,
        start_date: date,
        due_date: date,
    ) -> ProductionOrder:
        """
        Create a production order.

        Args:
            pr_id: Unique production order number
            bom_id: Bill of materials reference
            finished_sku: Product being manufactured
            quantity_ordered: Quantity to produce
            start_date: Scheduled start
            due_date: Scheduled completion

        Returns:
            Created ProductionOrder

        Raises:
            ManufacturingError: If BOM not found or PR already exists
        """
        if bom_id not in self.boms:
            raise ManufacturingError(f"BOM {bom_id} not found")

        if pr_id in self.production_orders:
            raise ManufacturingError(f"Production order {pr_id} already exists")

        self.boms[bom_id]

        planned_materials = self.explode_bom(finished_sku, quantity_ordered, bom_id)

        pr = ProductionOrder(
            id=pr_id,
            bom_id=bom_id,
            finished_sku=finished_sku,
            quantity_ordered=quantity_ordered,
            start_date=start_date,
            due_date=due_date,
            planned_materials=planned_materials,
        )

        self.production_orders[pr_id] = pr
        self.work_in_progress[pr_id] = {}

        return pr

    def release_production_order(self, pr_id: str) -> None:
        """
        Release a production order for manufacturing.

        Args:
            pr_id: Production order ID

        Raises:
            ManufacturingError: If PR not found
        """
        if pr_id not in self.production_orders:
            raise ManufacturingError(f"Production order {pr_id} not found")

        pr = self.production_orders[pr_id]
        pr.status = PRStatus.RELEASED

    def schedule_production(
        self,
        pr_id: str,
        forward_schedule: bool = True,
    ) -> dict[str, date]:
        """
        Schedule production (forward or backward from due date).

        Args:
            pr_id: Production order ID
            forward_schedule: Schedule forward from start date if True

        Returns:
            Map of operation sequence to scheduled date

        Raises:
            ManufacturingError: If PR not found
        """
        if pr_id not in self.production_orders:
            raise ManufacturingError(f"Production order {pr_id} not found")

        pr = self.production_orders[pr_id]
        routing = self._get_routing(pr.finished_sku)

        if not routing:
            return {}

        schedule: dict[str, date] = {}

        if forward_schedule:
            current_date = pr.start_date
            for op in routing.operations:
                schedule[str(op["sequence"])] = current_date
                current_date += timedelta(days=1)
        else:
            current_date = pr.due_date
            for op in reversed(routing.operations):
                schedule[str(op["sequence"])] = current_date
                current_date -= timedelta(days=1)

        return schedule

    def material_requirements_planning(
        self,
        demand_orders: dict[str, tuple[Decimal, date]],
    ) -> dict[str, dict[str, Decimal]]:
        """
        Run MRP calculation.

        Converts demand (sales orders) to planned material requirements.

        Args:
            demand_orders: Map of finished_sku to (quantity, required_date)

        Returns:
            Map of SKU to {gross_requirement, on_hand, net_requirement, planned_order_date}
        """
        mrp_results: dict[str, dict[str, Decimal]] = {}

        for finished_sku, (quantity, required_date) in demand_orders.items():
            requirements = self.explode_bom(finished_sku, quantity)

            for component_sku, gross_req in requirements.items():
                if component_sku not in mrp_results:
                    mrp_results[component_sku] = {
                        "gross_requirement": Decimal("0.00"),
                        "on_hand": Decimal("0.00"),
                        "net_requirement": Decimal("0.00"),
                        "planned_order_qty": Decimal("0.00"),
                        "planned_order_date": required_date,
                    }

                mrp_results[component_sku]["gross_requirement"] += gross_req

                net_req = max(
                    Decimal("0.00"),
                    mrp_results[component_sku]["gross_requirement"] - mrp_results[component_sku]["on_hand"],
                )
                mrp_results[component_sku]["net_requirement"] = net_req
                mrp_results[component_sku]["planned_order_qty"] = net_req

        self.planned_orders = {
            sku: {
                "quantity": data["planned_order_qty"],
                "date": data["planned_order_date"],
            }
            for sku, data in mrp_results.items()
        }

        return mrp_results

    def record_operation_start(
        self,
        pr_id: str,
        work_center_id: str,
        sequence: int,
        quantity_started: Decimal,
    ) -> WorkCenterOperation:
        """
        Record start of a work center operation.

        Args:
            pr_id: Production order ID
            work_center_id: Work center identifier
            sequence: Operation sequence number
            quantity_started: Quantity starting through operation

        Returns:
            Created WorkCenterOperation

        Raises:
            ManufacturingError: If PR not found
        """
        if pr_id not in self.production_orders:
            raise ManufacturingError(f"Production order {pr_id} not found")

        self.production_orders[pr_id]
        operation_id = f"OP_{uuid4().hex[:8]}"

        operation = WorkCenterOperation(
            operation_id=operation_id,
            production_order_id=pr_id,
            work_center_id=work_center_id,
            sequence=sequence,
            operation_date=date.today(),
            quantity_started=quantity_started,
        )

        self.work_center_operations.append(operation)
        operation.status = "IN_PROGRESS"

        return operation

    def record_operation_completion(
        self,
        operation_id: str,
        quantity_completed: Decimal,
        scrap_quantity: Decimal = Decimal("0.00"),
    ) -> None:
        """
        Record completion of a work center operation.

        Args:
            operation_id: Operation ID
            quantity_completed: Quantity completed
            scrap_quantity: Quantity scrapped

        Raises:
            ManufacturingError: If operation not found
        """
        operation = None
        for op in self.work_center_operations:
            if op.operation_id == operation_id:
                operation = op
                break

        if operation is None:
            raise ManufacturingError(f"Operation {operation_id} not found")

        operation.quantity_completed = quantity_completed
        operation.status = "COMPLETED"

        pr_id = operation.production_order_id
        pr = self.production_orders[pr_id]

        if pr_id not in self.work_in_progress:
            self.work_in_progress[pr_id] = {}

        if pr.finished_sku not in self.work_in_progress[pr_id]:
            self.work_in_progress[pr_id][pr.finished_sku] = Decimal("0.00")

        self.work_in_progress[pr_id][pr.finished_sku] += quantity_completed

    def complete_production_order(self, pr_id: str) -> None:
        """
        Mark production order as completed.

        Args:
            pr_id: Production order ID

        Raises:
            ManufacturingError: If PR not found
        """
        if pr_id not in self.production_orders:
            raise ManufacturingError(f"Production order {pr_id} not found")

        pr = self.production_orders[pr_id]

        if pr_id in self.work_in_progress:
            pr.quantity_completed = self.work_in_progress[pr_id].get(
                pr.finished_sku,
                Decimal("0.00"),
            )

        pr.status = PRStatus.COMPLETED

    def get_work_in_progress(self, pr_id: str) -> dict[str, Decimal]:
        """
        Get WIP status for a production order.

        Args:
            pr_id: Production order ID

        Returns:
            Map of SKU to WIP quantity

        Raises:
            ManufacturingError: If PR not found
        """
        if pr_id not in self.production_orders:
            raise ManufacturingError(f"Production order {pr_id} not found")

        return self.work_in_progress.get(pr_id, {})

    def calculate_yield(
        self,
        pr_id: str,
    ) -> Decimal:
        """
        Calculate production yield (completed/started percentage).

        Args:
            pr_id: Production order ID

        Returns:
            Yield percentage (0-100)

        Raises:
            ManufacturingError: If PR not found
        """
        if pr_id not in self.production_orders:
            raise ManufacturingError(f"Production order {pr_id} not found")

        pr = self.production_orders[pr_id]

        if pr.quantity_ordered == Decimal("0.00"):
            return Decimal("0.00")

        return (pr.quantity_completed / pr.quantity_ordered) * Decimal("100.00")

    def _get_active_bom(self, finished_sku: str) -> BOM | None:
        """Get the active BOM for a finished product."""
        for bom in self.boms.values():
            if bom.finished_sku == finished_sku and bom.is_active:
                return bom
        return None

    def _get_routing(self, finished_sku: str) -> Routing | None:
        """Get routing for a finished product."""
        for routing in self.routings.values():
            if routing.product_sku == finished_sku:
                return routing
        return None

    def create_routing(
        self,
        routing_id: str,
        product_sku: str,
        operations: list[dict[str, any]],
    ) -> Routing:
        """
        Create a production routing.

        Args:
            routing_id: Unique routing identifier
            product_sku: Product SKU
            operations: List of {work_center, sequence, run_time, setup_time}

        Returns:
            Created Routing
        """
        routing = Routing(routing_id, product_sku, operations)
        self.routings[routing_id] = routing
        return routing
