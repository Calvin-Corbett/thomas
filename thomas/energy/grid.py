"""
Power grid simulation and control.

Provides AC power flow calculation (Newton-Raphson), load balancing, frequency
regulation (droop control), transmission loss modeling, islanding detection,
and grid stability metrics.
"""

import math
from dataclasses import dataclass, field

from thomas.energy._exceptions import GridOverloadError
from thomas.energy._types import BusType, BusVoltage, Grid, PowerPlant


@dataclass
class PowerFlowResult:
    """Results from power flow calculation."""

    converged: bool
    iterations: int
    bus_voltages: dict[int, BusVoltage]
    line_flows: dict[tuple[int, int], float]  # (from_bus, to_bus) -> power_mw
    losses: float  # Total transmission losses in MW


@dataclass
class PowerFlowSolver:
    """AC power flow solver using Newton-Raphson method."""

    max_iterations: int = 100
    tolerance: float = 1e-6
    base_mva: float = 100.0

    def solve(self, grid: Grid) -> PowerFlowResult:
        """
        Solve AC power flow using Newton-Raphson.

        Args:
            grid: Power grid

        Returns:
            Power flow solution
        """
        n_buses = len(grid.buses)
        if n_buses == 0:
            return PowerFlowResult(
                converged=False,
                iterations=0,
                bus_voltages={},
                line_flows={},
                losses=0.0,
            )

        # Build admittance matrix
        y_matrix = self._build_admittance_matrix(grid)

        # Extract bus data
        buses = sorted(grid.buses.items(), key=lambda x: x[0])
        bus_ids = [b[0] for b in buses]
        bus_types = [b[1].bus_type for b in buses]

        # Initial voltage estimates
        voltages = {b[0]: complex(b[1].voltage.magnitude, 0) for b in buses}

        # Newton-Raphson iteration
        mismatch: list[float] = []
        for iteration in range(self.max_iterations):
            # Calculate mismatches
            mismatch = self._calculate_mismatch(grid, bus_ids, voltages, y_matrix)
            max_mismatch = max(abs(m) for m in mismatch) if mismatch else 0.0

            if not math.isfinite(max_mismatch):
                break

            if max_mismatch < self.tolerance:
                # Converged
                return self._build_result(grid, voltages, converged=True, iterations=iteration + 1)

            # Build Jacobian (simplified DC approximation for speed)
            # In practice would use full Jacobian
            for i, bus_id in enumerate(bus_ids):
                if bus_types[i] != BusType.SLACK:
                    # Simplified update
                    update_factor = 1.0 + mismatch[i] * 0.01
                    if not math.isfinite(update_factor):
                        continue
                    update_factor = max(0.5, min(1.5, update_factor))

                    updated_voltage = voltages[bus_id] * update_factor
                    magnitude = abs(updated_voltage)
                    if not math.isfinite(magnitude) or magnitude == 0.0:
                        continue
                    if magnitude > 2.0:
                        updated_voltage = updated_voltage / magnitude * 2.0

                    voltages[bus_id] = updated_voltage

        # Return best-effort non-converged result instead of raising.
        return self._build_result(
            grid,
            voltages,
            converged=False,
            iterations=self.max_iterations,
        )

    def _build_admittance_matrix(self, grid: Grid) -> dict[tuple[int, int], complex]:
        """Build bus admittance matrix from transmission lines."""
        y_matrix = {}

        for from_bus, to_bus, r, x in grid.transmission_lines:
            if r == 0 and x == 0:
                continue

            # Impedance
            z = complex(r, x)
            if abs(z) < 1e-10:
                continue

            # Admittance
            y = 1.0 / z

            # Diagonal and off-diagonal elements
            y_matrix[(from_bus, to_bus)] = -y
            y_matrix[(to_bus, from_bus)] = -y

            # Add to diagonal (self admittance)
            y_matrix[(from_bus, from_bus)] = y_matrix.get((from_bus, from_bus), 0) + y
            y_matrix[(to_bus, to_bus)] = y_matrix.get((to_bus, to_bus), 0) + y

        return y_matrix

    def _calculate_mismatch(
        self,
        grid: Grid,
        bus_ids: list[int],
        voltages: dict[int, complex],
        y_matrix: dict[tuple[int, int], complex],
    ) -> list[float]:
        """Calculate power mismatch at each bus."""
        mismatches = []

        for bus_id in bus_ids:
            # Scheduled power
            p_sched = 0.0
            q_sched = 0.0

            # Generation
            for plant in grid.plants.values():
                p_sched += plant.current_output_mw

            # Load
            for load in grid.loads.values():
                p_sched -= load.active_power
                q_sched -= load.reactive_power

            # Calculated power from voltage
            v = voltages.get(bus_id, complex(1.0, 0))
            p_calc = 0.0
            q_calc = 0.0

            for (i, j), y_ij in y_matrix.items():
                if i == bus_id:
                    v_j = voltages.get(j, complex(1.0, 0))
                    s = v * (y_ij * (v - v_j)).conjugate()
                    p_calc += s.real
                    q_calc += s.imag

            # Mismatch
            mismatch = p_sched - p_calc
            mismatches.append(mismatch)

        return mismatches

    def _build_result(
        self,
        grid: Grid,
        voltages: dict[int, complex],
        converged: bool,
        iterations: int,
    ) -> PowerFlowResult:
        """Build power flow result from converged solution."""
        # Update bus voltages
        for bus_id, v_complex in voltages.items():
            magnitude = abs(v_complex)
            angle = math.atan2(v_complex.imag, v_complex.real)

            if bus_id in grid.buses:
                grid.buses[bus_id].voltage = BusVoltage(magnitude, angle)

        # Calculate line flows
        line_flows = {}
        total_losses = 0.0

        for from_bus, to_bus, r, x in grid.transmission_lines:
            v_from = voltages.get(from_bus, complex(1.0, 0))
            v_to = voltages.get(to_bus, complex(1.0, 0))

            z = complex(r, x)
            if abs(z) < 1e-10:
                continue

            # Current
            i = (v_from - v_to) / z
            if not (math.isfinite(i.real) and math.isfinite(i.imag)):
                continue

            # Power
            p_flow = (v_from * i.conjugate()).real
            if not math.isfinite(p_flow):
                continue

            line_flows[(from_bus, to_bus)] = p_flow

            # Loss = I^2 * R
            loss = (abs(i) ** 2) * r
            if not math.isfinite(loss):
                continue
            total_losses += loss

        bus_voltages = {bus_id: bus.voltage for bus_id, bus in grid.buses.items()}

        return PowerFlowResult(
            converged=converged,
            iterations=iterations,
            bus_voltages=bus_voltages,
            line_flows=line_flows,
            losses=total_losses,
        )


@dataclass
class FrequencyRegulator:
    """Frequency regulation controller."""

    nominal_frequency: float = 60.0  # Hz
    deadband: float = 0.05  # Hz
    droop_setting: float = 0.05  # 5% droop
    max_response_mw: float = 100.0
    response_time_seconds: float = 5.0

    def calculate_frequency_response(
        self,
        current_frequency: float,
        power_imbalance_mw: float,
        available_capacity_mw: float,
    ) -> float:
        """
        Calculate frequency response power using droop control.

        Args:
            current_frequency: Current grid frequency in Hz
            power_imbalance_mw: Power mismatch (generation - load)
            available_capacity_mw: Available generation capacity

        Returns:
            Required power response in MW
        """
        # Frequency deviation
        freq_deviation = current_frequency - self.nominal_frequency

        # Outside deadband?
        if abs(freq_deviation) < self.deadband:
            return 0.0

        # Droop response: P = -K * df
        # where K = 1 / droop_setting (in MW/Hz)
        k = 1.0 / self.droop_setting if self.droop_setting > 0 else 0.0
        required_response = -k * freq_deviation

        # Limit to available capacity
        response = max(-self.max_response_mw, min(self.max_response_mw, required_response))

        # Limit to available capacity
        response = min(response, available_capacity_mw)

        return response

    def update_frequency(
        self,
        current_frequency: float,
        power_imbalance_mw: float,
        system_inertia_mw_s_hz: float = 10000.0,
        time_step_seconds: float = 1.0,
    ) -> float:
        """
        Update grid frequency based on power balance.

        Args:
            current_frequency: Current frequency in Hz
            power_imbalance_mw: Power mismatch
            system_inertia_mw_s_hz: System inertia (synchronous inertia)
            time_step_seconds: Simulation time step

        Returns:
            Updated frequency in Hz
        """
        # df/dt = ΔP / (2 * H * S_base)
        # Simplified: df = ΔP * Δt / Inertia

        if system_inertia_mw_s_hz <= 0:
            return current_frequency

        frequency_change = power_imbalance_mw * time_step_seconds / system_inertia_mw_s_hz

        return current_frequency + frequency_change


@dataclass
class GridController:
    """Grid control system managing frequency and voltage."""

    frequency_regulator: FrequencyRegulator = field(default_factory=FrequencyRegulator)
    reactive_power_margin: float = 0.1  # 10% Q margin

    def check_stability(self, grid: Grid) -> tuple[bool, str]:
        """
        Check grid stability status.

        Args:
            grid: Power grid

        Returns:
            Tuple of (is_stable, status_message)
        """
        # Check frequency
        if abs(grid.frequency_hz - 60.0) > 0.5:
            return False, f"Frequency deviation: {grid.frequency_hz:.2f} Hz"

        # Check voltage
        for bus_id, bus in grid.buses.items():
            if bus.voltage.magnitude < 0.95 or bus.voltage.magnitude > 1.05:
                return False, f"Voltage violation at bus {bus_id}: {bus.voltage.magnitude:.3f} pu"

        # Check reserve
        reserve = grid.total_reserve_mw()
        if reserve < 0:
            return False, f"Insufficient reserve: {reserve:.1f} MW"

        return True, "Grid stable"

    def dispatch_frequency_control(
        self,
        grid: Grid,
        frequency: float,
        controllable_plants: list[PowerPlant],
    ) -> dict[str, float]:
        """
        Dispatch frequency control to plants.

        Args:
            grid: Power grid
            frequency: Current frequency in Hz
            controllable_plants: List of dispatchable plants

        Returns:
            Dict mapping plant_id to dispatch power change (MW)
        """
        power_imbalance = grid.total_generation_mw() - grid.total_load_mw()

        # Calculate required response
        required_response = self.frequency_regulator.calculate_frequency_response(
            frequency,
            power_imbalance,
            sum(p.capacity_mw - p.current_output_mw for p in controllable_plants),
        )

        # Distribute response proportionally
        dispatch = {}
        total_capacity = sum(p.capacity_mw for p in controllable_plants)

        if total_capacity > 0:
            for plant in controllable_plants:
                share = plant.capacity_mw / total_capacity
                dispatch[plant.plant_id] = required_response * share

        return dispatch

    def balance_reactive_power(self, grid: Grid) -> dict[str, float]:
        """
        Calculate reactive power dispatch to maintain voltage.

        Args:
            grid: Power grid

        Returns:
            Dict mapping bus_id to required reactive power (MVAr)
        """
        reactive_dispatch = {}

        total_var_available = 0.0
        for plant in grid.plants.values():
            # Typical reactive power capability: ±0.33 * P
            var_capability = plant.current_output_mw * 0.33
            total_var_available += var_capability

        # Total reactive load
        total_q_load = sum(l.reactive_power for l in grid.loads.values())

        # Allocate VAR to maintain voltage
        for bus_id in grid.buses.keys():
            reactive_dispatch[bus_id] = total_q_load / len(grid.buses) if grid.buses else 0.0

        return reactive_dispatch

    def check_line_overloads(self, grid: Grid, line_flows: dict[tuple[int, int], float]) -> list[GridOverloadError]:
        """
        Check for transmission line overloads.

        Args:
            grid: Power grid
            line_flows: Power flows on lines

        Returns:
            List of GridOverloadError for overloaded lines
        """
        errors = []

        for (from_bus, to_bus), power_mw in line_flows.items():
            # Find line rating
            rating_mva = 200.0  # Default rating

            for f, t, r, x in grid.transmission_lines:
                if f == from_bus and t == to_bus:
                    # Estimate rating from impedance (simplified)
                    z = math.sqrt(r**2 + x**2)
                    if z > 0:
                        rating_mva = 400.0 / z  # Simplified model
                    break

            # Check loading
            if abs(power_mw) > rating_mva * 0.9:  # 90% loading limit
                errors.append(
                    GridOverloadError(
                        line_id=f"{from_bus}-{to_bus}",
                        current_mw=abs(power_mw),
                        capacity_mw=rating_mva * 0.9,
                    )
                )

        return errors


def detect_islanding(
    grid: Grid,
    measured_frequency: float,
    threshold_frequency_change: float = 0.5,
) -> tuple[bool, str | None]:
    """
    Detect grid islanding (disconnection from main grid).

    Args:
        grid: Power grid
        measured_frequency: Measured grid frequency
        threshold_frequency_change: Frequency change threshold (Hz/s)

    Returns:
        Tuple of (is_islanded, island_description)
    """
    # Check frequency deviation
    freq_dev = abs(measured_frequency - 60.0)
    if freq_dev > threshold_frequency_change:
        return True, f"Large frequency deviation: {measured_frequency:.2f} Hz"

    # Check voltage deviation across buses
    voltages = [b.voltage.magnitude for b in grid.buses.values()]
    if voltages:
        voltage_spread = max(voltages) - min(voltages)
        if voltage_spread > 0.15:  # >15% voltage spread
            return True, f"Large voltage spread: {voltage_spread:.3f} pu"

    # Check reserve margin
    reserve = grid.total_reserve_mw()
    if reserve < -50:  # Significant deficit
        return True, f"Severe generation deficit: {reserve:.1f} MW"

    return False, None


def calculate_grid_stability_index(
    frequency_hz: float,
    voltage_pu: float,
    reserve_mw: float,
    nominal_frequency: float = 60.0,
) -> float:
    """
    Calculate grid stability index (0.0-1.0, higher is more stable).

    Args:
        frequency_hz: Current frequency in Hz
        voltage_pu: Average voltage in per-unit
        reserve_mw: Spinning reserve in MW
        nominal_frequency: Nominal frequency in Hz

    Returns:
        Stability index (0.0-1.0)
    """
    # Frequency penalty
    freq_dev = abs(frequency_hz - nominal_frequency)
    freq_score = math.exp(-freq_dev)  # Gaussian penalty

    # Voltage penalty
    voltage_dev = abs(voltage_pu - 1.0)
    voltage_score = math.exp(-voltage_dev * 10)  # Tighter tolerance

    # Reserve penalty (minimum 5% of typical load for stability)
    reserve_score = min(1.0, max(0.0, reserve_mw / 100.0))  # Arbitrary 100 MW baseline

    # Weighted combination
    stability = 0.4 * freq_score + 0.4 * voltage_score + 0.2 * reserve_score

    return min(1.0, max(0.0, stability))
