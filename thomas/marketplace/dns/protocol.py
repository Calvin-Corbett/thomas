"""
DNS wire protocol: RFC 1035 message encoding/decoding.
"""

import struct
from ipaddress import IPv4Address, IPv6Address

from thomas.marketplace.dns._exceptions import FormatError
from thomas.marketplace.dns._types import (
    DNSHeader,
    DNSMessage,
    DNSQuestion,
    RecordType,
    ResourceRecord,
)


class DNSBuffer:
    """Buffer for reading/writing DNS messages with compression support."""

    def __init__(self, data: bytes = b"") -> None:
        """Initialize buffer.

        Args:
            data: Initial bytes (for reading)
        """
        self.data = bytearray(data)
        self.pos = 0
        self.compression_map: dict[str, int] = {}

    def read_byte(self) -> int:
        """Read single byte."""
        if self.pos >= len(self.data):
            raise FormatError("Buffer underrun")
        val = self.data[self.pos]
        self.pos += 1
        return val

    def read_bytes(self, n: int) -> bytes:
        """Read n bytes."""
        if self.pos + n > len(self.data):
            raise FormatError("Buffer underrun")
        result = bytes(self.data[self.pos : self.pos + n])
        self.pos += n
        return result

    def read_uint16(self) -> int:
        """Read 16-bit unsigned integer (network byte order)."""
        return struct.unpack("!H", self.read_bytes(2))[0]

    def read_uint32(self) -> int:
        """Read 32-bit unsigned integer (network byte order)."""
        return struct.unpack("!I", self.read_bytes(4))[0]

    def write_byte(self, val: int) -> None:
        """Write single byte."""
        self.data.append(val & 0xFF)

    def write_bytes(self, data: bytes) -> None:
        """Write bytes."""
        self.data.extend(data)

    def write_uint16(self, val: int) -> None:
        """Write 16-bit unsigned integer (network byte order)."""
        self.data.extend(struct.pack("!H", val & 0xFFFF))

    def write_uint32(self, val: int) -> None:
        """Write 32-bit unsigned integer (network byte order)."""
        self.data.extend(struct.pack("!I", val & 0xFFFFFFFF))

    def read_name(self) -> str:
        """Read domain name with compression support (RFC 1035 4.1.4).

        Compression pointers use 11000000xxxxxxxx (0xC0) prefix to 14-bit offset.
        """
        labels: list[str] = []
        seen_compression = False

        while True:
            length = self.read_byte()

            if length == 0:
                break
            elif length >= 0xC0:
                # Compression pointer
                if not seen_compression:
                    seen_compression = True
                pointer = ((length & 0x3F) << 8) | self.read_byte()
                saved_pos = self.pos
                self.pos = pointer
                suffix = self.read_name()
                # Remove trailing dot from suffix if present
                if suffix.endswith("."):
                    suffix = suffix[:-1]
                labels.extend(suffix.split(".") if suffix else [])
                self.pos = saved_pos
                break
            elif length <= 63:
                # Normal label
                label = self.read_bytes(length).decode("ascii", errors="replace")
                labels.append(label)
            else:
                raise FormatError(f"Invalid label length: {length}")

        result = ".".join(labels) if labels else "."
        # Always append trailing dot for FQDN
        if result != "." and not result.endswith("."):
            result += "."
        return result

    def write_name(self, name: str) -> None:
        """Write domain name with compression (RFC 1035 4.1.4).

        Uses compression pointers for previously seen labels to save space.
        """
        if name == ".":
            self.write_byte(0)
            return

        labels = name.rstrip(".").split(".")
        path_parts: list[str] = []

        for label in labels:
            path_parts.append(label)
            suffix = ".".join(path_parts)

            # Check for compression
            if suffix in self.compression_map:
                offset = self.compression_map[suffix]
                pointer = 0xC000 | offset
                self.write_uint16(pointer)
                return

            # Record position for future compression
            if len(self.data) < 0x3FFF:
                self.compression_map[suffix] = len(self.data)

            # Write label
            self.write_byte(len(label))
            self.write_bytes(label.encode("ascii"))

        self.write_byte(0)

    def get_bytes(self) -> bytes:
        """Get current buffer contents."""
        return bytes(self.data)

    def at_end(self) -> bool:
        """Check if at end of buffer."""
        return self.pos >= len(self.data)


def encode_dns_message(msg: DNSMessage) -> bytes:
    """Encode DNS message to bytes (RFC 1035).

    Args:
        msg: DNSMessage to encode

    Returns:
        Encoded message bytes

    Raises:
        FormatError: If message is invalid
    """
    buf = DNSBuffer()

    # Encode header
    buf.write_uint16(msg.header.id)
    buf.write_uint16(msg.header.to_flags())
    buf.write_uint16(msg.header.qdcount or len(msg.questions))
    buf.write_uint16(msg.header.ancount or len(msg.answers))
    buf.write_uint16(msg.header.nscount or len(msg.authority))
    buf.write_uint16(msg.header.arcount or len(msg.additional))

    # Encode questions
    for question in msg.questions:
        buf.write_name(question.name)
        buf.write_uint16(question.qtype)
        buf.write_uint16(question.qclass)

    # Encode resource records
    for rr in msg.answers:
        _encode_resource_record(buf, rr)

    for rr in msg.authority:
        _encode_resource_record(buf, rr)

    for rr in msg.additional:
        _encode_resource_record(buf, rr)

    return buf.get_bytes()


def decode_dns_message(data: bytes) -> DNSMessage:
    """Decode DNS message from bytes (RFC 1035).

    Args:
        data: Message bytes

    Returns:
        Decoded DNSMessage

    Raises:
        FormatError: If message is malformed
    """
    buf = DNSBuffer(data)

    # Decode header
    msg_id = buf.read_uint16()
    flags = buf.read_uint16()
    qdcount = buf.read_uint16()
    ancount = buf.read_uint16()
    nscount = buf.read_uint16()
    arcount = buf.read_uint16()

    header = DNSHeader.from_flags(msg_id, flags)
    header.qdcount = qdcount
    header.ancount = ancount
    header.nscount = nscount
    header.arcount = arcount

    # Decode questions
    questions: list[DNSQuestion] = []
    for _ in range(qdcount):
        name = buf.read_name()
        qtype = RecordType(buf.read_uint16())
        qclass = buf.read_uint16()
        questions.append(DNSQuestion(name, qtype, qclass))

    # Decode answer records
    answers: list[ResourceRecord] = []
    for _ in range(ancount):
        answers.append(_decode_resource_record(buf))

    # Decode authority records
    authority: list[ResourceRecord] = []
    for _ in range(nscount):
        authority.append(_decode_resource_record(buf))

    # Decode additional records
    additional: list[ResourceRecord] = []
    for _ in range(arcount):
        additional.append(_decode_resource_record(buf))

    return DNSMessage(
        header=header,
        questions=questions,
        answers=answers,
        authority=authority,
        additional=additional,
    )


def _encode_resource_record(buf: DNSBuffer, rr: ResourceRecord) -> None:
    """Encode single resource record."""
    buf.write_name(rr.name)
    buf.write_uint16(rr.rtype)
    buf.write_uint16(rr.rclass)
    buf.write_uint32(rr.ttl)

    # Encode RDATA
    rdata_buf = DNSBuffer()
    _encode_rdata(rdata_buf, rr.rtype, rr.rdata)
    rdata_bytes = rdata_buf.get_bytes()

    buf.write_uint16(len(rdata_bytes))
    buf.write_bytes(rdata_bytes)


def _decode_resource_record(buf: DNSBuffer) -> ResourceRecord:
    """Decode single resource record."""
    name = buf.read_name()
    rtype = RecordType(buf.read_uint16())
    rclass = buf.read_uint16()
    ttl = buf.read_uint32()
    rdlen = buf.read_uint16()

    saved_pos = buf.pos
    rdata = _decode_rdata(buf, rtype, rdlen)
    buf.pos = saved_pos + rdlen

    return ResourceRecord(name, rtype, rclass, ttl, rdata)


def _encode_rdata(buf: DNSBuffer, rtype: RecordType, rdata: object) -> None:
    """Encode RDATA based on record type."""
    if rtype == RecordType.A:
        # IPv4 address (4 bytes)
        addr = IPv4Address(rdata)
        buf.write_bytes(addr.packed)

    elif rtype == RecordType.AAAA:
        # IPv6 address (16 bytes)
        addr = IPv6Address(rdata)
        buf.write_bytes(addr.packed)

    elif rtype == RecordType.CNAME or rtype == RecordType.NS or rtype == RecordType.PTR:
        # Domain name
        buf.write_name(str(rdata))

    elif rtype == RecordType.MX:
        # Preference (2 bytes) + Exchange (name)
        preference = rdata["preference"]
        exchange = rdata["exchange"]
        buf.write_uint16(preference)
        buf.write_name(exchange)

    elif rtype == RecordType.TXT:
        # Character strings
        if isinstance(rdata, list):
            strings = rdata
        else:
            strings = [rdata]
        for s in strings:
            s_bytes = str(s).encode("utf-8")
            if len(s_bytes) > 255:
                raise FormatError("TXT string exceeds 255 bytes")
            buf.write_byte(len(s_bytes))
            buf.write_bytes(s_bytes)

    elif rtype == RecordType.SOA:
        # MNAME, RNAME, SERIAL, REFRESH, RETRY, EXPIRE, MINIMUM
        buf.write_name(rdata["mname"])
        buf.write_name(rdata["rname"])
        buf.write_uint32(rdata["serial"])
        buf.write_uint32(rdata["refresh"])
        buf.write_uint32(rdata["retry"])
        buf.write_uint32(rdata["expire"])
        buf.write_uint32(rdata["minimum"])

    elif rtype == RecordType.SRV:
        # Priority, Weight, Port, Target
        buf.write_uint16(rdata["priority"])
        buf.write_uint16(rdata["weight"])
        buf.write_uint16(rdata["port"])
        buf.write_name(rdata["target"])

    else:
        raise FormatError(f"Unknown record type: {rtype}")


def _decode_rdata(buf: DNSBuffer, rtype: RecordType, rdlen: int) -> object:
    """Decode RDATA based on record type."""
    start_pos = buf.pos

    if rtype == RecordType.A:
        # IPv4 address
        return IPv4Address(buf.read_bytes(4))

    elif rtype == RecordType.AAAA:
        # IPv6 address
        return IPv6Address(buf.read_bytes(16))

    elif rtype == RecordType.CNAME or rtype == RecordType.NS or rtype == RecordType.PTR:
        # Domain name
        return buf.read_name()

    elif rtype == RecordType.MX:
        # Preference + Exchange
        preference = buf.read_uint16()
        exchange = buf.read_name()
        return {"preference": preference, "exchange": exchange}

    elif rtype == RecordType.TXT:
        # Character strings
        strings: list[str] = []
        end_pos = start_pos + rdlen
        while buf.pos < end_pos:
            length = buf.read_byte()
            s = buf.read_bytes(length).decode("utf-8", errors="replace")
            strings.append(s)
        return strings

    elif rtype == RecordType.SOA:
        # MNAME, RNAME, SERIAL, REFRESH, RETRY, EXPIRE, MINIMUM
        return {
            "mname": buf.read_name(),
            "rname": buf.read_name(),
            "serial": buf.read_uint32(),
            "refresh": buf.read_uint32(),
            "retry": buf.read_uint32(),
            "expire": buf.read_uint32(),
            "minimum": buf.read_uint32(),
        }

    elif rtype == RecordType.SRV:
        # Priority, Weight, Port, Target
        return {
            "priority": buf.read_uint16(),
            "weight": buf.read_uint16(),
            "port": buf.read_uint16(),
            "target": buf.read_name(),
        }

    else:
        # Unknown type: return raw bytes
        return buf.read_bytes(rdlen)
