"""Focused regression tests for configuration-management core types."""

import importlib
from collections.abc import Callable
from typing import Any, get_type_hints


def test_callable_annotations_resolve_to_runtime_types() -> None:
    """Callable annotations must import and retain their concrete contracts."""
    core = importlib.import_module("thomas.config_mgmt.core")

    attribute_hints = get_type_hints(core.ResourceAttribute)
    resource_hints = get_type_hints(core.Resource)
    add_attribute_hints = get_type_hints(core.Resource.add_attribute)

    assert attribute_hints["validator"] == Callable[[Any], bool] | None
    assert resource_hints["handlers"] == dict[str, Callable[..., Any]]
    assert add_attribute_hints["validator"] == Callable[[Any], bool] | None
