"""
Type definitions for the telecommunications network module.

Provides comprehensive data structures for cells, base stations, subscribers,
call records, channels, frequencies, protocols, and network slices.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Literal


class Modulation(Enum):
    """Modulation schemes used in various technologies."""

    GMSK = "GMSK"  # GSM
    QPSK = "QPSK"  # UMTS
    QAM16 = "16QAM"  # LTE
    QAM64 = "64QAM"  # LTE
    QAM256 = "256QAM"  # 5G NR
    BPSK = "BPSK"


class Protocol(Enum):
    """Network protocols/generations."""

    GSM = "2G"
    UMTS = "3G"
    LTE = "4G"
    NR = "5G"


class BandwidthType(Enum):
    """Bandwidth options in MHz."""

    BW_20 = 20
    BW_10 = 10
    BW_5 = 5
    BW_1_4 = 1.4
    BW_400 = 400  # 5G NR mmWave


@dataclass
class Bandwidth:
    """Bandwidth specification."""

    mhz: float
    type: BandwidthType

    def __post_init__(self) -> None:
        if self.mhz <= 0:
            raise ValueError(f"Bandwidth must be positive, got {self.mhz}")

    def to_hz(self) -> float:
        """Convert bandwidth to Hz."""
        return self.mhz * 1e6

    def to_khz(self) -> float:
        """Convert bandwidth to kHz."""
        return self.mhz * 1e3


@dataclass
class Latency:
    """Latency specification in milliseconds."""

    ms: float

    def __post_init__(self) -> None:
        if self.ms < 0:
            raise ValueError(f"Latency cannot be negative, got {self.ms}")

    def to_seconds(self) -> float:
        """Convert to seconds."""
        return self.ms / 1000.0


@dataclass
class Frequency:
    """Frequency specification."""

    mhz: float
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])

    def __post_init__(self) -> None:
        if self.mhz <= 0:
            raise ValueError(f"Frequency must be positive, got {self.mhz}")

    def to_hz(self) -> float:
        """Convert to Hz."""
        return self.mhz * 1e6

    def to_ghz(self) -> float:
        """Convert to GHz."""
        return self.mhz / 1000.0

    def __hash__(self) -> int:
        return hash(self.mhz)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Frequency):
            return NotImplemented
        return self.mhz == other.mhz


@dataclass
class SignalStrength:
    """Signal strength in dBm."""

    dbm: float

    def __post_init__(self) -> None:
        if self.dbm > 0:
            raise ValueError(f"Signal strength cannot be positive, got {self.dbm}")

    def to_watts(self) -> float:
        """Convert dBm to watts."""
        return 10 ** (self.dbm / 10) / 1000

    def to_linear(self) -> float:
        """Convert dBm to linear scale."""
        return 10 ** (self.dbm / 10)


@dataclass
class Channel:
    """Communication channel specification."""

    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    frequency: Frequency = field(default_factory=lambda: Frequency(2100.0))
    bandwidth: Bandwidth = field(default_factory=lambda: Bandwidth(20.0, BandwidthType.BW_20))
    modulation: Modulation = Modulation.QAM64
    protocol: Protocol = Protocol.LTE
    signal_strength: SignalStrength | None = None
    snr_db: float = 15.0

    def capacity_bps(self) -> float:
        """Shannon capacity in bits per second."""
        bw_hz = self.bandwidth.to_hz()
        snr_linear = 10 ** (self.snr_db / 10)
        return bw_hz * (1 + snr_linear)


@dataclass
class Antenna:
    """Antenna specification."""

    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    gain_dbi: float = 10.0  # Antenna gain in dBi
    tilt_degrees: float = 0.0
    azimuth_degrees: float = 0.0
    pattern_type: Literal["isotropic", "directional", "mimo"] = "directional"
    num_elements: int = 1  # MIMO array size
    frequency: Frequency = field(default_factory=lambda: Frequency(2100.0))

    def __post_init__(self) -> None:
        if self.gain_dbi < 0:
            raise ValueError(f"Antenna gain cannot be negative, got {self.gain_dbi}")
        if not (0 <= self.tilt_degrees <= 90):
            raise ValueError(f"Antenna tilt must be 0-90 degrees, got {self.tilt_degrees}")


@dataclass
class Cell:
    """Represents a single cell (sector) in the network."""

    lat: float
    lon: float
    radius_meters: float
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    protocol: Protocol = Protocol.LTE
    frequencies: list[Frequency] = field(default_factory=list)
    channels: dict[str, Channel] = field(default_factory=dict)
    antenna: Antenna = field(default_factory=Antenna)
    max_subscribers: int = 500
    active_subscribers: int = 0
    tx_power_dbm: float = 46.0  # Typical base station power
    noise_figure_db: float = 5.0

    def __post_init__(self) -> None:
        if self.radius_meters <= 0:
            raise ValueError(f"Cell radius must be positive, got {self.radius_meters}")
        if not (-90 <= self.lat <= 90):
            raise ValueError(f"Invalid latitude: {self.lat}")
        if not (-180 <= self.lon <= 180):
            raise ValueError(f"Invalid longitude: {self.lon}")

    def coverage_area_km2(self) -> float:
        """Calculate coverage area in km²."""
        radius_km = self.radius_meters / 1000
        return 3.14159 * (radius_km**2)

    def load_percentage(self) -> float:
        """Get current load as percentage."""
        return (self.active_subscribers / self.max_subscribers) * 100 if self.max_subscribers > 0 else 0


@dataclass
class BaseStation:
    """Represents a base station with multiple cells."""

    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    lat: float = 0.0
    lon: float = 0.0
    cells: dict[str, Cell] = field(default_factory=dict)
    backhaul_capacity_mbps: float = 1000.0
    backhaul_utilization_percent: float = 0.0
    power_consumption_watts: float = 0.0
    commissioned_date: datetime = field(default_factory=datetime.now)

    def total_coverage_km2(self) -> float:
        """Total coverage area of all cells."""
        return sum(cell.coverage_area_km2() for cell in self.cells.values())

    def total_active_subscribers(self) -> int:
        """Total active subscribers across all cells."""
        return sum(cell.active_subscribers for cell in self.cells.values())


@dataclass
class Subscriber:
    """Represents a mobile subscriber."""

    msisdn: str  # Phone number
    imsi: str  # International Mobile Subscriber Identity
    imei: str  # International Mobile Equipment Identity
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = field(default="")
    plan_type: Literal["prepaid", "postpaid"] = "postpaid"
    protocol: Protocol = Protocol.LTE
    current_cell: Cell | None = None
    balance_credits: float = 0.0
    monthly_quota_gb: float = 10.0
    used_data_gb: float = 0.0
    used_voice_minutes: float = 0.0
    used_sms_count: int = 0
    registration_date: datetime = field(default_factory=datetime.now)
    last_activity: datetime = field(default_factory=datetime.now)
    roaming_enabled: bool = False
    active: bool = True

    def available_data_gb(self) -> float:
        """Remaining data quota."""
        return max(0.0, self.monthly_quota_gb - self.used_data_gb)

    def data_usage_percent(self) -> float:
        """Data usage as percentage."""
        return (self.used_data_gb / self.monthly_quota_gb * 100) if self.monthly_quota_gb > 0 else 0


@dataclass
class CallRecord:
    """Call Detail Record (CDR) for billing."""

    msisdn: str
    destination: str
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    start_time: datetime = field(default_factory=datetime.now)
    end_time: datetime | None = None
    duration_seconds: float = 0.0
    call_type: Literal["voice", "sms", "data"] = "voice"
    data_volume_mb: float = 0.0
    source_cell: str | None = None
    destination_cell: str | None = None
    handovers: int = 0
    dropped: bool = False
    cost_currency: float = 0.0
    roaming: bool = False

    def duration_minutes(self) -> float:
        """Get duration in minutes."""
        return self.duration_seconds / 60.0


@dataclass
class QoSProfile:
    """Quality of Service profile."""

    name: str
    qos_class: Literal["conversational", "streaming", "interactive", "background"]
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    guaranteed_bitrate_kbps: float = 0.0
    max_bitrate_kbps: float = 0.0
    max_delay_ms: float = 100.0
    max_jitter_ms: float = 50.0
    packet_loss_percent: float = 0.1
    priority: int = 5  # 1-9, higher = more priority

    def __post_init__(self) -> None:
        if not (1 <= self.priority <= 9):
            raise ValueError(f"Priority must be 1-9, got {self.priority}")


@dataclass
class Handover:
    """Handover event record."""

    msisdn: str
    source_cell: str
    target_cell: str
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: datetime = field(default_factory=datetime.now)
    handover_type: Literal["hard", "soft", "inter-rat"] = "hard"
    success: bool = True
    drop_probability: float = 0.01
    duration_ms: float = 50.0


@dataclass
class NetworkSlice:
    """5G network slice."""

    name: str
    slice_type: Literal["eMBB", "URLLC", "mMTC"]
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    subscribers: set[str] = field(default_factory=set)
    allocated_spectrum_mhz: float = 0.0
    allocated_compute_percent: float = 0.0
    latency_sla_ms: float = 100.0
    throughput_sla_gbps: float = 1.0
    reliability_sla_percent: float = 99.9
    traffic_volume_gb: float = 0.0

    def resource_utilization(self) -> float:
        """Calculate resource utilization percentage."""
        return (self.allocated_compute_percent + self.allocated_spectrum_mhz / 100) / 2


__all__ = [
    "Cell",
    "BaseStation",
    "Subscriber",
    "CallRecord",
    "Channel",
    "Frequency",
    "Modulation",
    "Protocol",
    "NetworkSlice",
    "QoSProfile",
    "Handover",
    "Antenna",
    "SignalStrength",
    "Bandwidth",
    "Latency",
    "BandwidthType",
]
