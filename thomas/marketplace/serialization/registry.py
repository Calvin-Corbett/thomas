"""
Global codec registry with format negotiation and codec benchmarking.

Provides auto-discovery, format negotiation between peers, content-type mapping,
and benchmark utilities for selecting optimal codecs.
"""

from .cbor_codec import CBORCodec
from .codec import codec_registry
from .json_codec import JSONCodec
from .msgpack_codec import MessagePackCodec
from .protobuf_codec import ProtobufCodec
from .types import SerializationFormat

# Content-type to format mapping
_CONTENT_TYPE_MAP: dict[str, SerializationFormat] = {
    "application/json": SerializationFormat.JSON,
    "application/x-msgpack": SerializationFormat.MSGPACK,
    "application/octet-stream": SerializationFormat.PROTOBUF,
    "application/cbor": SerializationFormat.CBOR,
}

# Format to content-type mapping
_FORMAT_CONTENT_TYPE_MAP: dict[SerializationFormat, str] = {
    SerializationFormat.JSON: "application/json",
    SerializationFormat.MSGPACK: "application/x-msgpack",
    SerializationFormat.PROTOBUF: "application/octet-stream",
    SerializationFormat.CBOR: "application/cbor",
}


def _register_default_codecs() -> None:
    """Register all default codecs."""
    codec_registry.register(JSONCodec())
    codec_registry.register(MessagePackCodec())
    codec_registry.register(ProtobufCodec())
    codec_registry.register(CBORCodec())


# Initialize default codecs on module load
_register_default_codecs()


def register_codec(codec: object) -> None:
    """Register a custom codec.

    Args:
        codec: Codec instance implementing Codec protocol.

    Raises:
        ValueError: If codec doesn't implement protocol.
    """
    codec_registry.register(codec)


def get_content_type(format: SerializationFormat) -> str:
    """Get MIME content type for format.

    Args:
        format: Serialization format.

    Returns:
        MIME content type string.
    """
    return _FORMAT_CONTENT_TYPE_MAP.get(
        format,
        "application/octet-stream",
    )


def get_format_from_content_type(content_type: str) -> SerializationFormat | None:
    """Get format from MIME content type.

    Args:
        content_type: MIME type string (may include parameters).

    Returns:
        SerializationFormat or None if unknown.
    """
    # Strip parameters (e.g., "application/json; charset=utf-8")
    base_type = content_type.split(";")[0].strip()
    return _CONTENT_TYPE_MAP.get(base_type)


def format_negotiate(
    client_formats: list[SerializationFormat],
    server_formats: list[SerializationFormat],
) -> SerializationFormat | None:
    """Negotiate format between client and server.

    Selects the first format in client list that server also supports.

    Args:
        client_formats: Formats client can handle (in preference order).
        server_formats: Formats server can handle.

    Returns:
        Negotiated format or None if no match.
    """
    set(client_formats)
    server_set = set(server_formats)

    # Find first match in client preference order
    for format in client_formats:
        if format in server_set:
            return format

    return None


def benchmark_codecs(
    obj: object,
    formats: list[SerializationFormat] | None = None,
) -> dict[SerializationFormat, dict[str, object]]:
    """Benchmark codecs for encoding/decoding an object.

    Args:
        obj: Object to benchmark.
        formats: Formats to benchmark (defaults to all registered).

    Returns:
        Results keyed by format with metrics:
        {
            'encode_time': float (seconds),
            'decode_time': float (seconds),
            'size': int (bytes),
            'throughput': float (MB/s),
            'error': str (if benchmark failed)
        }
    """
    return codec_registry.benchmark(obj, formats)


def get_recommended_format(
    obj: object,
    criteria: str = "size",
    formats: list[SerializationFormat] | None = None,
) -> SerializationFormat:
    """Get recommended format based on optimization criteria.

    Args:
        obj: Object to serialize.
        criteria: Optimization target: "size", "speed", or "balanced".
        formats: Formats to consider (defaults to all registered).

    Returns:
        Recommended SerializationFormat.

    Raises:
        ValueError: If no formats are available.
    """
    results = benchmark_codecs(obj, formats)

    if not results:
        raise ValueError("No formats available for benchmarking")

    # Filter out failed benchmarks
    valid_results = {fmt: metrics for fmt, metrics in results.items() if "error" not in metrics}

    if not valid_results:
        raise ValueError("All benchmark attempts failed")

    if criteria == "size":
        # Choose format with smallest payload
        return min(valid_results.keys(), key=lambda fmt: valid_results[fmt]["size"])

    elif criteria == "speed":
        # Choose format with best throughput
        return max(
            valid_results.keys(),
            key=lambda fmt: valid_results[fmt]["throughput"],
        )

    elif criteria == "balanced":
        # Choose format with best throughput/size ratio
        def balanced_score(fmt: SerializationFormat) -> float:
            metrics = valid_results[fmt]
            # Normalize throughput (higher is better) and size (lower is better)
            max_throughput = max(m["throughput"] for m in valid_results.values())
            max_size = max(m["size"] for m in valid_results.values())

            throughput_normalized = metrics["throughput"] / max_throughput if max_throughput > 0 else 0
            size_normalized = 1 - (metrics["size"] / max_size) if max_size > 0 else 1

            # Equal weight to both factors
            return (throughput_normalized + size_normalized) / 2

        return max(valid_results.keys(), key=balanced_score)

    else:
        raise ValueError(f"Unknown criteria: {criteria}")


def list_registered_formats() -> list[SerializationFormat]:
    """Get list of registered formats.

    Returns:
        List of available SerializationFormat values.
    """
    return codec_registry.list_formats()


def get_codec_by_format(format: SerializationFormat) -> object:
    """Get codec instance for format.

    Args:
        format: Serialization format.

    Returns:
        Codec instance.

    Raises:
        CodecNotFoundError: If format is not registered.
    """
    return codec_registry.get(format)


class FormatNegotiationHelper:
    """Helper for format negotiation in RPC scenarios."""

    def __init__(
        self,
        supported_formats: list[SerializationFormat] | None = None,
    ) -> None:
        """Initialize negotiation helper.

        Args:
            supported_formats: Formats supported by this side (defaults to all).
        """
        self.supported_formats = supported_formats or codec_registry.list_formats()

    def negotiate(
        self,
        peer_formats: list[SerializationFormat],
    ) -> SerializationFormat | None:
        """Negotiate format with peer.

        Args:
            peer_formats: Formats peer supports (in preference order).

        Returns:
            Negotiated format or None if no match.
        """
        return format_negotiate(peer_formats, self.supported_formats)

    def get_fallback_chain(self) -> list[SerializationFormat]:
        """Get fallback chain for codec robustness.

        Primary format is JSON (most compatible), followed by others by size.

        Returns:
            Ordered list of formats for fallback attempts.
        """
        # Start with JSON for maximum compatibility
        chain = [SerializationFormat.JSON]

        # Add others sorted by efficiency
        others = [fmt for fmt in self.supported_formats if fmt != SerializationFormat.JSON]
        # Binary formats first (more efficient)
        binary_formats = [fmt for fmt in others if fmt != SerializationFormat.JSON]
        chain.extend(sorted(binary_formats))

        return chain
