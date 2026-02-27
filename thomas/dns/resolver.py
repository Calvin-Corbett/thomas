"""
DNS resolver: recursive resolution with caching, CNAME following, and NS delegation.
"""

import logging
import socket

from thomas.dns._exceptions import (
    DNSError,
    DNSNameError,
    DNSTimeoutError,
)
from thomas.dns._types import (
    DNSHeader,
    DNSMessage,
    DNSQuestion,
    QClass,
    RecordType,
    ResourceRecord,
    ResponseCode,
)
from thomas.dns.protocol import decode_dns_message, encode_dns_message

logger = logging.getLogger(__name__)


class Resolver:
    """DNS resolver with recursive resolution, CNAME following, and caching."""

    def __init__(
        self,
        upstream_servers: list[str] | None = None,
        timeout: float = 5.0,
        retries: int = 3,
        use_tcp_fallback: bool = True,
    ) -> None:
        """Initialize resolver.

        Args:
            upstream_servers: List of upstream DNS server IPs (default: Google DNS)
            timeout: Query timeout in seconds
            retries: Number of retries per query
            use_tcp_fallback: Whether to fall back to TCP on truncation
        """
        self.upstream_servers = upstream_servers or ["8.8.8.8", "8.8.4.4"]
        self.timeout = timeout
        self.retries = retries
        self.use_tcp_fallback = use_tcp_fallback
        self.message_id = 1
        self._query_cache: dict[tuple, DNSMessage | None] = {}

    def resolve(self, name: str, rtype: RecordType = RecordType.A) -> list[ResourceRecord]:
        """Resolve a domain name to records.

        Performs recursive resolution with CNAME following and NS delegation.

        Args:
            name: Domain name to resolve
            rtype: Record type to query (default: A)

        Returns:
            List of matching resource records

        Raises:
            DNSNameError: If domain does not exist (NXDOMAIN)
            DNSTimeoutError: If query times out
            ServerFailure: If server returns SERVFAIL
        """
        cache_key = (name.lower(), rtype)
        if cache_key in self._query_cache:
            cached = self._query_cache[cache_key]
            if cached:
                return cached.answers
            return []

        visited_servers: set[str] = set()
        results = self._resolve_recursive(name, rtype, visited_servers)

        self._query_cache[cache_key] = (
            DNSMessage(DNSHeader(0), [DNSQuestion(name, rtype)], results) if results else None
        )
        return results

    def _resolve_recursive(
        self,
        name: str,
        rtype: RecordType,
        visited_servers: set[str],
        depth: int = 0,
    ) -> list[ResourceRecord]:
        """Recursive resolver implementation.

        Args:
            name: Name to resolve
            rtype: Record type
            visited_servers: Set of visited servers (cycle detection)
            depth: Current recursion depth

        Returns:
            List of matching resource records
        """
        if depth > 16:
            raise DNSError("Recursion depth exceeded")

        for server in self.upstream_servers:
            if server in visited_servers:
                continue
            visited_servers.add(server)

            try:
                response = self._query_server(server, name, rtype)

                if response.header.rcode == ResponseCode.NXDOMAIN:
                    raise DNSNameError(f"Domain {name} does not exist")
                elif response.header.rcode == ResponseCode.SERVFAIL or response.header.rcode != ResponseCode.NOERROR:
                    continue

                # Check for CNAME records
                for answer in response.answers:
                    if answer.rtype == RecordType.CNAME:
                        target = str(answer.rdata)
                        logger.debug(f"Following CNAME {name} -> {target}")
                        return self._resolve_recursive(target, rtype, visited_servers, depth + 1)

                # Return matching records
                matching = [a for a in response.answers if a.rtype == rtype]
                if matching:
                    return matching

                # Try authority records for NS delegation
                if response.authority:
                    ns_results = self._follow_delegation(name, rtype, response.authority, visited_servers, depth + 1)
                    if ns_results:
                        return ns_results

                return []

            except (OSError, DNSTimeoutError) as e:
                logger.debug(f"Query to {server} failed: {e}")
                continue

        raise DNSTimeoutError(f"All servers failed for {name}")

    def _follow_delegation(
        self,
        name: str,
        rtype: RecordType,
        authority: list[ResourceRecord],
        visited_servers: set[str],
        depth: int,
    ) -> list[ResourceRecord]:
        """Follow NS delegation records.

        Args:
            name: Name being resolved
            rtype: Record type
            authority: Authority section records
            visited_servers: Set of visited servers
            depth: Recursion depth

        Returns:
            List of resource records from delegation target
        """
        ns_records = [a for a in authority if a.rtype == RecordType.NS]
        if not ns_records:
            return []

        for ns in ns_records:
            ns_name = str(ns.rdata)
            try:
                ns_ips = self.resolve(ns_name, RecordType.A)
                for ip_record in ns_ips:
                    server = str(ip_record.rdata)
                    if server not in visited_servers:
                        return self._resolve_recursive(name, rtype, visited_servers, depth)
            except DNSError:
                continue

        return []

    def _query_server(self, server: str, name: str, rtype: RecordType) -> DNSMessage:
        """Send query to upstream server.

        Args:
            server: Server IP address
            name: Domain name
            rtype: Record type

        Returns:
            DNS response message

        Raises:
            DNSTimeoutError: If query times out
            DNSError: If query fails
        """
        question = DNSQuestion(name, rtype, QClass.IN)
        header = DNSHeader(id=self._next_message_id(), rd=True)
        message = DNSMessage(header=header, questions=[question])

        data = encode_dns_message(message)

        # Try UDP first
        response = self._query_udp(server, data)
        if not response.header.tc:
            return response

        # Fall back to TCP on truncation
        if self.use_tcp_fallback:
            logger.debug(f"Truncated response from {server}, falling back to TCP")
            return self._query_tcp(server, data)

        return response

    def _query_udp(self, server: str, data: bytes) -> DNSMessage:
        """Send query via UDP.

        Args:
            server: Server IP address
            data: Encoded DNS message

        Returns:
            DNS response message

        Raises:
            DNSTimeoutError: If query times out
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(self.timeout)

        try:
            for attempt in range(self.retries):
                try:
                    sock.sendto(data, (server, 53))
                    response_data, _ = sock.recvfrom(512)
                    return decode_dns_message(response_data)
                except TimeoutError:
                    if attempt == self.retries - 1:
                        raise DNSTimeoutError(f"Query to {server} timed out after {self.retries} attempts")
        finally:
            sock.close()

        raise DNSTimeoutError(f"Query to {server} failed")

    def _query_tcp(self, server: str, data: bytes) -> DNSMessage:
        """Send query via TCP.

        Args:
            server: Server IP address
            data: Encoded DNS message

        Returns:
            DNS response message

        Raises:
            DNSTimeoutError: If query times out
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)

        try:
            sock.connect((server, 53))
            # TCP format: 2-byte length + message
            message_with_length = len(data).to_bytes(2, "big") + data
            sock.sendall(message_with_length)

            # Read response length
            length_bytes = sock.recv(2)
            if len(length_bytes) != 2:
                raise DNSError("Failed to read response length")

            response_len = int.from_bytes(length_bytes, "big")
            response_data = b""
            while len(response_data) < response_len:
                chunk = sock.recv(response_len - len(response_data))
                if not chunk:
                    raise DNSError("Connection closed while reading response")
                response_data += chunk

            return decode_dns_message(response_data)
        finally:
            sock.close()

    def _next_message_id(self) -> int:
        """Get next message ID.

        Returns:
            16-bit message ID
        """
        self.message_id = (self.message_id + 1) & 0xFFFF
        return self.message_id

    def clear_cache(self) -> None:
        """Clear query cache."""
        self._query_cache.clear()
