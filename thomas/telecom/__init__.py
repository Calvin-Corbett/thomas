"""
Telecommunications Network Simulation and Management Module.

A comprehensive module for simulating cellular networks, managing subscribers,
handling billing, and optimizing network performance across 2G-5G technologies.
"""

from thomas.telecom._exceptions import (
    BillingError,
    HandoverFailedError,
    InterferenceError,
    NoSignalError,
    SpectrumError,
    TelecomError,
)
from thomas.telecom._types import (
    Antenna,
    Bandwidth,
    BaseStation,
    CallRecord,
    Cell,
    Channel,
    Frequency,
    Handover,
    Latency,
    Modulation,
    NetworkSlice,
    Protocol,
    QoSProfile,
    SignalStrength,
    Subscriber,
)
from thomas.telecom.analytics import (
    KPIMonitor,
    NetworkAnalytics,
)
from thomas.telecom.billing import (
    BillingEngine,
    InvoiceGenerator,
    RevenueAssurance,
    TariffPlan,
)
from thomas.telecom.five_g import (
    BeamManager,
    EdgeComputeOptimizer,
    MassiveMIMO,
    NetworkSlicingManager,
)
from thomas.telecom.network import (
    CellTowerOptimizer,
    FrequencyPlanner,
    HandoverManager,
    LoadBalancer,
    NetworkArchitecture,
)
from thomas.telecom.protocols import (
    HARQSimulator,
    OFDMAllocator,
    ProtocolStack,
    ResourceScheduler,
    RRCStateMachine,
)
from thomas.telecom.qos import (
    AdmissionControl,
    PacketScheduler,
    QoSManager,
    TrafficShaper,
)
from thomas.telecom.signal import (
    AntennaPattern,
    Beamformer,
    PathLossModel,
    SignalProcessor,
)
from thomas.telecom.spectrum import (
    CognitiveRadio,
    InterferenceCalculator,
    SpectrumManager,
)
from thomas.telecom.subscriber import (
    ChurnPredictor,
    SubscriberManager,
    UsageTracker,
)

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
    "TelecomError",
    "NoSignalError",
    "InterferenceError",
    "HandoverFailedError",
    "BillingError",
    "SpectrumError",
    "PathLossModel",
    "SignalProcessor",
    "AntennaPattern",
    "Beamformer",
    "NetworkArchitecture",
    "CellTowerOptimizer",
    "FrequencyPlanner",
    "HandoverManager",
    "LoadBalancer",
    "ProtocolStack",
    "OFDMAllocator",
    "ResourceScheduler",
    "HARQSimulator",
    "RRCStateMachine",
    "SubscriberManager",
    "UsageTracker",
    "ChurnPredictor",
    "BillingEngine",
    "TariffPlan",
    "InvoiceGenerator",
    "RevenueAssurance",
    "SpectrumManager",
    "InterferenceCalculator",
    "CognitiveRadio",
    "QoSManager",
    "TrafficShaper",
    "AdmissionControl",
    "PacketScheduler",
    "NetworkSlicingManager",
    "MassiveMIMO",
    "BeamManager",
    "EdgeComputeOptimizer",
    "NetworkAnalytics",
    "KPIMonitor",
]

__version__ = "1.0.0"
