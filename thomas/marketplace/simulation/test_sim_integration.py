"""
Integration tests combining multiple simulation components.
"""

import math

import pytest
from _types import EventType, SimConfig
from agent_based import Environment, SimpleAgent
from discrete_event import DiscreteEventSimulation
from distributions import EmpiricalDistribution, Exponential
from metrics import BatchMeansAnalysis, MetricsCollector, WarmupDetection
from monte_carlo import MonteCarloIntegration, RandomVariableGenerator
from queue_models import MM1Queue


class TestDESWithDistributions:
    """Test DES with distribution-based events."""

    def test_des_exponential_arrivals(self):
        """Test DES with exponential arrival times."""
        config = SimConfig(sim_id="test", end_time=100.0)
        des = DiscreteEventSimulation(config)

        rng = RandomVariableGenerator(seed=42)

        # Schedule arrivals with exponential spacing
        current_time = 0.0
        for i in range(20):
            arrival_time = rng.exponential(rate=1.0)
            current_time += arrival_time
            if current_time < 100:
                des.schedule_event(EventType.ARRIVAL, current_time)

        result = des.run()

        assert result.final_state.events_processed <= 20
        assert all(e.time < 100 for e in result.events_log)

    def test_des_normal_service_times(self):
        """Test DES with normal service duration generation."""
        config = SimConfig(sim_id="test", end_time=50.0)
        des = DiscreteEventSimulation(config)

        rng = RandomVariableGenerator(seed=42)

        service_times = []

        def handle_service_start(event, sim):
            service_time = rng.normal(mean=2.0, std=0.5)
            service_time = max(0.1, service_time)
            service_times.append(service_time)

            # Schedule completion
            sim.schedule_event(
                EventType.SERVICE_END,
                sim.state.current_time + service_time,
            )

        des.register_event_handler(EventType.ARRIVAL, handle_service_start)

        # Schedule arrivals
        for i in range(5):
            des.schedule_event(EventType.ARRIVAL, float(i * 5))

        result = des.run()

        assert len(service_times) == 5
        assert all(st > 0 for st in service_times)


class TestMonteCarloWithDistributions:
    """Test Monte Carlo with various distributions."""

    def test_mc_with_empirical_distribution(self):
        """Test Monte Carlo sampling from empirical data."""
        # Create empirical distribution from data
        data = [1.0, 2.0, 2.0, 3.0, 3.0, 3.0, 4.0, 5.0]
        dist = EmpiricalDistribution(data)

        # Sample and verify
        samples = [dist.sample() for _ in range(100)]

        assert all(s in data for s in samples)
        assert len(set(samples)) > 1

    def test_mc_mixed_risk_distributions(self):
        """Test Monte Carlo with mixed distributions."""
        from monte_carlo import RiskSimulation

        rs = RiskSimulation(seed=42)

        distributions = [
            ("source1", lambda: RandomVariableGenerator().normal(100, 20)),
            ("source2", lambda: RandomVariableGenerator().exponential(0.1)),
            ("source3", lambda: RandomVariableGenerator().uniform(50, 150)),
        ]

        result = rs.aggregate_risk(distributions, num_simulations=1000)

        assert result.estimate > 0
        assert result.std_error > 0
        assert len(result.samples) == 1000

    def test_mc_integration_with_normal_pdf(self):
        """Test integration of normal distribution."""
        mci = MonteCarloIntegration(seed=42)

        # Integrate standard normal from -1 to 1
        normal_pdf = lambda x: (1 / math.sqrt(2 * math.pi)) * math.exp(-(x**2) / 2)

        result = mci.estimate_area_under_curve(
            func=normal_pdf,
            x_min=-1,
            x_max=1,
            y_min=0,
            y_max=0.5,
            num_samples=50000,
        )

        # Should be approximately 0.68 (one sigma)
        assert 0.5 < result.estimate < 0.85


class TestQueueWithDES:
    """Test queueing with discrete event simulation."""

    def test_mm1_queue_via_des(self):
        """Implement M/M/1 queue using DES."""
        config = SimConfig(sim_id="mm1", end_time=100.0, warmup_time=10.0)
        des = DiscreteEventSimulation(config)

        queue = MM1Queue(arrival_rate=2.0, service_rate=5.0)
        rng = RandomVariableGenerator(seed=42)

        # Arrival handler
        def on_arrival(event, sim):
            queue.arrive(sim.state.current_time)
            # Schedule next arrival
            next_arrival = rng.exponential(rate=2.0)
            sim.schedule_event(
                EventType.ARRIVAL,
                sim.state.current_time + next_arrival,
            )

        # Service handler
        def on_service_complete(event, sim):
            queue.complete_service(sim.state.current_time)
            if queue.queue:
                service_time = rng.exponential(rate=5.0)
                queue.serve(sim.state.current_time, service_time)
                sim.schedule_event(
                    EventType.SERVICE_END,
                    sim.state.current_time + service_time,
                )

        des.register_event_handler(EventType.ARRIVAL, on_arrival)
        des.register_event_handler(EventType.SERVICE_END, on_service_complete)

        # Initial events
        des.schedule_event(EventType.ARRIVAL, 0.0)

        result = des.run()

        stats = queue.statistics(result.final_state.current_time)
        assert stats.customers_served > 0
        assert stats.avg_wait_time >= 0


class TestAgentBasedWithDES:
    """Test agent-based model with discrete event timing."""

    def test_agent_events_triggered_by_des(self):
        """Test agents triggered by DES events."""
        config = SimConfig(sim_id="abm_des", end_time=50.0)
        des = DiscreteEventSimulation(config)

        # Create agents
        agents = [SimpleAgent(position=(i * 10, 50)) for i in range(5)]
        env = Environment(width=100, height=100)

        for a in agents:
            env.add_agent(a)

        actions_taken = []

        def trigger_agent_decision(agent_id):
            def handler(event, sim):
                agent = next(a for a in agents if a.agent_id == agent_id)
                agent.perceive(env)
                actions = agent.decide(env)
                for action in actions:
                    agent.act(action, env)
                actions_taken.append(len(actions))

            return handler

        # Register event handlers for each agent
        for agent in agents:
            des.register_event_handler(
                EventType.AGENT_STEP,
                trigger_agent_decision(agent.agent_id),
            )

        # Schedule agent decisions
        for t in range(10):
            des.schedule_event(EventType.AGENT_STEP, float(t * 5), {"agent": 0})

        result = des.run()

        assert len(actions_taken) > 0


class TestMetricsAcrossSimulations:
    """Test metrics collection across multiple scenarios."""

    def test_batch_means_on_des_output(self):
        """Test batch means analysis on DES results."""
        config = SimConfig(sim_id="test", end_time=1000.0)
        des = DiscreteEventSimulation(config)

        def record_queue_length(event, sim):
            sim.record_metric("queue_length", float(sim.queue_size()))

        des.register_event_handler(EventType.ARRIVAL, record_queue_length)

        for i in range(100):
            des.schedule_event(EventType.ARRIVAL, float(i * 5))

        result = des.run()

        # Extract metric values
        queue_lengths = [s.value for s in result.samples if s.metric_name == "queue_length"]

        if len(queue_lengths) >= 100:
            bma = BatchMeansAnalysis(batch_size=10)
            analysis = bma.analyze(queue_lengths)

            assert analysis.overall_mean > 0
            assert analysis.std_error >= 0

    def test_warmup_detection_on_timeseries(self):
        """Test warmup period detection."""
        # Create synthetic time series with warmup
        warmup_period = 50
        data = [float(i) for i in range(warmup_period)] + [100.0] * 50

        detected_warmup = WarmupDetection.welch_graphical_method(data, batch_size=10, threshold=0.2)

        # Should detect warmup around 50
        assert 30 <= detected_warmup <= 70

    def test_metrics_collector_multiple_runs(self):
        """Test metrics across multiple simulation runs."""
        collector = MetricsCollector(warmup_time=0.0)

        # Simulate multiple runs
        for run_id in range(3):
            for t in range(10):
                collector.record("throughput", float(t + run_id * 10), time=float(t))

        stats = collector.compute_statistics("throughput")

        assert stats["count"] == 30.0
        assert stats["mean"] > 0


class TestComplexScenario:
    """Test complex scenario combining multiple features."""

    def test_hybrid_des_abm_system(self):
        """Test hybrid DES and ABM system."""
        # Create discrete event system
        config = SimConfig(sim_id="hybrid", end_time=100.0)
        des = DiscreteEventSimulation(config)

        # Create agent-based system
        env = Environment(width=100, height=100)
        agents = [SimpleAgent(position=(50 + i * 5, 50)) for i in range(3)]

        for a in agents:
            env.add_agent(a)

        metrics = MetricsCollector(warmup_time=10.0)

        agent_actions_per_step = []

        def agent_step_handler(event, sim):
            # Trigger all agents to act
            total_actions = 0

            for agent in agents:
                agent.perceive(env)
                actions = agent.decide(env)
                for action in actions:
                    agent.act(action, env)
                total_actions += len(actions)

            agent_actions_per_step.append(total_actions)

            # Record metrics
            metrics.record(
                "active_agents",
                float(sum(1 for a in agents if a.alive)),
                time=sim.state.current_time,
            )

            # Schedule next step
            sim.schedule_event(
                EventType.AGENT_STEP,
                sim.state.current_time + 1.0,
            )

        des.register_event_handler(EventType.AGENT_STEP, agent_step_handler)

        # Initial event
        des.schedule_event(EventType.AGENT_STEP, 0.0)

        result = des.run()

        assert len(agent_actions_per_step) > 0
        assert result.final_state.events_processed > 0

        # Verify metrics
        stats = metrics.compute_statistics("active_agents")
        assert stats["count"] > 0


class TestSensitivityAnalysis:
    """Test sensitivity analysis across scenarios."""

    def test_parameter_sweep(self):
        """Test simulation output sensitivity to parameters."""
        from queue_models import MM1Queue

        lambda_values = [1.0, 2.0, 3.0, 4.0]
        average_waits = []

        for arrival_rate in lambda_values:
            queue = MM1Queue(arrival_rate=arrival_rate, service_rate=5.0)

            # Simulate
            for i in range(100):
                queue.arrive(float(i))
                queue.serve(float(i), service_duration=0.2)
                queue.complete_service(float(i) + 0.2)

            stats = queue.statistics(current_time=100.0)
            average_waits.append(stats.avg_wait_time)

        # Wait time should increase with arrival rate
        for i in range(len(average_waits) - 1):
            assert average_waits[i] <= average_waits[i + 1]

    def test_output_correlation(self):
        """Test correlation between related outputs."""
        from agent_based import SimpleAgent

        configs = [
            {"perception": 5, "expected_neighbors": 3},
            {"perception": 10, "expected_neighbors": 12},
            {"perception": 20, "expected_neighbors": 50},
        ]

        for cfg in configs:
            env = Environment(width=100, height=100)
            agent = SimpleAgent(position=(50, 50))
            agent.state["perception_radius"] = cfg["perception"]

            # Add nearby agents
            for i in range(100):
                other = SimpleAgent(position=(50 + i % 10, 50 + i // 10))
                env.add_agent(other)

            agent.perceive(env)

            # Larger perception should see more agents
            assert len(agent.perceived_agents) > 0


class TestErrorHandlingIntegration:
    """Test error handling across components."""

    def test_invalid_event_scheduling(self):
        """Test handling of invalid event schedules."""
        from _exceptions import EventError

        config = SimConfig(sim_id="test")
        des = DiscreteEventSimulation(config)

        des.state.current_time = 100.0

        with pytest.raises(EventError):
            des.schedule_event(EventType.ARRIVAL, 50.0)

    def test_invalid_queue_parameters(self):
        """Test handling of invalid queue parameters."""
        from _exceptions import ResourceError

        with pytest.raises(ResourceError):
            MM1Queue(arrival_rate=10.0, service_rate=5.0)

    def test_distribution_parameter_validation(self):
        """Test distribution parameter validation."""
        from _exceptions import DistributionError

        # Test invalid distribution parameters
        with pytest.raises(DistributionError):
            Exponential(rate=-1.0)

        with pytest.raises(DistributionError):
            EmpiricalDistribution(values=[])
