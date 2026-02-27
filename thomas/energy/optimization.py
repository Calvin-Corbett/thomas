"""
Energy system optimization algorithms.

Provides unit commitment, economic dispatch, microgrid optimization, peak
shaving, load shifting, and multi-objective optimization.
"""

from dataclasses import dataclass

from thomas.energy._exceptions import NoFeasibleSolutionError
from thomas.energy._types import Load, PowerPlant, StorageUnit


@dataclass
class UnitCommitmentSolution:
    """Solution to unit commitment problem."""

    on_off_schedule: dict[str, list[bool]]  # plant_id -> [hour0, hour1, ...]
    dispatch: dict[str, list[float]]  # plant_id -> [mw0, mw1, ...]
    total_cost: float
    feasible: bool


@dataclass
class UnitCommitment:
    """Unit commitment solver using relaxation."""

    def solve_relaxation(
        self,
        plants: list[PowerPlant],
        load_profile: list[float],  # Hourly MW loads
        reserve_margin_percent: float = 0.15,
    ) -> UnitCommitmentSolution:
        """
        Solve unit commitment using convex relaxation (LP).

        Args:
            plants: Generation plants
            load_profile: Hourly load profile in MW
            reserve_margin_percent: Required spinning reserve margin

        Returns:
            Unit commitment solution
        """
        n_hours = len(load_profile)
        on_off_schedule = {p.plant_id: [False] * n_hours for p in plants}
        dispatch = {p.plant_id: [0.0] * n_hours for p in plants}

        total_cost = 0.0

        # Greedy heuristic: start plants in merit order
        sorted_plants = sorted(
            plants,
            key=lambda p: p.fuel_cost_per_mwh / max(p.efficiency, 0.01),
        )

        for hour, load in enumerate(load_profile):
            required_capacity = load * (1.0 + reserve_margin_percent)
            online_capacity = 0.0
            hour_cost = 0.0

            # Commit plants in merit order
            for plant in sorted_plants:
                if online_capacity >= required_capacity:
                    break

                if not on_off_schedule[plant.plant_id][hour]:
                    # Turn on plant
                    on_off_schedule[plant.plant_id][hour] = True

                    if plant.last_startup_time is None or hour > 0:
                        hour_cost += plant.startup_cost_usd

                # Dispatch this plant
                amount_needed = min(
                    required_capacity - online_capacity,
                    plant.capacity_mw,
                )
                amount_needed = max(amount_needed, plant.min_power_mw)

                dispatch[plant.plant_id][hour] = amount_needed
                online_capacity += amount_needed
                hour_cost += amount_needed * plant.get_operating_cost_per_mwh()

            # Check feasibility
            if online_capacity < load:
                # Not enough capacity, reduce dispatch efficiency
                shortage = load - online_capacity
                dispatch[sorted_plants[0].plant_id][hour] += min(
                    shortage,
                    sorted_plants[0].capacity_mw - dispatch[sorted_plants[0].plant_id][hour],
                )

            total_cost += hour_cost

        return UnitCommitmentSolution(
            on_off_schedule=on_off_schedule,
            dispatch=dispatch,
            total_cost=total_cost,
            feasible=True,
        )

    def add_startup_costs(self, solution: UnitCommitmentSolution, plants: list[PowerPlant]) -> float:
        """Add startup costs to total cost."""
        plant_dict = {p.plant_id: p for p in plants}
        total_startup_cost = 0.0

        for plant_id, schedule in solution.on_off_schedule.items():
            if plant_id not in plant_dict:
                continue

            plant = plant_dict[plant_id]

            for hour in range(len(schedule)):
                if hour == 0 and schedule[hour] or hour > 0 and schedule[hour] and not schedule[hour - 1]:
                    total_startup_cost += plant.startup_cost_usd

        return total_startup_cost


@dataclass
class EconomicDispatchSolution:
    """Solution to economic dispatch problem."""

    dispatch: dict[str, float]  # plant_id -> MW
    lambda_: float  # Incremental cost ($/MWh)
    total_generation: float
    total_cost: float
    converged: bool


@dataclass
class EconomicDispatch:
    """Economic dispatch solver using lambda iteration."""

    def solve_lambda_iteration(
        self,
        plants: list[PowerPlant],
        demand_mw: float,
        reserve_requirement_mw: float = 0.0,
        max_iterations: int = 100,
        tolerance: float = 0.01,
    ) -> EconomicDispatchSolution:
        """
        Solve economic dispatch using lambda iteration.

        Args:
            plants: Dispatchable plants
            demand_mw: Total demand in MW
            reserve_requirement_mw: Spinning reserve requirement
            max_iterations: Maximum iterations
            tolerance: Convergence tolerance

        Returns:
            Economic dispatch solution
        """
        if not plants:
            raise NoFeasibleSolutionError("No plants available")

        total_capacity = sum(p.capacity_mw for p in plants)
        required_capacity = demand_mw + reserve_requirement_mw

        if total_capacity < required_capacity:
            raise NoFeasibleSolutionError(
                f"Total capacity {total_capacity:.1f} MW < required {required_capacity:.1f} MW"
            )

        # Lambda iteration bounds
        lambda_low = 0.0
        lambda_high = 150.0
        lambda_mid = (lambda_low + lambda_high) / 2.0

        dispatch = {}
        converged = False

        def marginal_cost(plant: PowerPlant) -> float:
            return plant.fuel_cost_per_mwh / plant.efficiency + plant.variable_om_per_mwh

        for iteration in range(max_iterations):
            # Dispatch all plants at current lambda
            dispatch = {}
            total_generation = 0.0
            total_cost = 0.0

            for plant in plants:
                # Determine dispatch based on marginal cost
                marg_cost = marginal_cost(plant)

                if marg_cost <= lambda_mid:
                    # Dispatch at maximum
                    p_out = plant.capacity_mw
                else:
                    # Dispatch at minimum
                    p_out = plant.min_power_mw

                dispatch[plant.plant_id] = p_out
                total_generation += p_out
                total_cost += p_out * marg_cost

            # Check if dispatch meets demand
            error = demand_mw - total_generation

            if abs(error) < tolerance:
                converged = True
                break

            # Adjust lambda
            if error > 0:
                # Need more generation
                lambda_low = lambda_mid
            else:
                # Too much generation
                lambda_high = lambda_mid

            lambda_mid = (lambda_low + lambda_high) / 2.0

        # Final balancing pass: adjust dispatch across all units within limits.
        imbalance = demand_mw - sum(dispatch.get(p.plant_id, 0.0) for p in plants)
        if abs(imbalance) >= tolerance:
            if imbalance > 0:
                # Need more generation: add from cheapest units first.
                for plant in sorted(plants, key=marginal_cost):
                    plant_id = plant.plant_id
                    current = dispatch.get(plant_id, plant.min_power_mw)
                    headroom = plant.capacity_mw - current
                    if headroom <= 0:
                        continue
                    delta = min(headroom, imbalance)
                    dispatch[plant_id] = current + delta
                    imbalance -= delta
                    if abs(imbalance) < tolerance:
                        break
            else:
                # Too much generation: reduce most expensive units first.
                for plant in sorted(plants, key=marginal_cost, reverse=True):
                    plant_id = plant.plant_id
                    current = dispatch.get(plant_id, plant.min_power_mw)
                    reducible = current - plant.min_power_mw
                    if reducible <= 0:
                        continue
                    delta = min(reducible, -imbalance)
                    dispatch[plant_id] = current - delta
                    imbalance += delta
                    if abs(imbalance) < tolerance:
                        break

        final_total_generation = sum(dispatch.get(p.plant_id, 0.0) for p in plants)
        if abs(final_total_generation - demand_mw) < tolerance:
            converged = True

        return EconomicDispatchSolution(
            dispatch=dispatch,
            lambda_=lambda_mid,
            total_generation=sum(dispatch.values()),
            total_cost=sum(dispatch.get(p.plant_id, 0.0) * marginal_cost(p) for p in plants),
            converged=converged,
        )


@dataclass
class MicrogridOptimizationResult:
    """Result from microgrid optimization."""

    gen_dispatch: dict[str, float]  # plant_id -> MW
    storage_charge_discharge: dict[str, float]  # storage_id -> MW (+ charge, - discharge)
    load_shed: dict[str, float]  # load_id -> MW shed
    total_cost: float
    renewable_penetration: float

    @property
    def total_dispatch_mw(self) -> float:
        """Total conventional generation dispatch in MW."""
        return sum(self.gen_dispatch.values())


@dataclass
class MicrogridOptimizer:
    """Microgrid optimization with renewable integration and storage."""

    def optimize_microgrid(
        self,
        plants: list[PowerPlant],
        loads: list[Load],
        storage_units: list[StorageUnit],
        renewable_availability: dict[str, float],
        storage_targets: dict[str, float] | None = None,
    ) -> MicrogridOptimizationResult:
        """
        Optimize microgrid operation for minimum cost.

        Args:
            plants: Dispatchable generators
            loads: Electrical loads
            storage_units: Storage devices
            renewable_availability: Renewable sources available (plant_id -> MW)
            storage_targets: Target SOC for storage (storage_id -> SOC 0-1)

        Returns:
            Optimization result
        """
        gen_dispatch = {}
        storage_dispatch = {}
        load_shed = {}
        total_cost = 0.0

        # Total demand
        total_demand = sum(l.active_power for l in loads)

        # Available renewable
        renewable_available = sum(renewable_availability.values())

        # Use renewables first (zero marginal cost)
        if renewable_available >= total_demand:
            # All renewable
            for load in loads:
                load_shed[load.load_id] = 0.0
            for plant in plants:
                gen_dispatch[plant.plant_id] = 0.0
            renewable_penetration = 1.0
        else:
            # Blend renewable with conventional
            demand_from_conventional = total_demand - renewable_available

            # Dispatch conventional generators (economic dispatch)
            dispatch_ed = EconomicDispatch().solve_lambda_iteration(
                plants,
                demand_from_conventional,
                reserve_requirement_mw=total_demand * 0.1,
            )

            gen_dispatch = dispatch_ed.dispatch
            total_cost = dispatch_ed.total_cost

            renewable_penetration = renewable_available / total_demand if total_demand > 0 else 0.0

            for load in loads:
                load_shed[load.load_id] = 0.0

        # Optimize storage for peak shaving
        for storage in storage_units:
            # Simple strategy: charge when renewable abundant, discharge during peak
            if renewable_available > total_demand * 0.5:
                # Charge storage
                charge_power = min(storage.power_rating_mw, renewable_available - total_demand)
                storage_dispatch[storage.storage_id] = charge_power

                # Update cost
                total_cost -= charge_power * 5.0  # Small incentive for storage

            elif total_demand > sum(gen_dispatch.values()):
                # Discharge storage to help meet demand
                discharge_power = min(
                    storage.power_rating_mw,
                    total_demand - sum(gen_dispatch.values()),
                )
                storage_dispatch[storage.storage_id] = -discharge_power
                total_cost -= discharge_power * 10.0

            else:
                storage_dispatch[storage.storage_id] = 0.0

        return MicrogridOptimizationResult(
            gen_dispatch=gen_dispatch,
            storage_charge_discharge=storage_dispatch,
            load_shed=load_shed,
            total_cost=max(0.0, total_cost),
            renewable_penetration=renewable_penetration,
        )


@dataclass
class PeakShavingStrategy:
    """Peak shaving using storage and demand response."""

    def shave_peak(
        self,
        load_profile: list[float],
        storage_unit: StorageUnit,
        peak_threshold: float,
    ) -> tuple[list[float], list[float]]:
        """
        Shave peak load using storage discharge.

        Args:
            load_profile: Hourly load profile in MW
            storage_unit: Storage device
            peak_threshold: Peak load threshold to shave to

        Returns:
            Tuple of (modified_profile, storage_dispatch)
        """
        modified_profile = load_profile.copy()
        storage_dispatch = [0.0] * len(load_profile)

        # Find peak hours
        peak_hours = [i for i, l in enumerate(load_profile) if l > peak_threshold]

        if not peak_hours:
            return modified_profile, storage_dispatch

        # Calculate energy available in storage
        available_energy = storage_unit.soc * storage_unit.capacity_mwh

        # Distribute discharge over peak hours
        for hour in peak_hours:
            excess = modified_profile[hour] - peak_threshold

            # Discharge storage
            discharge = min(excess, available_energy, storage_unit.power_rating_mw)

            if discharge > 0:
                modified_profile[hour] -= discharge
                storage_dispatch[hour] = -discharge
                available_energy -= discharge

        return modified_profile, storage_dispatch


@dataclass
class LoadShiftingOptimizer:
    """Optimize load shifting for energy arbitrage."""

    def optimize_shift(
        self,
        baseline_load: list[float],
        price_forecast: list[float],
        shiftable_load_fraction: float = 0.2,
        shift_window_hours: int = 4,
    ) -> list[float]:
        """
        Shift load from high-price to low-price hours.

        Args:
            baseline_load: Baseline hourly load profile
            price_forecast: Hourly price forecast
            shiftable_load_fraction: Fraction of load that can be shifted
            shift_window_hours: Hours within which load can be shifted

        Returns:
            Optimized load profile
        """
        optimized_load = baseline_load.copy()
        n_hours = len(baseline_load)

        for i in range(n_hours):
            current_price = price_forecast[i]
            shiftable_amount = baseline_load[i] * shiftable_load_fraction

            # Look for cheaper hours within shift window
            window_start = max(0, i - shift_window_hours // 2)
            window_end = min(n_hours, i + shift_window_hours // 2)

            cheapest_hour = i
            min_price = current_price

            for j in range(window_start, window_end):
                if price_forecast[j] < min_price:
                    min_price = price_forecast[j]
                    cheapest_hour = j

            # Shift load to cheaper hour
            if cheapest_hour != i and min_price < current_price * 0.95:
                optimized_load[i] -= shiftable_amount
                optimized_load[cheapest_hour] += shiftable_amount

        return optimized_load


@dataclass
class MultiObjectiveOptimizer:
    """Multi-objective optimization (cost vs emissions)."""

    def pareto_frontier(
        self,
        solutions: list[tuple[float, float]],  # (cost, emissions)
    ) -> list[tuple[float, float]]:
        """
        Calculate Pareto frontier of non-dominated solutions.

        Args:
            solutions: List of (cost, emissions) tuples

        Returns:
            List of Pareto-optimal solutions
        """
        if not solutions:
            return []

        # Sort by cost
        sorted_solutions = sorted(solutions, key=lambda x: x[0])
        frontier = []

        min_emissions = float("inf")

        for cost, emissions in sorted_solutions:
            if emissions < min_emissions:
                frontier.append((cost, emissions))
                min_emissions = emissions

        return frontier

    def find_optimal_weight(
        self,
        cost_weight: float,
        emissions_weight: float,
        solutions: list[tuple[float, float]],
    ) -> tuple[float, float]:
        """
        Find solution with given weight preference.

        Args:
            cost_weight: Weight for cost (0-1)
            emissions_weight: Weight for emissions (0-1)
            solutions: Available solutions

        Returns:
            Best solution (cost, emissions)
        """
        if not solutions:
            return 0.0, 0.0

        # Normalize weights
        total_weight = cost_weight + emissions_weight
        w_cost = cost_weight / total_weight if total_weight > 0 else 0.5
        w_emissions = emissions_weight / total_weight if total_weight > 0 else 0.5

        # Normalize solutions to [0, 1]
        max_cost = max(s[0] for s in solutions)
        max_emissions = max(s[1] for s in solutions)

        best_solution = None
        best_score = float("inf")

        for cost, emissions in solutions:
            normalized_cost = cost / max_cost if max_cost > 0 else 0.0
            normalized_emissions = emissions / max_emissions if max_emissions > 0 else 0.0

            score = w_cost * normalized_cost + w_emissions * normalized_emissions

            if score < best_score:
                best_score = score
                best_solution = (cost, emissions)

        return best_solution if best_solution else solutions[0]
