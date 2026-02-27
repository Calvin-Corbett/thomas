"""
Validation decorators for functions and classes.
"""

import inspect
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

from thomas.validation._exceptions import ValidationException
from thomas.validation._types import SchemaDefinition, ValidatorConfig
from thomas.validation.core import Validator
from thomas.validation.schema import Schema

F = TypeVar("F", bound=Callable[..., Any])
T = TypeVar("T")


def validate_args(
    schema: SchemaDefinition | dict[str, Any] | str,
    config: ValidatorConfig | None = None,
    fail_on_error: bool = True,
) -> Callable[[F], F]:
    """Decorator to validate function arguments.

    Args:
        schema: Schema for arguments dict, dict schema, or JSON string.
        config: ValidatorConfig for validation behavior.
        fail_on_error: If True, raise ValidationException on invalid args.

    Returns:
        Decorator function.

    Example:
        @validate_args({
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"}
            },
            "required": ["name"]
        })
        def process(name: str, age: int = 0):
            pass
    """
    if isinstance(schema, str):
        schema = Schema.from_json(schema).definition
    elif isinstance(schema, dict):
        schema = Schema.from_dict(schema).definition

    validator = Validator(config)

    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Get function signature
            sig = inspect.signature(func)
            bound = sig.bind_partial(*args, **kwargs)
            bound.apply_defaults()

            # Build arguments dict
            args_dict = dict(bound.arguments)

            # Validate
            result = validator.validate(args_dict, schema)

            if not result.is_valid and fail_on_error:
                raise ValidationException(
                    f"Validation failed for {func.__name__}",
                    result.errors,
                )

            # Call function
            return func(*args, **kwargs)

        return wrapper  # type: ignore

    return decorator


def validate_return(
    schema: SchemaDefinition | dict[str, Any] | str,
    config: ValidatorConfig | None = None,
    fail_on_error: bool = True,
) -> Callable[[F], F]:
    """Decorator to validate function return value.

    Args:
        schema: Schema for return value.
        config: ValidatorConfig for validation behavior.
        fail_on_error: If True, raise ValidationException on invalid return.

    Returns:
        Decorator function.

    Example:
        @validate_return({
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "result": {"type": "string"}
            }
        })
        def fetch_data():
            return {"success": True, "result": "data"}
    """
    if isinstance(schema, str):
        schema = Schema.from_json(schema).definition
    elif isinstance(schema, dict):
        schema = Schema.from_dict(schema).definition

    validator = Validator(config)

    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            result_value = func(*args, **kwargs)

            # Validate return value
            result = validator.validate(result_value, schema)

            if not result.is_valid and fail_on_error:
                raise ValidationException(
                    f"Return value validation failed for {func.__name__}",
                    result.errors,
                )

            return result_value

        return wrapper  # type: ignore

    return decorator


def schema_class(
    schema: SchemaDefinition | dict[str, Any] | str | None = None,
    config: ValidatorConfig | None = None,
) -> Callable[[type[T]], type[T]]:
    """Decorator to add validation to a dataclass-like class.

    Validates on __init__ and provides validation methods.

    Args:
        schema: Schema definition or dict schema, or None to infer from type hints.
        config: ValidatorConfig for validation behavior.

    Returns:
        Decorator function.

    Example:
        @schema_class({
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "email": {"type": "string"}
            },
            "required": ["name", "email"]
        })
        class User:
            def __init__(self, name: str, email: str):
                self.name = name
                self.email = email
    """

    def decorator(cls: type[T]) -> type[T]:
        # Prepare schema
        if isinstance(schema, str):
            prepared_schema = Schema.from_json(schema).definition
        elif isinstance(schema, dict):
            prepared_schema = Schema.from_dict(schema).definition
        elif isinstance(schema, SchemaDefinition):
            prepared_schema = schema
        else:
            # Infer from type hints
            prepared_schema = _infer_schema_from_class(cls)

        validator = Validator(config)
        original_init = cls.__init__

        @wraps(original_init)
        def validated_init(self: Any, *args: Any, **kwargs: Any) -> None:
            # Build args dict from signature
            sig = inspect.signature(original_init)
            bound = sig.bind(self, *args, **kwargs)
            bound.apply_defaults()

            # Validate all arguments (except self)
            init_args = {k: v for k, v in bound.arguments.items() if k != "self"}
            result = validator.validate(init_args, prepared_schema)

            if not result.is_valid:
                raise ValidationException(
                    f"Validation failed for {cls.__name__}.__init__",
                    result.errors,
                )

            # Call original init
            original_init(self, *args, **kwargs)

        cls.__init__ = validated_init  # type: ignore

        # Add validation method
        def validate(self: Any) -> bool:
            """Validate instance data."""
            data = vars(self)
            result = validator.validate(data, prepared_schema)
            return result.is_valid

        cls.validate = validate  # type: ignore

        # Add validation_errors method
        def validation_errors(self: Any) -> list:
            """Get validation errors for instance."""
            data = vars(self)
            result = validator.validate(data, prepared_schema)
            return result.errors

        cls.validation_errors = validation_errors  # type: ignore

        return cls

    return decorator


def _infer_schema_from_class(cls: type) -> SchemaDefinition:
    """Infer JSON-Schema from class type hints.

    Args:
        cls: Class to infer from.

    Returns:
        SchemaDefinition.
    """
    from thomas.validation._types import SchemaDefinition

    hints = getattr(cls, "__annotations__", {})
    properties = {}

    type_mapping = {
        str: "string",
        int: "integer",
        float: "number",
        bool: "boolean",
        list: "array",
        dict: "object",
    }

    for field_name, field_type in hints.items():
        type_name = type_mapping.get(field_type, "string")
        properties[field_name] = SchemaDefinition(type=type_name)

    return SchemaDefinition(
        type="object",
        properties=properties,
        required=list(hints.keys()),
    )
