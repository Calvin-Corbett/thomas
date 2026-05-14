"""
IP Reputation Management

IP reputation tracking, blacklisting, whitelisting, CIDR range matching,
and threat scoring.
"""

import ipaddress
import logging
from datetime import datetime, timedelta

from thomas.marketplace.waf._types import IPReputation


class IPReputationManager:
    """
    Manages IP reputation, blacklist, whitelist, and threat scoring.

    Features:
    - IP blacklist/whitelist management
    - CIDR range matching
    - Reputation scoring (0-100)
    - Temporary bans with expiry
    - Threat type tracking
    - Tor exit node detection
    """

    # Known Tor exit node IP ranges (simplified)
    TOR_EXIT_NODES = [
        ipaddress.ip_network("193.0.6.0/24"),
        ipaddress.ip_network("128.31.0.0/16"),
    ]

    # Known VPN provider ranges (simplified)
    VPN_RANGES = [
        ipaddress.ip_network("185.217.116.0/22"),
        ipaddress.ip_network("196.52.43.0/24"),
    ]

    def __init__(self) -> None:
        """Initialize IP reputation manager."""
        self.reputation: dict[str, IPReputation] = {}
        self.blacklist: set[str] = set()
        self.whitelist: set[str] = set()
        self.blacklist_ranges: list[ipaddress.IPv4Network] = []
        self.whitelist_ranges: list[ipaddress.IPv4Network] = []
        self.ban_threshold: int = 75
        self.logger = logging.getLogger(__name__)

    def add_to_blacklist(self, ip_address: str) -> None:
        """
        Add IP to blacklist.

        Args:
            ip_address: IP address or CIDR range to blacklist
        """
        try:
            if "/" in ip_address:
                self.blacklist_ranges.append(ipaddress.ip_network(ip_address, strict=False))
            else:
                self.blacklist.add(ip_address)
        except ValueError as e:
            self.logger.error(f"Invalid IP address for blacklist: {e}")

    def add_to_whitelist(self, ip_address: str) -> None:
        """
        Add IP to whitelist.

        Args:
            ip_address: IP address or CIDR range to whitelist
        """
        try:
            if "/" in ip_address:
                self.whitelist_ranges.append(ipaddress.ip_network(ip_address, strict=False))
            else:
                self.whitelist.add(ip_address)
        except ValueError as e:
            self.logger.error(f"Invalid IP address for whitelist: {e}")

    def remove_from_blacklist(self, ip_address: str) -> bool:
        """
        Remove IP from blacklist.

        Args:
            ip_address: IP address to remove

        Returns:
            True if removed, False if not found
        """
        if ip_address in self.blacklist:
            self.blacklist.remove(ip_address)
            return True
        return False

    def remove_from_whitelist(self, ip_address: str) -> bool:
        """
        Remove IP from whitelist.

        Args:
            ip_address: IP address to remove

        Returns:
            True if removed, False if not found
        """
        if ip_address in self.whitelist:
            self.whitelist.remove(ip_address)
            return True
        return False

    def is_blacklisted(self, ip_address: str) -> bool:
        """
        Check if IP is blacklisted.

        Args:
            ip_address: IP address to check

        Returns:
            True if blacklisted, False otherwise
        """
        if ip_address in self.blacklist:
            return True

        try:
            ip_obj = ipaddress.ip_address(ip_address)
            for network in self.blacklist_ranges:
                if ip_obj in network:
                    return True
        except ValueError:
            self.logger.warning(f"Invalid IP address: {ip_address}")

        return False

    def is_whitelisted(self, ip_address: str) -> bool:
        """
        Check if IP is whitelisted.

        Args:
            ip_address: IP address to check

        Returns:
            True if whitelisted, False otherwise
        """
        if ip_address in self.whitelist:
            return True

        try:
            ip_obj = ipaddress.ip_address(ip_address)
            for network in self.whitelist_ranges:
                if ip_obj in network:
                    return True
        except ValueError:
            self.logger.warning(f"Invalid IP address: {ip_address}")

        return False

    def get_reputation(self, ip_address: str) -> IPReputation:
        """
        Get IP reputation information.

        Args:
            ip_address: IP address to check

        Returns:
            IPReputation object
        """
        if ip_address not in self.reputation:
            self.reputation[ip_address] = IPReputation(ip_address=ip_address)

        rep = self.reputation[ip_address]

        # Update last seen timestamp
        rep.last_seen = datetime.utcnow()

        # Check if ban has expired
        if rep.ban_until and datetime.utcnow() >= rep.ban_until:
            rep.ban_until = None

        return rep

    def set_reputation_score(self, ip_address: str, score: int) -> None:
        """
        Set IP reputation score.

        Args:
            ip_address: IP address
            score: Reputation score (0-100)
        """
        if not 0 <= score <= 100:
            raise ValueError("Score must be between 0 and 100")

        rep = self.get_reputation(ip_address)
        rep.reputation_score = score

    def increment_abuse_count(self, ip_address: str, increment: int = 1) -> None:
        """
        Increment abuse count for IP.

        Args:
            ip_address: IP address
            increment: Amount to increment by
        """
        rep = self.get_reputation(ip_address)
        rep.abuse_count += increment

        # Auto-ban if threshold exceeded
        if rep.abuse_count >= self.ban_threshold:
            self.ban_ip(ip_address, duration_minutes=60)

    def add_threat_type(self, ip_address: str, threat_type: str) -> None:
        """
        Add threat type to IP reputation.

        Args:
            ip_address: IP address
            threat_type: Type of threat
        """
        rep = self.get_reputation(ip_address)
        rep.add_threat_type(threat_type)

    def ban_ip(self, ip_address: str, duration_minutes: int = 60) -> None:
        """
        Ban IP temporarily.

        Args:
            ip_address: IP address to ban
            duration_minutes: Ban duration in minutes
        """
        rep = self.get_reputation(ip_address)
        rep.ban_until = datetime.utcnow() + timedelta(minutes=duration_minutes)
        self.logger.warning(f"IP {ip_address} banned for {duration_minutes} minutes")

    def unban_ip(self, ip_address: str) -> bool:
        """
        Remove ban from IP.

        Args:
            ip_address: IP address to unban

        Returns:
            True if unbanned, False if not banned
        """
        rep = self.get_reputation(ip_address)
        if rep.ban_until is not None:
            rep.ban_until = None
            return True
        return False

    def is_banned(self, ip_address: str) -> bool:
        """
        Check if IP is currently banned.

        Args:
            ip_address: IP address to check

        Returns:
            True if banned, False otherwise
        """
        rep = self.get_reputation(ip_address)
        return rep.is_banned()

    def is_tor_exit_node(self, ip_address: str) -> bool:
        """
        Check if IP is a known Tor exit node.

        Args:
            ip_address: IP address to check

        Returns:
            True if Tor exit node, False otherwise
        """
        try:
            ip_obj = ipaddress.ip_address(ip_address)
            for network in self.TOR_EXIT_NODES:
                if ip_obj in network:
                    return True
        except ValueError:
            pass
        return False

    def is_vpn(self, ip_address: str) -> bool:
        """
        Check if IP is known VPN provider.

        Args:
            ip_address: IP address to check

        Returns:
            True if VPN, False otherwise
        """
        try:
            ip_obj = ipaddress.ip_address(ip_address)
            for network in self.VPN_RANGES:
                if ip_obj in network:
                    return True
        except ValueError:
            pass
        return False

    def is_suspicious(self, ip_address: str) -> bool:
        """
        Check if IP exhibits suspicious patterns.

        Args:
            ip_address: IP address to check

        Returns:
            True if suspicious, False otherwise
        """
        rep = self.get_reputation(ip_address)

        # High abuse count
        if rep.abuse_count > 10:
            return True

        # High reputation score
        if rep.reputation_score > 50:
            return True

        # Multiple threat types
        if len(rep.threat_types) > 2:
            return True

        # Currently banned
        if rep.is_banned():
            return True

        # Tor or VPN
        if self.is_tor_exit_node(ip_address) or self.is_vpn(ip_address):
            return True

        return False

    def get_cidr_range(self, ip_address: str) -> str | None:
        """
        Get CIDR range for IP address (class C network).

        Args:
            ip_address: IP address

        Returns:
            CIDR notation string or None
        """
        try:
            ipaddress.ip_address(ip_address)
            # Return /24 network (class C)
            network = ipaddress.ip_network(f"{ip_address}/24", strict=False)
            return str(network)
        except ValueError:
            return None

    def cleanup_expired_bans(self) -> int:
        """
        Remove expired bans from tracking.

        Returns:
            Number of bans removed
        """
        count = 0

        for ip_address, rep in self.reputation.items():
            if rep.ban_until and datetime.utcnow() >= rep.ban_until:
                rep.ban_until = None
                count += 1

        return count

    def get_stats(self) -> dict[str, int]:
        """
        Get reputation manager statistics.

        Returns:
            Dictionary with statistics
        """
        return {
            "total_tracked": len(self.reputation),
            "blacklisted": len(self.blacklist),
            "whitelisted": len(self.whitelist),
            "blacklist_ranges": len(self.blacklist_ranges),
            "whitelist_ranges": len(self.whitelist_ranges),
            "currently_banned": sum(1 for rep in self.reputation.values() if rep.is_banned()),
        }
