"""
Smart grid features and advanced demand management.

Provides demand response automation, distributed energy resource management,
virtual power plant aggregation, vehicle-to-grid (V2G), microgrid control,
and self-healing network reconfiguration.
"""

from dataclasses import dataclass, field

from thomas.marketplace.energy._types import DemandResponse, Grid, Load, StorageUnit


@dataclass
class VirtualPowerPlant:
    """Virtual power plant aggregating distributed energy resources."""

    vpp_id: str
    name: str
    distributed_generators: dict[str, float] = field(default_factory=dict)  # id -> capacity_mw
    storage_units: dict[str, StorageUnit] = field(default_factory=dict)  # id -> unit
    controllable_loads: dict[str, Load] = field(default_factory=dict)  # id -> load
    demand_response_programs: dict[str, float] = field(default_factory=dict)  # id -> capacity_mw

    def get_available_capacity(self) -> float:
        """Get total available generation capacity."""
        gen_capacity = sum(self.distributed_generators.values())
        storage_capacity = sum(u.power_rating_mw for u in self.storage_units.values())
        return gen_capacity + storage_capacity

    def get_available_power(self) -> float:
        """Get available power considering current state."""
        gen_power = sum(self.distributed_generators.values())

        # Storage contribution (only discharge available)
        storage_power = 0.0
        for unit in self.storage_units.values():
            if unit.soc > unit.min_soc:
                available_energy = unit.soc * unit.capacity_mwh * (unit.max_soc - unit.min_soc)
                storage_power += min(unit.power_rating_mw, available_energy)

        return gen_power + storage_power

    def dispatch_to_grid(self, dispatch_power_mw: float) -> float:
        """
        Dispatch power from VPP to grid.

        Args:
            dispatch_power_mw: Required dispatch in MW

        Returns:
            Actual dispatched power
        """
        available = self.get_available_power()
        actual_dispatch = min(dispatch_power_mw, available)

        return actual_dispatch

    def participate_in_market(
        self,
        market_price: float,
    ) -> tuple[float, float]:
        """
        Determine VPP market participation.

        Args:
            market_price: Current market price $/MWh

        Returns:
            Tuple of (supply_mw, bid_price)
        """
        # Generate: marginal cost estimated at 30-40 $/MWh
        gen_marginal_cost = 35.0
        gen_bid = sum(self.distributed_generators.values()) if gen_marginal_cost < market_price else 0.0

        # Storage charging/discharging strategy
        storage_bid = 0.0
        if market_price > 50:
            # High price: discharge storage
            for unit in self.storage_units.values():
                if unit.soc > unit.min_soc:
                    storage_bid += unit.power_rating_mw

        elif market_price < 30:
            # Low price: charge storage
            for unit in self.storage_units.values():
                if unit.soc < unit.max_soc:
                    storage_bid -= unit.power_rating_mw

        total_supply = gen_bid + storage_bid
        effective_bid = gen_marginal_cost

        return total_supply, effective_bid

    def activate_demand_response(self, capacity_mw: float) -> float:
        """
        Activate demand response from controllable loads.

        Args:
            capacity_mw: Amount of load to shed

        Returns:
            Actual load shed
        """
        shedding = 0.0

        for load_id, load in self.controllable_loads.items():
            if shedding >= capacity_mw:
                break

            available_shed = load.active_power * load.emergency_shed_capability
            amount = min(available_shed, capacity_mw - shedding)
            shedding += amount

        return shedding


@dataclass
class DemandResponseController:
    """Automated demand response control system."""

    programs: dict[str, DemandResponse] = field(default_factory=dict)
    active_programs: dict[str, bool] = field(default_factory=dict)

    def register_program(self, program: DemandResponse) -> None:
        """Register a demand response program."""
        self.programs[program.program_id] = program
        self.active_programs[program.program_id] = False

    def should_activate_program(
        self,
        program_id: str,
        frequency: float,
        price: float,
        price_threshold: float = 100.0,
    ) -> bool:
        """
        Determine if a DR program should be activated.

        Args:
            program_id: Program identifier
            frequency: Current grid frequency
            price: Current energy price $/MWh
            price_threshold: Price threshold for activation

        Returns:
            Whether to activate
        """
        if program_id not in self.programs:
            return False

        # Activate based on frequency or price
        freq_trigger = abs(frequency - 60.0) > 0.2
        price_trigger = price > price_threshold

        return freq_trigger or price_trigger

    def activate_programs(self, program_ids: list[str]) -> float:
        """
        Activate specified demand response programs.

        Args:
            program_ids: List of program IDs to activate

        Returns:
            Total load shedding (MW)
        """
        total_shed = 0.0

        for prog_id in program_ids:
            if prog_id in self.programs:
                program = self.programs[prog_id]
                self.active_programs[prog_id] = True
                total_shed += program.effective_shed_capacity()

        return total_shed

    def deactivate_programs(self, program_ids: list[str]) -> None:
        """Deactivate specified programs."""
        for prog_id in program_ids:
            self.active_programs[prog_id] = False

    def get_shed_capability(self) -> float:
        """Get total available load shedding capacity."""
        total = 0.0

        for program_id, program in self.programs.items():
            total += program.effective_shed_capacity()

        return total

    def estimate_activation_cost(self, shed_mw: float) -> float:
        """
        Estimate cost of activating DR programs.

        Args:
            shed_mw: Amount of load to shed

        Returns:
            Cost in dollars
        """
        # Sort programs by cost
        programs_by_cost = sorted(
            self.programs.values(),
            key=lambda p: p.shed_price_per_mwh,
        )

        total_cost = 0.0
        remaining = shed_mw

        for program in programs_by_cost:
            if remaining <= 0:
                break

            capacity = program.effective_shed_capacity()
            amount = min(capacity, remaining)
            total_cost += amount * program.shed_price_per_mwh

            remaining -= amount

        return total_cost


@dataclass
class V2GManager:
    """Vehicle-to-Grid (V2G) energy management."""

    @dataclass
    class ElectricVehicle:
        vehicle_id: str
        battery_capacity_kwh: float
        charging_power_kw: float
        discharging_power_kw: float
        current_soc: float = 0.5
        available_for_v2g: bool = True

    vehicles: dict[str, ElectricVehicle] = field(default_factory=dict)

    def register_vehicle(self, vehicle: ElectricVehicle) -> None:
        """Register an electric vehicle."""
        self.vehicles[vehicle.vehicle_id] = vehicle

    def get_available_v2g_capacity(self) -> float:
        """Get available V2G discharge capacity (MW)."""
        total_kw = 0.0

        for vehicle in self.vehicles.values():
            if vehicle.available_for_v2g and vehicle.current_soc > 0.2:
                total_kw += vehicle.discharging_power_kw

        return total_kw / 1000.0  # Convert to MW

    def get_available_v2g_energy(self) -> float:
        """Get available V2G energy (MWh)."""
        total_kwh = 0.0

        for vehicle in self.vehicles.values():
            if vehicle.available_for_v2g:
                available_kwh = (vehicle.current_soc - 0.2) * vehicle.battery_capacity_kwh
                total_kwh += available_kwh

        return total_kwh / 1000.0  # Convert to MWh

    def dispatch_v2g(self, power_mw: float, duration_hours: float) -> float:
        """
        Dispatch V2G power.

        Args:
            power_mw: Requested power in MW
            duration_hours: Duration in hours

        Returns:
            Actual power dispatched
        """
        power_kw = power_mw * 1000
        dispatched_kw = 0.0

        for vehicle in self.vehicles.values():
            if dispatched_kw >= power_kw:
                break

            if vehicle.available_for_v2g and vehicle.current_soc > 0.2:
                available_kw = min(
                    vehicle.discharging_power_kw,
                    power_kw - dispatched_kw,
                )

                # Check energy constraint
                available_energy_kwh = (vehicle.current_soc - 0.2) * vehicle.battery_capacity_kwh
                max_energy_kw = available_energy_kwh / duration_hours if duration_hours > 0 else 0.0

                actual_kw = min(available_kw, max_energy_kw)

                # Update vehicle SOC
                energy_discharged = actual_kw * duration_hours
                vehicle.current_soc -= energy_discharged / vehicle.battery_capacity_kwh

                dispatched_kw += actual_kw

        return dispatched_kw / 1000.0  # Convert back to MW

    def charge_vehicles(self, available_power_mw: float, duration_hours: float) -> float:
        """
        Charge vehicles using available power.

        Args:
            available_power_mw: Available charging power in MW
            duration_hours: Duration in hours

        Returns:
            Actual power used for charging
        """
        power_kw = available_power_mw * 1000
        charged_kw = 0.0

        for vehicle in self.vehicles.values():
            if charged_kw >= power_kw:
                break

            if vehicle.current_soc < 0.9:
                available_kw = min(
                    vehicle.charging_power_kw,
                    power_kw - charged_kw,
                )

                # Check capacity constraint
                space_kwh = (0.9 - vehicle.current_soc) * vehicle.battery_capacity_kwh
                max_charge_kw = space_kwh / duration_hours if duration_hours > 0 else 0.0

                actual_kw = min(available_kw, max_charge_kw)

                # Update vehicle SOC
                energy_charged = actual_kw * duration_hours
                vehicle.current_soc += energy_charged / vehicle.battery_capacity_kwh

                charged_kw += actual_kw

        return charged_kw / 1000.0  # Convert back to MW


@dataclass
class MicrogridController:
    """Microgrid operation and control."""

    microgrid_id: str
    vpp: VirtualPowerPlant = field(default_factory=lambda: VirtualPowerPlant("vpp_1", "VPP"))
    dr_controller: DemandResponseController = field(default_factory=DemandResponseController)
    v2g_manager: V2GManager = field(default_factory=V2GManager)

    def operate_in_grid_mode(self, grid_power_mw: float) -> dict[str, float]:
        """
        Operate microgrid connected to main grid.

        Args:
            grid_power_mw: Power exchange with grid (+ import, - export)

        Returns:
            Dispatch decisions
        """
        return {
            "grid_exchange_mw": grid_power_mw,
            "vpp_dispatch_mw": 0.0,
            "storage_dispatch_mw": 0.0,
            "dr_activation_mw": 0.0,
        }

    def operate_in_island_mode(self, load_mw: float, reserve_margin: float = 0.1) -> dict[str, float]:
        """
        Operate microgrid in island mode (disconnected from grid).

        Args:
            load_mw: Current load in MW
            reserve_margin: Required reserve margin (fraction)

        Returns:
            Dispatch decisions
        """
        required_capacity = load_mw * (1.0 + reserve_margin)

        # Dispatch VPP
        vpp_dispatch = min(self.vpp.get_available_power(), required_capacity)

        # Use DR if needed
        dr_activation = 0.0
        if vpp_dispatch < load_mw:
            dr_activation = self.dr_controller.activate_programs(list(self.dr_controller.programs.keys()))

        # Use V2G if still needed
        v2g_dispatch = 0.0
        if vpp_dispatch + dr_activation < load_mw:
            v2g_dispatch = self.v2g_manager.dispatch_v2g(
                load_mw - vpp_dispatch - dr_activation,
                duration_hours=1.0,
            )

        return {
            "vpp_dispatch_mw": vpp_dispatch,
            "dr_activation_mw": dr_activation,
            "v2g_dispatch_mw": v2g_dispatch,
            "total_dispatch_mw": vpp_dispatch + dr_activation + v2g_dispatch,
        }

    def optimize_energy_cost(
        self,
        load_profile: list[float],
        price_forecast: list[float],
        horizon_hours: int = 24,
    ) -> dict[str, list[float]]:
        """
        Optimize energy costs over forecast horizon.

        Args:
            load_profile: Hourly load forecast (MW)
            price_forecast: Hourly price forecast ($/MWh)
            horizon_hours: Optimization horizon (hours)

        Returns:
            Dispatch schedule for each resource
        """
        dispatch_schedule = {
            "vpp": [0.0] * horizon_hours,
            "storage_charge": [0.0] * horizon_hours,
            "storage_discharge": [0.0] * horizon_hours,
            "dr": [0.0] * horizon_hours,
            "v2g": [0.0] * horizon_hours,
        }

        for hour in range(horizon_hours):
            price = price_forecast[hour] if hour < len(price_forecast) else price_forecast[-1]
            load = load_profile[hour] if hour < len(load_profile) else load_profile[-1]

            if price < 30:  # Low price hour -> charge storage
                dispatch_schedule["storage_charge"][hour] = self.vpp.get_available_capacity() * 0.3

            elif price > 80:  # High price hour -> discharge storage
                dispatch_schedule["storage_discharge"][hour] = self.vpp.get_available_capacity() * 0.2
                dispatch_schedule["dr"][hour] = self.dr_controller.get_shed_capability() * 0.5

            else:  # Normal -> dispatch to meet load
                dispatch_schedule["vpp"][hour] = min(load, self.vpp.get_available_power())

        return dispatch_schedule


@dataclass
class NetworkReconfiguration:
    """Self-healing network reconfiguration."""

    def find_alternate_paths(
        self,
        grid: Grid,
        failed_line: tuple[int, int],
    ) -> list[list[tuple[int, int]]]:
        """
        Find alternate paths around failed transmission line.

        Args:
            grid: Power grid
            failed_line: Failed line (from_bus, to_bus)

        Returns:
            List of alternate paths
        """
        # Simple path finding (simplified BFS)
        from_bus, to_bus = failed_line
        alternate_paths = []

        # Look for paths that bypass failed line
        visited = set()

        def find_path(current: int, target: int, path: list[tuple[int, int]]) -> list[tuple[int, int]] | None:
            if current == target:
                return path

            visited.add(current)

            for line in grid.transmission_lines:
                f, t, _, _ = line
                if f == current and t not in visited:
                    result = find_path(t, target, path + [(f, t)])
                    if result:
                        return result
                elif t == current and f not in visited:
                    result = find_path(f, target, path + [(t, f)])
                    if result:
                        return result

            return None

        path = find_path(from_bus, to_bus, [])
        if path and path != [failed_line]:
            alternate_paths.append(path)

        return alternate_paths

    def estimate_reconfiguration_time(self, required_switches: int) -> float:
        """
        Estimate time to reconfigure network.

        Args:
            required_switches: Number of switch operations required

        Returns:
            Time in seconds
        """
        # Assume 2 seconds per switch operation
        switching_time = required_switches * 2.0

        # Add time for protection coordination
        protection_time = 0.5

        return switching_time + protection_time

    def can_restore_service(self, alternate_paths: list[list[tuple[int, int]]]) -> bool:
        """
        Check if service can be restored using alternate paths.

        Args:
            alternate_paths: Available alternate routing paths

        Returns:
            Whether service restoration is possible
        """
        return len(alternate_paths) > 0
