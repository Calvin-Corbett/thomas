"""Digital forensics and timeline analysis.

Provides timeline reconstruction, hash analysis, network flow analysis,
artifact extraction, and chain of custody tracking.
"""

import hashlib
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4

from thomas.siem._exceptions import (
    HashAnalysisException,
    TimelineException,
)
from thomas.siem._types import (
    NetworkFlow,
    SecurityEvent,
    Timeline,
)


@dataclass
class Artifact:
    """Forensic artifact."""

    artifact_id: str = field(default_factory=lambda: str(uuid4()))
    artifact_type: str = ""  # file, registry, memory, network
    name: str = ""
    path: str = ""
    hash_md5: str = ""
    hash_sha256: str = ""
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChainOfCustody:
    """Chain of custody record."""

    custody_id: str = field(default_factory=lambda: str(uuid4()))
    artifact_id: str = ""
    acquired_by: str = ""
    acquired_at: datetime = field(default_factory=datetime.utcnow)
    location: str = ""
    hash_value: str = ""
    notes: str = ""


class TimelineReconstructor:
    """Reconstructs forensic timeline from multiple event sources."""

    def __init__(self):
        """Initialize timeline reconstructor."""
        self.timelines: dict[str, Timeline] = {}

    def build_timeline(self, events: list[SecurityEvent], timeline_id: str | None = None) -> Timeline:
        """Build forensic timeline from events.

        Args:
            events: Events to include.
            timeline_id: Optional timeline identifier.

        Returns:
            Constructed Timeline.

        Raises:
            TimelineException: If reconstruction fails.
        """
        try:
            if timeline_id is None:
                timeline_id = str(uuid4())

            timeline = Timeline(timeline_id=uuid4())

            # Add events sorted by timestamp
            for event in sorted(events, key=lambda e: e.timestamp):
                timeline.add_event(event)

            self.timelines[timeline_id] = timeline
            return timeline

        except Exception as e:
            raise TimelineException(f"Timeline reconstruction failed: {e}")

    def get_timeline_range(self, timeline_id: str, start: datetime, end: datetime) -> list[SecurityEvent] | None:
        """Get events in timeline within time range.

        Args:
            timeline_id: Timeline identifier.
            start: Start time.
            end: End time.

        Returns:
            List of events in range or None.
        """
        timeline = self.timelines.get(timeline_id)
        if not timeline:
            return None

        return timeline.get_events_in_range(start, end)

    def correlate_timelines(self, timeline_ids: list[str]) -> list[SecurityEvent]:
        """Correlate events across multiple timelines.

        Args:
            timeline_ids: Timeline identifiers.

        Returns:
            Combined sorted list of events.
        """
        all_events = []

        for timeline_id in timeline_ids:
            timeline = self.timelines.get(timeline_id)
            if timeline:
                all_events.extend(timeline.events)

        return sorted(all_events, key=lambda e: e.timestamp)


class FileHashAnalyzer:
    """Analyzes file hashes for known-bad detection."""

    def __init__(self):
        """Initialize hash analyzer."""
        self.known_bad_hashes: dict[str, dict[str, Any]] = {}
        self.file_hashes: dict[str, list[str]] = defaultdict(list)

    def add_known_bad_hash(
        self,
        hash_value: str,
        hash_type: str,
        malware_name: str,
        confidence: int = 100,
    ) -> None:
        """Add known-bad file hash.

        Args:
            hash_value: Hash value.
            hash_type: Hash type (md5, sha256).
            malware_name: Associated malware.
            confidence: Confidence (0-100).
        """
        self.known_bad_hashes[hash_value] = {
            "type": hash_type,
            "malware": malware_name,
            "confidence": confidence,
            "added_at": datetime.utcnow(),
        }

    def check_hash(self, hash_value: str) -> dict[str, Any] | None:
        """Check if hash is known-bad.

        Args:
            hash_value: Hash to check.

        Returns:
            Bad hash info or None if clean.

        Raises:
            HashAnalysisException: If check fails.
        """
        try:
            return self.known_bad_hashes.get(hash_value)
        except Exception as e:
            raise HashAnalysisException(f"Hash analysis failed: {e}")

    def calculate_file_hash(self, file_path: str, hash_type: str = "sha256") -> str:
        """Calculate hash of file.

        Args:
            file_path: Path to file.
            hash_type: Type of hash to calculate.

        Returns:
            Hash value.

        Raises:
            HashAnalysisException: If calculation fails.
        """
        try:
            if hash_type == "md5":
                hasher = hashlib.md5()
            elif hash_type == "sha256":
                hasher = hashlib.sha256()
            else:
                raise ValueError(f"Unsupported hash type: {hash_type}")

            # Simulate reading file
            with open(file_path, "rb") as f:
                while chunk := f.read(4096):
                    hasher.update(chunk)

            return hasher.hexdigest()

        except FileNotFoundError:
            raise HashAnalysisException(f"File not found: {file_path}")
        except Exception as e:
            raise HashAnalysisException(f"Hash calculation failed: {e}")

    def record_file_hash(self, file_path: str, hash_value: str) -> None:
        """Record file hash.

        Args:
            file_path: File path.
            hash_value: Hash value.
        """
        self.file_hashes[file_path].append(hash_value)


class NetworkFlowAnalyzer:
    """Analyzes network flows for suspicious patterns."""

    def __init__(self, beaconing_interval_threshold: int = 60):
        """Initialize network flow analyzer.

        Args:
            beaconing_interval_threshold: Max interval variance for beaconing (seconds).
        """
        self.beaconing_interval_threshold = beaconing_interval_threshold
        self.flows: list[NetworkFlow] = []

    def add_flow(self, flow: NetworkFlow) -> None:
        """Add network flow.

        Args:
            flow: NetworkFlow to add.
        """
        self.flows.append(flow)

    def detect_beaconing(self, src_ip: str, dst_ip: str, dst_port: int) -> dict[str, Any] | None:
        """Detect C2 beaconing pattern.

        Args:
            src_ip: Source IP.
            dst_ip: Destination IP.
            dst_port: Destination port.

        Returns:
            Beaconing details or None.
        """
        # Get flows for this connection
        flows = [f for f in self.flows if f.src_ip == src_ip and f.dst_ip == dst_ip and f.dst_port == dst_port]

        if len(flows) < 3:
            return None

        # Calculate intervals between flows
        sorted_flows = sorted(flows, key=lambda f: f.start_time)
        intervals = []

        for i in range(1, len(sorted_flows)):
            interval = (sorted_flows[i].start_time - sorted_flows[i - 1].start_time).total_seconds()
            intervals.append(interval)

        if not intervals:
            return None

        # Check for regular intervals
        avg_interval = sum(intervals) / len(intervals)
        variance = sum((i - avg_interval) ** 2 for i in intervals) / len(intervals)
        stddev = variance**0.5

        # Beaconing has low variance
        if stddev < self.beaconing_interval_threshold:
            return {
                "src_ip": src_ip,
                "dst_ip": dst_ip,
                "dst_port": dst_port,
                "avg_interval_seconds": avg_interval,
                "stddev": stddev,
                "flow_count": len(flows),
                "confidence": min(1.0, 1.0 - (stddev / self.beaconing_interval_threshold)),
            }

        return None

    def analyze_volume(self, src_ip: str, dst_ip: str) -> dict[str, Any] | None:
        """Analyze data volume for anomalies.

        Args:
            src_ip: Source IP.
            dst_ip: Destination IP.

        Returns:
            Volume analysis or None.
        """
        flows = [f for f in self.flows if f.src_ip == src_ip and f.dst_ip == dst_ip]

        if not flows:
            return None

        total_bytes_in = sum(f.bytes_in for f in flows)
        total_bytes_out = sum(f.bytes_out for f in flows)
        total_packets = sum(f.packets for f in flows)

        return {
            "src_ip": src_ip,
            "dst_ip": dst_ip,
            "flows": len(flows),
            "total_bytes_in": total_bytes_in,
            "total_bytes_out": total_bytes_out,
            "total_packets": total_packets,
            "avg_bytes_per_flow": (total_bytes_in + total_bytes_out) / len(flows),
        }

    def identify_lateral_movement(self, internal_subnet: str) -> list[dict[str, Any]]:
        """Identify lateral movement patterns.

        Args:
            internal_subnet: Internal network subnet (e.g., '192.168.0.0/16').

        Returns:
            List of suspicious flows.
        """
        suspicious = []

        # Group flows by source
        by_source = defaultdict(list)
        for flow in self.flows:
            by_source[flow.src_ip].append(flow)

        # Find sources with many outbound connections
        for src_ip, flows in by_source.items():
            unique_destinations = len(set(f.dst_ip for f in flows))

            # High number of connections to different hosts = lateral movement
            if unique_destinations > 5:
                suspicious.append(
                    {
                        "source_ip": src_ip,
                        "unique_destinations": unique_destinations,
                        "total_flows": len(flows),
                        "confidence": min(1.0, unique_destinations / 20.0),
                    }
                )

        return suspicious


class CustodyTracker:
    """Tracks chain of custody for forensic evidence."""

    def __init__(self):
        """Initialize custody tracker."""
        self.custody_records: dict[str, list[ChainOfCustody]] = defaultdict(list)
        self.artifacts: dict[str, Artifact] = {}

    def add_artifact(self, artifact: Artifact) -> None:
        """Add artifact to tracking.

        Args:
            artifact: Artifact to track.
        """
        self.artifacts[artifact.artifact_id] = artifact

    def record_custody_transfer(
        self,
        artifact_id: str,
        transferred_by: str,
        transferred_to: str,
        location: str,
    ) -> ChainOfCustody:
        """Record custody transfer.

        Args:
            artifact_id: Artifact identifier.
            transferred_by: Transferred by person.
            transferred_to: Transferred to person.
            location: Physical location.

        Returns:
            ChainOfCustody record.
        """
        custody = ChainOfCustody(
            artifact_id=artifact_id,
            acquired_by=transferred_to,
            location=location,
            notes=f"Transferred from {transferred_by}",
        )

        self.custody_records[artifact_id].append(custody)
        return custody

    def verify_artifact_integrity(self, artifact_id: str, current_hash: str) -> bool:
        """Verify artifact hasn't been modified.

        Args:
            artifact_id: Artifact identifier.
            current_hash: Current hash value.

        Returns:
            True if integrity verified.
        """
        artifact = self.artifacts.get(artifact_id)
        if not artifact:
            return False

        # Check against stored hash
        if artifact.hash_sha256 and artifact.hash_sha256 != current_hash:
            return False

        return True

    def get_custody_chain(self, artifact_id: str) -> list[ChainOfCustody]:
        """Get chain of custody for artifact.

        Args:
            artifact_id: Artifact identifier.

        Returns:
            List of custody records in chronological order.
        """
        records = self.custody_records.get(artifact_id, [])
        return sorted(records, key=lambda r: r.acquired_at)


class ForensicsEngine:
    """Main digital forensics engine.

    Coordinates timeline reconstruction, hash analysis, network flow analysis,
    artifact extraction, and chain of custody tracking.
    """

    def __init__(self):
        """Initialize forensics engine."""
        self.timeline_reconstructor = TimelineReconstructor()
        self.hash_analyzer = FileHashAnalyzer()
        self.flow_analyzer = NetworkFlowAnalyzer()
        self.custody_tracker = CustodyTracker()

    def reconstruct_incident_timeline(self, events: list[SecurityEvent]) -> Timeline:
        """Reconstruct timeline for incident investigation.

        Args:
            events: Events to include in timeline.

        Returns:
            Reconstructed Timeline.
        """
        return self.timeline_reconstructor.build_timeline(events)

    def analyze_file_involvement(self, file_hash: str) -> dict[str, Any] | None:
        """Analyze file involvement in incident.

        Args:
            file_hash: File hash to analyze.

        Returns:
            Analysis results or None.
        """
        bad_hash = self.hash_analyzer.check_hash(file_hash)
        return bad_hash

    def analyze_network_activity(self, src_ip: str, dst_ip: str) -> dict[str, Any]:
        """Analyze network activity between IPs.

        Args:
            src_ip: Source IP.
            dst_ip: Destination IP.

        Returns:
            Network analysis.
        """
        analysis = {}

        # Check for beaconing
        analysis["beaconing"] = self.flow_analyzer.detect_beaconing(src_ip, dst_ip, 443)

        # Check volume
        analysis["volume"] = self.flow_analyzer.analyze_volume(src_ip, dst_ip)

        # Check for lateral movement
        analysis["lateral_movement"] = self.flow_analyzer.identify_lateral_movement("192.168.0.0/16")

        return analysis

    def create_artifact(
        self,
        artifact_type: str,
        name: str,
        path: str,
        hash_sha256: str,
    ) -> Artifact:
        """Create forensic artifact record.

        Args:
            artifact_type: Type of artifact.
            name: Artifact name.
            path: Artifact path/location.
            hash_sha256: SHA256 hash.

        Returns:
            Created Artifact.
        """
        artifact = Artifact(
            artifact_type=artifact_type,
            name=name,
            path=path,
            hash_sha256=hash_sha256,
        )

        self.custody_tracker.add_artifact(artifact)
        return artifact

    def get_forensics_report(self, incident_events: list[SecurityEvent]) -> dict[str, Any]:
        """Generate forensics report.

        Args:
            incident_events: Events related to incident.

        Returns:
            Forensics report.
        """
        timeline = self.reconstruct_incident_timeline(incident_events)

        # Analyze network flows
        network_analysis = {}
        unique_connections = set()
        for event in incident_events:
            if event.src_ip and event.dst_ip:
                unique_connections.add((event.src_ip, event.dst_ip))

        for src, dst in list(unique_connections)[:5]:  # Limit for performance
            network_analysis[f"{src}-{dst}"] = self.analyze_network_activity(src, dst)

        return {
            "timeline": timeline,
            "events_count": len(timeline.events),
            "time_range": {
                "start": timeline.events[0].timestamp if timeline.events else None,
                "end": timeline.events[-1].timestamp if timeline.events else None,
            },
            "network_analysis": network_analysis,
            "artifacts": list(self.custody_tracker.artifacts.values()),
        }
