"""
Tests for energy market operations and pricing.
"""

from thomas.energy._types import EnergySource
from thomas.energy.market import (
    BidStack,
    DemandBid,
    EnergyMarket,
    MeritOrderDispatch,
    PricingEngine,
)


class TestMeritOrderDispatch:
    """Test merit order market clearing."""

    def test_create_dispatcher(self):
        """Test dispatcher creation."""
        dispatcher = MeritOrderDispatch()

        assert dispatcher is not None

    def test_merit_order_dispatch_basic(self):
        """Test basic merit order dispatch."""
        dispatcher = MeritOrderDispatch()

        supply = [
            BidStack("gen1", 50.0, 30.0, fuel_type=EnergySource.NATURAL_GAS),
            BidStack("gen2", 60.0, 40.0, fuel_type=EnergySource.COAL),
            BidStack("gen3", 40.0, 50.0, fuel_type=EnergySource.COAL),
        ]

        demand = [
            DemandBid("load1", 70.0, 60.0),
            DemandBid("load2", 50.0, 50.0),
        ]

        result = dispatcher.clear_market(supply, demand)

        # Lowest cost generator (gen1) should clear first
        assert result.clearing_price_per_mwh == 30.0
        assert result.total_cleared_mw > 0

    def test_merit_order_dispatch_all_generators(self):
        """Test dispatch with all generators needed."""
        dispatcher = MeritOrderDispatch()

        supply = [
            BidStack("gen1", 100.0, 25.0),
            BidStack("gen2", 100.0, 35.0),
            BidStack("gen3", 100.0, 45.0),
        ]

        demand = [
            DemandBid("load1", 280.0, 100.0),  # Large demand
        ]

        result = dispatcher.clear_market(supply, demand)

        # All generators should be dispatched
        assert "gen1" in result.gen_dispatch
        assert "gen2" in result.gen_dispatch
        assert "gen3" in result.gen_dispatch

    def test_merit_order_price_signal(self):
        """Test price signal from supply/demand balance."""
        dispatcher = MeritOrderDispatch()

        # High demand case
        supply_high = [
            BidStack("gen1", 50.0, 30.0),
            BidStack("gen2", 50.0, 60.0),  # Expensive
        ]

        demand_high = [
            DemandBid("load1", 80.0, 100.0),
        ]

        result_high = dispatcher.clear_market(supply_high, demand_high)

        # Low demand case
        supply_low = [
            BidStack("gen1", 50.0, 30.0),
            BidStack("gen2", 50.0, 60.0),
        ]

        demand_low = [
            DemandBid("load1", 30.0, 100.0),
        ]

        result_low = dispatcher.clear_market(supply_low, demand_low)

        # High demand should result in higher clearing price
        assert result_high.clearing_price_per_mwh >= result_low.clearing_price_per_mwh


class TestPricingEngine:
    """Test energy pricing calculations."""

    def test_create_pricing_engine(self):
        """Test engine creation."""
        engine = PricingEngine()

        assert engine is not None

    def test_day_ahead_price_loose_market(self):
        """Test day-ahead price with ample supply."""
        engine = PricingEngine()

        weather_forecast = {
            EnergySource.WIND: 200.0,
            EnergySource.SOLAR: 100.0,
            EnergySource.NUCLEAR: 500.0,
        }

        price = engine.calculate_day_ahead_price(
            hour=12,
            weather_forecast_available_mw=weather_forecast,
            demand_forecast_mw=300.0,
            reserve_requirement_mw=50.0,
            base_price_per_mwh=40.0,
        )

        # Ample supply should result in low price
        assert price < 40.0

    def test_day_ahead_price_tight_market(self):
        """Test day-ahead price with tight supply."""
        engine = PricingEngine()

        weather_forecast = {
            EnergySource.WIND: 50.0,
            EnergySource.SOLAR: 20.0,
        }

        price = engine.calculate_day_ahead_price(
            hour=12,
            weather_forecast_available_mw=weather_forecast,
            demand_forecast_mw=400.0,
            reserve_requirement_mw=50.0,
            base_price_per_mwh=40.0,
        )

        # Tight supply should result in high price
        assert price > 40.0

    def test_real_time_price_surplus(self):
        """Test real-time price with surplus generation."""
        engine = PricingEngine()

        price = engine.calculate_real_time_price(
            day_ahead_price=40.0,
            current_demand_mw=300.0,
            available_mw=600.0,  # Surplus
        )

        # Surplus should lower price
        assert price < 40.0

    def test_real_time_price_shortage(self):
        """Test real-time price with shortage."""
        engine = PricingEngine()

        price = engine.calculate_real_time_price(
            day_ahead_price=40.0,
            current_demand_mw=500.0,
            available_mw=400.0,  # Shortage
        )

        # Shortage should raise price
        assert price > 40.0

    def test_capacity_market_payment(self):
        """Test capacity market payment."""
        engine = PricingEngine()

        payment = engine.calculate_capacity_payment(
            available_capacity_mw=500.0,
            peak_demand_mw=400.0,
            annual_hours=8760,
        )

        assert payment > 0

    def test_capacity_payment_scarcity(self):
        """Test capacity payment with resource scarcity."""
        engine = PricingEngine()

        # Tight market
        payment_tight = engine.calculate_capacity_payment(
            available_capacity_mw=430.0,
            peak_demand_mw=400.0,
        )

        # Loose market
        payment_loose = engine.calculate_capacity_payment(
            available_capacity_mw=600.0,
            peak_demand_mw=400.0,
        )

        # Tight market should have higher payment
        assert payment_tight > payment_loose

    def test_time_of_use_rates(self):
        """Test TOU rate adjustment."""
        from thomas.energy._types import TariffSchedule, TariffType

        engine = PricingEngine()

        schedule = TariffSchedule(
            tariff_type=TariffType.TIME_OF_USE,
            base_rate=40.0,
            peak_rate=60.0,
            off_peak_rate=25.0,
            peak_hours=[12, 13, 14, 15, 16, 17, 18],
        )

        peak_price = engine.apply_time_of_use_rates(
            base_price=40.0,
            hour=14,  # Peak hour
            rate_schedule=schedule,
        )

        off_peak_price = engine.apply_time_of_use_rates(
            base_price=40.0,
            hour=2,  # Off-peak hour
            rate_schedule=schedule,
        )

        # Peak price should be higher than off-peak
        assert peak_price > off_peak_price

    def test_transmission_congestion(self):
        """Test transmission congestion pricing."""
        engine = PricingEngine()

        # Not congested
        cong_low = engine.calculate_transmission_congestion(
            line_power_mw=150.0,
            line_rating_mw=500.0,
        )

        # Congested
        cong_high = engine.calculate_transmission_congestion(
            line_power_mw=450.0,
            line_rating_mw=500.0,
        )

        # Congested should have higher component
        assert cong_high > cong_low

    def test_lmp_calculation(self):
        """Test locational marginal price."""
        engine = PricingEngine()

        lmp = engine.calculate_locational_marginal_price(
            node_id="bus_1",
            congestion_component=5.0,
            marginal_energy_price=40.0,
            transmission_loss_component=1.0,
        )

        # Should be sum of components
        assert lmp == 46.0


class TestEnergyMarket:
    """Test complete energy market."""

    def test_create_market(self):
        """Test market creation."""
        market = EnergyMarket()

        assert market.merit_order is not None
        assert market.pricing_engine is not None

    def test_demand_response_registration(self):
        """Test DR program registration."""
        from thomas.energy._types import DemandResponse

        market = EnergyMarket()

        dr_program = DemandResponse(
            program_id="dr1",
            max_shed_mw=50.0,
            shed_price_per_mwh=75.0,
            response_time_minutes=10,
            duration_hours=4,
            frequency_per_year=20,
            customer_participation_rate=0.8,
        )

        market.register_dr_program(dr_program)

        assert "dr1" in market.demand_response_programs

    def test_demand_response_activation(self):
        """Test DR activation."""
        from thomas.energy._types import DemandResponse

        market = EnergyMarket()

        dr_program = DemandResponse(
            program_id="dr1",
            max_shed_mw=50.0,
            shed_price_per_mwh=75.0,
            response_time_minutes=10,
            duration_hours=4,
            frequency_per_year=20,
            customer_participation_rate=0.8,
        )

        market.register_dr_program(dr_program)

        shed_mw = market.activate_demand_response(["dr1"])

        # Should shed effective capacity
        assert shed_mw > 0
        assert shed_mw <= 50.0

    def test_renewable_energy_credits(self):
        """Test REC calculation."""
        market = EnergyMarket()

        # 50% renewable
        rec_value = market.calculate_renewable_energy_credit(
            renewable_generation_mwh=500.0,
            total_generation_mwh=1000.0,
            credit_price_per_mwh=30.0,
            rps_target_percent=0.35,
        )

        assert rec_value > 0

        # Above RPS target
        rec_value_excess = market.calculate_renewable_energy_credit(
            renewable_generation_mwh=500.0,
            total_generation_mwh=1000.0,
            credit_price_per_mwh=30.0,
            rps_target_percent=0.40,  # Higher than achieved
        )

        # Below target should have higher value
        assert rec_value_excess > rec_value

    def test_marginal_emission_rate(self):
        """Test marginal emission rate calculation."""
        market = EnergyMarket()

        gen_mix = {
            EnergySource.COAL: 0.3,
            EnergySource.NATURAL_GAS: 0.4,
            EnergySource.WIND: 0.3,
        }

        emission_factors = {
            EnergySource.COAL: 950.0,
            EnergySource.NATURAL_GAS: 450.0,
            EnergySource.WIND: 11.0,
        }

        marginal = market.calculate_marginal_emission_rate(gen_mix, emission_factors)

        # Marginal should be NG (typically)
        assert marginal > 0

    def test_bilateral_contract_settlement(self):
        """Test bilateral contract reconciliation."""
        market = EnergyMarket()

        seller, buyer = market.reconcile_bilateral_contracts(
            day_ahead_price=50.0,
            day_ahead_quantity_mwh=100.0,
            contract_price=45.0,
            contract_quantity_mwh=100.0,
        )

        # With no deviation, payments should be equal
        assert seller == buyer
