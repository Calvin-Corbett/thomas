"""Detect scripts and animations that erase reviewed Canvas evidence."""

from __future__ import annotations

import re
from typing import Any

from thomas.server.chat_delegation_canvas_review_document import (
    CanvasDocument,
    element_has_prompt_evidence,
    hidden_css_selectors,
    targeted_elements,
)
from thomas.server.chat_delegation_canvas_review_rules import (
    CSS_RULE_RE,
    FINAL_HIDDEN_KEYFRAME_RE,
    KEYFRAME_BLOCK_RE,
    SCRIPT_BLOCK_RE,
    STYLE_BLOCK_RE,
    is_interactive,
    is_transient,
)
from thomas.server.chat_delegation_canvas_review_selectors import matches_selector, split_selector_list

_TARGET_PREFIX = (
    r"document\.(?P<method>getElementById|querySelector)\(\s*"
    r"(?P<quote>['\"])(?P<selector>.*?)(?P=quote)\s*\)"
)
_DIRECT_MUTATION_RE = re.compile(
    _TARGET_PREFIX + r"\s*(?P<operation>"
    r"\.hidden\s*=\s*true|"
    r"\.setAttribute\(\s*['\"](?:hidden|aria-hidden)['\"]\s*,\s*['\"](?:[^'\"]*|true)['\"]\s*\)|"
    r"\.style\.setProperty\(\s*['\"](?:display|visibility|opacity|filter|content-visibility)['\"]\s*,\s*"
    r"['\"](?:none|hidden|0|opacity\(\s*0\s*\))['\"]\s*\)|"
    r"\.style\.(?:display|visibility|opacity|filter|contentVisibility)\s*=\s*"
    r"(?:['\"](?:none|hidden|0|opacity\(\s*0\s*\))['\"]|0)|"
    r"\.remove\s*\(\s*\)|"
    r"\.(?:textContent|innerHTML)\s*=\s*['\"]\s*['\"]"
    r")",
    re.IGNORECASE | re.DOTALL,
)
_TARGET_RE = re.compile(_TARGET_PREFIX, re.IGNORECASE | re.DOTALL)
_CLASS_ADD_RE = re.compile(
    _TARGET_PREFIX + r"\s*\.classList\.add\(\s*(?P<class_quote>['\"])(?P<class_name>[\w-]+)(?P=class_quote)\s*\)",
    re.IGNORECASE | re.DOTALL,
)
_TARGET_BINDING_RE = re.compile(
    r"\b(?:const|let|var)\s+(?P<variable>[A-Za-z_$][\w$]*)\s*=\s*document\."
    r"(?P<method>getElementById|querySelector)\(\s*(?P<quote>['\"])(?P<selector>.*?)(?P=quote)\s*\)",
    re.IGNORECASE | re.DOTALL,
)
_QUERY_ALL_FOREACH_RE = re.compile(
    r"document\.querySelectorAll\(\s*(?P<quote>['\"])(?P<selector>.*?)(?P=quote)\s*\)"
    r"\s*\.forEach\(\s*(?P<variable>[A-Za-z_$][\w$]*)\s*=>\s*(?P<body>\{[^{}]*\}|[^;\n]+)",
    re.IGNORECASE | re.DOTALL,
)
_HIDING_STYLE_OBJECT_RE = re.compile(
    r"\b(?:display\s*:\s*['\"]none|visibility\s*:\s*['\"]hidden|opacity\s*:\s*(?:0|['\"]0)|"
    r"filter\s*:\s*['\"]opacity\(\s*0\s*\)|contentVisibility\s*:\s*['\"]hidden)",
    re.IGNORECASE,
)
_BROAD_DOCUMENT_REMOVAL_RE = re.compile(
    r"document\.(?P<target>body|documentElement)\s*\.\s*(?:"
    r"(?:innerHTML|textContent)\s*=\s*['\"]\s*['\"]|"
    r"replaceChildren\s*\(\s*\)"
    r")",
    re.IGNORECASE | re.DOTALL,
)


def _reviewed_target(element: dict[str, Any], prompt_tokens: set[str]) -> bool:
    return bool(
        not is_transient(element)
        and not is_interactive(element)
        and element_has_prompt_evidence(element, prompt_tokens)
    )


def _reference_mutation(
    script: str,
    reference: str,
    element: dict[str, Any],
    hidden_selectors: list[str],
) -> str:
    ref = rf"(?<![\w$]){re.escape(reference)}"
    direct = re.compile(
        ref + r"\s*(?P<operation>"
        r"\.hidden\s*=\s*true|"
        r"\.setAttribute\(\s*['\"](?:hidden|aria-hidden)['\"]\s*,\s*['\"](?:[^'\"]*|true)['\"]\s*\)|"
        r"\.style\.setProperty\(\s*['\"](?:display|visibility|opacity|filter|content-visibility)['\"]"
        r"\s*,\s*['\"](?:none|hidden|0|opacity\(\s*0\s*\))['\"]\s*\)|"
        r"\.style\.(?:display|visibility|opacity|filter|contentVisibility)\s*=\s*"
        r"(?:['\"](?:none|hidden|0|opacity\(\s*0\s*\))['\"]|0)|"
        r"\.style\.cssText\s*=\s*['\"][^'\"]*(?:display\s*:\s*none|visibility\s*:\s*hidden|"
        r"opacity\s*:\s*0|filter\s*:\s*opacity\(\s*0\s*\)|content-visibility\s*:\s*hidden)[^'\"]*['\"]|"
        r"\.remove\s*\(\s*\)|"
        r"\.(?:textContent|innerHTML)\s*=\s*['\"]\s*['\"]"
        r")",
        re.IGNORECASE | re.DOTALL,
    )
    if match := direct.search(script):
        return match.group("operation")[:120]
    for match in re.finditer(ref + r"\s*\.style\s*,\s*\{(?P<style>[^{}]*)\}", script, re.I | re.S):
        if _HIDING_STYLE_OBJECT_RE.search(match.group("style")):
            return "Object.assign(...style, hiding declarations)"

    class_mutations: list[tuple[str, bool]] = []
    for match in re.finditer(ref + r"\s*\.classList\.add\(\s*(['\"])([\w-]+)\1\s*\)", script, re.I):
        class_mutations.append((match.group(2), False))
    for match in re.finditer(ref + r"\s*\.className\s*=\s*(['\"])([^'\"]*)\1", script, re.I):
        class_mutations.append((match.group(2), True))
    for class_name, replaces in class_mutations:
        mutated = dict(element)
        existing = [] if replaces else str(mutated.get("class", "")).split()
        mutated["class"] = " ".join(dict.fromkeys([*existing, *class_name.split()]))
        ancestors = element.get("__ancestors__", [])
        if isinstance(ancestors, list) and any(
            matches_selector(selector, mutated, ancestors) for selector in hidden_selectors
        ):
            return f"class mutation to hidden selector: {class_name}"
    return ""


def suspicious_script_mutations(
    source: str,
    document: CanvasDocument,
    prompt_tokens: set[str],
) -> list[dict[str, str]]:
    """Return requested-content mutations, excluding transient UI and game objects."""

    findings: list[dict[str, str]] = []
    hidden_selectors = hidden_css_selectors(source)

    def _record(element: dict[str, Any], target: str, operation: str) -> None:
        if not _reviewed_target(element, prompt_tokens):
            return
        finding = {"target": target[:160], "operation": operation[:160]}
        if finding not in findings:
            findings.append(finding)

    for script in SCRIPT_BLOCK_RE.findall(str(source or "")):
        if broad := _BROAD_DOCUMENT_REMOVAL_RE.search(script):
            if any(_reviewed_target(element, prompt_tokens) for element in document.elements):
                findings.append(
                    {
                        "target": f"document.{broad.group('target')}",
                        "operation": broad.group(0)[:160],
                    }
                )
        for match in _DIRECT_MUTATION_RE.finditer(script):
            for element in targeted_elements(document, match.group("method"), match.group("selector")):
                _record(element, match.group("selector"), match.group("operation"))
        for match in _CLASS_ADD_RE.finditer(script):
            for element in targeted_elements(document, match.group("method"), match.group("selector")):
                mutated = dict(element)
                classes = str(mutated.get("class", "")).split()
                classes.append(match.group("class_name"))
                mutated["class"] = " ".join(dict.fromkeys(classes))
                ancestors = element.get("__ancestors__", [])
                if isinstance(ancestors, list) and any(
                    matches_selector(selector, mutated, ancestors) for selector in hidden_selectors
                ):
                    _record(element, match.group("selector"), f"classList.add({match.group('class_name')})")
        for binding in _TARGET_BINDING_RE.finditer(script):
            for element in targeted_elements(document, binding.group("method"), binding.group("selector")):
                operation = _reference_mutation(
                    script[binding.end() :], binding.group("variable"), element, hidden_selectors
                )
                if operation:
                    _record(element, binding.group("selector"), operation)
        for query_all in _QUERY_ALL_FOREACH_RE.finditer(script):
            targets = [
                element
                for element in document.elements
                if matches_selector(query_all.group("selector"), element, element.get("__ancestors__", []))
            ]
            for element in targets:
                operation = _reference_mutation(
                    query_all.group("body"), query_all.group("variable"), element, hidden_selectors
                )
                if operation:
                    _record(element, query_all.group("selector"), operation)
        for direct_target in _TARGET_RE.finditer(script):
            for element in targeted_elements(
                document,
                direct_target.group("method"),
                direct_target.group("selector"),
            ):
                tail = "TARGET" + script[direct_target.end() : direct_target.end() + 500]
                operation = _reference_mutation(tail, "TARGET", element, hidden_selectors)
                if operation:
                    _record(element, direct_target.group("selector"), operation)
        for element in document.elements:
            element_id = str(element.get("id", "")).strip()
            if element_id:
                operation = _reference_mutation(script, element_id, element, hidden_selectors)
                if operation:
                    _record(element, f"#{element_id}", operation)
    return findings


def disappearing_animations(
    source: str,
    document: CanvasDocument,
    prompt_tokens: set[str],
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for style in STYLE_BLOCK_RE.findall(str(source or "")):
        hidden_keyframes = {
            match.group("name").casefold()
            for match in KEYFRAME_BLOCK_RE.finditer(style)
            if FINAL_HIDDEN_KEYFRAME_RE.search(match.group("body"))
        }
        if not hidden_keyframes:
            continue
        for selector_list, declarations in CSS_RULE_RE.findall(style):
            if not re.search(r"(?:^|;)\s*animation(?:-name)?\s*:", declarations, re.I):
                continue
            names = [name for name in hidden_keyframes if re.search(rf"\b{re.escape(name)}\b", declarations, re.I)]
            if not names:
                continue
            if not (
                re.search(r"(?:^|;)\s*animation-fill-mode\s*:\s*(?:forwards|both)\b", declarations, re.I)
                or re.search(r"(?:^|;)\s*animation\s*:[^;]*\b(?:forwards|both)\b", declarations, re.I)
            ):
                continue
            for selector in split_selector_list(selector_list):
                if "data-reveal" in selector.casefold():
                    continue
                for element in document.elements:
                    ancestors = element.get("__ancestors__", [])
                    if (
                        isinstance(ancestors, list)
                        and matches_selector(selector, element, ancestors)
                        and _reviewed_target(element, prompt_tokens)
                    ):
                        finding = {"selector": selector[:160], "keyframe": names[0]}
                        if finding not in findings:
                            findings.append(finding)
    return findings
