"""The one list of style properties an overlay may set, and the value guard.

Mirrors STYLE_PROPS and safeStyleValue in thomas/server/web/js/ui_edit_layout.js
byte for byte; tests/test_overlay_client_contract.py asserts the two sets are
equal so the browser and the server can never disagree about what a restyle
may contain. ui_redesign_runtime.py imports this instead of carrying its own
copy, which is how the two lists stayed in lockstep before this module.

The guard exists because a style value ends up inside a CSS declaration and a
JSON view: no url(), no expression(), no @import, and none of ; { } < > so a
value can neither escape its declaration nor close a tag.
"""

from __future__ import annotations

import re

STYLE_PROPS: frozenset[str] = frozenset({
    "color", "background", "backgroundColor", "borderColor", "borderRadius", "borderWidth", "borderStyle",
    "fontSize", "fontWeight", "fontStyle", "letterSpacing", "lineHeight", "textAlign", "textTransform",
    "padding", "paddingTop", "paddingRight", "paddingBottom", "paddingLeft",
    "margin", "marginTop", "marginRight", "marginBottom", "marginLeft",
    "gap", "opacity", "boxShadow", "outline", "flexDirection", "justifyContent", "alignItems",
    "gridTemplateColumns", "order", "textDecoration",
})

_FORBIDDEN = re.compile(r"url\s*\(|expression\s*\(|@import|[;{}<>]", re.IGNORECASE)
_ATTR_FORBIDDEN = re.compile(r'["`\\]')
MAX_VALUE_LENGTH = 160


def value_ok(value: object) -> bool:
    """True when a CSS value may be written into a declaration or a token."""
    text = str(value if value is not None else "").strip()
    return 0 < len(text) <= MAX_VALUE_LENGTH and not _FORBIDDEN.search(text)


def attribute_value_ok(value: object) -> bool:
    """The stricter client guard for text interpolated into markup attributes."""
    return value_ok(value) and not _ATTR_FORBIDDEN.search(str(value))


def camel(prop: str) -> str:
    """background-color -> backgroundColor; camelCase input is returned as is."""
    if "-" not in prop:
        return prop
    head, *rest = prop.split("-")
    return head + "".join(part[:1].upper() + part[1:] for part in rest)


def clean_style(style: object) -> dict[str, str]:
    """Keep only whitelisted properties with values that pass the guard."""
    if not isinstance(style, dict):
        return {}
    out: dict[str, str] = {}
    for key, raw in style.items():
        prop = camel(str(key))
        if prop in STYLE_PROPS and value_ok(raw):
            out[prop] = str(raw).strip()
    return out


def canonical_style_errors(style: object) -> list[str]:
    """Reject rather than normalize an overlay style that is not already canonical."""
    if not isinstance(style, dict):
        return ["element style must be an object"]
    if not style:
        return ["element style has no whitelisted property"]
    errors: list[str] = []
    for key, raw in style.items():
        if not isinstance(key, str) or key not in STYLE_PROPS:
            errors.append(f"element style property {key!r} is not canonical or whitelisted")
        if not isinstance(raw, str):
            errors.append(f"element style {key!r} must be text")
        elif raw != raw.strip() or not value_ok(raw):
            errors.append(f"element style {key!r} must be canonical guarded text")
    return errors
