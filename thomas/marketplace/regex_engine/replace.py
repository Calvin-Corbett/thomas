"""
Substitution engine for regex replacements.

Handles pattern substitution with replacement string parsing.
Supports backreferences, callable replacements, and various substitution modes.
"""

from __future__ import annotations

from collections.abc import Callable


class ReplacementParser:
    """Parses replacement strings for substitution."""

    def __init__(self, replacement: str) -> None:
        """Initialize parser."""
        self.replacement = replacement
        self.position = 0

    def parse(self) -> list:
        """
        Parse replacement string into tokens.

        Handles:
        - \1, \2, ... (backreferences by group number)
        - \\g<name> (backreferences by group name)
        - \0 (entire match)
        - \\ (literal backslash)

        Returns:
            List of (type, value) tuples
        """
        tokens = []

        while self.position < len(self.replacement):
            if self.replacement[self.position] == "\\":
                if self.position + 1 < len(self.replacement):
                    next_char = self.replacement[self.position + 1]

                    if next_char == "g":
                        # \g<name>
                        if self.position + 2 < len(self.replacement) and self.replacement[self.position + 2] == "<":
                            end = self.replacement.find(">", self.position + 3)
                            if end != -1:
                                group_name = self.replacement[self.position + 3 : end]
                                tokens.append(("group_ref", group_name))
                                self.position = end + 1
                                continue

                    elif next_char.isdigit():
                        # \1, \2, ...
                        group_num = int(next_char)
                        tokens.append(("group_num", group_num))
                        self.position += 2
                        continue

                    elif next_char == "\\":
                        # \\ -> \
                        tokens.append(("literal", "\\"))
                        self.position += 2
                        continue

                    else:
                        # Other escape
                        tokens.append(("literal", next_char))
                        self.position += 2
                        continue

            # Regular character
            char = self.replacement[self.position]
            tokens.append(("literal", char))
            self.position += 1

        return tokens


class SubstitutionEngine:
    """Performs substitution operations."""

    def __init__(self) -> None:
        """Initialize engine."""
        pass

    def sub(
        self,
        pattern: str | Callable,
        replacement: str | Callable,
        text: str,
        count: int = 0,
    ) -> str:
        """
        Substitute pattern matches.

        Args:
            pattern: Compiled regex or pattern string
            replacement: Replacement string or callable
            text: Text to process
            count: Maximum number of replacements (0 = all)

        Returns:
            Text with replacements applied
        """
        # For now, simple implementation
        # In full system, would use compiled pattern
        if isinstance(replacement, str):
            return self._sub_string(pattern, replacement, text, count)
        elif callable(replacement):
            return self._sub_callable(pattern, replacement, text, count)
        else:
            raise TypeError("Replacement must be string or callable")

    def _sub_string(self, pattern: str, replacement: str, text: str, count: int) -> str:
        """Substitute with string replacement."""
        parser = ReplacementParser(replacement)
        tokens = parser.parse()

        # Use basic regex substitution for now
        # Full implementation would integrate with compiled regex
        result = text
        replacements_made = 0

        # Simple pattern matching
        import re as regex_module

        for match in regex_module.finditer(pattern, text):
            if count > 0 and replacements_made >= count:
                break

            replacement_text = self._build_replacement(match, tokens)
            result = result[: match.start()] + replacement_text + result[match.end() :]
            replacements_made += 1

        return result

    def _sub_callable(self, pattern: str, replacement: Callable, text: str, count: int) -> str:
        """Substitute with callable replacement."""
        result = text
        replacements_made = 0

        import re as regex_module

        for match in regex_module.finditer(pattern, text):
            if count > 0 and replacements_made >= count:
                break

            replacement_text = replacement(match)
            result = result[: match.start()] + replacement_text + result[match.end() :]
            replacements_made += 1

        return result

    def _build_replacement(self, match: object, tokens: list) -> str:
        """Build replacement string from tokens."""
        result = ""

        for token_type, value in tokens:
            if token_type == "literal":
                result += value
            elif token_type == "group_num":
                # Get group by number
                if hasattr(match, "group"):
                    try:
                        group_text = match.group(value)
                        if group_text is not None:
                            result += group_text
                    except (IndexError, AttributeError):
                        pass
            elif token_type == "group_ref":
                # Get group by name (if supported)
                if hasattr(match, "groupdict"):
                    try:
                        group_text = match.group(value)
                        if group_text is not None:
                            result += group_text
                    except (IndexError, AttributeError):
                        pass

        return result


def sub(
    pattern: str,
    replacement: str | Callable,
    text: str,
    count: int = 0,
) -> str:
    """
    Substitute all matches of pattern in text.

    Args:
        pattern: Regex pattern string
        replacement: Replacement string or callable
        text: Text to process
        count: Maximum replacements (0 = all)

    Returns:
        Text with replacements
    """
    engine = SubstitutionEngine()
    return engine.sub(pattern, replacement, text, count)


def subn(
    pattern: str,
    replacement: str | Callable,
    text: str,
    count: int = 0,
) -> tuple:
    """
    Substitute and return (new_string, number_of_subs).

    Args:
        pattern: Regex pattern string
        replacement: Replacement string or callable
        text: Text to process
        count: Maximum replacements (0 = all)

    Returns:
        Tuple of (replaced_text, num_replacements)
    """
    engine = SubstitutionEngine()
    result = engine.sub(pattern, replacement, text, count)

    # Count replacements
    import re as regex_module

    num_replacements = len(list(regex_module.finditer(pattern, text)))
    if count > 0:
        num_replacements = min(num_replacements, count)

    return result, num_replacements
