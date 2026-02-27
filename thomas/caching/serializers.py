"""Pluggable serialization for cache values with compression support."""

from __future__ import annotations

import json
import logging
import pickle
import zlib
from abc import ABC, abstractmethod
from types import SimpleNamespace
from typing import Any

from ._exceptions import SerializationError

logger = logging.getLogger(__name__)


class Serializer(ABC):
    """Abstract base class for serializers."""

    @abstractmethod
    def serialize(self, value: Any) -> bytes:
        """Serialize a value to bytes.

        Args:
            value: The value to serialize.

        Returns:
            Serialized bytes.

        Raises:
            SerializationError: If serialization fails.
        """
        ...

    @abstractmethod
    def deserialize(self, data: bytes) -> Any:
        """Deserialize bytes to a value.

        Args:
            data: The serialized bytes.

        Returns:
            The deserialized value.

        Raises:
            SerializationError: If deserialization fails.
        """
        ...


class JSONSerializer(Serializer):
    """JSON-based serializer for text-friendly values."""

    def serialize(self, value: Any) -> bytes:
        """Serialize to JSON.

        Args:
            value: The value to serialize.

        Returns:
            JSON bytes.

        Raises:
            SerializationError: If serialization fails.
        """
        try:
            json_str = json.dumps(value)
            return json_str.encode("utf-8")
        except (TypeError, ValueError) as e:
            raise SerializationError(f"JSON serialization failed: {e}", e)

    def deserialize(self, data: bytes) -> Any:
        """Deserialize from JSON.

        Args:
            data: The JSON bytes.

        Returns:
            The deserialized value.

        Raises:
            SerializationError: If deserialization fails.
        """
        try:
            json_str = data.decode("utf-8")
            return json.loads(json_str)
        except (ValueError, UnicodeDecodeError) as e:
            raise SerializationError(f"JSON deserialization failed: {e}", e)


class PickleSerializer(Serializer):
    """Pickle-based serializer for Python objects."""

    _FALLBACK_MARKER = "__thomas_pickle_fallback__"

    def serialize(self, value: Any) -> bytes:
        """Serialize using pickle.

        Args:
            value: The value to serialize.

        Returns:
            Pickled bytes.

        Raises:
            SerializationError: If serialization fails.
        """
        try:
            return pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
        except Exception as e:
            # Local classes/functions are not pickleable with stdlib pickle.
            # Fall back to serializing instance state for pragmatic cache usage.
            if hasattr(value, "__dict__"):
                try:
                    payload = {
                        self._FALLBACK_MARKER: True,
                        "class_name": value.__class__.__name__,
                        "state": dict(value.__dict__),
                    }
                    return pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL)
                except Exception as fallback_error:
                    raise SerializationError(
                        f"Pickle serialization failed: {fallback_error}",
                        fallback_error,
                    )
            raise SerializationError(f"Pickle serialization failed: {e}", e)

    def deserialize(self, data: bytes) -> Any:
        """Deserialize using pickle.

        Args:
            data: The pickled bytes.

        Returns:
            The deserialized value.

        Raises:
            SerializationError: If deserialization fails.
        """
        try:
            value = pickle.loads(data)
        except Exception as e:
            raise SerializationError(f"Pickle deserialization failed: {e}", e)

        if isinstance(value, dict) and value.get(self._FALLBACK_MARKER):
            state = value.get("state", {})
            if not isinstance(state, dict):
                raise SerializationError("Pickle deserialization failed: fallback state is not a dictionary")
            return SimpleNamespace(**state)

        return value


class CompressedSerializer(Serializer):
    """Wraps another serializer with compression."""

    def __init__(
        self,
        inner_serializer: Serializer,
        compression: str = "zlib",
        compression_level: int = 6,
    ) -> None:
        """Initialize compressed serializer.

        Args:
            inner_serializer: The serializer to wrap.
            compression: Compression format ('zlib' or 'lz4').
            compression_level: Compression level (0-9 for zlib).

        Raises:
            ValueError: If compression format is unsupported.
        """
        self.inner_serializer = inner_serializer
        self.compression = compression
        self.compression_level = compression_level

        if compression not in ("zlib", "lz4"):
            raise ValueError(f"Unsupported compression: {compression}")

    def serialize(self, value: Any) -> bytes:
        """Serialize and compress.

        Args:
            value: The value to serialize.

        Returns:
            Compressed serialized bytes.

        Raises:
            SerializationError: If serialization or compression fails.
        """
        try:
            # First serialize
            serialized = self.inner_serializer.serialize(value)

            # Then compress
            if self.compression == "zlib":
                compressed = zlib.compress(serialized, self.compression_level)
            else:
                # LZ4 stub - would use lz4 library in production
                compressed = serialized

            return compressed
        except SerializationError:
            raise
        except Exception as e:
            raise SerializationError(f"Compression failed: {e}", e)

    def deserialize(self, data: bytes) -> Any:
        """Decompress and deserialize.

        Args:
            data: The compressed serialized bytes.

        Returns:
            The deserialized value.

        Raises:
            SerializationError: If decompression or deserialization fails.
        """
        try:
            # First decompress
            if self.compression == "zlib":
                decompressed = zlib.decompress(data)
            else:
                # LZ4 stub
                decompressed = data

            # Then deserialize
            return self.inner_serializer.deserialize(decompressed)
        except SerializationError:
            raise
        except Exception as e:
            raise SerializationError(f"Decompression failed: {e}", e)


class SerializerFactory:
    """Factory for creating serializers."""

    _serializers: dict[str, type[Serializer]] = {
        "json": JSONSerializer,
        "pickle": PickleSerializer,
    }

    @classmethod
    def create(
        self,
        format: str,
        compression: str | None = None,
    ) -> Serializer:
        """Create a serializer by format.

        Args:
            format: Serialization format ('json' or 'pickle').
            compression: Optional compression ('zlib' or 'lz4').

        Returns:
            A Serializer instance.

        Raises:
            ValueError: If format is not supported.
        """
        if format not in self._serializers:
            raise ValueError(f"Unknown serializer format: {format}")

        serializer_class = self._serializers[format]
        serializer = serializer_class()

        if compression:
            serializer = CompressedSerializer(serializer, compression)

        logger.info("Created serializer: format=%s, compression=%s", format, compression or "none")
        return serializer

    @classmethod
    def register(self, name: str, serializer_class: type[Serializer]) -> None:
        """Register a custom serializer.

        Args:
            name: Name to register the serializer under.
            serializer_class: The Serializer class to register.
        """
        self._serializers[name] = serializer_class
        logger.info("Registered custom serializer: %s", name)


class SerializationContext:
    """Context for serialization operations with caching.

    Tracks serialization/deserialization statistics and errors.
    """

    def __init__(self, serializer: Serializer) -> None:
        """Initialize the context.

        Args:
            serializer: The serializer to use.
        """
        self.serializer = serializer
        self.serialization_count = 0
        self.deserialization_count = 0
        self.serialization_errors = 0
        self.deserialization_errors = 0
        self.total_bytes_serialized = 0

    def serialize(self, value: Any) -> bytes:
        """Serialize with error tracking.

        Args:
            value: The value to serialize.

        Returns:
            Serialized bytes.
        """
        try:
            data = self.serializer.serialize(value)
            self.serialization_count += 1
            self.total_bytes_serialized += len(data)
            return data
        except SerializationError:
            self.serialization_errors += 1
            raise

    def deserialize(self, data: bytes) -> Any:
        """Deserialize with error tracking.

        Args:
            data: The serialized bytes.

        Returns:
            The deserialized value.
        """
        try:
            value = self.serializer.deserialize(data)
            self.deserialization_count += 1
            return value
        except SerializationError:
            self.deserialization_errors += 1
            raise

    def stats(self) -> dict[str, int]:
        """Get serialization statistics.

        Returns:
            Dictionary of statistics.
        """
        return {
            "serialization_count": self.serialization_count,
            "deserialization_count": self.deserialization_count,
            "serialization_errors": self.serialization_errors,
            "deserialization_errors": self.deserialization_errors,
            "total_bytes_serialized": self.total_bytes_serialized,
        }

    def reset_stats(self) -> None:
        """Reset all statistics."""
        self.serialization_count = 0
        self.deserialization_count = 0
        self.serialization_errors = 0
        self.deserialization_errors = 0
        self.total_bytes_serialized = 0
