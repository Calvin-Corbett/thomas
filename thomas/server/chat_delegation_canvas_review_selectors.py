"""Small CSS-selector matcher used by Canvas visibility review."""

from __future__ import annotations

import re
from typing import Any

_ATTRIBUTE_RE = re.compile(r"^\s*([\w:-]+)\s*(?:([~^$*|]?=)\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s]+)))?\s*$")


def split_selector_list(selector_list: str) -> list[str]:
    selectors: list[str] = []
    current: list[str] = []
    depth = 0
    quote = ""
    for character in str(selector_list or ""):
        if quote:
            current.append(character)
            if character == quote:
                quote = ""
        elif character in {'"', "'"} and depth:
            quote = character
            current.append(character)
        elif character == "[":
            depth += 1
            current.append(character)
        elif character == "]":
            depth = max(0, depth - 1)
            current.append(character)
        elif character == "," and not depth:
            if selector := "".join(current).strip():
                selectors.append(selector)
            current = []
        else:
            current.append(character)
    if selector := "".join(current).strip():
        selectors.append(selector)
    return selectors


def _selector_chain(selector: str) -> tuple[list[str], list[str]] | None:
    compounds: list[str] = []
    combinators: list[str] = []
    current: list[str] = []
    depth = 0
    quote = ""
    pending_descendant = False
    for character in str(selector or "").strip():
        if quote:
            current.append(character)
            if character == quote:
                quote = ""
            continue
        if character in {'"', "'"} and depth:
            quote = character
            current.append(character)
            continue
        if character == "[":
            depth += 1
            current.append(character)
            continue
        if character == "]":
            depth = max(0, depth - 1)
            current.append(character)
            continue
        if not depth and character.isspace():
            if current:
                compounds.append("".join(current))
                current = []
            pending_descendant = True
            continue
        if not depth and character in ">+~":
            if current:
                compounds.append("".join(current))
                current = []
            if not compounds:
                return None
            if len(combinators) < len(compounds):
                combinators.append(character)
            else:
                combinators[-1] = character
            pending_descendant = False
            continue
        if pending_descendant:
            if compounds and len(combinators) < len(compounds):
                combinators.append(" ")
            pending_descendant = False
        current.append(character)
    if current:
        compounds.append("".join(current))
    if not compounds or len(combinators) != len(compounds) - 1:
        return None
    return compounds, combinators


def _matches_attribute(expression: str, attributes: dict[str, Any]) -> bool:
    match = _ATTRIBUTE_RE.fullmatch(expression)
    if not match:
        return False
    name, operator, double_value, single_value, bare_value = match.groups()
    key = name.casefold()
    if key not in attributes:
        return False
    if not operator:
        return True
    expected = next(value for value in (double_value, single_value, bare_value) if value is not None).casefold()
    actual = str(attributes[key]).casefold()
    if operator == "=":
        return actual == expected
    if operator == "~=":
        return expected in actual.split()
    if operator == "^=":
        return actual.startswith(expected)
    if operator == "$=":
        return actual.endswith(expected)
    if operator == "*=":
        return expected in actual
    return operator == "|=" and (actual == expected or actual.startswith(f"{expected}-"))


def _matches_compound(compound: str, attributes: dict[str, Any]) -> bool:
    negated: list[str] = []
    first_child = bool(re.search(r":first-child\b", compound, re.I))
    compound = re.sub(r":first-child\b", "", compound, flags=re.I)

    def _record(match: re.Match[str]) -> str:
        negated.append(match.group(1).strip())
        return ""

    compound = re.sub(r":not\(([^()]*)\)", _record, compound, flags=re.I)
    if ":" in compound or any(not condition for condition in negated):
        return False
    cursor = 0
    tag_match = re.match(r"(?:[a-zA-Z][\w-]*|\*)", compound)
    if tag_match:
        tag = tag_match.group(0).casefold()
        if tag != "*" and attributes.get("__tag__") != tag:
            return False
        cursor = tag_match.end()
    classes = set(str(attributes.get("class", "")).casefold().split())
    while cursor < len(compound):
        marker = compound[cursor]
        if marker in ".#":
            token_match = re.match(r"[\w-]+", compound[cursor + 1 :])
            if not token_match:
                return False
            token = token_match.group(0).casefold()
            if marker == "." and token not in classes:
                return False
            if marker == "#" and str(attributes.get("id", "")).casefold() != token:
                return False
            cursor += len(token_match.group(0)) + 1
        elif marker == "[":
            close = compound.find("]", cursor + 1)
            if close < 0 or not _matches_attribute(compound[cursor + 1 : close], attributes):
                return False
            cursor = close + 1
        else:
            return False
    return bool(
        (not first_child or attributes.get("__child_index__") == 1)
        and not any(_matches_compound(condition, attributes) for condition in negated)
    )


def matches_selector(selector: str, attributes: dict[str, Any], ancestors: list[dict[str, Any]]) -> bool:
    parsed = _selector_chain(selector)
    if not parsed:
        return False
    compounds, combinators = parsed
    if not _matches_compound(compounds[-1], attributes):
        return False
    current = attributes
    ancestor_index = len(ancestors) - 1
    for compound_index in range(len(compounds) - 2, -1, -1):
        relation = combinators[compound_index]
        if relation in {"+", "~"}:
            previous = current.get("__previous_sibling__")
            while isinstance(previous, dict) and not _matches_compound(compounds[compound_index], previous):
                if relation == "+":
                    return False
                previous = previous.get("__previous_sibling__")
            if not isinstance(previous, dict):
                return False
            current = previous
            continue
        if relation == ">":
            if ancestor_index < 0 or not _matches_compound(compounds[compound_index], ancestors[ancestor_index]):
                return False
            current = ancestors[ancestor_index]
            ancestor_index -= 1
            continue
        while ancestor_index >= 0 and not _matches_compound(compounds[compound_index], ancestors[ancestor_index]):
            ancestor_index -= 1
        if ancestor_index < 0:
            return False
        current = ancestors[ancestor_index]
        ancestor_index -= 1
    return True
