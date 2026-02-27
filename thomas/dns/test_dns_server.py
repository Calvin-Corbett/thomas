"""
Tests for DNS server: query handling, NXDOMAIN, authority/additional sections.
"""

from thomas.dns._types import (
    DNSHeader,
    DNSMessage,
    DNSQuestion,
    RecordType,
    ResourceRecord,
    ResponseCode,
)
from thomas.dns.protocol import decode_dns_message, encode_dns_message
from thomas.dns.server import DNSServer, DNSServerConnection
from thomas.dns.zone import Zone, ZoneParser


class TestDNSServer:
    """Test DNS server functionality."""

    def test_server_creation(self):
        """Test server creation."""
        server = DNSServer(port=5353, bind_address="127.0.0.1")
        assert server.port == 5353
        assert server.bind_address == "127.0.0.1"
        assert not server.running

    def test_add_zone(self):
        """Test adding zone to server."""
        server = DNSServer()
        zone = Zone("example.com.")
        server.add_zone(zone)

        assert "example.com." in server.zones

    def test_process_simple_query(self):
        """Test processing simple query."""
        server = DNSServer()

        # Add zone with record
        zone = Zone("example.com.")
        zone.add_record(ResourceRecord("example.com.", RecordType.A, 1, 300, "192.0.2.1"))
        zone.add_record(ResourceRecord("example.com.", RecordType.NS, 1, 3600, "ns1.example.com."))
        server.add_zone(zone)

        # Create query
        question = DNSQuestion("example.com.", RecordType.A)
        query = DNSMessage(header=DNSHeader(id=1, rd=True), questions=[question])

        # Process query
        response = server._process_query(query)

        assert response.header.qr is True
        assert response.header.rcode == ResponseCode.NOERROR
        assert len(response.answers) == 1
        assert response.answers[0].rdata == "192.0.2.1"

    def test_process_nxdomain(self):
        """Test NXDOMAIN response."""
        server = DNSServer()
        zone = Zone("example.com.")
        server.add_zone(zone)

        question = DNSQuestion("nonexistent.example.com.", RecordType.A)
        query = DNSMessage(header=DNSHeader(id=1), questions=[question])

        response = server._process_query(query)

        assert response.header.rcode == ResponseCode.NXDOMAIN

    def test_process_no_authority(self):
        """Test REFUSED response when no zone."""
        server = DNSServer()

        question = DNSQuestion("example.com.", RecordType.A)
        query = DNSMessage(header=DNSHeader(id=1), questions=[question])

        response = server._process_query(query)

        assert response.header.rcode == ResponseCode.REFUSED

    def test_find_zone_exact_match(self):
        """Test finding zone with exact match."""
        server = DNSServer()
        zone = Zone("example.com.")
        server.add_zone(zone)

        found = server._find_zone("example.com.")
        assert found is not None
        assert found.origin == "example.com."

    def test_find_zone_subdomain(self):
        """Test finding zone for subdomain."""
        server = DNSServer()
        zone = Zone("example.com.")
        server.add_zone(zone)

        found = server._find_zone("www.example.com.")
        assert found is not None
        assert found.origin == "example.com."

    def test_authority_section(self):
        """Test authority section in response."""
        server = DNSServer()
        zone = Zone("example.com.")
        zone.add_record(ResourceRecord("example.com.", RecordType.A, 1, 300, "192.0.2.1"))
        zone.add_record(ResourceRecord("example.com.", RecordType.NS, 1, 3600, "ns1.example.com."))
        server.add_zone(zone)

        question = DNSQuestion("example.com.", RecordType.A)
        query = DNSMessage(header=DNSHeader(id=1), questions=[question])

        response = server._process_query(query)

        assert len(response.authority) == 1
        assert response.authority[0].rtype == RecordType.NS

    def test_glue_records(self):
        """Test glue records in additional section."""
        server = DNSServer()
        zone = Zone("example.com.")

        # Add NS and A records for glue
        zone.add_record(ResourceRecord("example.com.", RecordType.NS, 1, 3600, "ns1.example.com."))
        zone.add_record(ResourceRecord("ns1.example.com.", RecordType.A, 1, 3600, "192.0.2.11"))

        server.add_zone(zone)

        question = DNSQuestion("example.com.", RecordType.A)
        query = DNSMessage(header=DNSHeader(id=1), questions=[question])

        response = server._process_query(query)

        # Should have glue record for NS server
        assert len(response.additional) > 0

    def test_query_case_insensitive(self):
        """Test case-insensitive query matching."""
        server = DNSServer()
        zone = Zone("example.com.")
        zone.add_record(ResourceRecord("example.com.", RecordType.A, 1, 300, "192.0.2.1"))
        server.add_zone(zone)

        question = DNSQuestion("EXAMPLE.COM.", RecordType.A)
        query = DNSMessage(header=DNSHeader(id=1), questions=[question])

        response = server._process_query(query)

        assert len(response.answers) == 1

    def test_multiple_questions(self):
        """Test handling multiple questions."""
        server = DNSServer()
        zone = Zone("example.com.")
        zone.add_record(ResourceRecord("example.com.", RecordType.A, 1, 300, "192.0.2.1"))
        server.add_zone(zone)

        questions = [
            DNSQuestion("example.com.", RecordType.A),
            DNSQuestion("example.com.", RecordType.AAAA),
        ]
        query = DNSMessage(header=DNSHeader(id=1), questions=questions)

        response = server._process_query(query)

        # Should process both questions
        assert len(response.questions) == 2

    def test_wildcard_response(self):
        """Test wildcard matching in response."""
        server = DNSServer()
        zone = Zone("example.com.")
        zone.add_record(ResourceRecord("*.example.com.", RecordType.A, 1, 300, "192.0.2.99"))
        server.add_zone(zone)

        question = DNSQuestion("www.example.com.", RecordType.A)
        query = DNSMessage(header=DNSHeader(id=1), questions=[question])

        response = server._process_query(query)

        assert len(response.answers) == 1


class TestDNSServerConnection:
    """Test DNS server client connection."""

    def test_connection_creation(self):
        """Test connection creation."""
        conn = DNSServerConnection("127.0.0.1", 5353, 5.0)
        assert conn.host == "127.0.0.1"
        assert conn.port == 5353
        assert conn.timeout == 5.0

    def test_query_method_exists(self):
        """Test query method exists."""
        conn = DNSServerConnection()
        assert hasattr(conn, "query")
        assert callable(conn.query)


class TestDNSServerIntegration:
    """Integration tests with server and client."""

    def test_server_with_zone_file(self):
        """Test server with parsed zone file."""
        zone_content = """
        $ORIGIN example.com.
        $TTL 86400

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
        mail IN A   192.0.2.3

        ns1 IN  A   192.0.2.11
        """

        parser = ZoneParser("example.com.")
        zone = parser.parse(zone_content)

        server = DNSServer()
        server.add_zone(zone)

        # Test query
        question = DNSQuestion("www.example.com.", RecordType.A)
        query = DNSMessage(header=DNSHeader(id=1), questions=[question])

        response = server._process_query(query)

        assert response.header.rcode == ResponseCode.NOERROR
        assert len(response.answers) == 1
        assert str(response.answers[0].rdata) == "192.0.2.2"

    def test_server_multiple_zones(self):
        """Test server with multiple zones."""
        server = DNSServer()

        # Add two zones
        zone1 = Zone("example.com.")
        zone1.add_record(ResourceRecord("example.com.", RecordType.A, 1, 300, "192.0.2.1"))
        zone1.add_record(ResourceRecord("example.com.", RecordType.NS, 1, 3600, "ns1.example.com."))

        zone2 = Zone("test.com.")
        zone2.add_record(ResourceRecord("test.com.", RecordType.A, 1, 300, "192.0.3.1"))
        zone2.add_record(ResourceRecord("test.com.", RecordType.NS, 1, 3600, "ns1.test.com."))

        server.add_zone(zone1)
        server.add_zone(zone2)

        # Query first zone
        q1 = DNSQuestion("example.com.", RecordType.A)
        resp1 = server._process_query(DNSMessage(header=DNSHeader(id=1), questions=[q1]))
        assert resp1.answers[0].rdata == "192.0.2.1"

        # Query second zone
        q2 = DNSQuestion("test.com.", RecordType.A)
        resp2 = server._process_query(DNSMessage(header=DNSHeader(id=2), questions=[q2]))
        assert resp2.answers[0].rdata == "192.0.3.1"

    def test_message_encoding_decoding_roundtrip(self):
        """Test message encoding/decoding round-trip."""
        question = DNSQuestion("example.com.", RecordType.A)
        header = DNSHeader(id=42, rd=True, ra=False)
        message = DNSMessage(header=header, questions=[question])

        data = encode_dns_message(message)
        decoded = decode_dns_message(data)

        assert decoded.header.id == 42
        assert decoded.header.rd is True
        assert len(decoded.questions) == 1
        assert decoded.questions[0].name == "example.com."
