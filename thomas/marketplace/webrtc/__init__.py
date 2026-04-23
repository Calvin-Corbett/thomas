"""WebRTC implementation for peer-to-peer communication.

Provides peer connections, data channels, and signaling
for real-time communication.
"""

from .core import (
    ConnectionState,
    DataChannel,
    DataChannelState,
    ICECandidate,
    ICEGatheringState,
    PeerConnection,
    RTCConfiguration,
    SignalingServer,
)

__all__ = [
    "ConnectionState",
    "DataChannelState",
    "ICEGatheringState",
    "RTCConfiguration",
    "ICECandidate",
    "DataChannel",
    "PeerConnection",
    "SignalingServer",
]

__version__ = "1.0.0"
