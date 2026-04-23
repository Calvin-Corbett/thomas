"""Threat intelligence management and IOC matching.

Manages indicators of compromise, threat feeds, MITRE ATT&CK mapping,
and fast IOC matching with bloom filters.
"""

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from thomas.marketplace.siem._exceptions import (
    IOCManagementException,
    ThreatIntelException,
)
from thomas.marketplace.siem._types import (
    IOC,
    KillChainPhase,
    MITREAttackTechnique,
    SecurityEvent,
    ThreatIntel,
)


class BloomFilter:
    """Simple Bloom filter for fast IOC pre-screening."""

    def __init__(self, size: int = 100000, hash_count: int = 3):
        """Initialize bloom filter.

        Args:
            size: Size of bit array.
            hash_count: Number of hash functions.
        """
        self.size = size
        self.hash_count = hash_count
        self.bits = [False] * size

    def add(self, item: str) -> None:
        """Add item to filter.

        Args:
            item: Item to add.
        """
        for i in range(self.hash_count):
            index = self._hash(item, i) % self.size
            self.bits[index] = True

    def contains(self, item: str) -> bool:
        """Check if item might be in filter.

        Args:
            item: Item to check.

        Returns:
            True if item might be present (false positives possible).
        """
        for i in range(self.hash_count):
            index = self._hash(item, i) % self.size
            if not self.bits[index]:
                return False
        return True

    @staticmethod
    def _hash(item: str, seed: int) -> int:
        """Hash function.

        Args:
            item: Item to hash.
            seed: Hash seed.

        Returns:
            Hash value.
        """
        h = hash((item, seed))
        return abs(h)


class IOCManager:
    """Manages indicators of compromise."""

    def __init__(self):
        """Initialize IOC manager."""
        self.iocs: dict[str, IOC] = {}
        self.bloom_filter = BloomFilter()
        self.iocs_by_type: dict[str, set[str]] = defaultdict(set)

    def add_ioc(self, ioc: IOC) -> None:
        """Add IOC to manager.

        Args:
            ioc: IOC to add.

        Raises:
            IOCManagementException: If add fails.
        """
        try:
            ioc_id = str(ioc.ioc_id)
            self.iocs[ioc_id] = ioc
            self.bloom_filter.add(ioc.value)
            self.iocs_by_type[ioc.ioc_type].add(ioc_id)
        except Exception as e:
            raise IOCManagementException(f"Failed to add IOC: {e}")

    def remove_ioc(self, ioc_id: str) -> bool:
        """Remove IOC from manager.

        Args:
            ioc_id: IOC identifier.

        Returns:
            True if removed, False if not found.
        """
        if ioc_id in self.iocs:
            ioc = self.iocs[ioc_id]
            del self.iocs[ioc_id]
            self.iocs_by_type[ioc.ioc_type].discard(ioc_id)
            return True
        return False

    def cleanup_expired(self) -> int:
        """Remove expired IOCs.

        Returns:
            Number of IOCs removed.
        """
        now = datetime.utcnow()
        expired = [ioc_id for ioc_id, ioc in self.iocs.items() if ioc.is_expired()]

        for ioc_id in expired:
            self.remove_ioc(ioc_id)

        return len(expired)

    def get_ioc(self, ioc_id: str) -> IOC | None:
        """Get IOC by ID.

        Args:
            ioc_id: IOC identifier.

        Returns:
            IOC or None if not found.
        """
        return self.iocs.get(ioc_id)

    def search_iocs(
        self,
        ioc_type: str | None = None,
        source: str | None = None,
        min_confidence: int = 0,
    ) -> list[IOC]:
        """Search IOCs with filters.

        Args:
            ioc_type: Filter by IOC type.
            source: Filter by source.
            min_confidence: Minimum confidence score.

        Returns:
            List of matching IOCs.
        """
        results = list(self.iocs.values())

        if ioc_type:
            results = [i for i in results if i.ioc_type == ioc_type]

        if source:
            results = [i for i in results if i.source == source]

        if min_confidence > 0:
            results = [i for i in results if i.confidence >= min_confidence]

        return results

    def match_value(self, value: str) -> list[IOC]:
        """Find IOCs matching a value.

        Args:
            value: Value to match.

        Returns:
            List of matching IOCs.
        """
        # Fast pre-screening with bloom filter
        if not self.bloom_filter.contains(value):
            return []

        # Exact match
        matches = []
        for ioc in self.iocs.values():
            if ioc.value == value and not ioc.is_expired():
                matches.append(ioc)

        return matches


class ThreatTaxonomy:
    """Maps threats to MITRE ATT&CK techniques and kill chain phases."""

    # MITRE technique to kill chain mapping (simplified)
    TECHNIQUE_TO_PHASES = {
        MITREAttackTechnique.T1078: [KillChainPhase.ACTIONS_ON_OBJECTIVES],
        MITREAttackTechnique.T1110: [KillChainPhase.DELIVERY, KillChainPhase.EXPLOITATION],
        MITREAttackTechnique.T1021: [KillChainPhase.INSTALLATION, KillChainPhase.ACTIONS_ON_OBJECTIVES],
        MITREAttackTechnique.T1570: [KillChainPhase.COMMAND_AND_CONTROL],
        MITREAttackTechnique.T1059: [KillChainPhase.EXPLOITATION],
        MITREAttackTechnique.T1071: [KillChainPhase.COMMAND_AND_CONTROL],
        MITREAttackTechnique.T1041: [KillChainPhase.ACTIONS_ON_OBJECTIVES],
        MITREAttackTechnique.T1020: [KillChainPhase.ACTIONS_ON_OBJECTIVES],
        MITREAttackTechnique.T1557: [KillChainPhase.DELIVERY],
        MITREAttackTechnique.T1566: [KillChainPhase.DELIVERY],
        MITREAttackTechnique.T1192: [KillChainPhase.WEAPONIZATION],
        MITREAttackTechnique.T1199: [KillChainPhase.RECONNAISSANCE],
        MITREAttackTechnique.T1091: [KillChainPhase.DELIVERY],
    }

    @staticmethod
    def get_phases(technique: MITREAttackTechnique) -> list[KillChainPhase]:
        """Get kill chain phases for technique.

        Args:
            technique: MITRE technique.

        Returns:
            List of kill chain phases.
        """
        return ThreatTaxonomy.TECHNIQUE_TO_PHASES.get(technique, [])


class ThreatFeed:
    """External threat intelligence feed."""

    def __init__(
        self,
        feed_id: str,
        name: str,
        source_url: str,
        update_interval: int = 3600,
    ):
        """Initialize threat feed.

        Args:
            feed_id: Unique feed identifier.
            name: Human-readable feed name.
            source_url: Feed source URL.
            update_interval: Update interval in seconds.
        """
        self.feed_id = feed_id
        self.name = name
        self.source_url = source_url
        self.update_interval = update_interval
        self.last_update: datetime | None = None
        self.iocs: list[IOC] = []

    def needs_update(self) -> bool:
        """Check if feed needs updating.

        Returns:
            True if update is needed.
        """
        if self.last_update is None:
            return True

        age = datetime.utcnow() - self.last_update
        return age > timedelta(seconds=self.update_interval)

    def update(self, iocs: list[IOC]) -> None:
        """Update feed with IOCs.

        Args:
            iocs: IOCs to add to feed.
        """
        self.iocs = iocs
        self.last_update = datetime.utcnow()


class ThreatIntelligenceManager:
    """Main threat intelligence engine.

    Manages IOCs, threat feeds, MITRE mapping, and threat scoring.
    """

    def __init__(self):
        """Initialize threat intelligence manager."""
        self.ioc_manager = IOCManager()
        self.feeds: dict[str, ThreatFeed] = {}
        self.threat_records: dict[str, ThreatIntel] = {}
        self.taxonomy = ThreatTaxonomy()

    def add_feed(self, feed: ThreatFeed) -> None:
        """Add threat feed.

        Args:
            feed: ThreatFeed to add.
        """
        self.feeds[feed.feed_id] = feed

    def ingest_feed(self, feed_id: str, iocs: list[IOC]) -> int:
        """Ingest IOCs from a feed.

        Args:
            feed_id: Feed identifier.
            iocs: IOCs to ingest.

        Returns:
            Number of IOCs ingested.

        Raises:
            ThreatIntelException: If ingestion fails.
        """
        if feed_id not in self.feeds:
            raise ThreatIntelException(f"Feed not found: {feed_id}")

        feed = self.feeds[feed_id]
        feed.update(iocs)

        added = 0
        for ioc in iocs:
            ioc.source = feed.name
            try:
                self.ioc_manager.add_ioc(ioc)
                added += 1
            except IOCManagementException:
                pass  # Continue on error

        return added

    def add_threat_intel(self, intel: ThreatIntel) -> None:
        """Add threat intelligence record.

        Args:
            intel: ThreatIntel to add.
        """
        self.threat_records[str(intel.intel_id)] = intel

    def match_event(self, event: SecurityEvent) -> list[tuple[IOC, ThreatIntel]]:
        """Match event against threat intelligence.

        Args:
            event: Event to match.

        Returns:
            List of (IOC, ThreatIntel) matches.
        """
        matches = []

        # Check IP addresses
        for ip in [event.src_ip, event.dst_ip]:
            if ip:
                iocs = self.ioc_manager.match_value(ip)
                for ioc in iocs:
                    # Find associated threat intel
                    intel = self._find_intel_for_ioc(ioc)
                    if intel:
                        matches.append((ioc, intel))

        # Check protocol/service
        if event.protocol:
            iocs = self.ioc_manager.match_value(event.protocol)
            for ioc in iocs:
                intel = self._find_intel_for_ioc(ioc)
                if intel:
                    matches.append((ioc, intel))

        return matches

    def _find_intel_for_ioc(self, ioc: IOC) -> ThreatIntel | None:
        """Find threat intel record for IOC.

        Args:
            ioc: IOC to find intel for.

        Returns:
            ThreatIntel or None.
        """
        for intel in self.threat_records.values():
            if ioc in intel.iocs:
                return intel
        return None

    def calculate_threat_score(self, ioc: IOC) -> float:
        """Calculate threat score for IOC.

        Args:
            ioc: IOC to score.

        Returns:
            Threat score (0-100).
        """
        intel = self._find_intel_for_ioc(ioc)
        if intel:
            # Aggregate confidence from IOC and associated intel
            base_score = ioc.confidence
            intel_boost = intel.confidence
            age_days = (datetime.utcnow() - ioc.created_at).days
            age_decay = max(0.1, 1.0 - (age_days / 365.0))
            return (base_score + intel_boost) / 2.0 * age_decay
        return float(ioc.confidence)

    def map_to_mitre(self, event: SecurityEvent, intel: ThreatIntel) -> dict[str, Any]:
        """Map event to MITRE ATT&CK techniques.

        Args:
            event: Event to map.
            intel: Associated threat intel.

        Returns:
            Mapping information.
        """
        techniques = intel.mitre_techniques
        phases = []

        for technique in techniques:
            technique_phases = self.taxonomy.get_phases(technique)
            phases.extend(technique_phases)

        return {
            "techniques": [t.name for t in techniques],
            "phases": list(set(p.name for p in phases)),
            "technique_ids": [t.name.split(".")[-1] for t in techniques],
        }

    def cleanup(self) -> int:
        """Clean up expired IOCs.

        Returns:
            Number of IOCs removed.
        """
        return self.ioc_manager.cleanup_expired()

    def get_statistics(self) -> dict[str, Any]:
        """Get threat intelligence statistics.

        Returns:
            Statistics dictionary.
        """
        all_iocs = list(self.ioc_manager.iocs.values())

        return {
            "total_iocs": len(all_iocs),
            "iocs_by_type": {
                ioc_type: len(self.ioc_manager.iocs_by_type[ioc_type]) for ioc_type in self.ioc_manager.iocs_by_type
            },
            "total_threats": len(self.threat_records),
            "feeds": len(self.feeds),
            "avg_confidence": (sum(i.confidence for i in all_iocs) / len(all_iocs) if all_iocs else 0),
        }

    def get_iocs(
        self,
        ioc_type: str | None = None,
        min_confidence: int = 0,
    ) -> list[IOC]:
        """Get IOCs with optional filtering.

        Args:
            ioc_type: Filter by type.
            min_confidence: Minimum confidence.

        Returns:
            List of IOCs.
        """
        return self.ioc_manager.search_iocs(
            ioc_type=ioc_type,
            min_confidence=min_confidence,
        )
