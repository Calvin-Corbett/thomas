"""
ModSecurity Rule Parser

Parse and import ModSecurity-compatible SecRule directives.
"""

import logging
import re

from thomas.marketplace.waf._exceptions import RuleParseException
from thomas.marketplace.waf._types import RuleAction, ThreatLevel, WAFRule


class ModSecurityParser:
    """
    Parse ModSecurity rule format.

    Supports:
    - SecRule directives with variables, operators, and actions
    - Variable matching (@rx, @eq, @gt, @contains, @beginsWith)
    - Transformations (lowercase, urlDecode, htmlEntityDecode, etc.)
    - Rule chaining
    - Skip/skipAfter directives
    """

    # Operator patterns
    OPERATORS = {
        "@rx": "regex",
        "@eq": "equals",
        "@gt": "greater_than",
        "@lt": "less_than",
        "@ge": "greater_equal",
        "@le": "less_equal",
        "@contains": "contains",
        "@beginsWith": "begins_with",
        "@endsWith": "ends_with",
        "@within": "within",
    }

    # Severity mappings
    SEVERITY_MAP = {
        "CRITICAL": ThreatLevel.CRITICAL,
        "HIGH": ThreatLevel.HIGH,
        "MEDIUM": ThreatLevel.MEDIUM,
        "LOW": ThreatLevel.LOW,
        "4": ThreatLevel.CRITICAL,
        "3": ThreatLevel.HIGH,
        "2": ThreatLevel.MEDIUM,
        "1": ThreatLevel.LOW,
    }

    # Action mappings
    ACTION_MAP = {
        "deny": RuleAction.BLOCK,
        "allow": RuleAction.ALLOW,
        "block": RuleAction.BLOCK,
        "log": RuleAction.LOG,
        "pass": RuleAction.ALLOW,
    }

    def __init__(self) -> None:
        """Initialize ModSecurity parser."""
        self.logger = logging.getLogger(__name__)

    def parse_file(self, filepath: str) -> list[WAFRule]:
        """
        Parse ModSecurity rules from file.

        Args:
            filepath: Path to rules file

        Returns:
            List of WAFRule objects

        Raises:
            RuleParseException: If parsing fails
        """
        rules: list[WAFRule] = []

        try:
            with open(filepath) as f:
                lines = f.readlines()

            line_number = 0
            for line in lines:
                line_number += 1
                line = line.strip()

                # Skip comments and empty lines
                if not line or line.startswith("#"):
                    continue

                # Parse SecRule directives
                if line.startswith("SecRule"):
                    try:
                        rule = self.parse_secrule(line, line_number)
                        if rule:
                            rules.append(rule)
                    except RuleParseException:
                        raise
                    except Exception as e:
                        raise RuleParseException(
                            f"Error parsing rule: {e}",
                            rule_line=line,
                            line_number=line_number,
                        )

        except RuleParseException:
            raise
        except Exception as e:
            raise RuleParseException(
                f"Error reading file: {e}",
                filepath,
            )

        return rules

    def parse_secrule(self, line: str, line_number: int = 0) -> WAFRule | None:
        """
        Parse a SecRule directive.

        Format: SecRule VARIABLES OPERATOR "ACTION1,ACTION2,..."

        Args:
            line: SecRule directive line
            line_number: Line number for error reporting

        Returns:
            WAFRule object or None

        Raises:
            RuleParseException: If parsing fails
        """
        # Example: SecRule ARGS|REQUEST_URI "@rx ^/admin" "id:1001,phase:2,deny,msg:'Admin access'"

        match = re.match(
            r'SecRule\s+(\S+)\s+(\S+)\s+"([^"]*)"',
            line,
        )

        if not match:
            raise RuleParseException(
                "Invalid SecRule format",
                rule_line=line,
                line_number=line_number,
            )

        variables_str, operator_str, actions_str = match.groups()

        # Parse variables
        variables = self._parse_variables(variables_str)

        # Parse operator and pattern
        operator, pattern = self._parse_operator(operator_str)

        if not operator or not pattern:
            raise RuleParseException(
                f"Invalid operator: {operator_str}",
                rule_line=line,
                line_number=line_number,
            )

        # Convert operator to regex pattern if needed
        if operator != "regex":
            pattern = self._operator_to_regex(operator, pattern)

        # Parse actions
        actions_dict = self._parse_actions(actions_str)

        # Extract key fields
        rule_id = actions_dict.get("id", f"modsec_{line_number}")
        action = self.ACTION_MAP.get(
            actions_dict.get("phase", "deny").lower(),
            RuleAction.BLOCK,
        )

        # Get phase for action determination
        phase = actions_dict.get("phase", "")
        if phase:
            action_key = next(
                (k for k, v in self.ACTION_MAP.items() if k in phase.lower()),
                "deny",
            )
            action = self.ACTION_MAP.get(action_key, RuleAction.BLOCK)
        else:
            # Check for explicit action
            for key in ["deny", "allow", "block", "log", "pass"]:
                if key in actions_str.lower():
                    action = self.ACTION_MAP.get(key, RuleAction.BLOCK)
                    break

        severity = self.SEVERITY_MAP.get(
            actions_dict.get("severity", "MEDIUM").upper(),
            ThreatLevel.MEDIUM,
        )

        msg = actions_dict.get("msg", f"ModSecurity rule {rule_id}")
        category = actions_dict.get("category", "ModSecurity")

        transformations = self._parse_transformations(actions_dict.get("t", ""))

        rule = WAFRule(
            id=rule_id,
            name=msg,
            pattern=pattern,
            action=action,
            severity=severity,
            category=category,
            priority=int(actions_dict.get("priority", "100")),
            variables=variables,
            transformations=transformations,
        )

        return rule

    def _parse_variables(self, variables_str: str) -> list[str]:
        """
        Parse variable specification.

        Args:
            variables_str: Variables string (e.g., "ARGS|REQUEST_URI")

        Returns:
            List of variable names
        """
        variables = []

        # Handle pipe-separated variables
        for var in variables_str.split("|"):
            var = var.strip()
            if var:
                variables.append(var)

        return variables if variables else ["ARGS|REQUEST_URI"]

    def _parse_operator(self, operator_str: str) -> tuple[str | None, str]:
        """
        Parse operator and extract pattern.

        Args:
            operator_str: Operator string (e.g., "@rx pattern")

        Returns:
            Tuple of (operator_type, pattern)
        """
        # Check for operator prefix
        for op_prefix, op_type in self.OPERATORS.items():
            if operator_str.startswith(op_prefix):
                pattern = operator_str[len(op_prefix) :].strip()
                # Remove quotes if present
                pattern = pattern.strip("'\"")
                return (op_type, pattern)

        # No operator prefix - treat as string match
        return ("contains", operator_str.strip("'\""))

    def _operator_to_regex(self, operator: str, pattern: str) -> str:
        """
        Convert operator pattern to regex.

        Args:
            operator: Operator type
            pattern: Pattern string

        Returns:
            Regex pattern
        """
        if operator == "equals":
            return f"^{re.escape(pattern)}$"
        elif operator == "contains":
            return re.escape(pattern)
        elif operator == "begins_with":
            return f"^{re.escape(pattern)}"
        elif operator == "ends_with":
            return f"{re.escape(pattern)}$"
        elif operator == "greater_than":
            try:
                value = int(pattern)
                return f"^[{value + 1},9][0-9]*$|^[0-9]*[1-9][0-9]+$"
            except ValueError:
                return pattern
        elif operator == "less_than":
            try:
                value = int(pattern)
                return f"^[0-{value - 1}]$|^0?[0-{value - 1}][0-9]*$"
            except ValueError:
                return pattern
        else:
            return pattern

    def _parse_actions(self, actions_str: str) -> dict[str, str]:
        """
        Parse actions/metadata string.

        Args:
            actions_str: Actions string (e.g., "id:123,phase:2,deny,msg:'test'")

        Returns:
            Dictionary of action key-value pairs
        """
        actions = {}

        # Split by comma, but respect quoted values
        parts = []
        current = ""
        in_quotes = False

        for char in actions_str:
            if char == '"':
                in_quotes = not in_quotes
            elif char == "," and not in_quotes:
                if current.strip():
                    parts.append(current.strip())
                current = ""
                continue
            current += char

        if current.strip():
            parts.append(current.strip())

        # Parse each part
        for part in parts:
            if ":" in part:
                key, value = part.split(":", 1)
                key = key.strip()
                value = value.strip().strip("'\"")
                actions[key] = value
            else:
                # Boolean action
                part = part.strip().strip("'\"")
                actions[part] = "true"

        return actions

    def _parse_transformations(self, transformations_str: str) -> list[str]:
        """
        Parse transformation list.

        Args:
            transformations_str: Transformation string (e.g., "lowercase,urlDecode")

        Returns:
            List of transformation names
        """
        if not transformations_str:
            return []

        transformations = []
        for transform in transformations_str.split(","):
            transform = transform.strip()
            if transform:
                transformations.append(transform)

        return transformations
