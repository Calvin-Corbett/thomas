"""
Integration tests: complete DNS pipeline from zone to server to resolver to cache.
"""

import time
from ipaddress import IPv4Address

from thomas.marketplace.dns._types import (
    DNSHeader,
    DNSMessage,
    DNSQuestion,
    RecordType,
    ResourceRecord,
    ResponseCode,
)
from thomas.marketplace.dns.cache import DNSCache
from thomas.marketplace.dns.protocol import decode_dns_message, encode_dns_message
from thomas.marketplace.dns.server import DNSServer
from thomas.marketplace.dns.zone import Zone, ZoneParser


class TestDNSPipeline:
    """Test complete DNS pipeline."""

    def test_zone_to_message(self):
        """Test zone records convert to DNS messages."""
        zone = Zone("example.com.")
        zone.add_record(ResourceRecord("example.com.", RecordType.A, 1, 300, IPv4Address("192.0.2.1")))

        # Lookup from zone
        results, rcode = zone.lookup("example.com.", RecordType.A)

        # Convert to message
        question = DNSQuestion("example.com.", RecordType.A)
        header = DNSHeader(id=1, qr=True, rcode=rcode)
        message = DNSMessage(header=header, questions=[question], answers=results)

        # Encode
        data = encode_dns_message(message)
        assert isinstance(data, bytes)
        assert len(data) > 0

        # Decode
        decoded = decode_dns_message(data)
        assert len(decoded.answers) == 1

    def test_server_to_cache(self):
        """Test server response goes to cache."""
        # Setup server with zone
        zone = Zone("example.com.")
        zone.add_record(ResourceRecord("example.com.", RecordType.A, 1, 300, IPv4Address("192.0.2.1")))
        server = DNSServer()
        server.add_zone(zone)

        # Query server
        question = DNSQuestion("example.com.", RecordType.A)
        query = DNSMessage(header=DNSHeader(id=1, rd=True), questions=[question])
        response = server._process_query(query)

        # Cache response
        cache = DNSCache()
        cache.put("example.com.", RecordType.A, response.answers)

        # Retrieve from cache
        cached = cache.get("example.com.", RecordType.A)
        assert cached is not None
        assert len(cached) == 1

    def test_complete_resolution_flow(self):
        """Test complete resolution flow: zone -> server -> resolver -> cache."""
        # 1. Create zone file
        zone_content = """
        $ORIGIN example.com.
        $TTL 300

        @   IN  SOA ns1.example.com. admin.example.com. (
                    2023010101
                    3600
                    1800
                    604800
                    86400
                    )

        @   IN  NS  ns1.example.com.
        @   IN  A   192.0.2.1

        www IN  A   192.0.2.2
        www IN  AAAA 2001:db8::2

        mail IN A   192.0.2.3
        """

        # 2. Parse zone file
        parser = ZoneParser("example.com.")
        zone = parser.parse(zone_content)
        assert zone.is_valid()

        # 3. Add zone to server
        server = DNSServer()
        server.add_zone(zone)

        # 4. Query server
        question = DNSQuestion("www.example.com.", RecordType.A)
        query = DNSMessage(header=DNSHeader(id=1), questions=[question])
        response = server._process_query(query)

        assert len(response.answers) == 1
        assert response.answers[0].rdata == IPv4Address("192.0.2.2")

        # 5. Cache response
        cache = DNSCache()
        cache.put("www.example.com.", RecordType.A, response.answers)

        # 6. Retrieve from cache
        cached = cache.get("www.example.com.", RecordType.A)
        assert cached is not None
        assert len(cached) == 1

        # 7. Check cache statistics
        stats = cache.get_stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 0

    def test_cname_resolution_pipeline(self):
        """Test CNAME resolution through pipeline."""
        # Setup zone with CNAME
        zone = Zone("example.com.")
        zone.add_record(ResourceRecord("www.example.com.", RecordType.CNAME, 1, 300, "web.example.com."))
        zone.add_record(ResourceRecord("web.example.com.", RecordType.A, 1, 300, IPv4Address("192.0.2.1")))
        zone.add_record(ResourceRecord("example.com.", RecordType.NS, 1, 3600, "ns1.example.com."))

        # Query from server
        server = DNSServer()
        server.add_zone(zone)

        question = DNSQuestion("www.example.com.", RecordType.A)
        query = DNSMessage(header=DNSHeader(id=1), questions=[question])
        response = server._process_query(query)

        # Server returns CNAME
        assert len(response.answers) == 1
        assert response.answers[0].rtype == RecordType.CNAME

    def test_wildcard_resolution_pipeline(self):
        """Test wildcard resolution through pipeline."""
        zone = Zone("example.com.")
        zone.add_record(ResourceRecord("*.example.com.", RecordType.A, 1, 300, IPv4Address("192.0.2.99")))

        server = DNSServer()
        server.add_zone(zone)

        # Query wildcard match
        question = DNSQuestion("wildcard.example.com.", RecordType.A)
        query = DNSMessage(header=DNSHeader(id=1), questions=[question])
        response = server._process_query(query)

        assert len(response.answers) == 1
        assert response.answers[0].rdata == IPv4Address("192.0.2.99")

    def test_negative_caching_pipeline(self):
        """Test negative caching (NXDOMAIN)."""
        zone = Zone("example.com.")
        zone.add_record(ResourceRecord("example.com.", RecordType.NS, 1, 3600, "ns1.example.com."))

        server = DNSServer()
        server.add_zone(zone)

        # Query nonexistent record
        question = DNSQuestion("nonexistent.example.com.", RecordType.A)
        query = DNSMessage(header=DNSHeader(id=1), questions=[question])
        response = server._process_query(query)

        assert response.header.rcode == ResponseCode.NXDOMAIN

        # Cache the NXDOMAIN
        cache = DNSCache()
        cache.put("nonexistent.example.com.", RecordType.A, [], is_negative=True)

        # Lookup should return None but be a negative hit
        result = cache.get("nonexistent.example.com.", RecordType.A)
        assert result is None
        assert cache.negative_hits == 1

    def test_multiple_record_types_pipeline(self):
        """Test resolution of multiple record types."""
        zone = Zone("example.com.")
        zone.add_record(ResourceRecord("example.com.", RecordType.A, 1, 300, IPv4Address("192.0.2.1")))
        zone.add_record(ResourceRecord("example.com.", RecordType.AAAA, 1, 300, "2001:db8::1"))
        zone.add_record(
            ResourceRecord("example.com.", RecordType.MX, 1, 300, {"preference": 10, "exchange": "mail.example.com."})
        )
        zone.add_record(ResourceRecord("example.com.", RecordType.NS, 1, 3600, "ns1.example.com."))

        server = DNSServer()
        server.add_zone(zone)

        # Query each type
        for rtype in [RecordType.A, RecordType.AAAA, RecordType.MX]:
            question = DNSQuestion("example.com.", rtype)
            query = DNSMessage(header=DNSHeader(id=1), questions=[question])
            response = server._process_query(query)

            # Should return matching records
            matching = [r for r in response.answers if r.rtype == rtype]
            assert len(matching) == 1

    def test_cache_expiration_pipeline(self):
        """Test cache TTL expiration in pipeline."""
        cache = DNSCache()

        # Cache record with short TTL
        records = [ResourceRecord("example.com.", RecordType.A, 1, 1, IPv4Address("192.0.2.1"))]
        cache.put("example.com.", RecordType.A, records)

        # Should be in cache
        assert cache.get("example.com.", RecordType.A) is not None

        # Wait for expiration
        time.sleep(1.1)

        # Should be expired
        assert cache.get("example.com.", RecordType.A) is None

    def test_round_trip_encoding_decoding(self):
        """Test encoding/decoding round-trip with real records."""
        # Create complex message
        zone = Zone("example.com.")
        zone.add_record(
            ResourceRecord(
                "example.com.",
                RecordType.SOA,
                1,
                3600,
                {
                    "mname": "ns1.example.com.",
                    "rname": "admin.example.com.",
                    "serial": 2023010101,
                    "refresh": 3600,
                    "retry": 1800,
                    "expire": 604800,
                    "minimum": 86400,
                },
            )
        )
        zone.add_record(ResourceRecord("example.com.", RecordType.NS, 1, 3600, "ns1.example.com."))
        zone.add_record(ResourceRecord("example.com.", RecordType.A, 1, 300, IPv4Address("192.0.2.1")))
        zone.add_record(ResourceRecord("www.example.com.", RecordType.A, 1, 300, IPv4Address("192.0.2.2")))

        # Create message
        question = DNSQuestion("example.com.", RecordType.A)
        results, _ = zone.lookup("example.com.", RecordType.A)
        header = DNSHeader(id=42, qr=True, ra=True, rcode=ResponseCode.NOERROR)
        message = DNSMessage(
            header=header,
            questions=[question],
            answers=results,
        )

        # Encode
        data = encode_dns_message(message)

        # Decode
        decoded = decode_dns_message(data)

        # Verify
        assert decoded.header.id == 42
        assert decoded.header.qr is True
        assert len(decoded.questions) == 1
        assert len(decoded.answers) == 1

    def test_zone_file_with_multiple_records(self):
        """Test zone file parsing with various record types."""
        zone_content = """
        $ORIGIN example.com.
        $TTL 3600

        @   IN  SOA ns1.example.com. admin.example.com. (
                    2023010101 ; serial
                    3600       ; refresh
                    1800       ; retry
                    604800     ; expire
                    86400      ; minimum
                    )

        @   IN  NS  ns1.example.com.
        @   IN  NS  ns2.example.com.

        @   IN  A   192.0.2.1
        @   IN  AAAA 2001:db8::1

        @   IN  MX  10 mail.example.com.
        @   IN  MX  20 mail2.example.com.

        @   IN  TXT "v=spf1 include:_spf.example.com ~all"

        www IN  A   192.0.2.2
        web IN  CNAME www.example.com.

        mail IN A   192.0.2.3
        mail2 IN A   192.0.2.4

        ns1 IN  A   192.0.2.11
        ns2 IN  A   192.0.2.12

        _service._tcp IN SRV 10 100 80 web.example.com.
        """

        parser = ZoneParser("example.com.")
        zone = parser.parse(zone_content)

        # Verify zone
        assert zone.is_valid()
        assert zone.soa_record is not None
        assert len(zone.ns_records) == 2

        # Test lookups
        a_records, _ = zone.lookup("example.com.", RecordType.A)
        assert len(a_records) == 1

        mx_records, _ = zone.lookup("example.com.", RecordType.MX)
        assert len(mx_records) == 2

        # Test server response
        server = DNSServer()
        server.add_zone(zone)

        question = DNSQuestion("www.example.com.", RecordType.A)
        query = DNSMessage(header=DNSHeader(id=1), questions=[question])
        response = server._process_query(query)

        assert response.header.rcode == ResponseCode.NOERROR
        assert len(response.answers) == 1
