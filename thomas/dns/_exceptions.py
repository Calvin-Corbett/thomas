"""
DNS protocol exceptions.
"""


class DNSError(Exception):
    """Base exception for DNS operations."""

    pass


class FormatError(DNSError):
    """DNS message format error (FORMERR)."""

    pass


class ServerFailure(DNSError):
    """DNS server failure (SERVFAIL)."""

    pass


class DNSNameError(DNSError):
    """Non-existent domain name (NXDOMAIN)."""

    pass


# Alias for compatibility
NameError = DNSNameError


class NotImplementedError(DNSError):
    """Operation not implemented (NOTIMP)."""

    pass


class RefusedError(DNSError):
    """Query refused (REFUSED)."""

    pass


class DNSTimeoutError(DNSError):
    """DNS query timeout."""

    pass


# Alias for compatibility
TimeoutError = DNSTimeoutError
