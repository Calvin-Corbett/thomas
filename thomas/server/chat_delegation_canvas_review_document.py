"""Visibility-aware HTML extraction for generated Canvas documents."""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any

from thomas.server.chat_delegation_canvas_review_rules import (
    CSS_RULE_RE,
    GRAPHICAL_TAGS,
    NON_CONTENT_TAGS,
    STYLE_BLOCK_RE,
    VOID_TAGS,
    css_custom_properties,
    is_transient,
    style_hides_content,
    tokenize_text,
)
from thomas.server.chat_delegation_canvas_review_selectors import matches_selector, split_selector_list


@dataclass(frozen=True)
class CanvasDocument:
    elements: tuple[dict[str, Any], ...]
    visible_text: str
    stable_text: str
    count_targets: tuple[str, ...]
    stable_count_targets: tuple[str, ...]
    stable_evidence: tuple[str, ...]
    has_graphical_content: bool

    @property
    def visible_tokens(self) -> set[str]:
        return tokenize_text(f"{self.visible_text} {' '.join(self.count_targets)}")

    @property
    def stable_tokens(self) -> set[str]:
        return tokenize_text(f"{self.stable_text} {' '.join(self.stable_count_targets)}")


def document_css_variables(source: str) -> dict[str, str]:
    """Collect unambiguous custom-property values used by the document."""

    candidates: dict[str, set[str]] = {}
    for block in STYLE_BLOCK_RE.findall(str(source or "")):
        for _selectors, declarations in CSS_RULE_RE.findall(block):
            for name, value in css_custom_properties(declarations).items():
                candidates.setdefault(name, set()).add(value)
    return {name: next(iter(values)) for name, values in candidates.items() if len(values) == 1}


def hidden_css_selectors(source: str, variables: dict[str, str] | None = None) -> list[str]:
    """Return selectors whose declarations permanently hide matched content."""

    selectors: list[str] = []
    resolved_variables = variables if variables is not None else document_css_variables(source)
    for block in STYLE_BLOCK_RE.findall(str(source or "")):
        for selector_list, declarations in CSS_RULE_RE.findall(block):
            if not style_hides_content(declarations, resolved_variables):
                continue
            for selector in split_selector_list(selector_list):
                if "data-reveal" not in selector.casefold():
                    selectors.append(selector)
    return selectors


class _VisibleCanvasParser(HTMLParser):
    def __init__(self, hidden_selectors: list[str], css_variables: dict[str, str]) -> None:
        super().__init__(convert_charrefs=True)
        self._hidden_selectors = hidden_selectors
        self._css_variables = css_variables
        self._hidden_stack: list[bool] = []
        self._transient_stack: list[bool] = []
        self._elements: list[dict[str, Any]] = []
        self._element_stack: list[dict[str, Any]] = []
        self._tag_stack: list[str] = []
        self._child_count_stack: list[int] = []
        self._last_child_stack: list[dict[str, Any] | None] = []
        self._root_child_count = 0
        self._root_last_child: dict[str, Any] | None = None
        self.visible_text: list[str] = []
        self.stable_text: list[str] = []
        self.count_targets: list[str] = []
        self.stable_count_targets: list[str] = []
        self.stable_evidence: list[str] = []
        self.has_graphical_content = False

    def _start(self, tag: str, attrs: list[tuple[str, str | None]], *, push: bool) -> None:
        name = str(tag or "").casefold()
        attributes = {str(key).casefold(): "" if value is None else str(value) for key, value in attrs}
        if self._child_count_stack:
            self._child_count_stack[-1] += 1
            child_index = self._child_count_stack[-1]
            previous_sibling = self._last_child_stack[-1]
        else:
            self._root_child_count += 1
            child_index = self._root_child_count
            previous_sibling = self._root_last_child
        element: dict[str, Any] = {
            "__tag__": name,
            "__child_index__": child_index,
            "__previous_sibling__": previous_sibling,
            "__ancestors__": list(self._element_stack),
            "__text_parts__": [],
            **attributes,
        }
        if self._last_child_stack:
            self._last_child_stack[-1] = element
        else:
            self._root_last_child = element
        inherited_hidden = self._hidden_stack[-1] if self._hidden_stack else False
        own_hidden = bool(
            name in NON_CONTENT_TAGS
            or "hidden" in attributes
            or attributes.get("aria-hidden", "").strip().casefold() == "true"
            or (name == "input" and attributes.get("type", "").strip().casefold() == "hidden")
            or style_hides_content(attributes.get("style", ""), self._css_variables)
            or any(matches_selector(selector, element, self._element_stack) for selector in self._hidden_selectors)
        )
        hidden = inherited_hidden or own_hidden
        transient = (self._transient_stack[-1] if self._transient_stack else False) or is_transient(element)
        element["__hidden__"] = hidden
        element["__transient__"] = transient
        self._elements.append(element)
        if not hidden:
            classes = set(attributes.get("class", "").casefold().split())
            self.has_graphical_content = self.has_graphical_content or name in GRAPHICAL_TAGS or "el" in classes
            target = attributes.get("data-count", "").strip()
            if target:
                self.count_targets.append(target)
                if not transient:
                    self.stable_count_targets.append(target)
                    self.stable_evidence.append(target)
        if push:
            self._hidden_stack.append(hidden)
            self._transient_stack.append(transient)
            self._element_stack.append(element)
            self._tag_stack.append(name)
            self._child_count_stack.append(0)
            self._last_child_stack.append(None)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._start(tag, attrs, push=str(tag or "").casefold() not in VOID_TAGS)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._start(tag, attrs, push=False)

    def handle_endtag(self, tag: str) -> None:
        name = str(tag or "").casefold()
        if name not in self._tag_stack:
            return
        matching_index = len(self._tag_stack) - 1 - self._tag_stack[::-1].index(name)
        while len(self._tag_stack) > matching_index:
            self._tag_stack.pop()
            self._hidden_stack.pop()
            self._transient_stack.pop()
            self._element_stack.pop()
            self._child_count_stack.pop()
            self._last_child_stack.pop()

    def handle_data(self, data: str) -> None:
        text = str(data or "")
        for element in self._element_stack:
            element["__text_parts__"].append(text)
        if self._hidden_stack and self._hidden_stack[-1]:
            return
        self.visible_text.append(text)
        if not (self._transient_stack and self._transient_stack[-1]):
            self.stable_text.append(text)
            if text.strip():
                self.stable_evidence.append(text)


def parse_canvas_document(source: str) -> CanvasDocument:
    variables = document_css_variables(source)
    parser = _VisibleCanvasParser(hidden_css_selectors(source, variables), variables)
    parser.feed(str(source or ""))
    parser.close()
    visible = re.sub(r"\s+", " ", " ".join(parser.visible_text)).strip()
    stable = re.sub(r"\s+", " ", " ".join(parser.stable_text)).strip()
    return CanvasDocument(
        elements=tuple(parser._elements),
        visible_text=visible,
        stable_text=stable,
        count_targets=tuple(parser.count_targets),
        stable_count_targets=tuple(parser.stable_count_targets),
        stable_evidence=tuple(parser.stable_evidence),
        has_graphical_content=parser.has_graphical_content,
    )


def element_has_prompt_evidence(element: dict[str, Any], prompt_tokens: set[str]) -> bool:
    if element.get("__hidden__") or element.get("__tag__") in NON_CONTENT_TAGS:
        return False
    element_text = " ".join(str(part) for part in element.get("__text_parts__", []))
    element_tokens = tokenize_text(f"{element_text} {element.get('data-count', '')}")
    numeric = {token for token in prompt_tokens if any(character.isdigit() for character in token)}
    if numeric & element_tokens:
        return True
    semantic = prompt_tokens - numeric
    required = min(2, max(1, (len(semantic) + 2) // 3))
    return bool(semantic and len(semantic & element_tokens) >= required)


def targeted_elements(document: CanvasDocument, method: str, selector: str) -> list[dict[str, Any]]:
    target = str(selector or "").strip()
    if not target:
        return []
    if method.casefold() == "getelementbyid":
        return [element for element in document.elements if str(element.get("id", "")) == target]
    matched = [
        element for element in document.elements if matches_selector(target, element, element.get("__ancestors__", []))
    ]
    return matched[:1]
