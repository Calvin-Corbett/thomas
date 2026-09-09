"""
Warehouse operations and optimization module.

Provides slotting optimization, pick path optimization, wave planning,
dock scheduling, put-away strategies, warehouse layout simulation,
and labor planning.
"""

import math
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from thomas.supply_chain._types import SKU, InventoryLevel, Warehouse


@dataclass
class SlotAssignment:
    """Warehouse slot/bin assignment for a SKU."""

    sku: SKU
    slot_id: str
    location: tuple[int, int, int]  # aisle, rack, level
    zone: str  # A, B, C, etc.
    distance_from_dispatch: Decimal
    velocity_rank: int
    affinity_group: str | None = None
    actual_stock: Decimal = Decimal("0")


@dataclass
class PickPath:
    """Optimized pick path for order fulfillment."""

    pick_path_id: str
    order_ids: list[str]
    slots: list[SlotAssignment]
    total_distance: Decimal
    estimated_time_minutes: int
    picker_id: str | None = None
    optimization_method: str = "s_shape"  # s_shape, largest_gap, combined


@dataclass
class Wave:
    """Picking wave for order consolidation."""

    wave_id: str
    wave_date: datetime
    pick_paths: list[PickPath]
    order_count: int
    line_count: int
    total_units: Decimal
    status: str = "planned"  # planned, released, in_progress, completed


@dataclass
class DockSchedule:
    """Dock door schedule."""

    dock_door: str
    scheduled_date: datetime
    scheduled_time: str
    shipment_id: UUID
    type: str  # "inbound" or "outbound"
    duration_minutes: int = 60
    truck_arrival: datetime | None = None
    door_open_time: datetime | None = None
    completion_time: datetime | None = None
    status: str = "scheduled"


@dataclass
class PutAwayInstruction:
    """Put-away instruction for receiving."""

    instruction_id: str
    sku: SKU
    quantity: Decimal
    source_location: str  # Receiving area
    target_slot: str
    put_away_date: datetime
    completed_date: datetime | None = None
    status: str = "pending"  # pending, in_progress, completed


@dataclass
class StorageZone:
    """Warehouse storage zone."""

    zone_id: str
    zone_name: str
    aisle_count: int
    rack_per_aisle: int
    levels_per_rack: int
    slot_capacity_units: Decimal
    current_utilization: Decimal
    characteristics: str  # "fast_moving", "slow_moving", "oversize", etc.


@dataclass
class LaborPlan:
    """Warehouse labor plan."""

    date: datetime
    shift: str  # "morning", "afternoon", "night"
    required_pickers: int
    required_packers: int
    required_receiving: int
    required_dock_staff: int
    peak_hour: int
    expected_orders: int
    estimated_lines: int


class WarehouseOptimizer:
    """
    Comprehensive warehouse operations and optimization system.

    Handles slotting, pick path optimization, wave planning, dock scheduling,
    put-away strategies, and labor planning.
    """

    def __init__(self) -> None:
        """Initialize warehouse optimizer."""
        pass

    def velocity_based_slotting(
        self,
        inventory_levels: list[InventoryLevel],
        annual_usage: dict[SKU, Decimal],
        warehouse: Warehouse,
        zones: list[StorageZone] | None = None,
    ) -> list[SlotAssignment]:
        """
        Assign slots based on product velocity (ABC classification).

        Args:
            inventory_levels: Current inventory levels
            annual_usage: Annual usage by SKU
            warehouse: Warehouse configuration
            zones: Storage zones (optional)

        Returns:
            List of slot assignments
        """
        if not zones:
            # Create default zones
            zones = [
                StorageZone("A", "Fast Moving", 5, 8, 4, Decimal("100"), Decimal("0"), "fast_moving"),
                StorageZone("B", "Medium Moving", 10, 8, 4, Decimal("50"), Decimal("0"), "medium_moving"),
                StorageZone("C", "Slow Moving", 15, 8, 4, Decimal("20"), Decimal("0"), "slow_moving"),
            ]

        # Rank SKUs by velocity
        sku_velocities = []
        for level in inventory_levels:
            velocity = annual_usage.get(level.sku, Decimal("0"))
            sku_velocities.append((level.sku, velocity))

        sku_velocities.sort(key=lambda x: x[1], reverse=True)

        assignments = []
        dispatch_point = (0, 0, 0)  # Assumed dispatch location

        for rank, (sku, velocity) in enumerate(sku_velocities):
            # Assign to zone based on velocity rank
            zone_index = min(rank // (len(sku_velocities) // len(zones) + 1), len(zones) - 1)
            zone = zones[zone_index]

            # Calculate slot location within zone
            slots_per_zone = zone.aisle_count * zone.rack_per_aisle * zone.levels_per_rack
            slot_index = rank % slots_per_zone
            aisle = (slot_index // (zone.rack_per_aisle * zone.levels_per_rack)) % zone.aisle_count
            rack = (slot_index // zone.levels_per_rack) % zone.rack_per_aisle
            level = slot_index % zone.levels_per_rack

            # Calculate distance from dispatch
            distance = Decimal(
                str(
                    math.sqrt(
                        float(
                            (aisle - dispatch_point[0]) ** 2
                            + (rack - dispatch_point[1]) ** 2
                            + (level - dispatch_point[2]) ** 2
                        )
                    )
                )
            )

            current_level = next((l for l in inventory_levels if l.sku == sku), None)
            actual_stock = current_level.quantity_on_hand if current_level else Decimal("0")

            assignment = SlotAssignment(
                sku=sku,
                slot_id=f"{zone.zone_id}-A{aisle}-R{rack}-L{level}",
                location=(int(aisle), int(rack), int(level)),
                zone=zone.zone_id,
                distance_from_dispatch=distance,
                velocity_rank=rank,
                actual_stock=actual_stock,
            )
            assignments.append(assignment)

        return assignments

    def affinity_based_slotting(
        self, inventory_levels: list[InventoryLevel], co_purchase_matrix: dict[str, list[str]], warehouse: Warehouse
    ) -> list[SlotAssignment]:
        """
        Assign slots based on product affinity (items purchased together).

        Args:
            inventory_levels: Current inventory levels
            co_purchase_matrix: Dictionary of SKU -> list of frequently co-purchased SKUs
            warehouse: Warehouse configuration

        Returns:
            List of slot assignments with affinity grouping
        """
        assignments = []
        placed_skus = set()
        affinity_groups = {}
        group_counter = 1

        for sku_str, co_purchases in co_purchase_matrix.items():
            if sku_str in placed_skus:
                continue

            # Create affinity group
            group_id = f"GROUP_{group_counter}"
            group_skus = [sku_str] + [cp for cp in co_purchases if cp not in placed_skus]
            affinity_groups[group_id] = group_skus

            # Assign slots close together for group
            base_aisle = (group_counter % 10) * 2
            for seq, sku_code in enumerate(group_skus):
                current_level = next((l for l in inventory_levels if l.sku.code == sku_code), None)
                if current_level:
                    assignment = SlotAssignment(
                        sku=current_level.sku,
                        slot_id=f"G{group_counter}-A{base_aisle}-R{seq}-L0",
                        location=(int(base_aisle), seq, 0),
                        zone="A",
                        distance_from_dispatch=Decimal(base_aisle) + Decimal(seq),
                        velocity_rank=seq,
                        affinity_group=group_id,
                        actual_stock=current_level.quantity_on_hand,
                    )
                    assignments.append(assignment)
                    placed_skus.add(sku_code)

            group_counter += 1

        return assignments

    def s_shape_pick_path(self, assignments: list[SlotAssignment]) -> PickPath:
        """
        Optimize pick path using S-shape (serpentine) method.

        Args:
            assignments: Slot assignments to pick

        Returns:
            PickPath with optimized sequence
        """
        if not assignments:
            return PickPath("", [], [], Decimal("0"), 0)

        # Group by aisle
        by_aisle = {}
        for assignment in assignments:
            aisle = assignment.location[0]
            if aisle not in by_aisle:
                by_aisle[aisle] = []
            by_aisle[aisle].append(assignment)

        # Sort aisles
        sorted_aisles = sorted(by_aisle.keys())

        ordered_picks = []
        total_distance = Decimal("0")
        last_position = (0, 0, 0)

        for aisle_idx, aisle in enumerate(sorted_aisles):
            picks = by_aisle[aisle]

            # Sort by rack within aisle
            if aisle_idx % 2 == 0:
                picks.sort(key=lambda x: x.location[1])
            else:
                picks.sort(key=lambda x: x.location[1], reverse=True)

            for pick in picks:
                ordered_picks.append(pick)
                distance = Decimal(
                    str(
                        math.sqrt(
                            float(
                                (pick.location[0] - last_position[0]) ** 2
                                + (pick.location[1] - last_position[1]) ** 2
                                + (pick.location[2] - last_position[2]) ** 2
                            )
                        )
                    )
                )
                total_distance += distance
                last_position = pick.location

        # Return to dispatch
        total_distance += Decimal(
            str(math.sqrt(float(last_position[0] ** 2 + last_position[1] ** 2 + last_position[2] ** 2)))
        )

        estimated_time = int(total_distance * Decimal("1.5"))  # ~1.5 min per unit distance

        return PickPath(
            pick_path_id=f"PATH_{int(datetime.utcnow().timestamp())}",
            order_ids=[],
            slots=ordered_picks,
            total_distance=total_distance,
            estimated_time_minutes=estimated_time,
            optimization_method="s_shape",
        )

    def largest_gap_pick_path(self, assignments: list[SlotAssignment]) -> PickPath:
        """
        Optimize pick path using largest gap method.

        Args:
            assignments: Slot assignments to pick

        Returns:
            PickPath with optimized sequence
        """
        if not assignments:
            return PickPath("", [], [], Decimal("0"), 0)

        # Start from dispatch point
        ordered_picks = []
        unvisited = set(range(len(assignments)))
        current_pos = (0, 0, 0)
        total_distance = Decimal("0")

        while unvisited:
            # Find closest unvisited slot
            nearest_idx = None
            nearest_dist = float("inf")

            for idx in unvisited:
                assignment = assignments[idx]
                dist = math.sqrt(
                    (assignment.location[0] - current_pos[0]) ** 2
                    + (assignment.location[1] - current_pos[1]) ** 2
                    + (assignment.location[2] - current_pos[2]) ** 2
                )
                if dist < nearest_dist:
                    nearest_dist = dist
                    nearest_idx = idx

            if nearest_idx is not None:
                assignment = assignments[nearest_idx]
                ordered_picks.append(assignment)
                total_distance += Decimal(str(nearest_dist))
                current_pos = assignment.location
                unvisited.remove(nearest_idx)

        # Return to dispatch
        total_distance += Decimal(
            str(math.sqrt(float(current_pos[0] ** 2 + current_pos[1] ** 2 + current_pos[2] ** 2)))
        )

        estimated_time = int(total_distance * Decimal("2"))

        return PickPath(
            pick_path_id=f"PATH_{int(datetime.utcnow().timestamp())}",
            order_ids=[],
            slots=ordered_picks,
            total_distance=total_distance,
            estimated_time_minutes=estimated_time,
            optimization_method="largest_gap",
        )

    def plan_waves(
        self,
        orders: list[dict],  # {order_id, lines: [{sku, qty}]}
        target_lines_per_wave: int = 100,
        wave_date: datetime | None = None,
    ) -> list[Wave]:
        """
        Plan picking waves for order consolidation.

        Args:
            orders: List of orders to wave
            target_lines_per_wave: Target lines per wave
            wave_date: Date for waves (default today)

        Returns:
            List of planned waves
        """
        if not wave_date:
            wave_date = datetime.utcnow()

        waves = []
        current_wave_orders = []
        current_line_count = 0
        current_unit_count = Decimal("0")
        wave_counter = 1

        for order in orders:
            line_count = len(order.get("lines", []))
            unit_count = Decimal(sum(line.get("qty", 1) for line in order.get("lines", [])))

            # Check if adding this order exceeds wave target
            if current_line_count + line_count > target_lines_per_wave and current_wave_orders:
                # Create wave
                wave = Wave(
                    wave_id=f"WAVE_{wave_date.strftime('%Y%m%d')}_{wave_counter:03d}",
                    wave_date=wave_date,
                    pick_paths=[],
                    order_count=len(current_wave_orders),
                    line_count=current_line_count,
                    total_units=current_unit_count,
                )
                waves.append(wave)

                current_wave_orders = []
                current_line_count = 0
                current_unit_count = Decimal("0")
                wave_counter += 1

            current_wave_orders.append(order)
            current_line_count += line_count
            current_unit_count += unit_count

        # Add remaining orders to final wave
        if current_wave_orders:
            wave = Wave(
                wave_id=f"WAVE_{wave_date.strftime('%Y%m%d')}_{wave_counter:03d}",
                wave_date=wave_date,
                pick_paths=[],
                order_count=len(current_wave_orders),
                line_count=current_line_count,
                total_units=current_unit_count,
            )
            waves.append(wave)

        return waves

    def schedule_docks(
        self,
        inbound_shipments: list[tuple[UUID, datetime]],
        outbound_shipments: list[tuple[UUID, datetime]],
        dock_count: int = 5,
        dock_hours: tuple[int, int] = (6, 22),
    ) -> list[DockSchedule]:
        """
        Schedule inbound and outbound dock doors.

        Args:
            inbound_shipments: List of (shipment_id, arrival_estimate)
            outbound_shipments: List of (shipment_id, ship_datetime)
            dock_count: Number of dock doors
            dock_hours: (start_hour, end_hour)

        Returns:
            List of dock schedules
        """
        schedules = []
        inbound_slots = {i: [] for i in range(dock_count)}
        outbound_slots = {i: [] for i in range(dock_count)}

        # Schedule inbound
        for shipment_id, arrival in inbound_shipments:
            # Find dock with least utilization at that time
            best_dock = min(range(dock_count), key=lambda x: len(inbound_slots[x]))

            schedule = DockSchedule(
                dock_door=f"DOCK_{best_dock + 1}",
                scheduled_date=arrival.date(),
                scheduled_time=arrival.strftime("%H:%M"),
                shipment_id=shipment_id,
                type="inbound",
                duration_minutes=90,
                status="scheduled",
            )
            schedules.append(schedule)
            inbound_slots[best_dock].append(arrival)

        # Schedule outbound
        for shipment_id, ship_time in outbound_shipments:
            best_dock = min(range(dock_count), key=lambda x: len(outbound_slots[x]))

            schedule = DockSchedule(
                dock_door=f"DOCK_{best_dock + 1}",
                scheduled_date=ship_time.date(),
                scheduled_time=ship_time.strftime("%H:%M"),
                shipment_id=shipment_id,
                type="outbound",
                duration_minutes=60,
                status="scheduled",
            )
            schedules.append(schedule)
            outbound_slots[best_dock].append(ship_time)

        return sorted(schedules, key=lambda x: (x.scheduled_date, x.scheduled_time))

    def put_away_strategy(
        self, inventory_level: InventoryLevel, slot_assignment: SlotAssignment, receiving_location: str = "RECV_01"
    ) -> PutAwayInstruction:
        """
        Create put-away instruction for received goods.

        Args:
            inventory_level: Received inventory
            slot_assignment: Target slot
            receiving_location: Receiving area location

        Returns:
            PutAwayInstruction
        """
        return PutAwayInstruction(
            instruction_id=f"PA_{int(datetime.utcnow().timestamp())}",
            sku=inventory_level.sku,
            quantity=inventory_level.quantity_on_hand,
            source_location=receiving_location,
            target_slot=slot_assignment.slot_id,
            put_away_date=datetime.utcnow(),
            status="pending",
        )

    def plan_labor(
        self,
        forecasted_orders: int,
        forecasted_lines: int,
        shift: str = "morning",
        productivity_orders_per_picker: int = 20,
        productivity_lines_per_packer: int = 100,
    ) -> LaborPlan:
        """
        Plan warehouse labor requirements.

        Args:
            forecasted_orders: Expected number of orders
            forecasted_lines: Expected number of order lines
            shift: Shift name
            productivity_orders_per_picker: Orders per picker per shift
            productivity_lines_per_packer: Lines per packer per shift

        Returns:
            LaborPlan with staffing requirements
        """
        # Calculate required staff
        required_pickers = max(1, math.ceil(forecasted_orders / productivity_orders_per_picker))
        required_packers = max(1, math.ceil(forecasted_lines / productivity_lines_per_packer))
        required_receiving = max(1, math.ceil(forecasted_orders / 50))
        required_dock = max(2, math.ceil(forecasted_orders / 30))

        # Estimate peak hour (usually 10am for morning shift)
        peak_hour = 10 if shift == "morning" else (16 if shift == "afternoon" else 22)

        return LaborPlan(
            date=datetime.utcnow(),
            shift=shift,
            required_pickers=required_pickers,
            required_packers=required_packers,
            required_receiving=required_receiving,
            required_dock_staff=required_dock,
            peak_hour=peak_hour,
            expected_orders=forecasted_orders,
            estimated_lines=forecasted_lines,
        )

    def calculate_storage_utilization(
        self, warehouse: Warehouse, inventory_levels: list[InventoryLevel]
    ) -> dict[str, Decimal]:
        """
        Calculate warehouse storage utilization metrics.

        Args:
            warehouse: Warehouse
            inventory_levels: Current inventory levels

        Returns:
            Dictionary with utilization metrics
        """
        total_units = Decimal(sum(level.quantity_on_hand for level in inventory_levels))
        total_value = Decimal(sum(level.quantity_on_hand * level.unit_cost for level in inventory_levels))

        volume_utilization = (
            warehouse.current_utilization / warehouse.total_capacity * Decimal("100")
            if warehouse.total_capacity > 0
            else Decimal("0")
        )

        return {
            "total_units": total_units,
            "total_value": total_value,
            "volume_utilization_percent": volume_utilization,
            "available_capacity": warehouse.total_capacity - warehouse.current_utilization,
            "space_per_unit": (warehouse.current_utilization / total_units if total_units > 0 else Decimal("0")),
        }
