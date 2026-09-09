"""
Template engine for configuration file generation and variable interpolation.

Provides Jinja2-like templating capabilities with custom filters,
context management, and variable resolution for configuration templates.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from re import Pattern
from typing import Any, Optional


@dataclass
class TemplateFilter:
    """Represents a custom template filter."""

    name: str
    func: Callable[[Any], Any]
    description: str = ""

    def apply(self, value: Any) -> Any:
        """Apply filter function to value."""
        return self.func(value)


@dataclass
class TemplateContext:
    """Context for template variable resolution."""

    variables: dict[str, Any] = field(default_factory=dict)
    filters: dict[str, TemplateFilter] = field(default_factory=dict)
    parent: Optional["TemplateContext"] = None

    def set_variable(self, name: str, value: Any) -> None:
        """Set a template variable."""
        self.variables[name] = value

    def get_variable(self, name: str, default: Any = None) -> Any:
        """Get a template variable with fallback to parent context."""
        if name in self.variables:
            return self.variables[name]
        if self.parent:
            return self.parent.get_variable(name, default)
        return default

    def add_filter(self, name: str, func: Callable[[Any], Any], description: str = "") -> None:
        """Register a custom template filter."""
        self.filters[name] = TemplateFilter(name, func, description)

    def get_filter(self, name: str) -> TemplateFilter | None:
        """Get a registered filter by name."""
        if name in self.filters:
            return self.filters[name]
        if self.parent:
            return self.parent.get_filter(name)
        return None

    def merge(self, other: "TemplateContext") -> "TemplateContext":
        """Merge another context into this one."""
        merged = TemplateContext(parent=self.parent)
        merged.variables = {**self.variables, **other.variables}
        merged.filters = {**self.filters, **other.filters}
        return merged

    def to_dict(self) -> dict[str, Any]:
        """Convert context to dictionary representation."""
        return {
            "variables": self.variables,
            "filters": {k: v.description for k, v in self.filters.items()},
        }


class TemplateEngine:
    """Template engine for variable substitution and text generation."""

    def __init__(self, context: TemplateContext | None = None) -> None:
        """Initialize template engine with optional context."""
        self.context = context or TemplateContext()
        self._variable_pattern: Pattern = re.compile(r"\{\{(\s*[\w\.]+(?:\|[\w]+)*\s*)\}\}")
        self._condition_pattern: Pattern = re.compile(r"\{%\s*if\s+(.+?)\s*%\}(.+?)\{%\s*endif\s*%\}", re.DOTALL)
        self._loop_pattern: Pattern = re.compile(
            r"\{%\s*for\s+(\w+)\s+in\s+(.+?)\s*%\}(.+?)\{%\s*endfor\s*%\}", re.DOTALL
        )
        self._setup_default_filters()

    def _setup_default_filters(self) -> None:
        """Setup built-in template filters."""
        self.context.add_filter("upper", str.upper, "Convert to uppercase")
        self.context.add_filter("lower", str.lower, "Convert to lowercase")
        self.context.add_filter("length", len, "Get length")
        self.context.add_filter("default", lambda x, d="": x if x else d, "Provide default value")
        self.context.add_filter(
            "reverse", lambda x: x[::-1] if isinstance(x, str) else list(reversed(x)), "Reverse string or list"
        )

    def render(self, template: str, context: TemplateContext | None = None) -> str:
        """Render template with variable substitution."""
        ctx = context or self.context

        # Process loops
        result = self._process_loops(template, ctx)

        # Process conditionals
        result = self._process_conditionals(result, ctx)

        # Process variable substitutions
        result = self._process_variables(result, ctx)

        return result

    def _process_variables(self, template: str, context: TemplateContext) -> str:
        """Process variable substitutions in template."""

        def replace_var(match: Any) -> str:
            var_expr = match.group(1).strip()
            return str(self._evaluate_expression(var_expr, context))

        return self._variable_pattern.sub(replace_var, template)

    def _process_conditionals(self, template: str, context: TemplateContext) -> str:
        """Process if/else conditionals in template."""

        def replace_condition(match: Any) -> str:
            condition = match.group(1).strip()
            content = match.group(2)
            if self._evaluate_condition(condition, context):
                return content
            return ""

        return self._condition_pattern.sub(replace_condition, template)

    def _process_loops(self, template: str, context: TemplateContext) -> str:
        """Process for loops in template."""

        def replace_loop(match: Any) -> str:
            loop_var = match.group(1).strip()
            iterable_expr = match.group(2).strip()
            loop_content = match.group(3)

            iterable = self._evaluate_expression(iterable_expr, context)
            if not hasattr(iterable, "__iter__") or isinstance(iterable, str):
                return ""

            result = []
            for item in iterable:
                loop_ctx = TemplateContext(parent=context)
                loop_ctx.set_variable(loop_var, item)
                rendered = self.render(loop_content, loop_ctx)
                result.append(rendered)

            return "".join(result)

        return self._loop_pattern.sub(replace_loop, template)

    def _evaluate_expression(self, expr: str, context: TemplateContext) -> Any:
        """Evaluate an expression with filters."""
        parts = [p.strip() for p in expr.split("|")]
        value = self._resolve_variable(parts[0], context)

        for filter_name in parts[1:]:
            filter_obj = context.get_filter(filter_name)
            if filter_obj:
                value = filter_obj.apply(value)

        return value

    def _resolve_variable(self, var_path: str, context: TemplateContext) -> Any:
        """Resolve nested variable references."""
        parts = var_path.split(".")
        value = context.get_variable(parts[0])

        if value is None:
            return ""

        for part in parts[1:]:
            if isinstance(value, dict) and part in value:
                value = value[part]
            elif hasattr(value, part):
                value = getattr(value, part)
            else:
                return ""

        return value

    def _evaluate_condition(self, condition: str, context: TemplateContext) -> bool:
        """Evaluate a condition expression."""
        # Simple condition evaluation (supports ==, !=, >, <, >=, <=, and, or)
        condition = condition.strip()

        # Handle 'and' operator
        if " and " in condition:
            parts = condition.split(" and ")
            return all(self._evaluate_condition(p, context) for p in parts)

        # Handle 'or' operator
        if " or " in condition:
            parts = condition.split(" or ")
            return any(self._evaluate_condition(p, context) for p in parts)

        # Handle comparison operators
        for op in ["==", "!=", "<=", ">=", "<", ">"]:
            if op in condition:
                left, right = condition.split(op, 1)
                left_val = self._evaluate_expression(left.strip(), context)
                right_val = self._evaluate_expression(right.strip(), context)

                if op == "==":
                    return left_val == right_val
                elif op == "!=":
                    return left_val != right_val
                elif op == "<":
                    return left_val < right_val
                elif op == ">":
                    return left_val > right_val
                elif op == "<=":
                    return left_val <= right_val
                elif op == ">=":
                    return left_val >= right_val

        # Simple truthiness check
        return bool(self._evaluate_expression(condition, context))

    def add_filter(self, name: str, func: Callable[[Any], Any], description: str = "") -> None:
        """Register a custom filter."""
        self.context.add_filter(name, func, description)

    def set_variable(self, name: str, value: Any) -> None:
        """Set a template variable."""
        self.context.set_variable(name, value)

    def get_variables(self) -> dict[str, Any]:
        """Get all current template variables."""
        return self.context.variables.copy()
