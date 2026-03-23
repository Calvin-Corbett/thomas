"""
Protocol stack implementation for 2G/3G/4G/5G networks.

Implements GSM/UMTS/LTE/5G NR frame structures, OFDM allocation, resource
scheduling, HARQ processes, and RRC state machines.
"""

import random
from dataclasses import dataclass, field
from enum import Enum

from thomas.marketplace.telecom._types import Modulation, Protocol


class RRCState(Enum):
    """RRC (Radio Resource Control) states."""

    IDLE = "idle"
    CONNECTED = "connected"
    INACTIVE = "inactive"


class ResourceAllocationScheme(Enum):
    """Resource scheduling algorithms."""

    ROUND_ROBIN = "round_robin"
    PROPORTIONAL_FAIR = "proportional_fair"
    MAX_THROUGHPUT = "max_throughput"
    MAX_MIN_FAIR = "max_min_fair"


@dataclass
class FrameStructure:
    """Frame structure for different protocols."""

    protocol: Protocol
    frame_duration_ms: float
    slots_per_frame: int
    subframes_per_slot: int
    subcarriers_per_rb: int = 12
    rbs_per_frame: int = 50

    def total_subcarriers(self) -> int:
        """Total subcarriers in frame."""
        return self.rbs_per_frame * self.subcarriers_per_rb

    def total_symbols_per_frame(self) -> int:
        """Total OFDM symbols per frame."""
        return self.slots_per_frame * self.subframes_per_slot * 7


@dataclass
class ProtocolStack:
    """Protocol stack implementation."""

    protocol: Protocol = Protocol.LTE
    frame_structures: dict[Protocol, FrameStructure] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.frame_structures = {
            Protocol.GSM: FrameStructure(
                protocol=Protocol.GSM,
                frame_duration_ms=4.615,
                slots_per_frame=8,
                subframes_per_slot=1,
                rbs_per_frame=24,
            ),
            Protocol.UMTS: FrameStructure(
                protocol=Protocol.UMTS,
                frame_duration_ms=10.0,
                slots_per_frame=15,
                subframes_per_slot=1,
                subcarriers_per_rb=1,
                rbs_per_frame=1,
            ),
            Protocol.LTE: FrameStructure(
                protocol=Protocol.LTE,
                frame_duration_ms=10.0,
                slots_per_frame=10,
                subframes_per_slot=2,
                subcarriers_per_rb=12,
                rbs_per_frame=50,
            ),
            Protocol.NR: FrameStructure(
                protocol=Protocol.NR,
                frame_duration_ms=10.0,
                slots_per_frame=10,
                subframes_per_slot=2,
                subcarriers_per_rb=12,
                rbs_per_frame=273,
            ),
        }

    def get_frame_structure(self) -> FrameStructure:
        """
        Get frame structure for current protocol.

        Returns:
            FrameStructure instance
        """
        return self.frame_structures[self.protocol]

    def calculate_frame_capacity_bits(self, modulation: Modulation) -> float:
        """
        Calculate frame capacity based on modulation.

        Args:
            modulation: Modulation scheme

        Returns:
            Capacity in bits per frame
        """
        bits_per_symbol = {
            Modulation.BPSK: 1,
            Modulation.QPSK: 2,
            Modulation.QAM16: 4,
            Modulation.QAM64: 6,
            Modulation.QAM256: 8,
            Modulation.GMSK: 1,
        }

        frame = self.get_frame_structure()
        symbols_per_frame = frame.total_symbols_per_frame()
        subcarriers = frame.total_subcarriers()
        bits_per_mod = bits_per_symbol.get(modulation, 1)

        return symbols_per_frame * subcarriers * bits_per_mod

    def estimate_transport_block_size(self, num_prbs: int, modulation: Modulation, coding_rate: float = 0.5) -> int:
        """
        Estimate transport block size.

        Args:
            num_prbs: Number of physical resource blocks
            modulation: Modulation scheme
            coding_rate: Channel coding rate (0.3-0.9)

        Returns:
            Transport block size in bits
        """
        bits_per_symbol = {
            Modulation.BPSK: 1,
            Modulation.QPSK: 2,
            Modulation.QAM16: 4,
            Modulation.QAM64: 6,
            Modulation.QAM256: 8,
        }

        bits_per_mod = bits_per_symbol.get(modulation, 1)
        frame = self.get_frame_structure()
        symbols_per_prb = frame.total_symbols_per_frame()

        tbs = int(num_prbs * symbols_per_prb * bits_per_mod * coding_rate)
        return tbs


@dataclass
class OFDMAllocator:
    """OFDM subcarrier allocation."""

    total_subcarriers: int = 1200  # 5G NR for 100 MHz
    subcarrier_spacing_khz: float = 15.0
    resource_blocks: int = 100
    subcarriers_per_rb: int = 12

    def allocate_subcarriers(self, user_id: str, num_rbs: int) -> list[int]:
        """
        Allocate contiguous resource blocks to user.

        Args:
            user_id: User identifier
            num_rbs: Number of resource blocks needed

        Returns:
            List of allocated RB indices
        """
        if num_rbs > self.resource_blocks:
            num_rbs = self.resource_blocks

        available_rbs = list(range(self.resource_blocks))
        random.shuffle(available_rbs)
        allocated = available_rbs[:num_rbs]

        return sorted(allocated)

    def calculate_bandwidth_mhz(self) -> float:
        """
        Calculate total bandwidth.

        Returns:
            Bandwidth in MHz
        """
        bandwidth_khz = self.total_subcarriers * self.subcarrier_spacing_khz
        return bandwidth_khz / 1000.0

    def get_rb_bandwidth_mhz(self) -> float:
        """
        Get bandwidth per resource block.

        Returns:
            Bandwidth per RB in MHz
        """
        rb_width_khz = self.subcarriers_per_rb * self.subcarrier_spacing_khz
        return rb_width_khz / 1000.0


@dataclass
class ResourceScheduler:
    """Resource block scheduling."""

    allocation_scheme: ResourceAllocationScheme = ResourceAllocationScheme.PROPORTIONAL_FAIR
    total_rbs: int = 100
    scheduling_interval_ms: int = 1
    user_queues: dict[str, float] = field(default_factory=dict)
    user_throughputs: dict[str, float] = field(default_factory=dict)

    def add_user(self, user_id: str) -> None:
        """
        Add user to scheduler.

        Args:
            user_id: User identifier
        """
        self.user_queues[user_id] = 0.0
        self.user_throughputs[user_id] = 0.1

    def allocate_resources(self, requested_rbs: dict[str, int]) -> dict[str, int]:
        """
        Allocate resources based on configured scheme.

        Args:
            requested_rbs: Requested RBs per user

        Returns:
            Allocated RBs per user
        """
        if self.allocation_scheme == ResourceAllocationScheme.ROUND_ROBIN:
            return self._round_robin_allocation(requested_rbs)
        elif self.allocation_scheme == ResourceAllocationScheme.PROPORTIONAL_FAIR:
            return self._proportional_fair_allocation(requested_rbs)
        elif self.allocation_scheme == ResourceAllocationScheme.MAX_THROUGHPUT:
            return self._max_throughput_allocation(requested_rbs)
        else:
            return self._max_min_fair_allocation(requested_rbs)

    def _round_robin_allocation(self, requested_rbs: dict[str, int]) -> dict[str, int]:
        """Round-robin allocation."""
        allocation = {}
        total_requested = sum(requested_rbs.values())
        available = self.total_rbs

        for user_id, requested in requested_rbs.items():
            share = int(requested / total_requested * available) if total_requested > 0 else 0
            allocation[user_id] = min(requested, share)

        return allocation

    def _proportional_fair_allocation(self, requested_rbs: dict[str, int]) -> dict[str, int]:
        """Proportional fair allocation."""
        allocation = {}
        weights = {}

        for user_id in requested_rbs:
            throughput = self.user_throughputs.get(user_id, 0.1)
            weights[user_id] = requested_rbs[user_id] / (throughput + 0.001)

        total_weight = sum(weights.values())
        available = self.total_rbs

        for user_id, weight in weights.items():
            share = int(weight / total_weight * available) if total_weight > 0 else 0
            allocation[user_id] = min(requested_rbs[user_id], share)

        return allocation

    def _max_throughput_allocation(self, requested_rbs: dict[str, int]) -> dict[str, int]:
        """Maximum throughput allocation."""
        allocation = {}
        users_by_throughput = sorted(
            requested_rbs.items(),
            key=lambda x: self.user_throughputs.get(x[0], 0.1),
            reverse=True,
        )

        available = self.total_rbs
        for user_id, requested in users_by_throughput:
            allocated = min(requested, available)
            allocation[user_id] = allocated
            available -= allocated

        return allocation

    def _max_min_fair_allocation(self, requested_rbs: dict[str, int]) -> dict[str, int]:
        """Max-min fairness allocation."""
        allocation = {user_id: 0 for user_id in requested_rbs}
        available = self.total_rbs
        remaining_users = set(requested_rbs.keys())

        while available > 0 and remaining_users:
            share = available / len(remaining_users)

            for user_id in list(remaining_users):
                if requested_rbs[user_id] <= share:
                    allocation[user_id] = requested_rbs[user_id]
                    available -= requested_rbs[user_id]
                    remaining_users.remove(user_id)

            for user_id in remaining_users:
                allocation[user_id] = int(share)

        return allocation


@dataclass
class HARQSimulator:
    """Hybrid Automatic Repeat Request (HARQ) simulation."""

    max_retransmissions: int = 4
    bler_initial: float = 0.1  # Block error rate
    bler_improvement_per_retx: float = 0.05
    coding_gain_db: float = 3.0

    def simulate_transmission(self, snr_db: float, num_retransmissions: int = 0) -> bool:
        """
        Simulate a transmission and determine success.

        Args:
            snr_db: Signal-to-noise ratio in dB
            num_retransmissions: Number of retransmissions

        Returns:
            True if transmission successful
        """
        import random

        bler = self.bler_initial / (1 + num_retransmissions * self.bler_improvement_per_retx)
        bler = max(0.001, bler - snr_db / 100)

        return random.random() > bler

    def harq_process(self, snr_db: float, initial_bler: float = None) -> tuple[bool, int]:
        """
        Simulate complete HARQ process.

        Args:
            snr_db: Signal-to-noise ratio in dB
            initial_bler: Custom initial BLER

        Returns:
            Tuple of (success, num_transmissions)
        """
        for attempt in range(self.max_retransmissions + 1):
            if self.simulate_transmission(snr_db, attempt):
                return True, attempt + 1

        return False, self.max_retransmissions + 1

    def calculate_effective_throughput(self, nominal_mbps: float, bler: float) -> float:
        """
        Calculate effective throughput accounting for retransmissions.

        Args:
            nominal_mbps: Nominal throughput in Mbps
            bler: Block error rate

        Returns:
            Effective throughput in Mbps
        """
        efficiency = 1.0
        for attempt in range(self.max_retransmissions):
            if attempt > 0:
                bler_attempt = bler / (1 + attempt * self.bler_improvement_per_retx)
                efficiency += (bler**attempt) * (1 - bler_attempt)

        return nominal_mbps * (1 - bler) / max(1.0, efficiency)


@dataclass
class RRCStateMachine:
    """RRC (Radio Resource Control) state machine."""

    current_state: RRCState = RRCState.IDLE
    idle_to_connected_delay_ms: float = 100.0
    connected_to_inactive_timeout_ms: float = 30000.0
    inactive_to_idle_timeout_ms: float = 60000.0
    last_activity_ms: float = 0.0

    def transition_to_connected(self) -> None:
        """
        Transition to connected state.
        """
        if self.current_state == RRCState.IDLE:
            self.current_state = RRCState.CONNECTED
            self.last_activity_ms = 0.0

    def transition_to_inactive(self) -> None:
        """
        Transition to inactive state (from connected).
        """
        if self.current_state == RRCState.CONNECTED:
            self.current_state = RRCState.INACTIVE

    def transition_to_idle(self) -> None:
        """
        Transition to idle state.
        """
        self.current_state = RRCState.IDLE

    def handle_activity(self) -> None:
        """
        Handle user activity (resets timers).
        """
        self.last_activity_ms = 0.0
        if self.current_state == RRCState.INACTIVE:
            self.transition_to_connected()

    def update_timers(self, time_elapsed_ms: float) -> None:
        """
        Update timers and potentially transition states.

        Args:
            time_elapsed_ms: Time elapsed since last update
        """
        self.last_activity_ms += time_elapsed_ms

        if self.current_state == RRCState.CONNECTED:
            if self.last_activity_ms > self.connected_to_inactive_timeout_ms:
                self.transition_to_inactive()

        elif self.current_state == RRCState.INACTIVE:
            if self.last_activity_ms > self.inactive_to_idle_timeout_ms:
                self.transition_to_idle()

    def get_state(self) -> RRCState:
        """
        Get current RRC state.

        Returns:
            Current RRCState
        """
        return self.current_state

    def is_data_transfer_possible(self) -> bool:
        """
        Check if data transfer is possible in current state.

        Returns:
            True if data transfer possible
        """
        return self.current_state in (RRCState.CONNECTED, RRCState.INACTIVE)


__all__ = [
    "ProtocolStack",
    "FrameStructure",
    "OFDMAllocator",
    "ResourceScheduler",
    "HARQSimulator",
    "RRCStateMachine",
    "RRCState",
    "ResourceAllocationScheme",
]
