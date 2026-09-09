"""Payload transformation for webhook delivery."""

import json
import re
from typing import Any


class FieldMapping:
    """Maps and transforms fields in payloads."""

    def __init__(self, mapping: dict[str, str] | None = None) -> None:
        """Initialize field mapper.

        Args:
            mapping: Dictionary of source -> target field names.
        """
        self.mapping = mapping or {}

    def apply(self, data: dict) -> dict:
        """Apply field mapping to data.

        Args:
            data: The data to transform.

        Returns:
            Transformed data with mapped fields.
        """
        result = {}

        for source, target in self.mapping.items():
            if source in data:
                result[target] = data[source]

        return result

    def add_mapping(self, source: str, target: str) -> None:
        """Add a field mapping.

        Args:
            source: Source field name.
            target: Target field name.
        """
        self.mapping[source] = target

    def remove_mapping(self, source: str) -> None:
        """Remove a field mapping.

        Args:
            source: Source field name to remove.
        """
        self.mapping.pop(source, None)


class JSONPathExtractor:
    """Extracts values from data using JSONPath-like expressions."""

    @staticmethod
    def extract(data: dict, path: str) -> Any:
        """Extract value from data using JSONPath.

        Examples:
            - $.user.name -> data['user']['name']
            - $.items[0].id -> data['items'][0]['id']

        Args:
            data: The data dictionary.
            path: JSONPath expression.

        Returns:
            The extracted value, or None if path doesn't exist.
        """
        if not path.startswith("$."):
            return None

        parts = path[2:].split(".")
        current = data

        for part in parts:
            if "[" in part and "]" in part:
                field, rest = part.split("[", 1)
                index = int(rest.rstrip("]"))

                if field:
                    current = current.get(field) if isinstance(current, dict) else None
                    if current is None:
                        return None

                if isinstance(current, (list, tuple)):
                    current = current[index] if index < len(current) else None
                else:
                    return None
            else:
                if isinstance(current, dict):
                    current = current.get(part)
                else:
                    return None

                if current is None:
                    return None

        return current

    @staticmethod
    def extract_all(data: dict, paths: list[str]) -> dict:
        """Extract multiple values from data.

        Args:
            data: The data dictionary.
            paths: List of JSONPath expressions.

        Returns:
            Dictionary of path -> value.
        """
        result = {}

        for path in paths:
            value = JSONPathExtractor.extract(data, path)
            if value is not None:
                result[path] = value

        return result


class TemplateTransformer:
    """Transforms payloads using Mustache-like templates.

    Supports {{field}} substitution with dot notation.
    """

    TEMPLATE_PATTERN = re.compile(r"\{\{(\w+(?:\.\w+)*)\}\}")

    def __init__(self, template: str = "") -> None:
        """Initialize template transformer.

        Args:
            template: The template string with {{field}} placeholders.
        """
        self.template = template

    def transform(self, data: dict) -> str:
        """Transform data using template.

        Args:
            data: The data to substitute into template.

        Returns:
            Rendered string.
        """

        def replace_field(match):
            field_path = match.group(1)
            value = self._get_nested_value(data, field_path)
            return str(value) if value is not None else ""

        return self.TEMPLATE_PATTERN.sub(replace_field, self.template)

    def transform_to_dict(self, data: dict) -> dict:
        """Transform template into a dictionary.

        Args:
            data: The data to substitute.

        Returns:
            Dictionary where values are rendered template strings.
        """
        return {
            "result": self.transform(data),
            "original_template": self.template,
        }

    @staticmethod
    def _get_nested_value(data: dict, path: str) -> Any:
        """Get nested value from data using dot notation.

        Args:
            data: The data dictionary.
            path: Dot-separated path (e.g., "user.name").

        Returns:
            The value, or None if not found.
        """
        parts = path.split(".")
        current = data

        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            else:
                return None

            if current is None:
                return None

        return current


class PayloadEnricher:
    """Enriches payloads with computed fields."""

    def __init__(self) -> None:
        """Initialize the payload enricher."""
        self._enrichers: dict[str, callable] = {}

    def add_enricher(self, field_name: str, func: callable) -> None:
        """Add an enricher function for a field.

        Args:
            field_name: Name of the field to add/compute.
            func: Callable that takes the payload and returns a value.
        """
        self._enrichers[field_name] = func

    def enrich(self, payload: dict) -> dict:
        """Enrich payload with computed fields.

        Args:
            payload: The payload to enrich.

        Returns:
            Enriched payload.
        """
        enriched = dict(payload)

        for field_name, func in self._enrichers.items():
            try:
                enriched[field_name] = func(payload)
            except (ValueError, TypeError):
                enriched[field_name] = None

        return enriched


class FormatConverter:
    """Converts payloads between different formats."""

    @staticmethod
    def json_to_xml(data: dict) -> str:
        """Convert JSON to XML.

        Args:
            data: Dictionary to convert.

        Returns:
            XML string representation.
        """
        lines = ['<?xml version="1.0" encoding="UTF-8"?>']
        lines.append("<root>")

        def dict_to_xml(d, indent=1):
            for key, value in d.items():
                if isinstance(value, dict):
                    lines.append("  " * indent + f"<{key}>")
                    dict_to_xml(value, indent + 1)
                    lines.append("  " * indent + f"</{key}>")
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, dict):
                            lines.append("  " * indent + f"<{key}>")
                            dict_to_xml(item, indent + 1)
                            lines.append("  " * indent + f"</{key}>")
                        else:
                            lines.append("  " * indent + f"<{key}>{str(item)}</{key}>")
                else:
                    lines.append("  " * indent + f"<{key}>{str(value)}</{key}>")

        dict_to_xml(data)
        lines.append("</root>")

        return "\n".join(lines)

    @staticmethod
    def json_to_form_encoded(data: dict) -> str:
        """Convert JSON to form-encoded format.

        Args:
            data: Dictionary to convert.

        Returns:
            Form-encoded string.
        """
        from urllib.parse import urlencode

        return urlencode(FormatConverter._flatten_dict(data))

    @staticmethod
    def _flatten_dict(data: dict, parent_key: str = "") -> dict:
        """Flatten nested dictionary for form encoding.

        Args:
            data: Dictionary to flatten.
            parent_key: Parent key prefix.

        Returns:
            Flattened dictionary.
        """
        items = []

        for k, v in data.items():
            new_key = f"{parent_key}[{k}]" if parent_key else k

            if isinstance(v, dict):
                items.extend(FormatConverter._flatten_dict(v, new_key).items())
            elif isinstance(v, list):
                for i, item in enumerate(v):
                    items.append((f"{new_key}[{i}]", item))
            else:
                items.append((new_key, v))

        return dict(items)


class SchemaValidator:
    """Validates payloads against JSON Schema."""

    def __init__(self, schema: dict | None = None) -> None:
        """Initialize validator.

        Args:
            schema: JSON Schema to validate against.
        """
        self.schema = schema or {}

    def validate(self, payload: dict) -> tuple:
        """Validate payload against schema.

        Args:
            payload: The payload to validate.

        Returns:
            Tuple of (is_valid, errors).
        """
        if not self.schema:
            return True, []

        errors = self._validate_against_schema(payload, self.schema)
        return len(errors) == 0, errors

    def _validate_against_schema(self, data: Any, schema: dict, path: str = "") -> list[str]:
        """Recursively validate data against schema.

        Args:
            data: The data to validate.
            schema: The schema to validate against.
            path: Current path in data.

        Returns:
            List of validation errors.
        """
        errors = []

        if "type" in schema:
            expected_type = schema["type"]
            if expected_type == "object" and not isinstance(data, dict):
                errors.append(f"{path}: Expected object, got {type(data).__name__}")
            elif expected_type == "array" and not isinstance(data, list):
                errors.append(f"{path}: Expected array, got {type(data).__name__}")
            elif expected_type == "string" and not isinstance(data, str):
                errors.append(f"{path}: Expected string, got {type(data).__name__}")
            elif expected_type == "number" and not isinstance(data, (int, float)):
                errors.append(f"{path}: Expected number, got {type(data).__name__}")

        if "properties" in schema and isinstance(data, dict):
            for key, prop_schema in schema["properties"].items():
                new_path = f"{path}.{key}" if path else key
                if key in data:
                    errors.extend(self._validate_against_schema(data[key], prop_schema, new_path))

        if "required" in schema and isinstance(data, dict):
            for required_key in schema["required"]:
                if required_key not in data:
                    new_path = f"{path}.{required_key}" if path else required_key
                    errors.append(f"{new_path}: Required field missing")

        return errors


class PayloadTruncator:
    """Truncates payloads to specified size."""

    @staticmethod
    def truncate(payload: dict, max_size_bytes: int = 1024 * 1024) -> dict:
        """Truncate payload to max size.

        Args:
            payload: The payload to truncate.
            max_size_bytes: Maximum size in bytes.

        Returns:
            Truncated payload.
        """
        json_str = json.dumps(payload)

        if len(json_str.encode("utf-8")) <= max_size_bytes:
            return payload

        keys = list(payload.keys())
        for key in keys:
            del payload[key]
            json_str = json.dumps(payload)
            if len(json_str.encode("utf-8")) <= max_size_bytes:
                break

        return payload

    @staticmethod
    def compress(payload: dict) -> bytes:
        """Compress payload.

        Args:
            payload: The payload to compress.

        Returns:
            Compressed bytes.
        """
        import gzip

        json_str = json.dumps(payload)
        return gzip.compress(json_str.encode("utf-8"))
