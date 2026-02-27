"""
Validator registry and discovery.
"""

from collections.abc import Callable
from typing import Any

from thomas.validation._exceptions import RuleError
from thomas.validation._types import FieldRule


class ValidatorRegistry:
    """Registry for custom validators and rules."""

    def __init__(self) -> None:
        """Initialize registry."""
        self._rules: dict[str, Callable[[Any], FieldRule]] = {}
        self._validators: dict[str, Callable[[Any], bool]] = {}
        self._chains: dict[str, list[FieldRule]] = {}

    def register_rule(
        self,
        name: str,
        factory: Callable[..., FieldRule],
    ) -> None:
        """Register a rule factory by name.

        Args:
            name: Rule name.
            factory: Function that creates FieldRule.

        Raises:
            RuleError: If rule already registered.
        """
        if name in self._rules:
            raise RuleError(f"Rule '{name}' already registered")
        self._rules[name] = factory

    def register_validator(
        self,
        name: str,
        validator: Callable[[Any], bool],
    ) -> None:
        """Register a validator function by name.

        Args:
            name: Validator name.
            validator: Function that returns True if valid.

        Raises:
            RuleError: If validator already registered.
        """
        if name in self._validators:
            raise RuleError(f"Validator '{name}' already registered")
        self._validators[name] = validator

    def get_rule(self, name: str) -> FieldRule | None:
        """Get a registered rule by name.

        Args:
            name: Rule name.

        Returns:
            FieldRule or None if not found.
        """
        if name not in self._rules:
            return None
        factory = self._rules[name]
        try:
            return factory()
        except Exception as e:
            raise RuleError(f"Error creating rule '{name}': {str(e)}")

    def get_validator(self, name: str) -> Callable[[Any], bool] | None:
        """Get a registered validator by name.

        Args:
            name: Validator name.

        Returns:
            Validator function or None if not found.
        """
        return self._validators.get(name)

    def create_rule(self, name: str, **kwargs: Any) -> FieldRule:
        """Create a rule instance with parameters.

        Args:
            name: Rule name.
            **kwargs: Parameters for rule factory.

        Returns:
            FieldRule instance.

        Raises:
            RuleError: If rule not found or creation fails.
        """
        if name not in self._rules:
            raise RuleError(f"Rule '{name}' not found in registry")

        factory = self._rules[name]
        try:
            return factory(**kwargs)
        except TypeError as e:
            raise RuleError(f"Invalid parameters for rule '{name}': {str(e)}")
        except Exception as e:
            raise RuleError(f"Error creating rule '{name}': {str(e)}")

    def register_chain(self, name: str, rules: list[FieldRule]) -> None:
        """Register a chain of rules.

        Args:
            name: Chain name.
            rules: List of FieldRule objects.
        """
        self._chains[name] = rules

    def get_chain(self, name: str) -> list[FieldRule] | None:
        """Get a registered rule chain.

        Args:
            name: Chain name.

        Returns:
            List of FieldRule objects or None if not found.
        """
        return self._chains.get(name)

    def list_rules(self) -> list[str]:
        """List all registered rule names.

        Returns:
            List of rule names.
        """
        return list(self._rules.keys())

    def list_validators(self) -> list[str]:
        """List all registered validator names.

        Returns:
            List of validator names.
        """
        return list(self._validators.keys())

    def list_chains(self) -> list[str]:
        """List all registered chain names.

        Returns:
            List of chain names.
        """
        return list(self._chains.keys())

    def clear(self) -> None:
        """Clear all registered items."""
        self._rules.clear()
        self._validators.clear()
        self._chains.clear()

    def discover_from_module(self, module: Any) -> None:
        """Discover and register validators from a module.

        Args:
            module: Python module to scan.
        """
        import inspect

        for name, obj in inspect.getmembers(module):
            if name.startswith("_"):
                continue

            # Check if it's a validator function
            if callable(obj) and inspect.isfunction(obj):
                sig = inspect.signature(obj)
                if len(sig.parameters) == 0 or all(
                    p.default != inspect.Parameter.empty for p in sig.parameters.values()
                ):
                    # Likely a rule factory
                    try:
                        result = obj()
                        if isinstance(result, FieldRule):
                            self.register_rule(name, obj)
                    except Exception:
                        pass

    def chain_validators(
        self,
        *validators: Callable[[Any], bool],
    ) -> Callable[[Any], bool]:
        """Chain multiple validators (all must pass).

        Args:
            *validators: Validator functions.

        Returns:
            Chained validator function.
        """

        def chained(value: Any) -> bool:
            return all(v(value) for v in validators)

        return chained

    def chain_rules(self, *rules: FieldRule) -> FieldRule:
        """Chain multiple rules into one.

        Args:
            *rules: FieldRule objects.

        Returns:
            Combined FieldRule that validates all.
        """

        def combined_validator(value: Any) -> bool:
            return all(r.validator(value) for r in rules)

        rule_names = ", ".join(r.name for r in rules)
        return FieldRule(
            name=f"chain_{rule_names}",
            validator=combined_validator,
            message=f"Failed one or more of: {rule_names}",
        )
