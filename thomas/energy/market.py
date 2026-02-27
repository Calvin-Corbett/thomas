"""
Energy market operations and pricing.

Provides day-ahead pricing (merit order dispatch), real-time pricing, demand
response, capacity markets, renewable energy certificates, carbon credit
trading, and locational marginal pricing.
"""

from dataclasses import dataclass, field

from thomas.energy._exceptions import MarketError
from thomas.energy._types import DemandResponse, EnergySource, TariffSchedule


@dataclass
class BidStack:
    """Generator bid for energy market."""

    plant_id: str
    mw_bid: float
    price_per_mwh: float
    min_mw: float = 0.0
    max_mw: float = 100.0
    ramp_rate_mw_per_min: float = 1.0
    fuel_type: EnergySource = EnergySource.NATURAL_GAS


@dataclass
class DemandBid:
    """Load bid for energy market."""

    load_id: str
    mw_bid: float
    price_willing_to_pay: float  # $/MWh
    min_mw: float = 0.0
    max_mw: float = 100.0


@dataclass
class MarketClearingResult:
    """Results from market clearing."""

    clearing_price_per_mwh: float
    total_cleared_mw: float
    gen_dispatch: dict[str, float]  # plant_id -> dispatch_mw
    load_served: dict[str, float]  # load_id -> served_mw
    surplus: float  # Consumer surplus
    generation_cost: float  # Total generation cost


@dataclass
class MeritOrderDispatch:
    """Merit order economic dispatch."""

    def clear_market(
        self,
        supply_bids: list[BidStack],
        demand_bids: list[DemandBid],
    ) -> MarketClearingResult:
        """
        Clear energy market using merit order (lowest cost first).

        Args:
            supply_bids: Generator supply bids
            demand_bids: Load demand bids

        Returns:
            Market clearing result
        """
        if not supply_bids or not demand_bids:
            raise MarketError("Empty supply or demand bids")

        # Sort supply bids by price (merit order)
        sorted_supply = sorted(supply_bids, key=lambda x: x.price_per_mwh)

        # Sort demand bids by willingness to pay (highest first)
        sorted_demand = sorted(demand_bids, key=lambda x: -x.price_willing_to_pay)

        # Dispatch generators and loads
        gen_dispatch = {}
        load_served = {}
        cumulative_mw = 0.0
        clearing_price = 0.0
        demand_needed = sum(d.mw_bid for d in demand_bids)

        for bid in sorted_supply:
            if cumulative_mw >= demand_needed:
                break

            available_mw = min(bid.mw_bid, bid.max_mw)
            dispatch_mw = min(available_mw, demand_needed - cumulative_mw)
            gen_dispatch[bid.plant_id] = dispatch_mw
            cumulative_mw += dispatch_mw

            # Market convention for this simplified model: first accepted offer sets price.
            if dispatch_mw > 0.0 and clearing_price == 0.0:
                clearing_price = bid.price_per_mwh

            # Check if demand is met
            if cumulative_mw >= demand_needed:
                break

        if clearing_price == 0.0 and sorted_supply:
            clearing_price = sorted_supply[0].price_per_mwh

        # Serve demand in order of willingness to pay
        remaining_supply = cumulative_mw
        for bid in sorted_demand:
            amount = min(bid.mw_bid, remaining_supply)
            load_served[bid.load_id] = amount
            remaining_supply -= amount

            if remaining_supply <= 0:
                break

        # Calculate totals
        total_cleared = sum(load_served.values())
        generation_cost = sum(gen_dispatch.get(bid.plant_id, 0) * bid.price_per_mwh for bid in sorted_supply)

        # Consumer surplus (simplified)
        surplus = 0.0
        for bid in sorted_demand:
            served = load_served.get(bid.load_id, 0)
            surplus += served * (bid.price_willing_to_pay - clearing_price)

        return MarketClearingResult(
            clearing_price_per_mwh=clearing_price,
            total_cleared_mw=total_cleared,
            gen_dispatch=gen_dispatch,
            load_served=load_served,
            surplus=max(0.0, surplus),
            generation_cost=generation_cost,
        )


@dataclass
class PricingEngine:
    """Energy pricing for various market structures."""

    def calculate_day_ahead_price(
        self,
        hour: int,
        weather_forecast_available_mw: dict[str, float],
        demand_forecast_mw: float,
        reserve_requirement_mw: float = 20.0,
        base_price_per_mwh: float = 40.0,
    ) -> float:
        """
        Calculate day-ahead market price.

        Args:
            hour: Hour of day (0-23)
            weather_forecast_available_mw: Dict mapping source -> available_mw
            demand_forecast_mw: Forecasted demand
            reserve_requirement_mw: Required spinning reserve
            base_price_per_mwh: Base price reference

        Returns:
            Hourly clearing price in $/MWh
        """
        # Total available generation
        total_available = sum(weather_forecast_available_mw.values())

        # Margin above demand + reserve
        margin = total_available - demand_forecast_mw - reserve_requirement_mw

        # Price adjusts based on margin
        # Tight margin -> higher price
        if margin < 0:
            # Scarcity condition
            return base_price_per_mwh * 2.0

        elif margin < reserve_requirement_mw:
            # Limited margin
            margin_ratio = margin / reserve_requirement_mw
            return base_price_per_mwh * (1.0 + (1.0 - margin_ratio))

        else:
            # Ample supply, price competition drives down
            excess_ratio = margin / demand_forecast_mw
            price = base_price_per_mwh * max(0.3, 1.0 - excess_ratio * 0.2)
            return price

    def calculate_real_time_price(
        self,
        day_ahead_price: float,
        current_demand_mw: float,
        available_mw: float,
        reserve_deployed: float = 0.0,
    ) -> float:
        """
        Calculate real-time price based on current conditions.

        Args:
            day_ahead_price: Day-ahead clearing price
            current_demand_mw: Current actual demand
            available_mw: Available generation
            reserve_deployed: Amount of reserve deployed

        Returns:
            Real-time clearing price
        """
        # Real-time deviation
        shortage = current_demand_mw - available_mw

        if shortage > 0:
            # Under-supply increases price significantly
            shortage_fraction = shortage / current_demand_mw
            penalty = shortage_fraction**2 * 4.0  # Quadratic penalty
            return day_ahead_price * (1.0 + penalty)

        else:
            # Over-supply lowers price
            surplus = available_mw - current_demand_mw
            surplus_fraction = surplus / current_demand_mw
            discount = surplus_fraction * 0.15  # 15% max discount
            return day_ahead_price * max(0.1, 1.0 - discount)

    def calculate_capacity_payment(
        self,
        available_capacity_mw: float,
        peak_demand_mw: float,
        annual_hours: int = 8760,
        target_roc_percent: float = 10.0,
    ) -> float:
        """
        Calculate capacity market payment.

        Args:
            available_capacity_mw: Available generation capacity
            peak_demand_mw: System peak demand
            annual_hours: Hours in analysis period
            target_roc_percent: Target return on capital

        Returns:
            Capacity payment in $/MW-year
        """
        if peak_demand_mw <= 0:
            return 0.0

        # Calculate reserve margin
        reserve_margin = (available_capacity_mw - peak_demand_mw) / peak_demand_mw

        if reserve_margin < 0.15:  # Less than 15% reserve margin
            # Increase payment to incentivize capacity
            scarcity_multiplier = 1.0 / (0.15 - reserve_margin + 0.05)
        else:
            scarcity_multiplier = 1.0

        # Base capacity payment (simplified)
        base_payment = 50000.0  # $/MW-year
        payment = base_payment * scarcity_multiplier

        return payment

    def apply_time_of_use_rates(
        self,
        base_price: float,
        hour: int,
        rate_schedule: TariffSchedule,
    ) -> float:
        """
        Apply time-of-use rate adjustment.

        Args:
            base_price: Base energy price
            hour: Hour of day
            rate_schedule: TOU rate schedule

        Returns:
            Adjusted price
        """
        rate_multiplier = rate_schedule.get_rate(hour) / rate_schedule.base_rate

        return base_price * rate_multiplier

    def calculate_locational_marginal_price(
        self,
        node_id: str,
        congestion_component: float,
        marginal_energy_price: float,
        transmission_loss_component: float = 0.0,
    ) -> float:
        """
        Calculate locational marginal price at a node.

        Args:
            node_id: Bus/node identifier
            congestion_component: Congestion price component
            marginal_energy_price: Energy price at reference node
            transmission_loss_component: Transmission loss price component

        Returns:
            LMP at node in $/MWh
        """
        lmp = marginal_energy_price + congestion_component + transmission_loss_component
        return max(0.0, lmp)

    def calculate_transmission_congestion(
        self,
        line_power_mw: float,
        line_rating_mw: float,
        base_price: float = 40.0,
    ) -> float:
        """
        Calculate congestion price component for transmission line.

        Args:
            line_power_mw: Current power on line
            line_rating_mw: Line thermal limit
            base_price: Base energy price

        Returns:
            Congestion price component in $/MWh
        """
        if line_rating_mw <= 0:
            return 0.0

        loading = line_power_mw / line_rating_mw

        if loading < 0.8:
            # No congestion
            return 0.0
        elif loading < 1.0:
            # Approaching limit
            congestion = (loading - 0.8) / 0.2 * base_price * 0.5
            return congestion
        else:
            # Overloaded
            overload = loading - 1.0
            congestion = (0.5 + overload) * base_price
            return min(base_price * 5.0, congestion)  # Cap at 5x base price


@dataclass
class EnergyMarket:
    """Complete energy market system."""

    merit_order: MeritOrderDispatch = field(default_factory=MeritOrderDispatch)
    pricing_engine: PricingEngine = field(default_factory=PricingEngine)
    demand_response_programs: dict[str, DemandResponse] = field(default_factory=dict)
    carbon_credit_price: float = 25.0  # $/ton CO2

    def register_dr_program(self, program: DemandResponse) -> None:
        """Register a demand response program."""
        self.demand_response_programs[program.program_id] = program

    def activate_demand_response(
        self,
        program_ids: list[str],
        duration_hours: int = 1,
    ) -> float:
        """
        Activate demand response programs.

        Args:
            program_ids: IDs of programs to activate
            duration_hours: Activation duration in hours

        Returns:
            Total load shedding activated in MW
        """
        total_shed = 0.0

        for prog_id in program_ids:
            if prog_id in self.demand_response_programs:
                program = self.demand_response_programs[prog_id]
                total_shed += program.effective_shed_capacity()

        return total_shed

    def calculate_marginal_emission_rate(
        self,
        gen_mix: dict[EnergySource, float],
        emission_factors: dict[EnergySource, float],
    ) -> float:
        """
        Calculate marginal emission rate (kg CO2/MWh) of marginal generator.

        Args:
            gen_mix: Generation mix (source -> fraction)
            emission_factors: Emission factors (source -> kg CO2/MWh)

        Returns:
            Marginal emission rate in kg CO2/MWh
        """
        # Marginal unit is typically highest cost (often fossil)
        # Simplified: assume natural gas is marginal
        if EnergySource.NATURAL_GAS in emission_factors:
            return emission_factors[EnergySource.NATURAL_GAS]

        # Fallback to weighted average
        avg_emission = 0.0
        for source, fraction in gen_mix.items():
            if source in emission_factors:
                avg_emission += fraction * emission_factors[source]

        return avg_emission

    def calculate_renewable_energy_credit(
        self,
        renewable_generation_mwh: float,
        total_generation_mwh: float,
        credit_price_per_mwh: float = 30.0,
        rps_target_percent: float = 0.35,
    ) -> float:
        """
        Calculate renewable energy certificate value.

        Args:
            renewable_generation_mwh: Renewable energy generated
            total_generation_mwh: Total generation
            credit_price_per_mwh: REC price
            rps_target_percent: Renewable portfolio standard target

        Returns:
            Total REC value in dollars
        """
        if total_generation_mwh <= 0:
            return 0.0

        renewable_fraction = renewable_generation_mwh / total_generation_mwh

        if renewable_fraction >= rps_target_percent:
            # RPS met, credits worth less
            excess = renewable_fraction - rps_target_percent
            credit_value = credit_price_per_mwh * max(0.1, 1.0 - excess * 2.0)
        else:
            # Shortage, credits worth more
            shortage = rps_target_percent - renewable_fraction
            credit_value = credit_price_per_mwh * (1.0 + shortage * 2.0)

        return renewable_generation_mwh * credit_value

    def calculate_locational_marginal_price(
        self,
        node_id: str,
        congestion_component: float,
        marginal_energy_price: float,
        transmission_loss_component: float = 0.0,
    ) -> float:
        """
        Calculate locational marginal price at a node.

        Args:
            node_id: Bus/node identifier
            congestion_component: Congestion price component
            marginal_energy_price: Energy price at reference node
            transmission_loss_component: Transmission loss price component

        Returns:
            LMP at node in $/MWh
        """
        lmp = marginal_energy_price + congestion_component + transmission_loss_component

        return max(0.0, lmp)

    def calculate_transmission_congestion(
        self,
        line_power_mw: float,
        line_rating_mw: float,
        base_price: float = 40.0,
    ) -> float:
        """
        Calculate congestion price component for transmission line.

        Args:
            line_power_mw: Current power on line
            line_rating_mw: Line thermal limit
            base_price: Base energy price

        Returns:
            Congestion price component in $/MWh
        """
        if line_rating_mw <= 0:
            return 0.0

        loading = line_power_mw / line_rating_mw

        if loading < 0.8:
            # No congestion
            return 0.0

        elif loading < 1.0:
            # Approaching limit
            congestion = (loading - 0.8) / 0.2 * base_price * 0.5
            return congestion

        else:
            # Overloaded
            overload = loading - 1.0
            congestion = (0.5 + overload) * base_price
            return min(base_price * 5.0, congestion)  # Cap at 5x base price

    def reconcile_bilateral_contracts(
        self,
        day_ahead_price: float,
        day_ahead_quantity_mwh: float,
        contract_price: float,
        contract_quantity_mwh: float,
    ) -> tuple[float, float]:
        """
        Reconcile bilateral contract with day-ahead settlement.

        Args:
            day_ahead_price: Day-ahead clearing price
            day_ahead_quantity_mwh: Day-ahead cleared quantity
            contract_price: Bilateral contract price
            contract_quantity_mwh: Bilateral contract quantity

        Returns:
            Tuple of (seller_payment, buyer_payment) in dollars
        """
        # Contract payment at contract price
        contract_payment = contract_quantity_mwh * contract_price

        # Deviation from contract settled at day-ahead price
        deviation = day_ahead_quantity_mwh - contract_quantity_mwh
        settlement = deviation * day_ahead_price

        # Seller receives contract payment plus settlement
        seller_payment = contract_payment + settlement

        # Buyer pays contract plus settlement
        buyer_payment = contract_payment + settlement

        return seller_payment, buyer_payment
