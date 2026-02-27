"""
Tests for DNS zone management: zone parsing, lookups, wildcards, validation.
"""

import pytest

from thomas.dns._exceptions import FormatError
from thomas.dns._types import RecordType, ResourceRecord, ResponseCode
from thomas.dns.zone import Zone, ZoneParser


class TestZone:
    """Test Zone data structure."""

    def test_zone_creation(self):
        """Test zone creation."""
        zone = Zone("example.com.")
        assert zone.origin == "example.com."
        assert len(zone.records) == 0

    def test_add_record(self):
        """Test adding records to zone."""
        zone = Zone("example.com.")
        record = ResourceRecord(
            "www.example.com.",
            RecordType.A,
            1,
            300,
            "192.0.2.1",
        )
        zone.add_record(record)

        assert "www.example.com." in zone.records

    def test_add_soa_record(self):
        """Test adding SOA record."""
        zone = Zone("example.com.")
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
        zone.add_record(record)

        assert zone.soa_record is not None

    def test_add_ns_records(self):
        """Test adding NS records."""
        zone = Zone("example.com.")
        ns_record = ResourceRecord(
            "example.com.",
            RecordType.NS,
            1,
            3600,
            "ns1.example.com.",
        )
        zone.add_record(ns_record)

        assert len(zone.ns_records) == 1

    def test_lookup_exact_match(self):
        """Test exact match lookup."""
        zone = Zone("example.com.")
        record = ResourceRecord(
            "www.example.com.",
            RecordType.A,
            1,
            300,
            "192.0.2.1",
        )
        zone.add_record(record)

        results, rcode = zone.lookup("www.example.com.", RecordType.A)

        assert len(results) == 1
        assert results[0].rdata == "192.0.2.1"
        assert rcode == ResponseCode.NOERROR

    def test_lookup_nonexistent(self):
        """Test lookup for nonexistent name."""
        zone = Zone("example.com.")

        results, rcode = zone.lookup("nonexistent.example.com.", RecordType.A)

        assert len(results) == 0
        assert rcode == ResponseCode.NXDOMAIN

    def test_lookup_wrong_type(self):
        """Test lookup for wrong record type."""
        zone = Zone("example.com.")
        record = ResourceRecord(
            "example.com.",
            RecordType.A,
            1,
            300,
            "192.0.2.1",
        )
        zone.add_record(record)

        results, rcode = zone.lookup("example.com.", RecordType.AAAA)

        assert len(results) == 0
        assert rcode == ResponseCode.NOERROR

    def test_wildcard_matching(self):
        """Test wildcard matching."""
        zone = Zone("example.com.")
        record = ResourceRecord(
            "*.example.com.",
            RecordType.A,
            1,
            300,
            "192.0.2.1",
        )
        zone.add_record(record)

        results, rcode = zone.lookup("www.example.com.", RecordType.A)

        assert len(results) == 1
        assert results[0].rdata == "192.0.2.1"

    def test_wildcard_no_match_apex(self):
        """Test wildcard doesn't match apex."""
        zone = Zone("example.com.")
        record = ResourceRecord(
            "*.example.com.",
            RecordType.A,
            1,
            300,
            "192.0.2.1",
        )
        zone.add_record(record)

        results, rcode = zone.lookup("example.com.", RecordType.A)

        # Should not match (wildcard is for subdomains only)
        assert rcode == ResponseCode.NXDOMAIN

    def test_zone_validity(self):
        """Test zone validation."""
        zone = Zone("example.com.")

        # Invalid without SOA and NS
        assert not zone.is_valid()

        # Add SOA
        soa_rdata = {
            "mname": "ns1.example.com.",
            "rname": "admin.example.com.",
            "serial": 1,
            "refresh": 3600,
            "retry": 1800,
            "expire": 604800,
            "minimum": 86400,
        }
        zone.add_record(ResourceRecord("example.com.", RecordType.SOA, 1, 3600, soa_rdata))

        # Still invalid without NS
        assert not zone.is_valid()

        # Add NS
        zone.add_record(ResourceRecord("example.com.", RecordType.NS, 1, 3600, "ns1.example.com."))

        # Now valid
        assert zone.is_valid()


class TestZoneParser:
    """Test BIND zone file parser."""

    def test_parse_simple_record(self):
        """Test parsing simple A record."""
        content = """
        @ IN A 192.0.2.1
        """
        parser = ZoneParser("example.com.")
        zone = parser.parse(content)

        results, _ = zone.lookup("example.com.", RecordType.A)
        assert len(results) == 1

    def test_parse_subdomain(self):
        """Test parsing subdomain."""
        content = """
        www IN A 192.0.2.2
        """
        parser = ZoneParser("example.com.")
        zone = parser.parse(content)

        results, _ = zone.lookup("www.example.com.", RecordType.A)
        assert len(results) == 1

    def test_parse_with_comments(self):
        """Test parsing with comments."""
        content = """
        ; This is a comment
        @ IN A 192.0.2.1
        ; Another comment
        www IN A 192.0.2.2
        """
        parser = ZoneParser("example.com.")
        zone = parser.parse(content)

        results, _ = zone.lookup("example.com.", RecordType.A)
        assert len(results) == 1

    def test_parse_origin_directive(self):
        """Test $ORIGIN directive."""
        content = """
        $ORIGIN example.com.
        @ IN A 192.0.2.1
        """
        parser = ZoneParser(".")
        zone = parser.parse(content)

        assert zone.origin == "example.com."

    def test_parse_ttl_directive(self):
        """Test $TTL directive."""
        content = """
        $TTL 86400
        @ IN A 192.0.2.1
        """
        parser = ZoneParser("example.com.")
        zone = parser.parse(content)

        results, _ = zone.lookup("example.com.", RecordType.A)
        assert results[0].ttl == 86400

    def test_parse_explicit_ttl(self):
        """Test explicit TTL in record."""
        content = """
        @ 3600 IN A 192.0.2.1
        """
        parser = ZoneParser("example.com.")
        zone = parser.parse(content)

        results, _ = zone.lookup("example.com.", RecordType.A)
        assert results[0].ttl == 3600

    def test_parse_soa_record(self):
        """Test parsing SOA record."""
        content = """
        @ IN SOA ns1.example.com. admin.example.com. 2023010101 3600 1800 604800 86400
        """
        parser = ZoneParser("example.com.")
        zone = parser.parse(content)

        assert zone.soa_record is not None
        soa = zone.soa_record.rdata
        assert soa["serial"] == 2023010101

    def test_parse_ns_record(self):
        """Test parsing NS record."""
        content = """
        @ IN NS ns1.example.com.
        @ IN NS ns2.example.com.
        """
        parser = ZoneParser("example.com.")
        zone = parser.parse(content)

        assert len(zone.ns_records) == 2

    def test_parse_mx_record(self):
        """Test parsing MX record."""
        content = """
        @ IN MX 10 mail.example.com.
        """
        parser = ZoneParser("example.com.")
        zone = parser.parse(content)

        results, _ = zone.lookup("example.com.", RecordType.MX)
        assert len(results) == 1
        assert results[0].rdata["preference"] == 10

    def test_parse_txt_record(self):
        """Test parsing TXT record."""
        content = """
        @ IN TXT "v=spf1 -all"
        """
        parser = ZoneParser("example.com.")
        zone = parser.parse(content)

        results, _ = zone.lookup("example.com.", RecordType.TXT)
        assert len(results) == 1

    def test_parse_cname_record(self):
        """Test parsing CNAME record."""
        content = """
        www IN CNAME web.example.com.
        """
        parser = ZoneParser("example.com.")
        zone = parser.parse(content)

        results, _ = zone.lookup("www.example.com.", RecordType.CNAME)
        assert len(results) == 1

    def test_parse_wildcard(self):
        """Test parsing wildcard record."""
        content = """
        * IN A 192.0.2.99
        """
        parser = ZoneParser("example.com.")
        zone = parser.parse(content)

        results, _ = zone.lookup("any.example.com.", RecordType.A)
        assert len(results) == 1

    def test_parse_relative_names(self):
        """Test parsing relative names."""
        content = """
        www IN A 192.0.2.1
        mail IN A 192.0.2.2
        """
        parser = ZoneParser("example.com.")
        zone = parser.parse(content)

        results, _ = zone.lookup("www.example.com.", RecordType.A)
        assert len(results) == 1

    def test_parse_invalid_record(self):
        """Test parsing invalid record."""
        content = """
        invalid record line
        """
        parser = ZoneParser("example.com.")

        with pytest.raises(FormatError):
            parser.parse(content)

    def test_parse_multiple_records_same_name(self):
        """Test parsing multiple records for same name."""
        content = """
        @ IN A 192.0.2.1
        @ IN A 192.0.2.2
        """
        parser = ZoneParser("example.com.")
        zone = parser.parse(content)

        results, _ = zone.lookup("example.com.", RecordType.A)
        assert len(results) == 2

    def test_parse_complete_zone_file(self):
        """Test parsing complete zone file."""
        content = """
        $ORIGIN example.com.
        $TTL 86400

        @   IN  SOA ns1.example.com. admin.example.com. (
                    2023010101  ; serial
                    3600        ; refresh
                    1800        ; retry
                    604800      ; expire
                    86400       ; minimum
                    )

        @   IN  NS  ns1.example.com.
        @   IN  NS  ns2.example.com.

        @   IN  A   192.0.2.1
        www IN  A   192.0.2.2
        mail IN A   192.0.2.3

        @   IN  MX  10 mail.example.com.

        ns1 IN  A   192.0.2.11
        ns2 IN  A   192.0.2.12
        """
        parser = ZoneParser("example.com.")
        zone = parser.parse(content)

        assert zone.is_valid()
        assert len(zone.records) > 0
        assert zone.soa_record is not None
        assert len(zone.ns_records) == 2
