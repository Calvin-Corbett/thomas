"""
Abstract codec protocol and registry for serialization formats.

Defines the Codec protocol that all format-specific codecs must implement,
manages global codec registration, and provides codec negotiation and
fallback chain capabilities.
"""

import time
from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

from .exceptions import CodecNotFoundError
from .types import CodecConfig, SerializationFormat


@runtime_checkable
class Codec(Protocol):
    """Protocol for serialization codecs.

    All codecs must implement these methods to handle encoding and decoding
    of Python objects to/from bytes.
    """

    def encode(self, obj: Any, config: CodecConfig | None = None) -> bytes:
        """Encode a Python object to bytes.

        Args:
            obj: Object to serialize.
            config: Optional codec configuration.

        Returns:
            Serialized bytes.

        Raises:
            SerializationError: If encoding fails.
        """
        ...

    def decode(self, data: bytes, config: CodecConfig | None = None) -> Any:
        """Decode bytes to a Python object.

        Args:
            data: Serialized bytes.
            config: Optional codec configuration.

        Returns:
            Deserialized object.

        Raises:
            DeserializationError: If decoding fails.
        """
        ...

    @property
    def format(self) -> SerializationFormat:
        """Return the serialization format this codec handles."""
        ...


class CodecRegistry:
    """Registry for serialization codecs.

    Manages codec registration, lookup, and fallback chains. Provides
    codec negotiation between different formats.
    """

    def __init__(self) -> None:
        """Initialize codec registry."""
        self._codecs: dict[SerializationFormat, Codec] = {}
        self._fallback_chains: dict[SerializationFormat, list[SerializationFormat]] = {}
        self._encode_hooks: list[Callable[[Any, CodecConfig], Any]] = []
        self._decode_hooks: list[Callable[[Any, CodecConfig], Any]] = []

    def register(self, codec: Codec, fallback_chain: list[SerializationFormat] | None = None) -> None:
        """Register a codec for a format.

        Args:
            codec: Codec instance implementing the Codec protocol.
            fallback_chain: List of formats to try if codec fails (in order).

        Raises:
            ValueError: If codec doesn't implement required protocol.
        """
        if not isinstance(codec, Codec):
            raise ValueError("Codec must implement Codec protocol")

        self._codecs[codec.format] = codec
        if fallback_chain:
            self._fallback_chains[codec.format] = fallback_chain

    def get(self, format: SerializationFormat) -> Codec:
        """Get codec for a format.

        Args:
            format: Serialization format.

        Returns:
            Codec instance.

        Raises:
            CodecNotFoundError: If no codec is registered for format.
        """
        if format not in self._codecs:
            raise CodecNotFoundError(format.value)
        return self._codecs[format]

    def encode(self, obj: Any, config: CodecConfig) -> bytes:
        """Encode object using appropriate codec.

        Tries fallback chain if primary codec fails.

        Args:
            obj: Object to encode.
            config: Codec configuration with format.

        Returns:
            Serialized bytes.

        Raises:
            CodecNotFoundError: If no suitable codec found.
            SerializationError: If all codecs fail.
        """
        # Apply encode hooks
        current_obj = obj
        for hook in self._encode_hooks:
            current_obj = hook(current_obj, config)

        try:
            codec = self.get(config.format)
            return codec.encode(current_obj, config)
        except CodecNotFoundError:
            raise
        except Exception as e:
            # Try fallback chain
            fallback_chain = self._fallback_chains.get(config.format, [])
            for fallback_format in fallback_chain:
                try:
                    fallback_codec = self.get(fallback_format)
                    return fallback_codec.encode(current_obj, config)
                except Exception:
                    continue
            # All codecs failed
            raise CodecNotFoundError(config.format.value) from e

    def decode(self, data: bytes, config: CodecConfig) -> Any:
        """Decode bytes using appropriate codec.

        Tries fallback chain if primary codec fails.

        Args:
            data: Serialized bytes.
            config: Codec configuration with format.

        Returns:
            Deserialized object.

        Raises:
            CodecNotFoundError: If no suitable codec found.
            DeserializationError: If all codecs fail.
        """
        try:
            codec = self.get(config.format)
            result = codec.decode(data, config)
        except CodecNotFoundError:
            raise
        except Exception as e:
            # Try fallback chain
            fallback_chain = self._fallback_chains.get(config.format, [])
            result = None
            for fallback_format in fallback_chain:
                try:
                    fallback_codec = self.get(fallback_format)
                    result = fallback_codec.decode(data, config)
                    break
                except Exception:
                    continue
            if result is None:
                raise CodecNotFoundError(config.format.value) from e

        # Apply decode hooks
        for hook in self._decode_hooks:
            result = hook(result, config)

        return result

    def add_encode_hook(self, hook: Callable[[Any, CodecConfig], Any]) -> None:
        """Add a hook to transform objects before encoding.

        Args:
            hook: Function taking (obj, config) -> transformed_obj.
        """
        self._encode_hooks.append(hook)

    def add_decode_hook(self, hook: Callable[[Any, CodecConfig], Any]) -> None:
        """Add a hook to transform objects after decoding.

        Args:
            hook: Function taking (obj, config) -> transformed_obj.
        """
        self._decode_hooks.append(hook)

    def list_formats(self) -> list[SerializationFormat]:
        """List all registered formats."""
        return list(self._codecs.keys())

    def benchmark(
        self, obj: Any, formats: list[SerializationFormat] | None = None
    ) -> dict[SerializationFormat, dict[str, Any]]:
        """Benchmark encoding/decoding for formats.

        Args:
            obj: Object to benchmark.
            formats: Formats to benchmark (defaults to all registered).

        Returns:
            Dict mapping formats to their benchmark results:
            {
                'encode_time': float (seconds),
                'decode_time': float (seconds),
                'size': int (bytes),
                'throughput': float (MB/s)
            }
        """
        if formats is None:
            formats = self.list_formats()

        results = {}
        for format in formats:
            try:
                codec = self.get(format)
                config = CodecConfig(format=format)

                # Benchmark encoding
                start = time.perf_counter()
                encoded = codec.encode(obj, config)
                encode_time = time.perf_counter() - start

                # Benchmark decoding
                start = time.perf_counter()
                _ = codec.decode(encoded, config)
                decode_time = time.perf_counter() - start

                size = len(encoded)
                throughput = size / (encode_time + decode_time) / 1024 / 1024

                results[format] = {
                    "encode_time": encode_time,
                    "decode_time": decode_time,
                    "size": size,
                    "throughput": throughput,
                }
            except Exception:
                results[format] = {"error": "benchmark failed"}

        return results


# Global codec registry instance
codec_registry = CodecRegistry()
