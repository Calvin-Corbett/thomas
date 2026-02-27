"""
Tests for DNS wire protocol encoding/decoding (RFC 1035).
"""

from ipaddress import IPv4Address, IPv6Address

import pytest

from thomas.dns._exceptions import FormatError
from thomas.dns._types import (
    DNSHeader,
    DNSMessage,
    DNSQuestion,
    RecordType,
    ResourceRecord,
    ResponseCode,
)
from thomas.dns.protocol import (
    DNSBuffer,
    decode_dns_message,
    encode_dns_message,
)


class TestDNSBuffer:
    """Test DNS wire protocol buffer."""

    def test_read_write_bytes(self):
        """Test basic read/write operations."""
        buf = DNSBuffer()
        buf.write_bytes(b"hello")
        assert buf.get_bytes() == b"hello"

    def test_read_write_uint16(self):
        """Test 16-bit integer encoding."""
        buf = DNSBuffer()
        buf.write_uint16(0x1234)
        buf.write_uint16(0xABCD)

        buf2 = DNSBuffer(buf.get_bytes())
        assert buf2.read_uint16() == 0x1234
        assert buf2.read_uint16() == 0xABCD

    def test_read_write_uint32(self):
        """Test 32-bit integer encoding."""
        buf = DNSBuffer()
        buf.write_uint32(0x12345678)

        buf2 = DNSBuffer(buf.get_bytes())
        assert buf2.read_uint32() == 0x12345678

    def test_name_encoding(self):
        """Test domain name encoding."""
        buf = DNSBuffer()
        buf.write_name("www.example.com.")
        buf.write_name("example.com.")

        buf2 = DNSBuffer(buf.get_bytes())
        assert buf2.read_name() == "www.example.com."
        assert buf2.read_name() == "example.com."

    def test_name_compression(self):
        """Test domain name compression."""
        buf = DNSBuffer()
        buf.write_name("www.example.com.")
        buf.write_name("mail.example.com.")

        data = buf.get_bytes()
        # Second name should be shorter due to compression
        assert len(data) < 40

        buf2 = DNSBuffer(data)
        assert buf2.read_name() == "www.example.com."
        assert buf2.read_name() == "mail.example.com."

    def test_buffer_underrun(self):
        """Test buffer underrun error."""
        buf = DNSBuffer(b"\x00\x01")
        with pytest.raises(FormatError):
            buf.read_bytes(10)


class TestDNSMessageEncoding:
    """Test DNS message encoding."""

    def test_encode_simple_query(self):
        """Test encoding simple A query."""
        question = DNSQuestion("example.com.", RecordType.A)
        header = DNSHeader(id=1, rd=True)
        msg = DNSMessage(header=header, questions=[question])

        data = encode_dns_message(msg)
        assert len(data) > 0
        assert isinstance(data, bytes)

    def test_encode_response_with_answers(self):
        """Test encoding response with answers."""
        question = DNSQuestion("example.com.", RecordType.A)
        header = DNSHeader(id=1, qr=True, rd=True, ra=True)
        answer = ResourceRecord(
            "example.com.",
            RecordType.A,
            1,
            300,
            IPv4Address("192.0.2.1"),
        )
        msg = DNSMessage(header=header, questions=[question], answers=[answer])

        data = encode_dns_message(msg)
        assert len(data) > 0

    def test_encode_multiple_questions(self):
        """Test encoding multiple questions."""
        questions = [
            DNSQuestion("example.com.", RecordType.A),
            DNSQuestion("example.com.", RecordType.AAAA),
        ]
        header = DNSHeader(id=1)
        msg = DNSMessage(header=header, questions=questions)

        data = encode_dns_message(msg)
        assert len(data) > 0

    def test_encode_soa_record(self):
        """Test encoding SOA record."""
        soa_rdata = {
            "mname": "ns1.example.com.",
            "rname": "admin.example.com.",
            "serial": 2023010101,
            "refresh": 3600,
            "retry": 1800,
            "expire": 604800,
            "minimum": 86400,
        }
        record = ResourceRecord(
            "example.com.",
            RecordType.SOA,
            1,
            3600,
            soa_rdata,
        )
        msg = DNSMessage(
            header=DNSHeader(id=1, qr=True),
            answers=[record],
        )

        data = encode_dns_message(msg)
        assert len(data) > 0

    def test_encode_mx_record(self):
        """Test encoding MX record."""
        mx_rdata = {"preference": 10, "exchange": "mail.example.com."}
        record = ResourceRecord(
            "example.com.",
            RecordType.MX,
            1,
            3600,
            mx_rdata,
        )
        msg = DNSMessage(
            header=DNSHeader(id=1, qr=True),
            answers=[record],
        )

        data = encode_dns_message(msg)
        assert len(data) > 0

    def test_encode_txt_record(self):
        """Test encoding TXT record."""
        txt_rdata = ["v=spf1 -all"]
        record = ResourceRecord(
            "example.com.",
            RecordType.TXT,
            1,
            3600,
            txt_rdata,
        )
        msg = DNSMessage(
            header=DNSHeader(id=1, qr=True),
            answers=[record],
        )

        data = encode_dns_message(msg)
        assert len(data) > 0

    def test_encode_ipv6_record(self):
        """Test encoding AAAA record."""
        record = ResourceRecord(
            "example.com.",
            RecordType.AAAA,
            1,
            300,
            IPv6Address("2001:db8::1"),
        )
        msg = DNSMessage(
            header=DNSHeader(id=1, qr=True),
            answers=[record],
        )

        data = encode_dns_message(msg)
        assert len(data) > 0


class TestDNSMessageDecoding:
    """Test DNS message decoding."""

    def test_decode_query(self):
        """Test decoding query message."""
        # Encode then decode
        question = DNSQuestion("example.com.", RecordType.A)
        header = DNSHeader(id=42, rd=True)
        msg = DNSMessage(header=header, questions=[question])

        data = encode_dns_message(msg)
        decoded = decode_dns_message(data)

        assert decoded.header.id == 42
        assert decoded.header.rd is True
        assert len(decoded.questions) == 1
        assert decoded.questions[0].name == "example.com."

    def test_decode_response(self):
        """Test decoding response message."""
        question = DNSQuestion("example.com.", RecordType.A)
        header = DNSHeader(id=1, qr=True, rd=True, ra=True)
        answer = ResourceRecord(
            "example.com.",
            RecordType.A,
            1,
            300,
            IPv4Address("192.0.2.1"),
        )
        msg = DNSMessage(header=header, questions=[question], answers=[answer])

        data = encode_dns_message(msg)
        decoded = decode_dns_message(data)

        assert decoded.header.qr is True
        assert decoded.header.ra is True
        assert len(decoded.answers) == 1
        assert decoded.answers[0].rtype == RecordType.A

    def test_decode_malformed_message(self):
        """Test decoding malformed message."""
        with pytest.raises(FormatError):
            decode_dns_message(b"\x00\x01")

    def test_decode_soa_record(self):
        """Test decoding SOA record."""
        soa_rdata = {
            "mname": "ns1.example.com.",
            "rname": "admin.example.com.",
            "serial": 2023010101,
            "refresh": 3600,
            "retry": 1800,
            "expire": 604800,
            "minimum": 86400,
        }
        record = ResourceRecord(
            "example.com.",
            RecordType.SOA,
            1,
            3600,
            soa_rdata,
        )
        msg = DNSMessage(
            header=DNSHeader(id=1, qr=True),
            answers=[record],
        )

        data = encode_dns_message(msg)
        decoded = decode_dns_message(data)

        assert decoded.answers[0].rtype == RecordType.SOA
        soa = decoded.answers[0].rdata
        assert soa["mname"] == "ns1.example.com."
        assert soa["serial"] == 2023010101

    def test_decode_srv_record(self):
        """Test decoding SRV record."""
        srv_rdata = {
            "priority": 10,
            "weight": 100,
            "port": 80,
            "target": "web.example.com.",
        }
        record = ResourceRecord(
            "_http._tcp.example.com.",
            RecordType.SRV,
            1,
            3600,
            srv_rdata,
        )
        msg = DNSMessage(
            header=DNSHeader(id=1, qr=True),
            answers=[record],
        )

        data = encode_dns_message(msg)
        decoded = decode_dns_message(data)

        srv = decoded.answers[0].rdata
        assert srv["priority"] == 10
        assert srv["weight"] == 100
        assert srv["port"] == 80

    def test_header_flags(self):
        """Test header flags encoding/decoding."""
        header = DNSHeader(
            id=100,
            qr=True,
            opcode=2,
            aa=True,
            tc=True,
            rd=False,
            ra=True,
            rcode=ResponseCode.NXDOMAIN,
        )
        msg = DNSMessage(header=header)

        data = encode_dns_message(msg)
        decoded = decode_dns_message(data)

        assert decoded.header.qr is True
        assert decoded.header.aa is True
        assert decoded.header.tc is True
        assert decoded.header.ra is True
        assert decoded.header.rcode == ResponseCode.NXDOMAIN


class TestRecordTypeEncoding:
    """Test encoding of various record types."""

    def test_cname_record(self):
        """Test CNAME record."""
        record = ResourceRecord(
            "www.example.com.",
            RecordType.CNAME,
            1,
            3600,
            "web.example.com.",
        )
        msg = DNSMessage(
            header=DNSHeader(id=1, qr=True),
            answers=[record],
        )

        data = encode_dns_message(msg)
        decoded = decode_dns_message(data)

        assert decoded.answers[0].rdata == "web.example.com."

    def test_ns_record(self):
        """Test NS record."""
        record = ResourceRecord(
            "example.com.",
            RecordType.NS,
            1,
            3600,
            "ns1.example.com.",
        )
        msg = DNSMessage(
            header=DNSHeader(id=1, qr=True),
            answers=[record],
        )

        data = encode_dns_message(msg)
        decoded = decode_dns_message(data)

        assert decoded.answers[0].rdata == "ns1.example.com."

    def test_ptr_record(self):
        """Test PTR record."""
        record = ResourceRecord(
            "1.2.0.192.in-addr.arpa.",
            RecordType.PTR,
            1,
            3600,
            "example.com.",
        )
        msg = DNSMessage(
            header=DNSHeader(id=1, qr=True),
            answers=[record],
        )

        data = encode_dns_message(msg)
        decoded = decode_dns_message(data)

        assert decoded.answers[0].rdata == "example.com."

    def test_multi_line_txt_record(self):
        """Test TXT record with multiple strings."""
        txt_rdata = ["part1", "part2", "part3"]
        record = ResourceRecord(
            "example.com.",
            RecordType.TXT,
            1,
            3600,
            txt_rdata,
        )
        msg = DNSMessage(
            header=DNSHeader(id=1, qr=True),
            answers=[record],
        )

        data = encode_dns_message(msg)
        decoded = decode_dns_message(data)

        assert len(decoded.answers[0].rdata) == 3
