"""
DNS utilities: domain validation, punycode, reverse DNS names, TTL parsing.
"""

import re


def validate_domain_name(name: str) -> bool:
    """Validate domain name format.

    Args:
        name: Domain name to validate

    Returns:
        True if valid domain name

    Rules:
        - Each label is 1-63 characters
        - Total length <= 253 characters
        - Labels contain alphanumeric and hyphens (not starting/ending with hyphen)
        - May start with * for wildcard
    """
    if not name or len(name) > 253:
        return False

    # Remove trailing dot
    name = name.rstrip(".")

    # Check for wildcard
    if name.startswith("*."):
        name = name[2:]

    if not name:
        return False

    labels = name.split(".")

    for label in labels:
        if not label or len(label) > 63:
            return False

        # Label must contain only alphanumeric, hyphens, underscores
        if not re.match(r"^[a-zA-Z0-9_-]+$", label):
            return False

        # Label cannot start or end with hyphen
        if label.startswith("-") or label.endswith("-"):
            return False

    return True


def generate_reverse_dns_name(ip: str) -> str:
    """Generate reverse DNS name for IP address.

    Args:
        ip: IPv4 or IPv6 address

    Returns:
        Reverse DNS name (e.g., "1.2.3.4.in-addr.arpa" for 4.3.2.1)

    Examples:
        >>> generate_reverse_dns_name("192.0.2.1")
        "1.2.0.192.in-addr.arpa."

        >>> generate_reverse_dns_name("2001:db8::1")
        "1.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.8.b.d.0.1.0.0.2.ip6.arpa."
    """
    # IPv4
    if "." in ip:
        parts = ip.split(".")
        if len(parts) != 4:
            raise ValueError(f"Invalid IPv4 address: {ip}")
        reversed_parts = reversed(parts)
        return ".".join(reversed_parts) + ".in-addr.arpa."

    # IPv6
    if ":" in ip:
        # Expand IPv6 address
        expanded = _expand_ipv6(ip)
        # Remove colons and reverse order
        hex_str = expanded.replace(":", "")
        reversed_hex = reversed(hex_str)
        return ".".join(reversed_hex) + ".ip6.arpa."

    raise ValueError(f"Invalid IP address: {ip}")


def parse_ttl(ttl_str: str) -> int:
    """Parse human-readable TTL format to seconds.

    Args:
        ttl_str: TTL string (e.g., "1h30m", "3600", "1d")

    Returns:
        TTL in seconds

    Examples:
        >>> parse_ttl("3600")
        3600

        >>> parse_ttl("1h")
        3600

        >>> parse_ttl("1h30m")
        5400

        >>> parse_ttl("1d")
        86400
    """
    if not ttl_str:
        return 0

    ttl_str = ttl_str.lower().strip()

    # Try integer parse first
    try:
        return int(ttl_str)
    except ValueError:
        pass

    # Parse with units
    units = {
        "s": 1,
        "m": 60,
        "h": 3600,
        "d": 86400,
        "w": 604800,
    }

    total = 0
    pattern = r"(\d+)([smhdw])"

    for match in re.finditer(pattern, ttl_str):
        value = int(match.group(1))
        unit = match.group(2)
        total += value * units.get(unit, 0)

    return total


def punycode_encode(domain: str) -> str:
    """Encode domain name to ASCII (punycode for IDN support).

    Args:
        domain: Domain name (may contain Unicode)

    Returns:
        ASCII-encoded domain name

    Examples:
        >>> punycode_encode("münchen.example.com")
        "xn--mnchen-3ya.example.com"
    """
    labels = domain.rstrip(".").split(".")
    encoded_labels = []

    for label in labels:
        try:
            # Try ASCII first
            label.encode("ascii")
            encoded_labels.append(label)
        except UnicodeEncodeError:
            # Use punycode
            encoded_labels.append(label.encode("idna").decode("ascii"))

    return ".".join(encoded_labels)


def punycode_decode(domain: str) -> str:
    """Decode ASCII (punycode) domain name to Unicode.

    Args:
        domain: ASCII-encoded domain name

    Returns:
        Unicode domain name

    Examples:
        >>> punycode_decode("xn--mnchen-3ya.example.com")
        "münchen.example.com"
    """
    labels = domain.rstrip(".").split(".")
    decoded_labels = []

    for label in labels:
        try:
            decoded_labels.append(label.encode("ascii").decode("idna"))
        except (UnicodeError, UnicodeDecodeError):
            # Already Unicode or not punycode
            decoded_labels.append(label)

    return ".".join(decoded_labels)


def _expand_ipv6(ip: str) -> str:
    """Expand compressed IPv6 address to full format.

    Args:
        ip: IPv6 address (possibly compressed)

    Returns:
        Fully expanded IPv6 address

    Examples:
        >>> _expand_ipv6("2001:db8::1")
        "2001:0db8:0000:0000:0000:0000:0000:0001"
    """
    # Handle :: compression
    if "::" in ip:
        parts = ip.split("::")
        if len(parts) != 2:
            raise ValueError(f"Invalid IPv6 format: {ip}")

        left = parts[0].split(":") if parts[0] else []
        right = parts[1].split(":") if parts[1] else []

        # Number of missing groups
        missing = 8 - len(left) - len(right)

        # Build expanded form
        groups = left + ["0000"] * missing + right
    else:
        groups = ip.split(":")

    # Pad each group to 4 hex digits
    expanded = ":".join(g.zfill(4) for g in groups)
    return expanded


def parse_dns_name_labels(name: str) -> list:
    """Split domain name into labels.

    Args:
        name: Domain name

    Returns:
        List of labels

    Examples:
        >>> parse_dns_name_labels("www.example.com.")
        ["www", "example", "com"]
    """
    return [label for label in name.rstrip(".").split(".") if label]
