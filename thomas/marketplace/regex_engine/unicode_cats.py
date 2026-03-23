"""
Unicode category helpers for regex engine.

Provides functions for character classification and Unicode-aware matching.
"""

import unicodedata


def is_digit(char: str) -> bool:
    """Check if character is a digit (0-9)."""
    return char.isdigit()


def is_word_char(char: str) -> bool:
    """Check if character is a word character [a-zA-Z0-9_]."""
    return char.isalnum() or char == "_"


def is_whitespace(char: str) -> bool:
    """Check if character is whitespace."""
    return char.isspace()


def get_unicode_category(char: str) -> str:
    """Get Unicode category of character."""
    return unicodedata.category(char)


def is_unicode_letter(char: str) -> bool:
    """Check if character is a Unicode letter."""
    cat = get_unicode_category(char)
    return cat.startswith("L")


def is_unicode_mark(char: str) -> bool:
    """Check if character is a Unicode combining mark."""
    cat = get_unicode_category(char)
    return cat.startswith("M")


def is_unicode_number(char: str) -> bool:
    """Check if character is a Unicode number."""
    cat = get_unicode_category(char)
    return cat.startswith("N")


def is_unicode_punctuation(char: str) -> bool:
    """Check if character is Unicode punctuation."""
    cat = get_unicode_category(char)
    return cat.startswith("P")


def is_unicode_separator(char: str) -> bool:
    """Check if character is Unicode separator."""
    cat = get_unicode_category(char)
    return cat.startswith("Z")


def is_unicode_symbol(char: str) -> bool:
    """Check if character is Unicode symbol."""
    cat = get_unicode_category(char)
    return cat.startswith("S")


def is_unicode_other(char: str) -> bool:
    """Check if character is Unicode 'other' category."""
    cat = get_unicode_category(char)
    return cat.startswith("C")


def case_fold(char: str) -> str:
    """Case-fold character for case-insensitive matching."""
    return char.casefold()


def expand_digit_class() -> set[str]:
    """Return set of all digit characters."""
    return set("0123456789")


def expand_word_class() -> set[str]:
    """Return set of all word characters (for ASCII mode)."""
    import string

    return set(string.ascii_letters + string.digits + "_")


def expand_whitespace_class() -> set[str]:
    """Return set of all whitespace characters."""
    return {" ", "\t", "\n", "\r", "\f", "\v"}


def expand_unicode_category(cat_code: str) -> set[str]:
    """
    Expand Unicode category code to set of characters.

    Args:
        cat_code: Unicode category (e.g., 'Ll', 'Lu', 'Nd')

    Returns:
        Set of characters matching the category
    """
    result = set()
    # Only check printable range for reasonable performance
    for code_point in range(0x20, 0x10000):
        try:
            char = chr(code_point)
            if unicodedata.category(char) == cat_code:
                result.add(char)
        except ValueError:
            pass
    return result


def normalize_char_for_matching(char: str, ignore_case: bool = False, case_fold: bool = False) -> str:
    """
    Normalize character for matching.

    Args:
        char: Character to normalize
        ignore_case: Convert to lowercase
        case_fold: Use case folding

    Returns:
        Normalized character
    """
    if case_fold:
        return char.casefold()
    if ignore_case:
        return char.lower()
    return char


def build_char_class_set(
    chars: set[str],
    ranges: list,
    escape_classes: set[str],
    negated: bool = False,
    ignore_case: bool = False,
) -> set[str]:
    """
    Build complete character class set from components.

    Args:
        chars: Individual characters
        ranges: Character ranges (e.g., [('a', 'z')])
        escape_classes: Escape sequences like \\d, \\w, \\s
        negated: Whether class is negated [^...]
        ignore_case: Case-insensitive matching

    Returns:
        Set of characters in the class
    """
    result = set()

    # Add individual characters
    for char in chars:
        if ignore_case:
            result.add(char.lower())
            result.add(char.upper())
        else:
            result.add(char)

    # Add ranges
    for start, end in ranges:
        start_code = ord(start)
        end_code = ord(end)
        for code_point in range(start_code, end_code + 1):
            char = chr(code_point)
            if ignore_case:
                result.add(char.lower())
                result.add(char.upper())
            else:
                result.add(char)

    # Add escape classes
    if "d" in escape_classes:
        result.update(expand_digit_class())
    if "D" in escape_classes:
        # All non-digits
        result.update(chr(i) for i in range(256) if chr(i) not in expand_digit_class())
    if "w" in escape_classes:
        result.update(expand_word_class())
    if "W" in escape_classes:
        # All non-word
        result.update(chr(i) for i in range(256) if chr(i) not in expand_word_class())
    if "s" in escape_classes:
        result.update(expand_whitespace_class())
    if "S" in escape_classes:
        # All non-whitespace
        result.update(chr(i) for i in range(256) if chr(i) not in expand_whitespace_class())

    return result
