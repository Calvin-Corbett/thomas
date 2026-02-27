"""
Thomas Validation Module

A comprehensive schema validation engine supporting nested objects, arrays,
conditional validation, and extensive error tracking.
"""

from thomas.validation._exceptions import (
    CircularReferenceError,
    RuleError,
    SchemaError,
    ValidationException,
)
from thomas.validation._types import (
    FieldRule,
    SchemaDefinition,
    Severity,
    TypeSpec,
    ValidationError,
    ValidationResult,
    ValidatorConfig,
)
from thomas.validation.coercion import CoercionConfig, TypeCoercer
from thomas.validation.composites import (
    And,
    ArrayValidator,
    Conditional,
    DependentFields,
    MapValidator,
    Not,
    Or,
)
from thomas.validation.core import Validator
from thomas.validation.decorators import (
    schema_class,
    validate_args,
    validate_return,
)
from thomas.validation.formatters import (
    ErrorGrouper,
    HumanErrorFormatter,
    JsonErrorFormatter,
)
from thomas.validation.registry import ValidatorRegistry
from thomas.validation.rules import (
    all_of,
    custom_predicate,
    date_format,
    email,
    enum_rule,
    ip_address,
    max_length,
    max_value,
    min_length,
    min_value,
    one_of,
    pattern,
    range_rule,
    required,
    type_check,
    url,
    uuid_rule,
)
from thomas.validation.sanitizers import InputSanitizer, SanitizerConfig
from thomas.validation.schema import (
    Schema,
    SchemaCompiler,
    SchemaRegistry,
)

__all__ = [
    # Types
    "ValidationResult",
    "ValidationError",
    "FieldRule",
    "SchemaDefinition",
    "ValidatorConfig",
    "Severity",
    "TypeSpec",
    # Exceptions
    "ValidationException",
    "SchemaError",
    "RuleError",
    "CircularReferenceError",
    # Core
    "Validator",
    # Rules
    "required",
    "type_check",
    "min_value",
    "max_value",
    "min_length",
    "max_length",
    "pattern",
    "enum_rule",
    "email",
    "url",
    "uuid_rule",
    "ip_address",
    "date_format",
    "range_rule",
    "one_of",
    "all_of",
    "custom_predicate",
    # Schema
    "Schema",
    "SchemaCompiler",
    "SchemaRegistry",
    # Coercion
    "TypeCoercer",
    "CoercionConfig",
    # Sanitizers
    "InputSanitizer",
    "SanitizerConfig",
    # Composites
    "And",
    "Or",
    "Not",
    "Conditional",
    "DependentFields",
    "ArrayValidator",
    "MapValidator",
    # Registry
    "ValidatorRegistry",
    # Formatters
    "JsonErrorFormatter",
    "HumanErrorFormatter",
    "ErrorGrouper",
    # Decorators
    "validate_args",
    "validate_return",
    "schema_class",
]

__version__ = "0.1.0"
