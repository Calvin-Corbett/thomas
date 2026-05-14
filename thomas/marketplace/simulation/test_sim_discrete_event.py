"""
Tests for discrete event simulation engine.
"""

import pytest
from _exceptions import EventError
from _types import Event, EventType, SimConfig
from discrete_event import DiscreteEventSimulation


class TestEventScheduling:
    """Test event scheduling and processing."""

    def test_schedule_event(self):
        """Test basic event scheduling."""
        config = SimConfig(sim_id="test", end_time=100.0)
        des = DiscreteEventSimulation(config)

        event_id = des.schedule_event(EventType.ARRIVAL, 10.0, {"customer": 1})
        assert event_id >= 0

        next_event = des.peek_next_event()
        assert next_event is not None
        assert next_event.time == 10.0

    def test_schedule_event_in_past_fails(self):
        """Test that scheduling in past raises error."""
        config = SimConfig(sim_id="test")
        des = DiscreteEventSimulation(config)

        des.state.current_time = 10.0

        with pytest.raises(EventError):
            des.schedule_event(EventType.ARRIVAL, 5.0)

    def test_event_priority(self):
        """Test event priority ordering."""
        config = SimConfig(sim_id="test", end_time=100.0)
        des = DiscreteEventSimulation(config)

        # Schedule with different priorities at same time
        des.schedule_event(EventType.DEPARTURE, 10.0, priority=2)
        des.schedule_event(EventType.ARRIVAL, 10.0, priority=0)
        des.schedule_event(EventType.ARRIVAL, 10.0, priority=1)

        # Higher priority processed first
        events = []
        for _ in range(3):
            event = des.peek_next_event()
            if event:
                events.append(event)
                des._event_queue.pop(0)

        assert events[0].priority == 0
        assert events[1].priority == 1
        assert events[2].priority == 2

    def test_event_cancellation(self):
        """Test event cancellation."""
        config = SimConfig(sim_id="test", end_time=100.0)
        des = DiscreteEventSimulation(config)

        event_id = des.schedule_event(EventType.ARRIVAL, 10.0)
        assert des.queue_size() == 1

        cancelled = des.cancel_event(event_id)
        assert cancelled is True

        # Cancelled event still in queue but skipped during processing
        assert des.queue_size() == 1

    def test_event_handler_registry(self):
        """Test handler registration and execution."""
        config = SimConfig(sim_id="test", end_time=100.0)
        des = DiscreteEventSimulation(config)

        handler_called = []

        def test_handler(event: Event, sim: DiscreteEventSimulation):
            handler_called.append(True)

        des.register_event_handler(EventType.ARRIVAL, test_handler)

        event = Event(time=10.0, event_type=EventType.ARRIVAL, data={})
        des._process_event(event)

        assert len(handler_called) == 1

    def test_multiple_handlers_same_type(self):
        """Test multiple handlers for same event type."""
        config = SimConfig(sim_id="test")
        des = DiscreteEventSimulation(config)

        calls = []

        def handler1(event: Event, sim: DiscreteEventSimulation):
            calls.append(1)

        def handler2(event: Event, sim: DiscreteEventSimulation):
            calls.append(2)

        des.register_event_handler(EventType.ARRIVAL, handler1, priority=0)
        des.register_event_handler(EventType.ARRIVAL, handler2, priority=1)

        event = Event(time=10.0, event_type=EventType.ARRIVAL, data={})
        des._process_event(event)

        assert calls == [2, 1]  # Higher priority first


class TestSimulationExecution:
    """Test simulation execution and stopping."""

    def test_run_until_time_limit(self):
        """Test simulation stops at end time."""
        config = SimConfig(sim_id="test", start_time=0.0, end_time=100.0)
        des = DiscreteEventSimulation(config)

        des.schedule_event(EventType.ARRIVAL, 10.0)
        des.schedule_event(EventType.ARRIVAL, 50.0)
        des.schedule_event(EventType.ARRIVAL, 150.0)

        result = des.run()

        assert result.final_state.current_time >= 100.0
        assert result.final_state.stopped

    def test_run_until_event_limit(self):
        """Test simulation stops at event limit."""
        config = SimConfig(sim_id="test", max_events=5)
        des = DiscreteEventSimulation(config)

        for i in range(10):
            des.schedule_event(EventType.ARRIVAL, float(i))

        result = des.run()

        assert result.final_state.events_processed <= 5

    def test_run_until_no_events(self):
        """Test simulation stops when queue empty."""
        config = SimConfig(sim_id="test", end_time=1000.0)
        des = DiscreteEventSimulation(config)

        des.schedule_event(EventType.ARRIVAL, 10.0)
        des.schedule_event(EventType.ARRIVAL, 20.0)

        result = des.run()

        assert result.final_state.events_processed == 2
        assert des.queue_size() == 0

    def test_warmup_period(self):
        """Test warmup period excluded from metrics."""
        config = SimConfig(sim_id="test", end_time=100.0, warmup_time=50.0)
        des = DiscreteEventSimulation(config)

        def record_metric(event: Event, sim: DiscreteEventSimulation):
            sim.record_metric("test_metric", float(sim.state.events_processed))

        des.register_event_handler(EventType.ARRIVAL, record_metric)

        for i in range(10):
            des.schedule_event(EventType.ARRIVAL, float(i * 10))

        result = des.run()

        # Only events after warmup should be in samples
        warmup_samples = [s for s in result.samples if s.time < 50.0]
        assert len(warmup_samples) == 0


class TestStatisticsCollection:
    """Test statistics and metrics collection."""

    def test_event_count_statistics(self):
        """Test event counting statistics."""
        config = SimConfig(sim_id="test", end_time=100.0)
        des = DiscreteEventSimulation(config)

        for i in range(5):
            des.schedule_event(EventType.ARRIVAL, float(i * 10))

        for i in range(3):
            des.schedule_event(EventType.DEPARTURE, float(i * 15))

        result = des.run()

        assert result.metrics["event_count_arrival"] == 5.0
        assert result.metrics["event_count_departure"] == 3.0

    def test_metric_recording(self):
        """Test metric sample recording."""
        config = SimConfig(sim_id="test", end_time=100.0)
        des = DiscreteEventSimulation(config)

        def record_queue_length(event: Event, sim: DiscreteEventSimulation):
            sim.record_metric("queue_length", float(sim.queue_size()))

        des.register_event_handler(EventType.ARRIVAL, record_queue_length)

        for i in range(5):
            des.schedule_event(EventType.ARRIVAL, float(i))

        result = des.run()

        assert len(result.samples) == 5
        assert all(s.metric_name == "queue_length" for s in result.samples)

    def test_event_timing_statistics(self):
        """Test event timing analysis."""
        config = SimConfig(sim_id="test", end_time=100.0)
        des = DiscreteEventSimulation(config)

        for i in range(10):
            des.schedule_event(EventType.ARRIVAL, float(i * 5))

        result = des.run()

        assert "event_mean_time_arrival" in result.metrics
        assert "event_min_time_arrival" in result.metrics
        assert "event_max_time_arrival" in result.metrics

        mean = result.metrics["event_mean_time_arrival"]
        assert 20 <= mean <= 25  # Average of 0, 5, 10, ..., 45


class TestConditionalEvents:
    """Test conditional event handling."""

    def test_conditional_event_firing(self):
        """Test conditional event triggers."""
        config = SimConfig(sim_id="test", end_time=100.0)
        des = DiscreteEventSimulation(config)

        fired = []

        def condition(sim: DiscreteEventSimulation) -> bool:
            return sim.state.current_time >= 50.0

        def action(sim: DiscreteEventSimulation):
            fired.append(True)

        des.schedule_conditional_event(condition, action, check_frequency=10.0)

        for i in range(10):
            des.schedule_event(EventType.ARRIVAL, float(i * 15))

        des.run()

        assert len(fired) > 0

    def test_conditional_event_check_frequency(self):
        """Test conditional event check frequency."""
        config = SimConfig(sim_id="test", end_time=100.0)
        des = DiscreteEventSimulation(config)

        check_count = [0]

        def condition(sim: DiscreteEventSimulation) -> bool:
            check_count[0] += 1
            return False

        def action(sim: DiscreteEventSimulation):
            pass

        des.schedule_conditional_event(condition, action, check_frequency=20.0)

        for i in range(10):
            des.schedule_event(EventType.ARRIVAL, float(i * 15))

        des.run()

        # Should check less frequently due to check_frequency
        assert check_count[0] > 0


class TestEventProcessing:
    """Test event processing details."""

    def test_events_logged(self):
        """Test all events are logged."""
        config = SimConfig(sim_id="test", end_time=100.0)
        des = DiscreteEventSimulation(config)

        for i in range(5):
            des.schedule_event(EventType.ARRIVAL, float(i))

        result = des.run()

        assert len(result.events_log) == 5
        assert all(e.time >= 0 for e in result.events_log)

    def test_get_events_by_type(self):
        """Test filtering events by type."""
        config = SimConfig(sim_id="test", end_time=100.0)
        des = DiscreteEventSimulation(config)

        des.schedule_event(EventType.ARRIVAL, 10.0)
        des.schedule_event(EventType.DEPARTURE, 20.0)
        des.schedule_event(EventType.ARRIVAL, 30.0)

        des.run()

        arrivals = des.get_events_of_type(EventType.ARRIVAL)
        departures = des.get_events_of_type(EventType.DEPARTURE)

        assert len(arrivals) == 2
        assert len(departures) == 1

    def test_simulation_time_advancement(self):
        """Test simulation time advances correctly."""
        config = SimConfig(sim_id="test", end_time=100.0)
        des = DiscreteEventSimulation(config)

        times = [10.0, 25.0, 50.0, 75.0]
        for t in times:
            des.schedule_event(EventType.ARRIVAL, t)

        result = des.run()

        event_times = [e.time for e in result.events_log]
        assert event_times == sorted(times)
