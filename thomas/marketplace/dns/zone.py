"""
DNS zone management: zone data structures, BIND zone file parsing, and lookups.
"""

import re

from thomas.marketplace.dns._exceptions import FormatError
from thomas.marketplace.dns._types import RecordType, ResourceRecord, ResponseCode


class Zone:
    """DNS zone data structure with authoritative lookups."""

    def __init__(self, origin: str) -> None:
        """Initialize zone.

        Args:
            origin: Zone origin (e.g., "example.com.")
        """
        self.origin = origin.rstrip(".") + "."
        self.records: dict[str, list[ResourceRecord]] = {}
        self.soa_record: ResourceRecord | None = None
        self.ns_records: list[ResourceRecord] = []

    def add_record(self, record: ResourceRecord) -> None:
        """Add record to zone.

        Args:
            record: ResourceRecord to add
        """
        # Normalize name
        name = self._normalize_name(record.name)
        record.name = name

        if record.rtype == RecordType.SOA:
            self.soa_record = record
        elif record.rtype == RecordType.NS:
            self.ns_records.append(record)

        if name not in self.records:
            self.records[name] = []
        self.records[name].append(record)

    def lookup(self, name: str, rtype: RecordType) -> tuple[list[ResourceRecord], ResponseCode]:
        """Look up records in zone.

        Args:
            name: Domain name to look up
            rtype: Record type

        Returns:
            Tuple of (records, response_code)
        """
        name = self._normalize_name(name)

        # Check exact match
        if name in self.records:
            matching = [r for r in self.records[name] if r.rtype == rtype]
            if matching:
                return matching, ResponseCode.NOERROR

            # Check if there's a CNAME (return it if requesting other type)
            cnames = [r for r in self.records[name] if r.rtype == RecordType.CNAME]
            if cnames and rtype != RecordType.CNAME:
                return cnames, ResponseCode.NOERROR

            # Name exists but type doesn't - NOERROR with empty answer
            return [], ResponseCode.NOERROR

        # Check wildcard
        wildcard = self._find_wildcard_match(name)
        if wildcard:
            matching = [r for r in self.records[wildcard] if r.rtype == rtype]
            if matching:
                return matching, ResponseCode.NOERROR

        # Name does not exist - NXDOMAIN
        return [], ResponseCode.NXDOMAIN

    def get_authority(self, name: str) -> list[ResourceRecord]:
        """Get authority records for name.

        Args:
            name: Domain name

        Returns:
            List of NS records (authority)
        """
        name = self._normalize_name(name)

        # Check if name is in zone
        if name.endswith(self.origin):
            return self.ns_records

        return []

    def is_valid(self) -> bool:
        """Validate zone has required SOA and NS records.

        Returns:
            True if zone is valid
        """
        return self.soa_record is not None and len(self.ns_records) > 0

    def _normalize_name(self, name: str) -> str:
        """Normalize domain name relative to zone origin.

        Args:
            name: Domain name (may be relative)

        Returns:
            Fully qualified name
        """
        name = name.lower()
        if not name.endswith("."):
            # Relative to origin
            if name == "@" or name == "":
                return self.origin
            return name.rstrip(".") + "." + self.origin
        return name

    def _find_wildcard_match(self, name: str) -> str | None:
        """Find wildcard match for name.

        Args:
            name: Domain name

        Returns:
            Matching wildcard pattern or None
        """
        # Extract subdomain
        parts = name.rstrip(".").split(".")
        if len(parts) < 2:
            return None

        # Try wildcard at current level
        wildcard = "*." + ".".join(parts[1:]) + "."
        if wildcard in self.records:
            return wildcard

        # Try parent levels
        for i in range(1, len(parts) - 1):
            parent_parts = parts[i:]
            wildcard = "*." + ".".join(parent_parts) + "."
            if wildcard in self.records:
                return wildcard

        return None


class ZoneParser:
    """BIND format zone file parser."""

    # Regex patterns for zone file parsing
    COMMENT_PATTERN = re.compile(r";.*$")
    DIRECTIVE_PATTERN = re.compile(r"^\$(\w+)\s+(.+)$")
    RECORD_PATTERN = re.compile(
        r"^(\S+)\s+(?:(\d+)\s+)?(?:(IN|CH|HS)\s+)?(\w+)\s+(.+)$",
        re.IGNORECASE,
    )

    def __init__(self, origin: str = ".") -> None:
        """Initialize parser.

        Args:
            origin: Default zone origin
        """
        self.origin = origin.rstrip(".") + "." if origin != "." else "."
        self.ttl = 3600

    def parse(self, content: str) -> Zone:
        """Parse zone file content.

        Args:
            content: Zone file content

        Returns:
            Parsed Zone object

        Raises:
            FormatError: If zone file is invalid
        """
        zone = Zone(self.origin)
        lines = content.split("\n")
        line_num = 0
        current_line = ""

        for line in lines:
            line_num += 1
            # Remove comments
            line = self.COMMENT_PATTERN.sub("", line).strip()
            if not line:
                continue

            # Handle line continuation (parentheses)
            current_line += " " + line
            if "(" in line and ")" not in line:
                # Multi-line record, accumulate
                continue
            if "(" in current_line and ")" not in current_line:
                # Still waiting for closing paren
                continue

            line = current_line.strip()
            current_line = ""

            # Check for directives
            directive_match = self.DIRECTIVE_PATTERN.match(line)
            if directive_match:
                self._process_directive(directive_match.group(1), directive_match.group(2))
                # Update zone origin if ORIGIN directive was processed
                zone.origin = self.origin
                continue

            # Parse record
            try:
                record = self._parse_record(line)
                if record:
                    zone.add_record(record)
            except Exception as e:
                raise FormatError(f"Error at line {line_num}: {e}")

        return zone

    def _process_directive(self, directive: str, value: str) -> None:
        """Process zone file directive.

        Args:
            directive: Directive name ($ORIGIN, $TTL, etc.)
            value: Directive value
        """
        directive = directive.upper()

        if directive == "ORIGIN":
            self.origin = value.rstrip(".") + "."
        elif directive == "TTL":
            try:
                self.ttl = int(value)
            except ValueError:
                raise FormatError(f"Invalid TTL: {value}")

    def _parse_record(self, line: str) -> ResourceRecord | None:
        """Parse single resource record line.

        Args:
            line: Record line

        Returns:
            ResourceRecord or None
        """
        match = self.RECORD_PATTERN.match(line)
        if not match:
            return None

        name = match.group(1)
        ttl = int(match.group(2)) if match.group(2) else self.ttl
        qclass = match.group(3) or "IN"
        rtype = match.group(4).upper()
        rdata = match.group(5)

        # Normalize name
        if name == "@":
            name = self.origin
        elif not name.endswith("."):
            name = name + "." + self.origin
        else:
            name = name.rstrip(".") + "." + self.origin

        # Parse rdata based on type
        try:
            rtype_enum = RecordType[rtype]
        except KeyError:
            raise FormatError(f"Unknown record type: {rtype}")

        parsed_rdata = self._parse_rdata(rtype_enum, rdata)

        return ResourceRecord(
            name=name,
            rtype=rtype_enum,
            rclass=self._parse_class(qclass),
            ttl=ttl,
            rdata=parsed_rdata,
        )

    def _parse_rdata(self, rtype: RecordType, rdata: str) -> object:
        """Parse RDATA based on record type.

        Args:
            rtype: Record type
            rdata: Raw RDATA string

        Returns:
            Parsed RDATA object
        """
        from ipaddress import IPv4Address, IPv6Address

        # Remove comments and extra whitespace
        rdata = rdata.split(";")[0].strip()

        if rtype == RecordType.A:
            return IPv4Address(rdata)

        elif rtype == RecordType.AAAA:
            return IPv6Address(rdata)

        elif rtype == RecordType.CNAME or rtype == RecordType.NS or rtype == RecordType.PTR:
            return rdata.rstrip(".")

        elif rtype == RecordType.MX:
            parts = rdata.split(None, 1)
            if len(parts) != 2:
                raise FormatError("MX record requires preference and exchange")
            return {"preference": int(parts[0]), "exchange": parts[1].rstrip(".")}

        elif rtype == RecordType.TXT:
            # Parse quoted strings
            strings = []
            current = ""
            in_quotes = False

            for char in rdata:
                if char == '"':
                    in_quotes = not in_quotes
                elif in_quotes or not char.isspace():
                    current += char
                elif current:
                    strings.append(current)
                    current = ""

            if current:
                strings.append(current)

            return strings if strings else [rdata]

        elif rtype == RecordType.SOA:
            # Remove parentheses for multi-line SOA
            rdata_clean = rdata.replace("(", "").replace(")", "")
            parts = rdata_clean.split()
            if len(parts) < 7:
                raise FormatError("SOA record requires mname, rname, serial, refresh, retry, expire, minimum")
            return {
                "mname": parts[0].rstrip("."),
                "rname": parts[1].rstrip("."),
                "serial": int(parts[2]),
                "refresh": int(parts[3]),
                "retry": int(parts[4]),
                "expire": int(parts[5]),
                "minimum": int(parts[6]),
            }

        elif rtype == RecordType.SRV:
            parts = rdata.split()
            if len(parts) < 4:
                raise FormatError("SRV record requires priority, weight, port, target")
            return {
                "priority": int(parts[0]),
                "weight": int(parts[1]),
                "port": int(parts[2]),
                "target": parts[3].rstrip("."),
            }

        else:
            return rdata

    def _parse_class(self, qclass: str) -> int:
        """Parse DNS class.

        Args:
            qclass: Class string (IN, CH, HS)

        Returns:
            Class value
        """
        class_map = {"IN": 1, "CH": 3, "HS": 4}
        return class_map.get(qclass.upper(), 1)
