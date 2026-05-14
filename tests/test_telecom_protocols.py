"""
Tests for protocol stack module.
"""

import pytest

from thomas.marketplace.telecom._types import Modulation, Protocol
from thomas.marketplace.telecom.protocols import (
    FrameStructure,
    HARQSimulator,
    OFDMAllocator,
    ProtocolStack,
    ResourceAllocationScheme,
    ResourceScheduler,
    RRCState,
    RRCStateMachine,
)


class TestProtocolStack:
    """Test protocol stack."""

    def test_protocol_stack_initialization(self) -> None:
        """Test protocol stack creation."""
        stack = ProtocolStack(protocol=Protocol.LTE)
        assert stack.protocol == Protocol.LTE

    def test_get_frame_structure_lte(self) -> None:
        """Test LTE frame structure."""
        stack = ProtocolStack(protocol=Protocol.LTE)
        frame = stack.get_frame_structure()
        assert frame.protocol == Protocol.LTE
        assert frame.frame_duration_ms == 10.0

    def test_get_frame_structure_nr(self) -> None:
        """Test 5G NR frame structure."""
        stack = ProtocolStack(protocol=Protocol.NR)
        frame = stack.get_frame_structure()
        assert frame.protocol == Protocol.NR
        assert frame.rbs_per_frame == 273

    def test_frame_capacity_calculation(self) -> None:
        """Test frame capacity calculation."""
        stack = ProtocolStack(protocol=Protocol.LTE)
        capacity = stack.calculate_frame_capacity_bits(Modulation.QAM64)
        assert capacity > 0

    def test_transport_block_size(self) -> None:
        """Test transport block size estimation."""
        stack = ProtocolStack(protocol=Protocol.LTE)
        tbs = stack.estimate_transport_block_size(num_prbs=25, modulation=Modulation.QAM64, coding_rate=0.75)
        assert tbs > 0


class TestFrameStructure:
    """Test frame structure."""

    def test_total_subcarriers(self) -> None:
        """Test total subcarriers calculation."""
        frame = FrameStructure(
            protocol=Protocol.LTE,
            frame_duration_ms=10.0,
            slots_per_frame=10,
            subframes_per_slot=2,
            subcarriers_per_rb=12,
            rbs_per_frame=50,
        )
        total_sc = frame.total_subcarriers()
        assert total_sc == 600

    def test_total_symbols_per_frame(self) -> None:
        """Test symbols per frame."""
        frame = FrameStructure(
            protocol=Protocol.LTE,
            frame_duration_ms=10.0,
            slots_per_frame=10,
            subframes_per_slot=2,
        )
        symbols = frame.total_symbols_per_frame()
        assert symbols == 140


class TestOFDMAllocator:
    """Test OFDM allocation."""

    def test_allocate_subcarriers(self) -> None:
        """Test subcarrier allocation."""
        allocator = OFDMAllocator(resource_blocks=100)
        allocated = allocator.allocate_subcarriers(user_id="user1", num_rbs=25)
        assert len(allocated) == 25
        assert all(0 <= rb < 100 for rb in allocated)

    def test_allocate_more_than_available(self) -> None:
        """Test allocating more RBs than available."""
        allocator = OFDMAllocator(resource_blocks=50)
        allocated = allocator.allocate_subcarriers(user_id="user1", num_rbs=100)
        assert len(allocated) <= 50

    def test_bandwidth_calculation(self) -> None:
        """Test total bandwidth calculation."""
        allocator = OFDMAllocator(total_subcarriers=1200, subcarrier_spacing_khz=15.0)
        bandwidth = allocator.calculate_bandwidth_mhz()
        assert bandwidth > 0
        assert abs(bandwidth - 18.0) < 0.1

    def test_rb_bandwidth(self) -> None:
        """Test RB bandwidth."""
        allocator = OFDMAllocator()
        rb_bw = allocator.get_rb_bandwidth_mhz()
        assert rb_bw > 0


class TestResourceScheduler:
    """Test resource scheduling."""

    def test_add_user(self) -> None:
        """Test adding user to scheduler."""
        scheduler = ResourceScheduler()
        scheduler.add_user("user1")
        assert "user1" in scheduler.user_queues

    def test_round_robin_allocation(self) -> None:
        """Test round-robin scheduling."""
        scheduler = ResourceScheduler(
            allocation_scheme=ResourceAllocationScheme.ROUND_ROBIN,
            total_rbs=100,
        )
        requested = {"user1": 30, "user2": 20, "user3": 25}
        allocated = scheduler.allocate_resources(requested)

        total_allocated = sum(allocated.values())
        assert total_allocated <= 100

    def test_proportional_fair_allocation(self) -> None:
        """Test proportional fair scheduling."""
        scheduler = ResourceScheduler(
            allocation_scheme=ResourceAllocationScheme.PROPORTIONAL_FAIR,
            total_rbs=100,
        )
        scheduler.add_user("user1")
        scheduler.add_user("user2")

        requested = {"user1": 30, "user2": 40}
        allocated = scheduler.allocate_resources(requested)

        assert sum(allocated.values()) <= 100

    def test_max_throughput_allocation(self) -> None:
        """Test max throughput scheduling."""
        scheduler = ResourceScheduler(
            allocation_scheme=ResourceAllocationScheme.MAX_THROUGHPUT,
            total_rbs=100,
        )
        scheduler.user_throughputs["user1"] = 5.0
        scheduler.user_throughputs["user2"] = 10.0

        requested = {"user1": 50, "user2": 50}
        allocated = scheduler.allocate_resources(requested)

        assert sum(allocated.values()) <= 100


class TestHARQSimulator:
    """Test HARQ simulation."""

    def test_transmission_success(self) -> None:
        """Test successful transmission."""
        harq = HARQSimulator()
        success = harq.simulate_transmission(snr_db=20.0)
        assert isinstance(success, bool)

    def test_harq_process(self) -> None:
        """Test HARQ process."""
        harq = HARQSimulator(max_retransmissions=4)
        success, num_tx = harq.harq_process(snr_db=10.0)
        assert isinstance(success, bool)
        assert 1 <= num_tx <= 5

    def test_effective_throughput(self) -> None:
        """Test effective throughput with HARQ."""
        harq = HARQSimulator()
        nominal = 100.0
        bler = 0.1

        effective = harq.calculate_effective_throughput(nominal, bler)
        assert effective <= nominal
        assert effective > 0


class TestRRCStateMachine:
    """Test RRC state machine."""

    def test_initial_idle_state(self) -> None:
        """Test initial state is idle."""
        rrc = RRCStateMachine()
        assert rrc.current_state == RRCState.IDLE

    def test_transition_idle_to_connected(self) -> None:
        """Test transition to connected."""
        rrc = RRCStateMachine()
        rrc.transition_to_connected()
        assert rrc.current_state == RRCState.CONNECTED

    def test_transition_connected_to_inactive(self) -> None:
        """Test transition to inactive."""
        rrc = RRCStateMachine()
        rrc.transition_to_connected()
        rrc.transition_to_inactive()
        assert rrc.current_state == RRCState.INACTIVE

    def test_transition_inactive_to_idle(self) -> None:
        """Test transition to idle."""
        rrc = RRCStateMachine()
        rrc.transition_to_connected()
        rrc.transition_to_inactive()
        rrc.transition_to_idle()
        assert rrc.current_state == RRCState.IDLE

    def test_activity_handling(self) -> None:
        """Test activity handling."""
        rrc = RRCStateMachine()
        rrc.transition_to_connected()
        rrc.transition_to_inactive()

        rrc.handle_activity()
        assert rrc.current_state == RRCState.CONNECTED

    def test_timer_transitions(self) -> None:
        """Test timer-based transitions."""
        rrc = RRCStateMachine(connected_to_inactive_timeout_ms=1000)
        rrc.transition_to_connected()

        rrc.update_timers(500)
        assert rrc.current_state == RRCState.CONNECTED

        rrc.update_timers(600)
        assert rrc.current_state == RRCState.INACTIVE

    def test_data_transfer_possible(self) -> None:
        """Test data transfer availability."""
        rrc = RRCStateMachine()

        assert rrc.is_data_transfer_possible() is False

        rrc.transition_to_connected()
        assert rrc.is_data_transfer_possible() is True

        rrc.transition_to_inactive()
        assert rrc.is_data_transfer_possible() is True

        rrc.transition_to_idle()
        assert rrc.is_data_transfer_possible() is False


class TestProtocolIntegration:
    """Integration tests for protocols."""

    def test_lte_to_nr_frame_structure(self) -> None:
        """Test difference between LTE and NR frame structures."""
        lte_stack = ProtocolStack(protocol=Protocol.LTE)
        nr_stack = ProtocolStack(protocol=Protocol.NR)

        lte_frame = lte_stack.get_frame_structure()
        nr_frame = nr_stack.get_frame_structure()

        assert lte_frame.rbs_per_frame < nr_frame.rbs_per_frame

    def test_rrc_state_machine_realistic_flow(self) -> None:
        """Test realistic RRC state machine flow."""
        rrc = RRCStateMachine(
            idle_to_connected_delay_ms=100,
            connected_to_inactive_timeout_ms=5000,
            inactive_to_idle_timeout_ms=10000,
        )

        assert rrc.current_state == RRCState.IDLE

        rrc.transition_to_connected()
        assert rrc.is_data_transfer_possible()

        rrc.update_timers(6000)
        assert rrc.current_state == RRCState.INACTIVE

        rrc.handle_activity()
        assert rrc.current_state == RRCState.CONNECTED


if __name__ == "__main__":
    pytest.main([__file__])
