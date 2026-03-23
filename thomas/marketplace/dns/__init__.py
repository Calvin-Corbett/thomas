"""
Thomas DNS Module - Complete DNS protocol implementation.

Public API for DNS parsing, resolution, caching, and zone management.
"""

from thomas.marketplace.dns._exceptions import (
    DNSError,
    DNSNameError,
    DNSTimeoutError,
    FormatError,
    RefusedError,
    ServerFailure,
)
from thomas.marketplace.dns._exceptions import (
    NotImplementedError as DNSNotImplementedError,
)
from thomas.marketplace.dns._types import (
    DNSConfig,
    DNSHeader,
    DNSMessage,
    DNSQuestion,
    RecordType,
    ResourceRecord,
    ResponseCode,
)
from thomas.marketplace.dns.cache import DNSCache
from thomas.marketplace.dns.hosts import HostsFile
from thomas.marketplace.dns.protocol import decode_dns_message, encode_dns_message
from thomas.marketplace.dns.resolver import Resolver
from thomas.marketplace.dns.server import DNSServer
from thomas.marketplace.dns.utils import (
    generate_reverse_dns_name,
    parse_ttl,
    punycode_decode,
    punycode_encode,
    validate_domain_name,
)
from thomas.marketplace.dns.zone import Zone, ZoneParser

__all__ = [
    # Types
    "DNSHeader",
    "DNSQuestion",
    "ResourceRecord",
    "DNSMessage",
    "RecordType",
    "ResponseCode",
    "DNSConfig",
    # Exceptions
    "DNSError",
    "FormatError",
    "ServerFailure",
    "DNSNameError",
    "DNSNotImplementedError",
    "RefusedError",
    "DNSTimeoutError",
    # Protocol
    "encode_dns_message",
    "decode_dns_message",
    # Services
    "Resolver",
    "DNSCache",
    "Zone",
    "ZoneParser",
    "DNSServer",
    "HostsFile",
    # Utilities
    "validate_domain_name",
    "generate_reverse_dns_name",
    "parse_ttl",
    "punycode_encode",
    "punycode_decode",
]

__version__ = "0.1.0"
