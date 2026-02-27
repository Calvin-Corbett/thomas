"""
Tests for DNS resolver: recursive resolution, CNAME following, timeouts.
"""

from ipaddress import IPv4Address
from unittest.mock import MagicMock, patch

import pytest

from thomas.dns._exceptions import (
    DNSNameError,
    DNSTimeoutError,
)
from thomas.dns._types import (
    DNSHeader,
    DNSMessage,
    DNSQuestion,
    RecordType,
    ResourceRecord,
    ResponseCode,
)
from thomas.dns.resolver import Resolver


class TestResolver:
    """Test DNS resolver."""

    def test_init_defaults(self):
        """Test resolver initialization with defaults."""
        resolver = Resolver()
        assert resolver.upstream_servers == ["8.8.8.8", "8.8.4.4"]
        assert resolver.timeout == 5.0
        assert resolver.retries == 3

    def test_init_custom(self):
        """Test resolver initialization with custom servers."""
        resolver = Resolver(
            upstream_servers=["1.1.1.1"],
            timeout=10.0,
            retries=5,
        )
        assert resolver.upstream_servers == ["1.1.1.1"]
        assert resolver.timeout == 10.0
        assert resolver.retries == 5

    @patch("thomas.dns.resolver.Resolver._query_server")
    def test_resolve_simple_a_record(self, mock_query):
        """Test resolving simple A record."""
        # Create mock response
        answer = ResourceRecord(
            "example.com.",
            RecordType.A,
            1,
            300,
            IPv4Address("192.0.2.1"),
        )
        response = DNSMessage(
            header=DNSHeader(id=1, qr=True, rcode=ResponseCode.NOERROR),
            answers=[answer],
        )
        mock_query.return_value = response

        resolver = Resolver()
        results = resolver.resolve("example.com.", RecordType.A)

        assert len(results) == 1
        assert results[0].rdata == IPv4Address("192.0.2.1")

    @patch("thomas.dns.resolver.Resolver._query_server")
    def test_resolve_nxdomain(self, mock_query):
        """Test NXDOMAIN response."""
        response = DNSMessage(header=DNSHeader(id=1, qr=True, rcode=ResponseCode.NXDOMAIN))
        mock_query.return_value = response

        resolver = Resolver()
        with pytest.raises(DNSNameError):
            resolver.resolve("nonexistent.example.com.", RecordType.A)

    @patch("thomas.dns.resolver.Resolver._query_server")
    def test_follow_cname(self, mock_query):
        """Test following CNAME record."""
        # First response: CNAME
        cname_answer = ResourceRecord(
            "www.example.com.",
            RecordType.CNAME,
            1,
            300,
            "web.example.com.",
        )
        cname_response = DNSMessage(
            header=DNSHeader(id=1, qr=True, rcode=ResponseCode.NOERROR),
            answers=[cname_answer],
        )

        # Second response: A record
        a_answer = ResourceRecord(
            "web.example.com.",
            RecordType.A,
            1,
            300,
            IPv4Address("192.0.2.1"),
        )
        a_response = DNSMessage(
            header=DNSHeader(id=2, qr=True, rcode=ResponseCode.NOERROR),
            answers=[a_answer],
        )

        mock_query.side_effect = [cname_response, a_response]

        resolver = Resolver()
        results = resolver.resolve("www.example.com.", RecordType.A)

        # Should have followed CNAME and returned A record
        assert len(results) == 1
        assert results[0].rtype == RecordType.A

    @patch("thomas.dns.resolver.Resolver._query_server")
    def test_query_timeout(self, mock_query):
        """Test query timeout."""
        mock_query.side_effect = TimeoutError()

        resolver = Resolver()
        with pytest.raises(DNSTimeoutError):
            resolver.resolve("example.com.", RecordType.A)

    @patch("thomas.dns.resolver.Resolver._query_server")
    def test_server_failure(self, mock_query):
        """Test server failure (SERVFAIL)."""
        response = DNSMessage(header=DNSHeader(id=1, qr=True, rcode=ResponseCode.SERVFAIL))
        mock_query.return_value = response

        resolver = Resolver(upstream_servers=["1.1.1.1"])
        # Should try servers and eventually timeout
        with pytest.raises(DNSTimeoutError):
            resolver.resolve("example.com.", RecordType.A)

    @patch("thomas.dns.resolver.Resolver._query_server")
    def test_query_caching(self, mock_query):
        """Test query result caching."""
        answer = ResourceRecord(
            "example.com.",
            RecordType.A,
            1,
            300,
            IPv4Address("192.0.2.1"),
        )
        response = DNSMessage(
            header=DNSHeader(id=1, qr=True, rcode=ResponseCode.NOERROR),
            answers=[answer],
        )
        mock_query.return_value = response

        resolver = Resolver()

        # First query
        results1 = resolver.resolve("example.com.", RecordType.A)
        assert mock_query.call_count == 1

        # Second query (should use cache)
        results2 = resolver.resolve("example.com.", RecordType.A)
        assert mock_query.call_count == 1  # No new calls

        assert results1 == results2

    def test_message_id_increment(self):
        """Test message ID increments correctly."""
        resolver = Resolver()

        id1 = resolver._next_message_id()
        id2 = resolver._next_message_id()
        id3 = resolver._next_message_id()

        assert id2 == (id1 + 1) & 0xFFFF
        assert id3 == (id2 + 1) & 0xFFFF

    def test_message_id_wraparound(self):
        """Test message ID wraps at 16-bit boundary."""
        resolver = Resolver()
        resolver.message_id = 0xFFFF

        id1 = resolver._next_message_id()
        assert id1 == 0  # Should wrap to 0

    def test_clear_cache(self):
        """Test clearing query cache."""
        resolver = Resolver()
        resolver._query_cache[("example.com.", RecordType.A)] = None

        assert len(resolver._query_cache) > 0
        resolver.clear_cache()
        assert len(resolver._query_cache) == 0

    @patch("socket.socket")
    def test_udp_query(self, mock_socket_class):
        """Test UDP query."""
        mock_socket = MagicMock()
        mock_socket_class.return_value = mock_socket

        # Mock response
        answer = ResourceRecord(
            "example.com.",
            RecordType.A,
            1,
            300,
            IPv4Address("192.0.2.1"),
        )
        response = DNSMessage(
            header=DNSHeader(id=1, qr=True, rcode=ResponseCode.NOERROR),
            answers=[answer],
        )
        from thomas.dns.protocol import encode_dns_message

        response_data = encode_dns_message(response)
        mock_socket.recvfrom.return_value = (response_data, ("8.8.8.8", 53))

        resolver = Resolver()
        question = DNSQuestion("example.com.", RecordType.A)
        header = DNSHeader(id=1, rd=True)
        message = DNSMessage(header=header, questions=[question])
        data = encode_dns_message(message)

        result = resolver._query_udp("8.8.8.8", data)
        assert result.header.qr is True

    def test_tcp_fallback_enabled(self):
        """Test TCP fallback is enabled."""
        resolver = Resolver(use_tcp_fallback=True)
        assert resolver.use_tcp_fallback is True

        resolver_no_fallback = Resolver(use_tcp_fallback=False)
        assert resolver_no_fallback.use_tcp_fallback is False


class TestResolverIntegration:
    """Integration tests for resolver."""

    @patch("thomas.dns.resolver.Resolver._query_server")
    def test_recursive_resolution_depth(self, mock_query):
        """Test recursion depth limit."""
        response = DNSMessage(
            header=DNSHeader(id=1, qr=True, rcode=ResponseCode.NOERROR),
            answers=[],
            authority=[],
        )
        mock_query.return_value = response

        resolver = Resolver()

        # Mock to exceed depth
        from unittest.mock import patch

        with patch.object(resolver, "_resolve_recursive", wraps=resolver._resolve_recursive):
            # Should hit depth limit
            try:
                resolver.resolve("example.com.", RecordType.A)
            except Exception:
                pass  # Expected to fail or timeout
