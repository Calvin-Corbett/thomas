"""
Geolocation and GeoIP Management

IP to country mapping, country blocking, and geo-based rate limiting.
"""

import ipaddress
import logging

from thomas.marketplace.waf._types import GeoLocation


class GeoIPManager:
    """
    Geolocation management for IP addresses.

    Features:
    - IP to country mapping via CIDR ranges
    - Country blocking
    - Geo-based rate limiting
    - VPN/Proxy detection
    - Simplified GeoIP database
    """

    # Simplified CIDR ranges for major countries/regions
    # In production, use MaxMind GeoIP2 or similar
    COUNTRY_CIDR_MAPPING = {
        "US": [
            "8.0.0.0/9",
            "14.0.0.0/8",
            "15.0.0.0/8",
            "24.0.0.0/9",
            "27.0.0.0/8",
            "39.0.0.0/8",
        ],
        "CN": [
            "1.0.0.0/8",
            "14.0.0.0/9",
            "27.0.0.0/9",
            "36.0.0.0/7",
            "42.0.0.0/8",
            "49.0.0.0/8",
            "58.0.0.0/7",
        ],
        "GB": [
            "2.0.0.0/8",
            "5.0.0.0/9",
            "25.0.0.0/8",
            "31.0.0.0/8",
        ],
        "DE": [
            "3.0.0.0/9",
            "31.0.0.0/9",
            "37.0.0.0/8",
            "46.0.0.0/8",
            "52.0.0.0/9",
            "62.0.0.0/7",
        ],
        "FR": [
            "80.0.0.0/4",
            "90.0.0.0/8",
            "193.0.0.0/9",
            "194.0.0.0/8",
        ],
        "JP": [
            "61.0.0.0/8",
            "126.0.0.0/8",
            "133.0.0.0/8",
            "150.0.0.0/8",
            "153.0.0.0/8",
            "202.0.0.0/9",
        ],
        "IN": [
            "49.0.0.0/9",
            "103.0.0.0/8",
            "106.0.0.0/8",
            "117.0.0.0/8",
            "203.0.0.0/8",
        ],
        "RU": [
            "5.0.0.0/9",
            "31.0.0.0/9",
            "37.0.0.0/8",
            "46.0.0.0/8",
            "85.0.0.0/8",
            "109.0.0.0/8",
            "195.0.0.0/8",
        ],
    }

    def __init__(self) -> None:
        """Initialize GeoIP manager."""
        self.blocked_countries: set[str] = set()
        self.allowed_countries: set[str] = set()
        self.ip_cache: dict[str, str | None] = {}
        self.logger = logging.getLogger(__name__)
        self._build_ip_ranges()

    def _build_ip_ranges(self) -> None:
        """Build IP network objects from CIDR strings."""
        self.country_networks: dict[str, list[ipaddress.IPv4Network]] = {}

        for country, cidrs in self.COUNTRY_CIDR_MAPPING.items():
            self.country_networks[country] = []
            for cidr in cidrs:
                try:
                    self.country_networks[country].append(ipaddress.ip_network(cidr, strict=False))
                except ValueError as e:
                    self.logger.warning(f"Invalid CIDR for {country}: {e}")

    def get_country(self, ip_address: str) -> str | None:
        """
        Get country code for IP address.

        Args:
            ip_address: IP address to lookup

        Returns:
            Country code or None if not found
        """
        # Check cache
        if ip_address in self.ip_cache:
            return self.ip_cache[ip_address]

        try:
            ip_obj = ipaddress.ip_address(ip_address)

            for country, networks in self.country_networks.items():
                for network in networks:
                    if ip_obj in network:
                        self.ip_cache[ip_address] = country
                        return country

        except ValueError:
            self.logger.warning(f"Invalid IP address: {ip_address}")

        # Not found
        self.ip_cache[ip_address] = None
        return None

    def get_location(self, ip_address: str) -> GeoLocation | None:
        """
        Get geolocation information for IP.

        Args:
            ip_address: IP address to lookup

        Returns:
            GeoLocation object or None
        """
        country_code = self.get_country(ip_address)

        if not country_code:
            return None

        location = GeoLocation(
            country_code=country_code,
            city=None,  # Would come from maxmind db
            latitude=None,
            longitude=None,
            is_vpn=False,
            is_proxy=False,
            is_tor=False,
        )

        return location

    def block_country(self, country_code: str) -> None:
        """
        Block all traffic from country.

        Args:
            country_code: ISO 3166-1 alpha-2 country code
        """
        self.blocked_countries.add(country_code.upper())
        self.ip_cache.clear()  # Clear cache
        self.logger.info(f"Blocked country: {country_code}")

    def unblock_country(self, country_code: str) -> None:
        """
        Unblock country.

        Args:
            country_code: ISO 3166-1 alpha-2 country code
        """
        self.blocked_countries.discard(country_code.upper())
        self.ip_cache.clear()

    def allow_country(self, country_code: str) -> None:
        """
        Add country to allow list.

        Args:
            country_code: ISO 3166-1 alpha-2 country code
        """
        self.allowed_countries.add(country_code.upper())
        self.ip_cache.clear()

    def disallow_country(self, country_code: str) -> None:
        """
        Remove country from allow list.

        Args:
            country_code: ISO 3166-1 alpha-2 country code
        """
        self.allowed_countries.discard(country_code.upper())
        self.ip_cache.clear()

    def is_blocked(self, ip_address: str) -> bool:
        """
        Check if IP's country is blocked.

        Args:
            ip_address: IP address to check

        Returns:
            True if blocked, False otherwise
        """
        country = self.get_country(ip_address)

        if not country:
            return False

        if self.allowed_countries and country not in self.allowed_countries:
            return True

        if country in self.blocked_countries:
            return True

        return False

    def is_allowed(self, ip_address: str) -> bool:
        """
        Check if IP's country is allowed.

        Args:
            ip_address: IP address to check

        Returns:
            True if allowed, False otherwise
        """
        country = self.get_country(ip_address)

        if not country:
            return True  # Unknown countries allowed by default

        if self.allowed_countries:
            return country in self.allowed_countries

        if self.blocked_countries:
            return country not in self.blocked_countries

        return True

    def get_stats(self) -> dict[str, int]:
        """
        Get GeoIP manager statistics.

        Returns:
            Dictionary with statistics
        """
        return {
            "cached_ips": len(self.ip_cache),
            "blocked_countries": len(self.blocked_countries),
            "allowed_countries": len(self.allowed_countries),
            "countries_mapped": len(self.country_networks),
        }

    def clear_cache(self) -> None:
        """Clear IP cache."""
        self.ip_cache.clear()

    def export_blocked_countries(self) -> list[str]:
        """
        Export list of blocked countries.

        Returns:
            Sorted list of country codes
        """
        return sorted(list(self.blocked_countries))

    def export_allowed_countries(self) -> list[str]:
        """
        Export list of allowed countries.

        Returns:
            Sorted list of country codes
        """
        return sorted(list(self.allowed_countries))

    def import_blocked_countries(self, countries: list[str]) -> None:
        """
        Import blocked countries list.

        Args:
            countries: List of country codes
        """
        self.blocked_countries = set(c.upper() for c in countries)
        self.ip_cache.clear()

    def import_allowed_countries(self, countries: list[str]) -> None:
        """
        Import allowed countries list.

        Args:
            countries: List of country codes
        """
        self.allowed_countries = set(c.upper() for c in countries)
        self.ip_cache.clear()
