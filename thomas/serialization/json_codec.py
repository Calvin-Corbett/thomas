"""
JSON codec with custom type support.

Implements JSON serialization with custom encoders/decoders for datetime,
UUID, Decimal, bytes, Enum, dataclass, and NamedTuple types. Supports
streaming JSON parsing and JSON Lines format.
"""

import base64
import dataclasses
import json
import uuid
from collections.abc import Iterator
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from typing import Any

from .codec import Codec
from .exceptions import DeserializationError, SerializationError
from .types import CodecConfig, SerializationFormat


class JSONEncoder(json.JSONEncoder):
    """Custom JSON encoder for special types."""

    def __init__(self, *args: Any, allow_nan: bool = False, **kwargs: Any) -> None:
        super().__init__(*args, allow_nan=allow_nan, **kwargs)
        self.allow_nan = allow_nan

    def default(self, obj: Any) -> Any:
        """Encode special types to JSON-serializable forms."""
        if isinstance(obj, datetime):
            return {"__datetime__": obj.isoformat()}
        elif isinstance(obj, date):
            return {"__date__": obj.isoformat()}
        elif isinstance(obj, time):
            return {"__time__": obj.isoformat()}
        elif isinstance(obj, Decimal):
            if obj.is_nan():
                if not self.allow_nan:
                    raise ValueError("NaN not allowed")
                return None
            elif obj.is_infinite():
                if not self.allow_nan:
                    raise ValueError("Infinity not allowed")
                return None
            return {"__decimal__": str(obj)}
        elif isinstance(obj, uuid.UUID):
            return {"__uuid__": str(obj)}
        elif isinstance(obj, bytes):
            return {"__bytes__": base64.b64encode(obj).decode("ascii")}
        elif isinstance(obj, Enum):
            return {"__enum__": {"type": obj.__class__.__name__, "value": obj.value}}
        elif dataclasses.is_dataclass(obj):
            return {
                "__dataclass__": {
                    "type": obj.__class__.__name__,
                    "data": dataclasses.asdict(obj),
                }
            }
        elif isinstance(obj, tuple) and hasattr(obj, "_fields"):
            # NamedTuple
            return {
                "__namedtuple__": {
                    "type": obj.__class__.__name__,
                    "data": obj._asdict(),
                }
            }
        return super().default(obj)


class JSONDecoder(json.JSONDecoder):
    """Custom JSON decoder for special types."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(object_hook=self._object_hook, *args, **kwargs)

    @staticmethod
    def _object_hook(obj: dict[str, Any]) -> Any:
        """Decode special type markers."""
        if len(obj) == 1:
            if "__datetime__" in obj:
                return datetime.fromisoformat(obj["__datetime__"])
            elif "__date__" in obj:
                return date.fromisoformat(obj["__date__"])
            elif "__time__" in obj:
                return time.fromisoformat(obj["__time__"])
            elif "__decimal__" in obj:
                return Decimal(obj["__decimal__"])
            elif "__uuid__" in obj:
                return uuid.UUID(obj["__uuid__"])
            elif "__bytes__" in obj:
                return base64.b64decode(obj["__bytes__"])
            elif "__enum__" in obj:
                data = obj["__enum__"]
                return {"_enum_type": data["type"], "_enum_value": data["value"]}
            elif "__dataclass__" in obj:
                data = obj["__dataclass__"]
                return {"_dataclass_type": data["type"], "_dataclass_data": data["data"]}
            elif "__namedtuple__" in obj:
                data = obj["__namedtuple__"]
                return {
                    "_namedtuple_type": data["type"],
                    "_namedtuple_data": data["data"],
                }
        return obj


class JSONCodec(Codec):
    """JSON serialization codec."""

    @property
    def format(self) -> SerializationFormat:
        """Return JSON format identifier."""
        return SerializationFormat.JSON

    def encode(self, obj: Any, config: CodecConfig | None = None) -> bytes:
        """Encode object to JSON bytes.

        Args:
            obj: Object to serialize.
            config: Optional codec configuration.

        Returns:
            JSON bytes.

        Raises:
            SerializationError: If encoding fails.
        """
        if config is None:
            config = CodecConfig(format=self.format)

        try:
            indent = 2 if config.pretty_print else None
            json_str = json.dumps(
                obj,
                cls=JSONEncoder,
                indent=indent,
                allow_nan=config.allow_nan,
            )
            return json_str.encode("utf-8")
        except (TypeError, ValueError) as e:
            raise SerializationError(f"Failed to encode to JSON: {e}") from e

    def decode(self, data: bytes, config: CodecConfig | None = None) -> Any:
        """Decode JSON bytes to object.

        Args:
            data: JSON bytes.
            config: Optional codec configuration.

        Returns:
            Deserialized object.

        Raises:
            DeserializationError: If decoding fails.
        """
        if config is None:
            config = CodecConfig(format=self.format)

        try:
            json_str = data.decode("utf-8")
            return json.loads(json_str, cls=JSONDecoder)
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise DeserializationError(f"Failed to decode JSON: {e}", data=data) from e

    def stream_encode(self, objects: Iterator[Any], config: CodecConfig | None = None) -> Iterator[bytes]:
        """Encode stream of objects as JSON Lines.

        Each object is encoded as a complete JSON object on a single line.

        Args:
            objects: Iterator of objects to serialize.
            config: Optional codec configuration.

        Yields:
            JSON line bytes (one per object).

        Raises:
            SerializationError: If encoding fails.
        """
        if config is None:
            config = CodecConfig(format=self.format)

        for obj in objects:
            try:
                json_str = json.dumps(obj, cls=JSONEncoder, allow_nan=config.allow_nan)
                yield (json_str + "\n").encode("utf-8")
            except (TypeError, ValueError) as e:
                raise SerializationError(f"Failed to encode to JSON: {e}") from e

    def stream_decode(self, data: bytes, config: CodecConfig | None = None) -> Iterator[Any]:
        """Decode JSON Lines (newline-delimited JSON).

        Args:
            data: JSON Lines bytes.
            config: Optional codec configuration.

        Yields:
            Deserialized objects.

        Raises:
            DeserializationError: If decoding fails.
        """
        if config is None:
            config = CodecConfig(format=self.format)

        try:
            lines = data.decode("utf-8").strip().split("\n")
            for line_num, line in enumerate(lines, 1):
                if line:
                    yield json.loads(line, cls=JSONDecoder)
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise DeserializationError(
                f"Failed to decode JSON Lines at line {line_num}: {e}",
                data=data,
                position=line_num,
            ) from e

    def encode_streaming_parser(self, data: bytes, config: CodecConfig | None = None) -> Iterator[Any]:
        """Parse JSON array/objects from bytes stream.

        Handles partial JSON and incomplete payloads.

        Args:
            data: JSON bytes containing array or objects.
            config: Optional codec configuration.

        Yields:
            Parsed objects from array.

        Raises:
            DeserializationError: If JSON is invalid.
        """
        if config is None:
            config = CodecConfig(format=self.format)

        json_str = data.decode("utf-8")
        decoder = JSONDecoder()

        # Try to parse as array first
        try:
            obj = decoder.decode(json_str)
            if isinstance(obj, list):
                for item in obj:
                    yield item
                return
            else:
                yield obj
                return
        except json.JSONDecodeError:
            pass

        # Try parsing as newline-delimited JSON
        try:
            for line in json_str.strip().split("\n"):
                if line.strip():
                    yield decoder.decode(line)
        except json.JSONDecodeError as e:
            raise DeserializationError(f"Failed to parse JSON stream: {e}", data=data) from e
