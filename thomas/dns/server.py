"""
Mini authoritative DNS server: listen for queries and respond from local zones.
"""

import logging
import socket
import threading

from thomas.dns._exceptions import FormatError
from thomas.dns._types import (
    DNSHeader,
    DNSMessage,
    DNSQuestion,
    RecordType,
    ResponseCode,
)
from thomas.dns.protocol import decode_dns_message, encode_dns_message
from thomas.dns.zone import Zone

logger = logging.getLogger(__name__)


class DNSServer:
    """Authoritative DNS server serving from local zones."""

    def __init__(self, port: int = 5353, bind_address: str = "127.0.0.1") -> None:
        """Initialize DNS server.

        Args:
            port: UDP port to bind to
            bind_address: IP address to bind to
        """
        self.port = port
        self.bind_address = bind_address
        self.zones: dict[str, Zone] = {}
        self.running = False
        self.sock: socket.socket | None = None
        self.thread: threading.Thread | None = None

    def add_zone(self, zone: Zone) -> None:
        """Register a zone with the server.

        Args:
            zone: Zone to add
        """
        self.zones[zone.origin.lower()] = zone
        logger.info(f"Added zone {zone.origin}")

    def start(self) -> None:
        """Start DNS server in background thread."""
        if self.running:
            return

        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        logger.info(f"DNS server started on {self.bind_address}:{self.port}")

    def stop(self) -> None:
        """Stop DNS server."""
        self.running = False
        if self.sock:
            self.sock.close()
        if self.thread:
            self.thread.join(timeout=2)
        logger.info("DNS server stopped")

    def _run(self) -> None:
        """Run DNS server."""
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((self.bind_address, self.port))

        try:
            while self.running:
                try:
                    data, addr = self.sock.recvfrom(512)
                    self._handle_query(data, addr)
                except TimeoutError:
                    continue
                except Exception as e:
                    logger.error(f"Error handling query: {e}")
        finally:
            if self.sock:
                self.sock.close()

    def _handle_query(self, data: bytes, addr: tuple) -> None:
        """Handle incoming DNS query.

        Args:
            data: Query message bytes
            addr: Source address (host, port)
        """
        try:
            query = decode_dns_message(data)
        except FormatError as e:
            logger.warning(f"Invalid query from {addr}: {e}")
            return

        response = self._process_query(query)

        try:
            response_data = encode_dns_message(response)
            self.sock.sendto(response_data, addr)
        except Exception as e:
            logger.error(f"Error sending response to {addr}: {e}")

    def _process_query(self, query: DNSMessage) -> DNSMessage:
        """Process DNS query and generate response.

        Args:
            query: Query message

        Returns:
            Response message
        """
        response = DNSMessage(
            header=DNSHeader(
                id=query.header.id,
                qr=True,  # Response
                opcode=query.header.opcode,
                rd=query.header.rd,
                ra=False,  # Not recursive
            ),
            questions=query.questions,
        )

        if not query.questions:
            response.header.rcode = ResponseCode.FORMERR
            return response

        for question in query.questions:
            zone = self._find_zone(question.name)

            if not zone:
                response.header.rcode = ResponseCode.REFUSED
                continue

            # Look up records
            records, rcode = zone.lookup(question.name, question.qtype)
            response.header.rcode = rcode

            # Add answer records
            response.answers.extend(records)

            # Add authority records
            response.authority.extend(zone.get_authority(question.name))

            # Add glue records (additional section)
            self._add_glue_records(response, zone)

        return response

    def _find_zone(self, name: str) -> Zone | None:
        """Find zone responsible for name.

        Args:
            name: Domain name

        Returns:
            Zone or None
        """
        name = name.lower().rstrip(".") + "."

        # Try exact match first
        if name in self.zones:
            return self.zones[name]

        # Try parent domains
        parts = name.split(".")
        for i in range(1, len(parts)):
            parent = ".".join(parts[i:])
            if parent in self.zones:
                return self.zones[parent]

        return None

    def _add_glue_records(self, response: DNSMessage, zone: Zone) -> None:
        """Add glue records (NS server addresses) to additional section.

        Args:
            response: Response message being built
            zone: Zone being queried
        """
        for ns_record in zone.ns_records:
            ns_name = str(ns_record.rdata)

            # Look up A record for NS server
            a_records, _ = zone.lookup(ns_name, RecordType.A)
            response.additional.extend(a_records)

            # Look up AAAA record for NS server
            aaaa_records, _ = zone.lookup(ns_name, RecordType.AAAA)
            response.additional.extend(aaaa_records)


class DNSServerConnection:
    """Helper for making queries to a DNS server (client-side)."""

    def __init__(self, host: str = "127.0.0.1", port: int = 5353, timeout: float = 5.0) -> None:
        """Initialize connection.

        Args:
            host: Server host
            port: Server port
            timeout: Query timeout
        """
        self.host = host
        self.port = port
        self.timeout = timeout

    def query(self, name: str, rtype: RecordType) -> DNSMessage | None:
        """Send query to server.

        Args:
            name: Domain name
            rtype: Record type

        Returns:
            Response message or None on timeout
        """
        question = DNSQuestion(name, rtype)
        header = DNSHeader(id=1, rd=False)
        message = DNSMessage(header=header, questions=[question])

        data = encode_dns_message(message)

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(self.timeout)

        try:
            sock.sendto(data, (self.host, self.port))
            response_data, _ = sock.recvfrom(512)
            return decode_dns_message(response_data)
        except TimeoutError:
            logger.warning(f"Query to {self.host}:{self.port} timed out")
            return None
        finally:
            sock.close()
