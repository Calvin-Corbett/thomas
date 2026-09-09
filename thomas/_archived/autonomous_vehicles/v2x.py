"""Vehicle-to-everything (V2X) communication system.

Includes V2V (vehicle-to-vehicle), V2I (vehicle-to-infrastructure),
platooning, cooperative merge, emergency vehicle preemption, and security.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from thomas.autonomous_vehicles._types import (
    TrafficLightState,
    Vector2D,
    VehicleState,
)


class V2XMessageType(Enum):
    """V2X message types."""

    CAM = "cam"  # Cooperative Awareness Message
    DENM = "denm"  # Decentralized Environmental Notification Message
    SPaT = "spat"  # Signal Phase and Timing
    MAP = "map"  # Map
    IVA = "iva"  # Infrastructure to Vehicle Alert
    PLATOONING = "platooning"  # Platooning protocol
    MERGE_REQUEST = "merge_request"  # Merge request
    EVP = "evp"  # Emergency Vehicle Preemption


@dataclass
class CAMMessage:
    """Cooperative Awareness Message (V2V)."""

    message_id: int
    sender_id: str
    timestamp: float
    position: Vector2D
    velocity: Vector2D
    heading: float
    speed: float
    acceleration: float
    vehicle_length: float
    vehicle_width: float
    steering_angle: float

    def to_dict(self: CAMMessage) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "message_id": self.message_id,
            "sender_id": self.sender_id,
            "timestamp": self.timestamp,
            "position": {"x": self.position.x, "y": self.position.y},
            "velocity": {"x": self.velocity.x, "y": self.velocity.y},
            "heading": self.heading,
            "speed": self.speed,
            "acceleration": self.acceleration,
            "vehicle_length": self.vehicle_length,
            "vehicle_width": self.vehicle_width,
            "steering_angle": self.steering_angle,
        }

    @classmethod
    def from_vehicle_state(cls: type, sender_id: str, state: VehicleState, **kwargs: Any) -> CAMMessage:
        """Create CAM from vehicle state."""
        return cls(
            message_id=int(state.timestamp * 1000),
            sender_id=sender_id,
            timestamp=state.timestamp,
            position=state.position,
            velocity=state.velocity,
            heading=state.heading,
            speed=state.speed,
            acceleration=0.0,
            vehicle_length=kwargs.get("vehicle_length", 4.5),
            vehicle_width=kwargs.get("vehicle_width", 1.8),
            steering_angle=state.steering_angle,
        )


@dataclass
class SPaTMessage:
    """Signal Phase and Timing message (V2I)."""

    intersection_id: str
    timestamp: float
    lanes: dict[str, TrafficLightState]
    timing_info: dict[str, float]  # lane_id -> time_until_change

    def get_next_state(self: SPaTMessage, lane_id: str) -> tuple[TrafficLightState, float]:
        """Get next state for lane.

        Returns:
            Tuple of (current_state, time_until_change)
        """
        state = self.lanes.get(lane_id, TrafficLightState.RED)
        time_until = self.timing_info.get(lane_id, 0.0)
        return state, time_until


@dataclass
class MergeRequest:
    """Request for cooperative merge."""

    request_id: str
    requester_id: str
    timestamp: float
    current_position: Vector2D
    target_position: Vector2D
    desired_speed: float
    estimated_merge_time: float
    urgency_level: int = 0  # 0-10, 0=low, 10=emergency


@dataclass
class PlatooneMessage:
    """Platooning protocol message."""

    platoone_id: str
    leader_id: str
    timestamp: float
    formation: list[str]  # Vehicle IDs in order
    inter_vehicle_gap: float  # Target gap between vehicles
    speed: float
    acceleration: float
    heading: float


class MessageAuthenticator:
    """Message authentication and verification."""

    def __init__(self: MessageAuthenticator, shared_key: str = "default_key") -> None:
        """Initialize authenticator.

        Args:
            shared_key: Shared secret key for authentication
        """
        self.shared_key = shared_key

    def compute_signature(self: MessageAuthenticator, message: str) -> str:
        """Compute HMAC-SHA256 signature.

        Args:
            message: Message to sign

        Returns:
            Signature string
        """
        signature = hmac.new(
            self.shared_key.encode(),
            message.encode(),
            hashlib.sha256,
        ).hexdigest()
        return signature

    def verify_signature(self: MessageAuthenticator, message: str, signature: str) -> bool:
        """Verify message signature.

        Args:
            message: Message to verify
            signature: Signature to check

        Returns:
            True if signature is valid
        """
        computed = self.compute_signature(message)
        return hmac.compare_digest(computed, signature)


class V2VCommunicationModule:
    """Vehicle-to-Vehicle communication."""

    def __init__(
        self: V2VCommunicationModule,
        vehicle_id: str,
        broadcast_range: float = 500.0,
    ) -> None:
        """Initialize V2V module.

        Args:
            vehicle_id: This vehicle's ID
            broadcast_range: Communication range in meters
        """
        self.vehicle_id = vehicle_id
        self.broadcast_range = broadcast_range
        self.received_messages: list[CAMMessage] = []
        self.authenticator = MessageAuthenticator()

    def generate_cam(
        self: V2VCommunicationModule,
        vehicle_state: VehicleState,
        vehicle_length: float = 4.5,
        vehicle_width: float = 1.8,
    ) -> CAMMessage:
        """Generate Cooperative Awareness Message.

        Args:
            vehicle_state: Current vehicle state
            vehicle_length: Vehicle length
            vehicle_width: Vehicle width

        Returns:
            CAM message
        """
        return CAMMessage.from_vehicle_state(
            self.vehicle_id,
            vehicle_state,
            vehicle_length=vehicle_length,
            vehicle_width=vehicle_width,
        )

    def broadcast_cam(self: V2VCommunicationModule, message: CAMMessage) -> str:
        """Broadcast CAM with authentication.

        Args:
            message: Message to broadcast

        Returns:
            Signed message as JSON string
        """
        message_json = json.dumps(message.to_dict())
        signature = self.authenticator.compute_signature(message_json)

        broadcast_payload = {
            "message": message.to_dict(),
            "signature": signature,
            "type": V2XMessageType.CAM.value,
        }

        return json.dumps(broadcast_payload)

    def receive_cam(
        self: V2VCommunicationModule,
        broadcast_payload: str,
    ) -> CAMMessage | None:
        """Receive and verify CAM.

        Args:
            broadcast_payload: Signed message payload

        Returns:
            Verified CAM or None if verification fails
        """
        try:
            payload = json.loads(broadcast_payload)

            message_dict = payload["message"]
            signature = payload["signature"]

            # Verify signature
            message_json = json.dumps(message_dict)
            if not self.authenticator.verify_signature(message_json, signature):
                return None

            # Parse message
            cam = CAMMessage(
                message_id=message_dict["message_id"],
                sender_id=message_dict["sender_id"],
                timestamp=message_dict["timestamp"],
                position=Vector2D(message_dict["position"]["x"], message_dict["position"]["y"]),
                velocity=Vector2D(message_dict["velocity"]["x"], message_dict["velocity"]["y"]),
                heading=message_dict["heading"],
                speed=message_dict["speed"],
                acceleration=message_dict["acceleration"],
                vehicle_length=message_dict["vehicle_length"],
                vehicle_width=message_dict["vehicle_width"],
                steering_angle=message_dict["steering_angle"],
            )

            self.received_messages.append(cam)
            return cam

        except (json.JSONDecodeError, KeyError, TypeError):
            return None

    def get_nearby_vehicles(self: V2VCommunicationModule, ego_position: Vector2D) -> list[CAMMessage]:
        """Get messages from nearby vehicles.

        Args:
            ego_position: Ego vehicle position

        Returns:
            List of CAM messages from nearby vehicles
        """
        nearby = [
            msg for msg in self.received_messages if ego_position.distance_to(msg.position) <= self.broadcast_range
        ]

        return nearby


class V2ICommunicationModule:
    """Vehicle-to-Infrastructure communication."""

    def __init__(
        self: V2ICommunicationModule,
        vehicle_id: str,
        infrastructure_range: float = 1000.0,
    ) -> None:
        """Initialize V2I module.

        Args:
            vehicle_id: Vehicle ID
            infrastructure_range: Max range to infrastructure
        """
        self.vehicle_id = vehicle_id
        self.infrastructure_range = infrastructure_range
        self.traffic_light_info: dict[str, SPaTMessage] = {}
        self.speed_limit_zones: dict[str, float] = {}

    def query_spat(self: V2ICommunicationModule, intersection_id: str) -> SPaTMessage | None:
        """Query traffic light state and timing.

        Args:
            intersection_id: Intersection ID

        Returns:
            SPaT message or None
        """
        return self.traffic_light_info.get(intersection_id)

    def receive_spat(self: V2ICommunicationModule, message: SPaTMessage) -> None:
        """Receive Signal Phase and Timing message.

        Args:
            message: SPaT message from infrastructure
        """
        self.traffic_light_info[message.intersection_id] = message

    def get_speed_advisories(self: V2ICommunicationModule, position: Vector2D) -> dict[str, float]:
        """Get speed advisories for position.

        Args:
            position: Query position

        Returns:
            Dictionary of zone_id -> speed_limit
        """
        advisories = {}

        for zone_id, speed_limit in self.speed_limit_zones.items():
            # In real implementation, would check if position is in zone
            advisories[zone_id] = speed_limit

        return advisories


class PlatooningManager:
    """Manage platooning (vehicle following protocol)."""

    def __init__(self: PlatooningManager, vehicle_id: str) -> None:
        """Initialize platooning manager.

        Args:
            vehicle_id: Vehicle ID
        """
        self.vehicle_id = vehicle_id
        self.platoone_id: str | None = None
        self.is_leader = False
        self.formation: list[str] = []
        self.target_inter_vehicle_gap = 5.0  # meters
        self.target_speed = 25.0  # m/s

    def join_platoone(
        self: PlatooningManager,
        platoone_id: str,
        leader_id: str,
        formation: list[str],
    ) -> None:
        """Join a platoone.

        Args:
            platoone_id: Platoone ID
            leader_id: Leader vehicle ID
            formation: Vehicle IDs in platoone order
        """
        self.platoone_id = platoone_id
        self.is_leader = self.vehicle_id == leader_id
        self.formation = formation

    def create_platoone(self: PlatooningManager) -> str:
        """Create new platoone with this vehicle as leader.

        Returns:
            Platoone ID
        """
        self.platoone_id = f"platoone_{self.vehicle_id}_{int(datetime.now().timestamp())}"
        self.is_leader = True
        self.formation = [self.vehicle_id]
        return self.platoone_id

    def add_vehicle_to_platoone(self: PlatooningManager, vehicle_id: str) -> bool:
        """Add vehicle to platoone.

        Args:
            vehicle_id: Vehicle to add

        Returns:
            True if successful
        """
        if not self.is_leader or self.platoone_id is None:
            return False

        self.formation.append(vehicle_id)
        return True

    def compute_target_gap(
        self: PlatooningManager,
        vehicle_speed: float,
        safe_time_headway: float = 1.0,
    ) -> float:
        """Compute target inter-vehicle gap.

        Args:
            vehicle_speed: Speed of vehicles in platoone
            safe_time_headway: Safe time headway

        Returns:
            Target gap in meters
        """
        return max(2.0, vehicle_speed * safe_time_headway)


class CooperativeMergeManager:
    """Manage cooperative merge maneuvers."""

    def __init__(self: CooperativeMergeManager, vehicle_id: str) -> None:
        """Initialize cooperative merge manager.

        Args:
            vehicle_id: Vehicle ID
        """
        self.vehicle_id = vehicle_id
        self.merge_requests: dict[str, MergeRequest] = {}
        self.accepted_merges: list[str] = []

    def request_merge(
        self: CooperativeMergeManager,
        current_position: Vector2D,
        target_position: Vector2D,
        desired_speed: float,
    ) -> MergeRequest:
        """Create merge request.

        Args:
            current_position: Current position
            target_position: Target position after merge
            desired_speed: Desired speed for merge

        Returns:
            Merge request
        """
        request_id = f"merge_{self.vehicle_id}_{int(datetime.now().timestamp())}"

        request = MergeRequest(
            request_id=request_id,
            requester_id=self.vehicle_id,
            timestamp=datetime.now().timestamp(),
            current_position=current_position,
            target_position=target_position,
            desired_speed=desired_speed,
            estimated_merge_time=5.0,
            urgency_level=1,
        )

        self.merge_requests[request_id] = request
        return request

    def evaluate_merge_request(
        self: CooperativeMergeManager,
        request: MergeRequest,
        vehicle_position: Vector2D,
        vehicle_speed: float,
    ) -> tuple[bool, str]:
        """Evaluate if merge is safe to allow.

        Args:
            request: Merge request to evaluate
            vehicle_position: Current vehicle position
            vehicle_speed: Current vehicle speed

        Returns:
            Tuple of (can_accept, reason)
        """
        # Check if there is adequate gap
        gap_behind = abs(vehicle_position.x - request.current_position.x)
        gap_ahead = abs(request.target_position.x - vehicle_position.x)

        safe_gap = max(10.0, vehicle_speed * 1.5)

        if gap_behind < safe_gap or gap_ahead < safe_gap:
            return False, "Insufficient gap"

        # Check speed compatibility
        speed_difference = abs(vehicle_speed - request.desired_speed)
        if speed_difference > 5.0:
            return False, "Incompatible speed"

        return True, "Merge approved"

    def accept_merge(self: CooperativeMergeManager, request_id: str) -> bool:
        """Accept a merge request.

        Args:
            request_id: Merge request ID

        Returns:
            True if accepted
        """
        if request_id in self.merge_requests:
            self.accepted_merges.append(request_id)
            return True

        return False


class EmergencyVehiclePreemption:
    """Emergency Vehicle Preemption (EVP) system."""

    def __init__(self: EmergencyVehiclePreemption) -> None:
        """Initialize EVP system."""
        self.emergency_alerts: dict[str, dict[str, Any]] = {}

    def broadcast_emergency_alert(
        self: EmergencyVehiclePreemption,
        vehicle_id: str,
        position: Vector2D,
        heading: float,
        speed: float,
        urgency: int = 10,
    ) -> dict[str, Any]:
        """Broadcast emergency vehicle alert.

        Args:
            vehicle_id: Emergency vehicle ID
            position: Current position
            heading: Current heading
            speed: Current speed
            urgency: Urgency level (0-10)

        Returns:
            Alert message
        """
        alert = {
            "vehicle_id": vehicle_id,
            "position": {"x": position.x, "y": position.y},
            "heading": heading,
            "speed": speed,
            "urgency": urgency,
            "timestamp": datetime.now().timestamp(),
        }

        self.emergency_alerts[vehicle_id] = alert
        return alert

    def get_nearby_emergency_vehicles(
        self: EmergencyVehiclePreemption,
        position: Vector2D,
        radius: float = 1000.0,
    ) -> list[dict[str, Any]]:
        """Get nearby emergency vehicle alerts.

        Args:
            position: Query position
            radius: Search radius

        Returns:
            List of emergency alerts
        """
        nearby = []

        for alert in self.emergency_alerts.values():
            alert_pos = Vector2D(alert["position"]["x"], alert["position"]["y"])
            if position.distance_to(alert_pos) <= radius:
                nearby.append(alert)

        return nearby

    def should_yield(
        self: EmergencyVehiclePreemption,
        position: Vector2D,
        heading: float,
    ) -> tuple[bool, dict[str, Any] | None]:
        """Determine if vehicle should yield to emergency vehicle.

        Args:
            position: Current position
            heading: Current heading

        Returns:
            Tuple of (should_yield, closest_emergency)
        """
        nearby = self.get_nearby_emergency_vehicles(position)

        if not nearby:
            return False, None

        # Find closest emergency vehicle
        closest = min(
            nearby,
            key=lambda a: position.distance_to(Vector2D(a["position"]["x"], a["position"]["y"])),
        )

        # High urgency emergency vehicles should be yielded to
        if closest["urgency"] >= 8:
            return True, closest

        return False, closest
