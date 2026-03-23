"""
DNS type definitions: headers, messages, records, and enums.
"""

from dataclasses import dataclass, field
from enum import IntEnum
from ipaddress import IPv4Address, IPv6Address


class RecordType(IntEnum):
    """DNS record types (RRTYPEs)."""

    A = 1
    NS = 2
    CNAME = 5
    SOA = 6
    PTR = 12
    MX = 15
    TXT = 16
    AAAA = 28
    SRV = 33


class ResponseCode(IntEnum):
    """DNS response codes (RCODE)."""

    NOERROR = 0  # No error condition
    FORMERR = 1  # Format error
    SERVFAIL = 2  # Server failure
    NXDOMAIN = 3  # Non-existent domain
    NOTIMP = 4  # Not implemented
    REFUSED = 5  # Query refused
    YXDOMAIN = 6  # Name exists when it should not
    YXRRSET = 7  # RR set exists when it should not
    NXRRSET = 8  # RR set that should exist does not
    NOTAUTH = 9  # Server not authoritative for zone
    NOTZONE = 10  # Name not contained in zone


class QClass(IntEnum):
    """DNS question classes."""

    IN = 1  # Internet
    CH = 3  # Chaos
    HS = 4  # Hesiod
    ANY = 255  # Any class


@dataclass
class DNSHeader:
    """DNS message header (RFC 1035 section 4.1.1).

    Attributes:
        id: Message ID (16-bit)
        qr: Query response flag (0=query, 1=response)
        opcode: Operation code (0=query, 1=inverse query, 2=status)
        aa: Authoritative answer flag
        tc: Truncation flag
        rd: Recursion desired flag
        ra: Recursion available flag
        rcode: Response code
        qdcount: Number of questions
        ancount: Number of answer records
        nscount: Number of authority records
        arcount: Number of additional records
    """

    id: int
    qr: bool = False
    opcode: int = 0
    aa: bool = False
    tc: bool = False
    rd: bool = False
    ra: bool = False
    rcode: ResponseCode = ResponseCode.NOERROR
    qdcount: int = 0
    ancount: int = 0
    nscount: int = 0
    arcount: int = 0

    def to_flags(self) -> int:
        """Convert header flags to 16-bit integer.

        Returns:
            16-bit flags value following RFC 1035 format.
        """
        flags = 0
        if self.qr:
            flags |= 0x8000
        flags |= (self.opcode & 0x0F) << 11
        if self.aa:
            flags |= 0x0400
        if self.tc:
            flags |= 0x0200
        if self.rd:
            flags |= 0x0100
        if self.ra:
            flags |= 0x0080
        flags |= int(self.rcode) & 0x0F
        return flags

    @classmethod
    def from_flags(cls, id_val: int, flags: int) -> "DNSHeader":
        """Create header from flags integer.

        Args:
            id_val: Message ID
            flags: 16-bit flags value

        Returns:
            DNSHeader instance.
        """
        return cls(
            id=id_val,
            qr=bool(flags & 0x8000),
            opcode=(flags >> 11) & 0x0F,
            aa=bool(flags & 0x0400),
            tc=bool(flags & 0x0200),
            rd=bool(flags & 0x0100),
            ra=bool(flags & 0x0080),
            rcode=ResponseCode(flags & 0x0F),
        )


@dataclass
class DNSQuestion:
    """DNS question section (RFC 1035 section 4.1.2).

    Attributes:
        name: Domain name being queried
        qtype: Query type (RecordType)
        qclass: Query class (default: IN)
    """

    name: str
    qtype: RecordType
    qclass: int = QClass.IN


@dataclass
class ResourceRecord:
    """DNS resource record (RFC 1035 section 4.1.3).

    Attributes:
        name: Resource record name
        rtype: Resource record type
        rclass: Resource record class
        ttl: Time to live in seconds
        rdata: Raw resource data (type-specific)
    """

    name: str
    rtype: RecordType
    rclass: int
    ttl: int
    rdata: str | IPv4Address | IPv6Address | dict | list[str]


@dataclass
class DNSMessage:
    """Complete DNS message (RFC 1035 section 4.1).

    Attributes:
        header: DNS header
        questions: List of questions
        answers: List of answer records
        authority: List of authority records
        additional: List of additional records
    """

    header: DNSHeader
    questions: list[DNSQuestion] = field(default_factory=list)
    answers: list[ResourceRecord] = field(default_factory=list)
    authority: list[ResourceRecord] = field(default_factory=list)
    additional: list[ResourceRecord] = field(default_factory=list)


@dataclass
class DNSConfig:
    """DNS resolver configuration.

    Attributes:
        upstream_servers: List of upstream DNS server IPs
        timeout: Query timeout in seconds
        retries: Number of retries per query
        cache_size: Maximum cache size in bytes
        cache_negative: Whether to cache NXDOMAIN responses
        use_tcp_fallback: Whether to fall back to TCP on truncation
        enable_dnssec: Whether to validate DNSSEC
    """

    upstream_servers: list[str] = field(default_factory=lambda: ["8.8.8.8", "8.8.4.4"])
    timeout: float = 5.0
    retries: int = 3
    cache_size: int = 10 * 1024 * 1024  # 10 MB
    cache_negative: bool = True
    use_tcp_fallback: bool = True
    enable_dnssec: bool = False
