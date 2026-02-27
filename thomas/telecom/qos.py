"""
Quality of Service (QoS) management module.

Implements QoS classes, traffic shaping, admission control, packet scheduling,
SLA monitoring, and Mean Opinion Score (MOS) estimation.
"""

import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum

from thomas.telecom._types import QoSProfile


class QoSClass(Enum):
    """QoS classes/categories."""

    CONVERSATIONAL = "conversational"  # Real-time (VoIP, video call)
    STREAMING = "streaming"  # Streaming media
    INTERACTIVE = "interactive"  # Web browsing, gaming
    BACKGROUND = "background"  # File transfer, email


@dataclass
class QoSManager:
    """Manage QoS policies and profiles."""

    profiles: dict[str, QoSProfile] = field(default_factory=dict)
    subscriber_profiles: dict[str, str] = field(default_factory=dict)
    sla_monitoring: dict[str, dict] = field(default_factory=dict)

    def add_profile(self, profile: QoSProfile) -> None:
        """
        Add QoS profile.

        Args:
            profile: QoSProfile to add
        """
        self.profiles[profile.id] = profile

    def assign_profile(self, msisdn: str, profile_id: str) -> bool:
        """
        Assign QoS profile to subscriber.

        Args:
            msisdn: Phone number
            profile_id: Profile ID

        Returns:
            True if successful
        """
        if profile_id not in self.profiles:
            return False

        self.subscriber_profiles[msisdn] = profile_id
        return True

    def get_subscriber_profile(self, msisdn: str) -> QoSProfile | None:
        """
        Get subscriber QoS profile.

        Args:
            msisdn: Phone number

        Returns:
            QoSProfile or None
        """
        profile_id = self.subscriber_profiles.get(msisdn)
        if profile_id:
            return self.profiles.get(profile_id)
        return None

    def monitor_sla(
        self,
        msisdn: str,
        achieved_latency_ms: float,
        achieved_jitter_ms: float,
        achieved_packet_loss_percent: float,
    ) -> dict[str, bool]:
        """
        Monitor SLA compliance.

        Args:
            msisdn: Phone number
            achieved_latency_ms: Achieved latency
            achieved_jitter_ms: Achieved jitter
            achieved_packet_loss_percent: Achieved packet loss

        Returns:
            Dict with SLA compliance status
        """
        profile = self.get_subscriber_profile(msisdn)
        if not profile:
            return {}

        compliance = {
            "latency_ok": achieved_latency_ms <= profile.max_delay_ms,
            "jitter_ok": achieved_jitter_ms <= profile.max_jitter_ms,
            "packet_loss_ok": achieved_packet_loss_percent <= profile.packet_loss_percent,
        }

        if msisdn not in self.sla_monitoring:
            self.sla_monitoring[msisdn] = {
                "violations": 0,
                "total_checks": 0,
            }

        self.sla_monitoring[msisdn]["total_checks"] += 1
        if not all(compliance.values()):
            self.sla_monitoring[msisdn]["violations"] += 1

        compliance["sla_compliant"] = (
            self.sla_monitoring[msisdn]["violations"] / self.sla_monitoring[msisdn]["total_checks"] < 0.01
        )

        return compliance


@dataclass
class TrafficShaper:
    """Traffic shaping using token bucket and leaky bucket algorithms."""

    bucket_capacity_bytes: float
    refill_rate_bps: float
    current_tokens: float = field(default_factory=float)
    last_refill_time: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        self.current_tokens = self.bucket_capacity_bytes
        self.last_refill_time = time.time()

    def add_tokens(self) -> None:
        """Refill tokens based on elapsed time."""
        current_time = time.time()
        time_elapsed = current_time - self.last_refill_time
        tokens_to_add = (self.refill_rate_bps / 8) * time_elapsed
        self.current_tokens = min(self.bucket_capacity_bytes, self.current_tokens + tokens_to_add)
        self.last_refill_time = current_time

    def can_transmit(self, packet_size_bytes: float) -> bool:
        """
        Check if packet can be transmitted (token bucket).

        Args:
            packet_size_bytes: Packet size in bytes

        Returns:
            True if packet can be transmitted
        """
        self.add_tokens()
        return self.current_tokens >= packet_size_bytes

    def transmit_packet(self, packet_size_bytes: float) -> bool:
        """
        Transmit packet if tokens available.

        Args:
            packet_size_bytes: Packet size in bytes

        Returns:
            True if transmitted
        """
        if self.can_transmit(packet_size_bytes):
            self.current_tokens -= packet_size_bytes
            return True
        return False

    def calculate_delay(self, packet_size_bytes: float) -> float:
        """
        Calculate transmission delay for packet.

        Args:
            packet_size_bytes: Packet size in bytes

        Returns:
            Delay in seconds
        """
        if self.current_tokens >= packet_size_bytes:
            return 0.0
        required_tokens = packet_size_bytes - self.current_tokens
        return (required_tokens * 8) / self.refill_rate_bps


@dataclass
class AdmissionControl:
    """Admission control for bandwidth reservation."""

    total_bandwidth_bps: float
    reserved_bandwidth_bps: float = 0.0
    reservations: dict[str, float] = field(default_factory=dict)

    def get_available_bandwidth(self) -> float:
        """
        Get available bandwidth.

        Returns:
            Available bandwidth in bps
        """
        return self.total_bandwidth_bps - self.reserved_bandwidth_bps

    def request_admission(self, flow_id: str, required_bps: float) -> bool:
        """
        Request bandwidth admission.

        Args:
            flow_id: Flow identifier
            required_bps: Required bandwidth in bps

        Returns:
            True if admission granted
        """
        available = self.get_available_bandwidth()
        if required_bps <= available:
            self.reservations[flow_id] = required_bps
            self.reserved_bandwidth_bps += required_bps
            return True
        return False

    def release_admission(self, flow_id: str) -> bool:
        """
        Release bandwidth reservation.

        Args:
            flow_id: Flow identifier

        Returns:
            True if successful
        """
        if flow_id in self.reservations:
            bandwidth = self.reservations[flow_id]
            self.reserved_bandwidth_bps -= bandwidth
            del self.reservations[flow_id]
            return True
        return False

    def get_admission_ratio(self) -> float:
        """
        Get admission ratio (accepted / requested).

        Returns:
            Ratio 0-1
        """
        if not self.reservations:
            return 0.0
        return self.reserved_bandwidth_bps / self.total_bandwidth_bps


@dataclass
class PacketScheduler:
    """Packet scheduling algorithms (WFQ, priority queue, etc.)."""

    queues: dict[str, deque] = field(default_factory=dict)
    weights: dict[str, float] = field(default_factory=dict)
    scheduler_type: str = "wfq"  # wfq, strict_priority, round_robin

    def add_queue(self, queue_id: str, weight: float = 1.0) -> None:
        """
        Add queue.

        Args:
            queue_id: Queue identifier
            weight: Queue weight for WFQ
        """
        self.queues[queue_id] = deque()
        self.weights[queue_id] = weight

    def enqueue(self, queue_id: str, packet: dict) -> bool:
        """
        Enqueue packet.

        Args:
            queue_id: Queue identifier
            packet: Packet data

        Returns:
            True if successful
        """
        if queue_id not in self.queues:
            return False

        self.queues[queue_id].append(packet)
        return True

    def dequeue_strict_priority(self) -> dict | None:
        """
        Dequeue using strict priority.

        Higher priority queues dequeued first.

        Returns:
            Packet or None
        """
        for queue_id in sorted(self.queues.keys(), reverse=True):
            if self.queues[queue_id]:
                return self.queues[queue_id].popleft()
        return None

    def dequeue_wfq(self) -> dict | None:
        """
        Dequeue using Weighted Fair Queuing.

        Returns:
            Packet or None
        """
        total_weight = sum(self.weights.values())
        if total_weight == 0:
            return None

        for queue_id in sorted(self.weights.keys(), key=lambda q: self.weights[q], reverse=True):
            if self.queues[queue_id]:
                return self.queues[queue_id].popleft()

        return None

    def dequeue_round_robin(self) -> dict | None:
        """
        Dequeue using round-robin.

        Returns:
            Packet or None
        """
        for queue_id in self.queues:
            if self.queues[queue_id]:
                return self.queues[queue_id].popleft()
        return None

    def dequeue(self) -> dict | None:
        """
        Dequeue next packet.

        Returns:
            Packet or None
        """
        if self.scheduler_type == "strict_priority":
            return self.dequeue_strict_priority()
        elif self.scheduler_type == "wfq":
            return self.dequeue_wfq()
        else:
            return self.dequeue_round_robin()

    def get_queue_depths(self) -> dict[str, int]:
        """
        Get depth of each queue.

        Returns:
            Dict mapping queue ID to depth
        """
        return {qid: len(queue) for qid, queue in self.queues.items()}


@dataclass
class MOSEstimator:
    """Estimate Mean Opinion Score for voice quality."""

    def estimate_mos_from_snr(self, snr_db: float) -> float:
        """
        Estimate MOS from SNR.

        Args:
            snr_db: Signal-to-noise ratio in dB

        Returns:
            MOS score (1-5)
        """
        if snr_db < 5:
            return 1.0
        elif snr_db > 35:
            return 4.5
        else:
            return 4.5 - 24 / (snr_db + 1)

    def estimate_mos_e_model(
        self,
        latency_ms: float,
        jitter_ms: float,
        packet_loss_percent: float,
        codec: str = "g711",
    ) -> float:
        """
        Estimate MOS using ITU-T E.800 model.

        Args:
            latency_ms: One-way latency in ms
            jitter_ms: Jitter in ms
            packet_loss_percent: Packet loss percentage
            codec: Codec type (g711, g729, gsm)

        Returns:
            MOS score (1-5)
        """
        codec_factor = {
            "g711": 0,
            "g729": 10,
            "gsm": 20,
        }.get(codec, 0)

        d_e = latency_ms + jitter_ms * 2 + 10

        if packet_loss_percent < 1:
            loss_penalty = packet_loss_percent
        else:
            loss_penalty = (packet_loss_percent - 1) * 40

        r_factor = 93.2 - d_e / 40 - loss_penalty - codec_factor

        mos = 1 + 0.035 * r_factor + 0.007 * (r_factor**2) / 300

        return max(1.0, min(5.0, mos))

    def get_quality_category(self, mos: float) -> str:
        """
        Get quality category from MOS score.

        Args:
            mos: MOS score (1-5)

        Returns:
            Quality category
        """
        if mos >= 4.0:
            return "Excellent"
        elif mos >= 3.5:
            return "Good"
        elif mos >= 3.0:
            return "Fair"
        elif mos >= 2.0:
            return "Poor"
        else:
            return "Bad"


__all__ = [
    "QoSManager",
    "TrafficShaper",
    "AdmissionControl",
    "PacketScheduler",
    "MOSEstimator",
    "QoSClass",
]
