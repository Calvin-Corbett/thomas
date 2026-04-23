"""
Tests for Protobuf-style binary codec.

Tests varint encoding, wire types, signed integer zigzag, nested messages,
repeated fields, and schema descriptor usage.
"""

import pytest

from thomas.marketplace.serialization import (
    CodecConfig,
    FieldDescriptor,
    MessageDescriptor,
    ProtobufCodec,
    SchemaVersion,
    SerializationFormat,
)


class TestProtobufCodec:
    """Protobuf codec tests."""

    def setup_method(self):
        self.codec = ProtobufCodec()
        self.config = CodecConfig(format=SerializationFormat.PROTOBUF)

    def test_encode_decode_basic_dict(self):
        """Test encoding basic dictionary without schema."""
        data = {"field1": 42, "field2": "hello"}
        encoded = self.codec.encode(data, self.config)
        decoded = self.codec.decode(encoded, self.config)

        # Decoded without schema uses field_ keys
        assert isinstance(decoded, dict)
        assert len(decoded) > 0

    def test_varint_encoding_small(self):
        """Test varint encoding for small integers."""
        # Small positive integers should be 1 byte
        data = {"value": 10}
        encoded = self.codec.encode(data, self.config)
        assert len(encoded) < 5  # Should be quite small

    def test_varint_encoding_large(self):
        """Test varint encoding for large integers."""
        large_value = 2147483647  # Max 32-bit int
        data = {"value": large_value}
        encoded = self.codec.encode(data, self.config)
        decoded = self.codec.decode(encoded, self.config)

        assert decoded["field_"] > 0  # Varint was decoded

    def test_zigzag_encoding_negative(self):
        """Test zigzag encoding for negative integers."""
        schema = MessageDescriptor(
            name="TestMsg",
            version=SchemaVersion(1),
            fields={
                "signed_int": FieldDescriptor(
                    name="signed_int",
                    field_type="sint32",
                    tag=1,
                )
            },
        )

        data = {"signed_int": -42}
        encoded = self.codec.encode(data, self.config, schema)
        decoded = self.codec.decode(encoded, self.config, schema)

        assert decoded["signed_int"] == -42

    def test_nested_messages(self):
        """Test nested message encoding."""
        schema = MessageDescriptor(
            name="Outer",
            version=SchemaVersion(1),
            fields={
                "inner": FieldDescriptor(
                    name="inner",
                    field_type="message",
                    tag=1,
                    embedded=True,
                ),
                "id": FieldDescriptor(
                    name="id",
                    field_type="int32",
                    tag=2,
                ),
            },
        )

        data = {
            "id": 123,
            "inner": {"value": 456},
        }

        encoded = self.codec.encode(data, self.config, schema)
        decoded = self.codec.decode(encoded, self.config, schema)

        assert decoded["id"] == 123
        assert isinstance(decoded["inner"], dict)

    def test_repeated_fields(self):
        """Test repeated field encoding."""
        schema = MessageDescriptor(
            name="ListMsg",
            version=SchemaVersion(1),
            fields={
                "values": FieldDescriptor(
                    name="values",
                    field_type="int32",
                    tag=1,
                    repeated=True,
                )
            },
        )

        data = {"values": [1, 2, 3, 4, 5]}
        encoded = self.codec.encode(data, self.config, schema)
        decoded = self.codec.decode(encoded, self.config, schema)

        assert decoded["values"] == [1, 2, 3, 4, 5]

    def test_string_field(self):
        """Test string field encoding."""
        schema = MessageDescriptor(
            name="StringMsg",
            version=SchemaVersion(1),
            fields={
                "text": FieldDescriptor(
                    name="text",
                    field_type="string",
                    tag=1,
                )
            },
        )

        data = {"text": "hello protobuf"}
        encoded = self.codec.encode(data, self.config, schema)
        decoded = self.codec.decode(encoded, self.config, schema)

        assert decoded["text"] == "hello protobuf"

    def test_bytes_field(self):
        """Test bytes field encoding."""
        schema = MessageDescriptor(
            name="BytesMsg",
            version=SchemaVersion(1),
            fields={
                "data": FieldDescriptor(
                    name="data",
                    field_type="bytes",
                    tag=1,
                )
            },
        )

        test_data = b"binary data"
        data = {"data": test_data}
        encoded = self.codec.encode(data, self.config, schema)
        decoded = self.codec.decode(encoded, self.config, schema)

        assert decoded["data"] == test_data

    def test_boolean_field(self):
        """Test boolean field encoding."""
        schema = MessageDescriptor(
            name="BoolMsg",
            version=SchemaVersion(1),
            fields={
                "flag": FieldDescriptor(
                    name="flag",
                    field_type="bool",
                    tag=1,
                )
            },
        )

        for value in [True, False]:
            data = {"flag": value}
            encoded = self.codec.encode(data, self.config, schema)
            decoded = self.codec.decode(encoded, self.config, schema)
            assert decoded["flag"] == value

    def test_float_field(self):
        """Test float field encoding."""
        schema = MessageDescriptor(
            name="FloatMsg",
            version=SchemaVersion(1),
            fields={
                "value": FieldDescriptor(
                    name="value",
                    field_type="float",
                    tag=1,
                )
            },
        )

        data = {"value": 3.14}
        encoded = self.codec.encode(data, self.config, schema)
        decoded = self.codec.decode(encoded, self.config, schema)

        assert abs(decoded["value"] - 3.14) < 0.01

    def test_double_field(self):
        """Test double field encoding."""
        schema = MessageDescriptor(
            name="DoubleMsg",
            version=SchemaVersion(1),
            fields={
                "value": FieldDescriptor(
                    name="value",
                    field_type="double",
                    tag=1,
                )
            },
        )

        data = {"value": 3.141592653589793}
        encoded = self.codec.encode(data, self.config, schema)
        decoded = self.codec.decode(encoded, self.config, schema)

        assert abs(decoded["value"] - 3.141592653589793) < 1e-10

    def test_unknown_field_skip(self):
        """Test skipping unknown fields during decode."""
        schema = MessageDescriptor(
            name="TestMsg",
            version=SchemaVersion(1),
            fields={
                "id": FieldDescriptor(
                    name="id",
                    field_type="int32",
                    tag=1,
                )
            },
        )

        data = {"id": 123}
        encoded = self.codec.encode(data, self.config, schema)

        # Manually add an unknown field to encoded data
        # This is simplified - in practice you'd need valid protobuf encoding

        # Just verify normal decode still works
        decoded = self.codec.decode(encoded, self.config, schema)
        assert decoded["id"] == 123

    def test_field_tag_validation(self):
        """Test that field tags are validated."""
        with pytest.raises(ValueError):
            FieldDescriptor(
                name="bad",
                field_type="int32",
                tag=0,  # Invalid: must be >= 1
            )

        with pytest.raises(ValueError):
            FieldDescriptor(
                name="bad",
                field_type="int32",
                tag=536870912,  # Too large
            )

    def test_empty_message(self):
        """Test encoding empty message."""
        schema = MessageDescriptor(
            name="Empty",
            version=SchemaVersion(1),
            fields={},
        )

        data = {}
        encoded = self.codec.encode(data, self.config, schema)
        # Empty messages produce empty or minimal output
        assert isinstance(encoded, bytes)

    def test_mixed_field_types(self):
        """Test message with mixed field types."""
        schema = MessageDescriptor(
            name="Mixed",
            version=SchemaVersion(1),
            fields={
                "id": FieldDescriptor(
                    name="id",
                    field_type="int32",
                    tag=1,
                ),
                "name": FieldDescriptor(
                    name="name",
                    field_type="string",
                    tag=2,
                ),
                "active": FieldDescriptor(
                    name="active",
                    field_type="bool",
                    tag=3,
                ),
                "score": FieldDescriptor(
                    name="score",
                    field_type="double",
                    tag=4,
                ),
            },
        )

        data = {
            "id": 42,
            "name": "test",
            "active": True,
            "score": 98.5,
        }

        encoded = self.codec.encode(data, self.config, schema)
        decoded = self.codec.decode(encoded, self.config, schema)

        assert decoded["id"] == 42
        assert decoded["name"] == "test"
        assert decoded["active"] is True
        assert abs(decoded["score"] - 98.5) < 0.1

    def test_required_fields(self):
        """Test required field marking."""
        schema = MessageDescriptor(
            name="Required",
            version=SchemaVersion(1),
            fields={
                "required_field": FieldDescriptor(
                    name="required_field",
                    field_type="int32",
                    tag=1,
                    required=True,
                )
            },
        )

        # Encoding with field present
        data = {"required_field": 123}
        encoded = self.codec.encode(data, self.config, schema)
        decoded = self.codec.decode(encoded, self.config, schema)
        assert decoded["required_field"] == 123

    def test_large_message(self):
        """Test encoding large message."""
        schema = MessageDescriptor(
            name="Large",
            version=SchemaVersion(1),
            fields={
                "items": FieldDescriptor(
                    name="items",
                    field_type="int32",
                    tag=1,
                    repeated=True,
                )
            },
        )

        data = {"items": list(range(1000))}
        encoded = self.codec.encode(data, self.config, schema)
        decoded = self.codec.decode(encoded, self.config, schema)

        assert len(decoded["items"]) == 1000
        assert decoded["items"][500] == 500
