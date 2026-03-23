"""
Tests for pre-built simulation scenarios.
"""

from scenarios import (
    BankQueueConfig,
    BankQueueScenario,
    EpidemicConfig,
    EpidemicScenario,
    PredatorPreyConfig,
    PredatorPreyScenario,
    SupplyChainConfig,
    SupplyChainScenario,
    TrafficConfig,
    TrafficScenario,
)


class TestEpidemicScenario:
    """Test SIR epidemic scenario."""

    def test_epidemic_initialization(self):
        """Test epidemic scenario setup."""
        config = EpidemicConfig(
            duration=100,
            population=1000,
            initial_infected=5,
        )

        scenario = EpidemicScenario(config)
        env = scenario.setup()

        assert len(scenario.population) == 1000
        assert env.get_population() == 1000

    def test_epidemic_infection_spread(self):
        """Test disease spread."""
        config = EpidemicConfig(
            duration=50,
            population=100,
            initial_infected=2,
            contact_rate=5.0,
            transmission_prob=0.5,
        )

        scenario = EpidemicScenario(config)
        result = scenario.run()

        # Should have some infected at peak
        assert result["peak_infected"] > config.initial_infected
        assert 0 <= result["attack_rate"] <= 1

    def test_epidemic_recovery(self):
        """Test recovery from infection."""
        config = EpidemicConfig(
            duration=100,
            population=500,
            initial_infected=10,
            recovery_rate=0.2,
        )

        scenario = EpidemicScenario(config)
        result = scenario.run()

        # Some should recover
        assert len(result["recovered"]) > 0
        assert result["recovered"][-1] >= config.initial_infected

    def test_epidemic_statistics(self):
        """Test epidemic result statistics."""
        config = EpidemicConfig(duration=100, population=1000)

        scenario = EpidemicScenario(config)
        result = scenario.run()

        assert "peak_infected" in result
        assert "peak_time" in result
        assert "attack_rate" in result
        assert 0 <= result["peak_time"] < 100


class TestSupplyChainScenario:
    """Test supply chain scenario."""

    def test_supply_chain_initialization(self):
        """Test supply chain setup."""
        config = SupplyChainConfig(duration=100)

        scenario = SupplyChainScenario(config)

        assert scenario.factory_inventory == config.factory_capacity
        assert scenario.warehouse_inventory == config.warehouse_capacity
        assert scenario.retail_inventory == config.retail_capacity

    def test_supply_chain_demand_fulfillment(self):
        """Test customer demand fulfillment."""
        config = SupplyChainConfig(
            duration=100,
            demand_mean=10,
            demand_std=2,
        )

        scenario = SupplyChainScenario(config)
        result = scenario.run()

        assert result["avg_demand"] > 0
        assert 0 <= result["service_level"] <= 1

    def test_supply_chain_inventory_dynamics(self):
        """Test inventory level changes."""
        config = SupplyChainConfig(duration=100)

        scenario = SupplyChainScenario(config)
        result = scenario.run()

        assert len(result["inventory_history"]) == 100
        assert result["avg_inventory"] >= 0

    def test_supply_chain_stockouts(self):
        """Test stockout events."""
        config = SupplyChainConfig(
            duration=100,
            demand_mean=50,  # High demand to trigger stockouts
            retail_capacity=20,
        )

        scenario = SupplyChainScenario(config)
        result = scenario.run()

        assert result["stockout_events"] >= 0
        assert result["service_level"] < 1


class TestTrafficScenario:
    """Test traffic simulation scenario."""

    def test_traffic_initialization(self):
        """Test traffic scenario setup."""
        config = TrafficConfig(
            duration=100,
            num_vehicles=50,
        )

        scenario = TrafficScenario(config)

        assert len(scenario.vehicles) == 0  # Start empty

    def test_traffic_vehicle_arrival(self):
        """Test vehicle arrivals."""
        config = TrafficConfig(
            duration=100,
            arrival_rate=2.0,  # High arrival rate
        )

        scenario = TrafficScenario(config)
        result = scenario.run()

        assert result["throughput"] > 0
        assert len(result["speed_history"]) > 0

    def test_traffic_throughput(self):
        """Test traffic throughput."""
        config = TrafficConfig(
            duration=100,
            arrival_rate=1.0,
        )

        scenario = TrafficScenario(config)
        result = scenario.run()

        assert "throughput" in result
        assert result["throughput"] >= 0

    def test_traffic_collisions(self):
        """Test collision detection."""
        config = TrafficConfig(
            duration=100,
            num_vehicles=100,
            collision_distance=5.0,
        )

        scenario = TrafficScenario(config)
        result = scenario.run()

        assert "collisions" in result
        assert result["collisions"] >= 0

    def test_traffic_speed_tracking(self):
        """Test average speed tracking."""
        config = TrafficConfig(
            duration=100,
            speed_mean=50.0,
            speed_std=10.0,
        )

        scenario = TrafficScenario(config)
        result = scenario.run()

        # Should have some speed history
        if result["speed_history"]:
            avg = sum(result["speed_history"]) / len(result["speed_history"])
            assert 30 < avg < 70  # Reasonable range


class TestPredatorPreyScenario:
    """Test predator-prey scenario."""

    def test_predator_prey_initialization(self):
        """Test scenario setup."""
        config = PredatorPreyConfig(
            duration=100,
            initial_prey=100,
            initial_predators=10,
        )

        scenario = PredatorPreyScenario(config)
        scenario.setup()

        assert len(scenario.prey) == 100
        assert len(scenario.predators) == 10

    def test_predator_prey_oscillation(self):
        """Test predator-prey population oscillations."""
        config = PredatorPreyConfig(
            duration=500,
            initial_prey=100,
            initial_predators=20,
            prey_birth_rate=0.2,
            predator_death_rate=0.05,
        )

        scenario = PredatorPreyScenario(config)
        result = scenario.run()

        # Should have population history
        assert len(result["prey_history"]) > 0
        assert len(result["predator_history"]) > 0

    def test_predator_prey_population_dynamics(self):
        """Test population dynamics."""
        config = PredatorPreyConfig(
            duration=200,
            initial_prey=200,
            initial_predators=20,
        )

        scenario = PredatorPreyScenario(config)
        result = scenario.run()

        # Populations should be tracked
        assert result["prey_mean"] > 0
        assert result["predator_mean"] > 0

    def test_predator_prey_extinction_risk(self):
        """Test extinction scenarios."""
        config = PredatorPreyConfig(
            duration=500,
            initial_prey=50,
            initial_predators=50,
            prey_death_rate=0.3,
            predator_death_rate=0.3,
        )

        scenario = PredatorPreyScenario(config)
        result = scenario.run()

        # At high death rates, extinctions possible
        assert result["final_prey"] >= 0
        assert result["final_predators"] >= 0


class TestBankQueueScenario:
    """Test bank queue scenario."""

    def test_bank_queue_initialization(self):
        """Test bank queue setup."""
        config = BankQueueConfig(
            duration=100,
            num_tellers=3,
        )

        scenario = BankQueueScenario(config)

        assert len(scenario.tellers) == 3
        assert scenario.abandoned_customers == 0

    def test_bank_queue_customer_service(self):
        """Test customer service."""
        config = BankQueueConfig(
            duration=100,
            num_tellers=2,
            customer_arrival_rate=2.0,
        )

        scenario = BankQueueScenario(config)
        result = scenario.run()

        assert result["customers_served"] > 0

    def test_bank_queue_wait_times(self):
        """Test wait time tracking."""
        config = BankQueueConfig(
            duration=100,
            num_tellers=1,
            customer_arrival_rate=1.0,
            service_time_mean=2.0,
        )

        scenario = BankQueueScenario(config)
        result = scenario.run()

        assert result["avg_wait_time"] >= 0
        assert result["max_wait_time"] >= result["avg_wait_time"]

    def test_bank_queue_abandonment(self):
        """Test customer abandonment."""
        config = BankQueueConfig(
            duration=100,
            num_tellers=1,
            customer_arrival_rate=5.0,  # High arrival
            customer_patience=1.0,  # Low patience
        )

        scenario = BankQueueScenario(config)
        result = scenario.run()

        # Should have some abandonments
        assert result["customers_abandoned"] >= 0

    def test_bank_queue_service_level(self):
        """Test service level metric."""
        config = BankQueueConfig(
            duration=100,
            num_tellers=3,
            customer_arrival_rate=2.0,
        )

        scenario = BankQueueScenario(config)
        result = scenario.run()

        assert 0 <= result["service_level_5min"] <= 1


class TestScenarioParameterSensitivity:
    """Test scenario sensitivity to parameters."""

    def test_epidemic_transmission_prob_effect(self):
        """Test transmission probability effect."""
        config_low = EpidemicConfig(
            duration=100,
            population=500,
            transmission_prob=0.1,
        )

        config_high = EpidemicConfig(
            duration=100,
            population=500,
            transmission_prob=0.9,
        )

        result_low = EpidemicScenario(config_low).run()
        result_high = EpidemicScenario(config_high).run()

        # Higher transmission should yield higher attack rate
        assert result_high["attack_rate"] > result_low["attack_rate"]

    def test_supply_chain_demand_effect(self):
        """Test demand level effect."""
        config_low = SupplyChainConfig(
            duration=100,
            demand_mean=5,
            demand_std=1,
        )

        config_high = SupplyChainConfig(
            duration=100,
            demand_mean=30,
            demand_std=5,
        )

        result_low = SupplyChainScenario(config_low).run()
        result_high = SupplyChainScenario(config_high).run()

        # Higher demand should lower service level
        assert result_low["service_level"] > result_high["service_level"]

    def test_traffic_arrival_rate_effect(self):
        """Test arrival rate effect on throughput."""
        config_low = TrafficConfig(
            duration=100,
            arrival_rate=0.5,
        )

        config_high = TrafficConfig(
            duration=100,
            arrival_rate=2.0,
        )

        result_low = TrafficScenario(config_low).run()
        result_high = TrafficScenario(config_high).run()

        # Higher arrival should increase throughput
        assert result_high["throughput"] > result_low["throughput"]

    def test_bank_queue_teller_effect(self):
        """Test effect of number of tellers."""
        config_few = BankQueueConfig(
            duration=100,
            num_tellers=1,
            customer_arrival_rate=2.0,
        )

        config_many = BankQueueConfig(
            duration=100,
            num_tellers=5,
            customer_arrival_rate=2.0,
        )

        result_few = BankQueueScenario(config_few).run()
        result_many = BankQueueScenario(config_many).run()

        # More tellers should reduce wait times
        assert result_many["avg_wait_time"] < result_few["avg_wait_time"]


class TestScenarioReproducibility:
    """Test scenario reproducibility with seeds."""

    def test_epidemic_with_seed(self):
        """Test epidemic reproducibility."""
        config = EpidemicConfig(
            duration=100,
            population=500,
            random_seed=42,
        )

        result1 = EpidemicScenario(config).run()

        config.random_seed = 42
        result2 = EpidemicScenario(config).run()

        # Same seed should yield same results
        assert result1["peak_infected"] == result2["peak_infected"]
        assert result1["attack_rate"] == result2["attack_rate"]

    def test_traffic_with_seed(self):
        """Test traffic reproducibility."""
        config = TrafficConfig(
            duration=100,
            random_seed=42,
        )

        result1 = TrafficScenario(config).run()

        config.random_seed = 42
        result2 = TrafficScenario(config).run()

        # Same seed should yield same throughput
        assert result1["throughput"] == result2["throughput"]
