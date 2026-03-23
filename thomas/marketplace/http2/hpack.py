"""HPACK header compression (RFC 7541)."""

from thomas.marketplace.http2._exceptions import CompressionError
from thomas.marketplace.http2.huffman_table import HuffmanDecoder, HuffmanEncoder

# HPACK static table (first 61 entries per RFC 7541 Appendix B)
STATIC_TABLE: list[tuple[bytes, bytes]] = [
    (b":authority", b""),
    (b":method", b"GET"),
    (b":method", b"POST"),
    (b":path", b"/"),
    (b":path", b"/index.html"),
    (b":scheme", b"http"),
    (b":scheme", b"https"),
    (b":status", b"200"),
    (b":status", b"204"),
    (b":status", b"206"),
    (b":status", b"304"),
    (b":status", b"400"),
    (b":status", b"404"),
    (b":status", b"500"),
    (b"accept-charset", b""),
    (b"accept-encoding", b"gzip, deflate"),
    (b"accept-language", b""),
    (b"accept-ranges", b"bytes"),
    (b"accept", b""),
    (b"access-control-allow-origin", b""),
    (b"age", b""),
    (b"allow", b""),
    (b"authorization", b""),
    (b"cache-control", b""),
    (b"content-disposition", b""),
    (b"content-encoding", b""),
    (b"content-language", b""),
    (b"content-length", b""),
    (b"content-location", b""),
    (b"content-range", b""),
    (b"content-type", b""),
    (b"cookie", b""),
    (b"date", b""),
    (b"etag", b""),
    (b"expect", b""),
    (b"expires", b""),
    (b"from", b""),
    (b"host", b""),
    (b"if-match", b""),
    (b"if-modified-since", b""),
    (b"if-none-match", b""),
    (b"if-range", b""),
    (b"if-unmodified-since", b""),
    (b"last-modified", b""),
    (b"link", b""),
    (b"location", b""),
    (b"max-forwards", b""),
    (b"proxy-authenticate", b""),
    (b"proxy-authorization", b""),
    (b"range", b""),
    (b"referer", b""),
    (b"refresh", b""),
    (b"retry-after", b""),
    (b"server", b""),
    (b"set-cookie", b""),
    (b"strict-transport-security", b""),
    (b"transfer-encoding", b""),
    (b"user-agent", b""),
    (b"vary", b""),
    (b"via", b""),
    (b"www-authenticate", b""),
]


class HeaderEncoder:
    """HPACK header encoder."""

    def __init__(self, max_dynamic_table_size: int = 4096) -> None:
        """Initialize encoder.

        Args:
            max_dynamic_table_size: Maximum size of dynamic table.
        """
        self.max_dynamic_table_size = max_dynamic_table_size
        self.dynamic_table: list[tuple[bytes, bytes]] = []
        self.dynamic_table_size = 0
        self.huffman_encoder = HuffmanEncoder()

    def encode_headers(self, headers: list[tuple[bytes, bytes]]) -> bytes:
        """Encode header list.

        Args:
            headers: List of (name, value) tuples.

        Returns:
            Encoded header block.
        """
        result = b""

        for name, value in headers:
            result += self._encode_header(name, value)

        return result

    def _encode_header(self, name: bytes, value: bytes) -> bytes:
        """Encode a single header field.

        Args:
            name: Header name.
            value: Header value.

        Returns:
            Encoded header field.
        """
        # Try to find in static or dynamic table
        static_idx = self._find_static_table(name, value)
        if static_idx is not None:
            return self._encode_indexed(static_idx)

        # Try to find name-only match
        name_idx = self._find_name_in_tables(name)

        # Use literal with incremental indexing
        result = b""
        if name_idx is not None:
            result += self._encode_indexed_name(name_idx, value, with_indexing=True)
        else:
            result += self._encode_literal_name(name, value, with_indexing=True)

        # Add to dynamic table
        self._add_to_dynamic_table(name, value)

        return result

    def _encode_indexed(self, index: int) -> bytes:
        """Encode an indexed header.

        Args:
            index: Static table index (1-based).

        Returns:
            Encoded indexed header.
        """
        if index < 1 or index > 61:
            raise ValueError(f"Invalid static table index: {index}")

        return self._encode_integer(index, 7, 0x80)

    def _encode_indexed_name(self, index: int, value: bytes, with_indexing: bool = True) -> bytes:
        """Encode header with indexed name.

        Args:
            index: Name index.
            value: Header value.
            with_indexing: Whether to use incremental indexing.

        Returns:
            Encoded header.
        """
        if with_indexing:
            prefix = 0x40
            bits = 6
        else:
            prefix = 0x00
            bits = 4

        result = self._encode_integer(index, bits, prefix)
        result += self._encode_string(value)
        return result

    def _encode_literal_name(self, name: bytes, value: bytes, with_indexing: bool = True) -> bytes:
        """Encode header with literal name.

        Args:
            name: Header name.
            value: Header value.
            with_indexing: Whether to use incremental indexing.

        Returns:
            Encoded header.
        """
        if with_indexing:
            result = bytes([0x40])  # Literal with incremental indexing
        else:
            result = b""  # Literal without indexing

        result += self._encode_string(name)
        result += self._encode_string(value)
        return result

    def _encode_string(self, data: bytes) -> bytes:
        """Encode a string with optional Huffman compression.

        Args:
            data: String to encode.

        Returns:
            Encoded string (length + data).
        """
        # Try Huffman encoding
        huffman_encoded = self.huffman_encoder.encode(data)

        # Use Huffman if smaller
        if len(huffman_encoded) < len(data):
            length = self._encode_integer(len(huffman_encoded), 7, 0x80)
            return length + huffman_encoded
        else:
            length = self._encode_integer(len(data), 7, 0x00)
            return length + data

    def _encode_integer(self, value: int, prefix_bits: int, prefix_byte: int) -> bytes:
        """Encode an integer with prefix.

        Args:
            value: Integer value.
            prefix_bits: Number of prefix bits (5, 6, or 7).
            prefix_byte: Prefix byte value.

        Returns:
            Encoded integer.
        """
        max_prefix = (1 << prefix_bits) - 1

        if value < max_prefix:
            return bytes([prefix_byte | value])

        result = bytearray([prefix_byte | max_prefix])
        value -= max_prefix

        while value >= 128:
            result.append((value % 128) | 0x80)
            value //= 128

        result.append(value)
        return bytes(result)

    def _find_static_table(self, name: bytes, value: bytes) -> int | None:
        """Find header in static table (exact match).

        Args:
            name: Header name.
            value: Header value.

        Returns:
            1-based index or None.
        """
        for i, (sname, svalue) in enumerate(STATIC_TABLE, 1):
            if sname == name and svalue == value:
                return i
        return None

    def _find_name_in_tables(self, name: bytes) -> int | None:
        """Find name in static or dynamic table.

        Args:
            name: Header name.

        Returns:
            Index or None.
        """
        # Check dynamic table first
        for i, (dname, _) in enumerate(self.dynamic_table):
            if dname == name:
                return len(STATIC_TABLE) + 1 + i

        # Check static table
        for i, (sname, _) in enumerate(STATIC_TABLE, 1):
            if sname == name:
                return i

        return None

    def _add_to_dynamic_table(self, name: bytes, value: bytes) -> None:
        """Add header to dynamic table.

        Args:
            name: Header name.
            value: Header value.
        """
        entry_size = len(name) + len(value) + 32

        # Evict entries if necessary
        while self.dynamic_table_size + entry_size > self.max_dynamic_table_size:
            if not self.dynamic_table:
                break
            old_name, old_value = self.dynamic_table.pop()
            self.dynamic_table_size -= len(old_name) + len(old_value) + 32

        self.dynamic_table.insert(0, (name, value))
        self.dynamic_table_size += entry_size

    def update_max_table_size(self, size: int) -> bytes:
        """Update maximum dynamic table size.

        Args:
            size: New maximum size.

        Returns:
            Encoded table size update.
        """
        self.max_dynamic_table_size = size
        return self._encode_integer(size, 5, 0x20)


class HeaderDecoder:
    """HPACK header decoder."""

    def __init__(self, max_dynamic_table_size: int = 4096) -> None:
        """Initialize decoder.

        Args:
            max_dynamic_table_size: Maximum size of dynamic table.
        """
        self.max_dynamic_table_size = max_dynamic_table_size
        self.dynamic_table: list[tuple[bytes, bytes]] = []
        self.dynamic_table_size = 0
        self.huffman_decoder = HuffmanDecoder()

    def decode_headers(self, data: bytes) -> list[tuple[bytes, bytes]]:
        """Decode header block.

        Args:
            data: Encoded header block.

        Returns:
            List of (name, value) tuples.

        Raises:
            CompressionError: If data is invalid.
        """
        headers: list[tuple[bytes, bytes]] = []
        pos = 0

        while pos < len(data):
            header, consumed = self._decode_header(data[pos:])
            headers.append(header)
            pos += consumed

        return headers

    def _decode_header(self, data: bytes) -> tuple[tuple[bytes, bytes], int]:
        """Decode a single header field.

        Args:
            data: Encoded header data.

        Returns:
            Tuple of ((name, value), bytes_consumed).

        Raises:
            CompressionError: If data is invalid.
        """
        if not data:
            raise CompressionError("Empty header data")

        first_byte = data[0]

        # Indexed header
        if first_byte & 0x80:
            index, consumed = self._decode_integer(data, 7)
            if index == 0:
                raise CompressionError("Invalid indexed header index: 0")

            name, value = self._get_from_table(index)
            return (name, value), consumed

        # Literal with incremental indexing
        elif first_byte & 0x40:
            index, consumed = self._decode_integer(data, 6)
            pos = consumed

            if index == 0:
                name, consumed_name = self._decode_string(data[pos:])
                pos += consumed_name
            else:
                name, _ = self._get_from_table(index)

            value, consumed_value = self._decode_string(data[pos:])
            pos += consumed_value

            self._add_to_dynamic_table(name, value)
            return (name, value), pos

        # Table size update
        elif first_byte & 0x20:
            size, consumed = self._decode_integer(data, 5)
            if size > self.max_dynamic_table_size:
                raise CompressionError(f"Dynamic table size {size} exceeds maximum {self.max_dynamic_table_size}")
            self.max_dynamic_table_size = size

            # Evict entries if necessary
            while self.dynamic_table_size > size:
                if not self.dynamic_table:
                    break
                name, value = self.dynamic_table.pop()
                self.dynamic_table_size -= len(name) + len(value) + 32

            return self._decode_header(data[consumed:])

        # Literal without indexing
        else:
            index, consumed = self._decode_integer(data, 4)
            pos = consumed

            if index == 0:
                name, consumed_name = self._decode_string(data[pos:])
                pos += consumed_name
            else:
                name, _ = self._get_from_table(index)

            value, consumed_value = self._decode_string(data[pos:])
            pos += consumed_value

            return (name, value), pos

    def _decode_integer(self, data: bytes, prefix_bits: int) -> tuple[int, int]:
        """Decode an integer with prefix.

        Args:
            data: Encoded data.
            prefix_bits: Number of prefix bits (4, 5, 6, or 7).

        Returns:
            Tuple of (value, bytes_consumed).

        Raises:
            CompressionError: If data is invalid.
        """
        if not data:
            raise CompressionError("Empty data for integer decoding")

        max_prefix = (1 << prefix_bits) - 1
        first_byte = data[0]
        value = first_byte & max_prefix

        if value < max_prefix:
            return value, 1

        pos = 1
        m = 0

        while pos < len(data):
            byte = data[pos]
            value += (byte & 0x7F) << m
            pos += 1
            if byte & 0x80 == 0:
                return value, pos

            m += 7

        raise CompressionError("Incomplete integer encoding")

    def _decode_string(self, data: bytes) -> tuple[bytes, int]:
        """Decode a string with optional Huffman compression.

        Args:
            data: Encoded string data.

        Returns:
            Tuple of (string, bytes_consumed).

        Raises:
            CompressionError: If data is invalid.
        """
        if not data:
            raise CompressionError("Empty data for string decoding")

        first_byte = data[0]
        huffman_encoded = bool(first_byte & 0x80)

        length, consumed = self._decode_integer(data, 7)
        pos = consumed

        if pos + length > len(data):
            raise CompressionError(f"String length {length} exceeds available data")

        string_data = data[pos : pos + length]

        if huffman_encoded:
            try:
                return self.huffman_decoder.decode(string_data), pos + length
            except ValueError as e:
                raise CompressionError(f"Huffman decoding error: {e}")
        else:
            return string_data, pos + length

    def _get_from_table(self, index: int) -> tuple[bytes, bytes]:
        """Get header from static or dynamic table.

        Args:
            index: 1-based index.

        Returns:
            Tuple of (name, value).

        Raises:
            CompressionError: If index is invalid.
        """
        if index < 1:
            raise CompressionError(f"Invalid table index: {index}")

        if index <= len(STATIC_TABLE):
            return STATIC_TABLE[index - 1]

        dynamic_idx = index - len(STATIC_TABLE) - 1
        if dynamic_idx >= len(self.dynamic_table):
            raise CompressionError(f"Invalid dynamic table index: {index}")

        return self.dynamic_table[dynamic_idx]

    def _add_to_dynamic_table(self, name: bytes, value: bytes) -> None:
        """Add header to dynamic table.

        Args:
            name: Header name.
            value: Header value.
        """
        entry_size = len(name) + len(value) + 32

        # Evict entries if necessary
        while self.dynamic_table_size + entry_size > self.max_dynamic_table_size:
            if not self.dynamic_table:
                break
            old_name, old_value = self.dynamic_table.pop()
            self.dynamic_table_size -= len(old_name) + len(old_value) + 32

        self.dynamic_table.insert(0, (name, value))
        self.dynamic_table_size += entry_size
