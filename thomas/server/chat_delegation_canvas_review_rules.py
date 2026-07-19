"""Shared rules for fail-closed Canvas presentation review."""

from __future__ import annotations

import ast
import re

GENERIC_PLACEHOLDER_RE = re.compile(
    r"tasks?\s*[-\u2013\u2014]+\s*separated individually|separate individual item|"
    r"(?:^|\s)task\s+1(?:\s|$).*?(?:^|\s)task\s+2(?:\s|$)",
    re.IGNORECASE | re.DOTALL,
)
PROMPT_STOPWORDS = {
    "a",
    "an",
    "and",
    "area",
    "bar",
    "canvas",
    "chart",
    "create",
    "design",
    "display",
    "donut",
    "draw",
    "for",
    "from",
    "graph",
    "in",
    "it",
    "line",
    "make",
    "of",
    "on",
    "pie",
    "please",
    "plot",
    "polished",
    "render",
    "scatter",
    "show",
    "showing",
    "static",
    "the",
    "titled",
    "to",
    "visual",
    "with",
    "backing",
    "deliver",
    "live",
    "plus",
}
GRAPHICAL_TAGS = {"canvas", "circle", "ellipse", "img", "line", "path", "polygon", "polyline", "rect", "svg"}
NON_CONTENT_TAGS = {"script", "style", "template"}
VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}
TRANSIENT_HINTS = {
    "confetti",
    "decoration",
    "decorative",
    "loader",
    "loading",
    "particle",
    "popover",
    "skeleton",
    "spinner",
    "splash",
    "toast",
    "tooltip",
}
INTERACTIVE_HINTS = {
    "bullet",
    "coin",
    "enemy",
    "game-object",
    "pickup",
    "player",
    "projectile",
    "sprite",
    "target",
}
INTERACTIVE_TAGS = {"button", "input", "option", "select", "textarea"}

INLINE_HIDDEN_RE = re.compile(
    r"(?:^|;)\s*(?:display\s*:\s*none|visibility\s*:\s*hidden|opacity\s*:\s*0(?:\.0+)?)"
    r"\s*(?:!important\s*)?(?=;|$)",
    re.IGNORECASE,
)
ZERO_FONT_RE = re.compile(
    r"(?:^|;)\s*font-size\s*:\s*0(?:\.0+)?(?:px|pt|pc|em|rem|%|vh|vw|vmin|vmax)?"
    r"\s*(?:!important\s*)?(?=;|$)",
    re.IGNORECASE,
)
OFFSCREEN_RE = re.compile(
    r"(?:^|;)\s*(?:left|right|top|bottom|text-indent)\s*:\s*-\s*[1-9]\d{3,}(?:\.\d+)?"
    r"(?:px|pt|pc|em|rem|vh|vw|vmin|vmax)?\b|"
    r"(?:^|;)\s*(?:left|right|top|bottom|text-indent)\s*:\s*-\s*[1-9]\d{2,}(?:\.\d+)?"
    r"(?:vh|vw|vmin|vmax)\b|"
    r"(?:^|;)\s*transform\s*:[^;]*\btranslate(?:x|y|3d)?\([^;)]*(?:-\s*[1-9]\d{3,}|"
    r"-?\s*(?:[2-9]\d{2,}|1\d{3,})(?:vh|vw|vmin|vmax))|"
    r"(?:^|;)\s*inset\s*:\s*-\s*[1-9]\d{3,}|"
    r"(?:^|;)\s*(?:left|right|top|bottom|inset)\s*:\s*(?:[2-9]\d{2,}|1\d{3,})(?:vh|vw|vmin|vmax)",
    re.IGNORECASE,
)
SCALE_ZERO_RE = re.compile(r"(?:^|;)\s*transform\s*:[^;]*\bscale(?:x|y|3d)?\(\s*0(?:\.0+)?(?:\D|$)", re.IGNORECASE)
CLIPPED_RE = re.compile(
    r"(?:^|;)\s*clip\s*:\s*rect\(\s*0(?:px)?(?:\s*,?\s*0(?:px)?){3}\s*\)|"
    r"(?:^|;)\s*clip-path\s*:\s*inset\(\s*100(?:\.0+)?%|"
    r"(?:^|;)\s*clip-path\s*:\s*(?:circle|ellipse)\(\s*0(?:\.0+)?(?:px|%)?\s*\)",
    re.IGNORECASE,
)
ZERO_WIDTH_RE = re.compile(r"(?:^|;)\s*width\s*:\s*0(?:\.0+)?(?:px|pt|em|rem|%|vh|vw)?\b", re.IGNORECASE)
ZERO_HEIGHT_RE = re.compile(r"(?:^|;)\s*height\s*:\s*0(?:\.0+)?(?:px|pt|em|rem|%|vh|vw)?\b", re.IGNORECASE)
TINY_WIDTH_RE = re.compile(r"(?:^|;)\s*width\s*:\s*(?:0(?:\.\d+)?|1(?:\.0+)?)(?:px|pt)\b", re.IGNORECASE)
TINY_HEIGHT_RE = re.compile(r"(?:^|;)\s*height\s*:\s*(?:0(?:\.\d+)?|1(?:\.0+)?)(?:px|pt)\b", re.IGNORECASE)
CLIPPED_OVERFLOW_RE = re.compile(r"(?:^|;)\s*overflow(?:-x|-y)?\s*:\s*(?:hidden|clip)\b", re.IGNORECASE)
TRANSPARENT_TEXT_RE = re.compile(
    r"(?:^|;)\s*(?:-webkit-)?text-fill-color\s*:\s*transparent\b|"
    r"(?:^|;)\s*color\s*:\s*(?:transparent|rgba\([^;)]*,\s*0(?:\.0+)?\s*\))",
    re.IGNORECASE,
)
FILTER_OPACITY_ZERO_RE = re.compile(r"(?:^|;)\s*filter\s*:[^;]*\bopacity\(\s*0(?:\.0+)?(?:%\s*)?\)", re.IGNORECASE)
CONTENT_VISIBILITY_HIDDEN_RE = re.compile(r"(?:^|;)\s*content-visibility\s*:\s*hidden\b", re.IGNORECASE)
CUSTOM_PROPERTY_RE = re.compile(r"(?:^|;)\s*(--[\w-]+)\s*:\s*([^;]+)", re.IGNORECASE)
OPACITY_VALUE_RE = re.compile(r"(?:^|;)\s*opacity\s*:\s*([^;]+)", re.IGNORECASE)
CSS_VAR_RE = re.compile(r"var\(\s*(--[\w-]+)\s*(?:,\s*([^()]*))?\)", re.IGNORECASE)
CHART_PAIR_RE = re.compile(
    r"(?<![\w.])([A-Za-z][A-Za-z0-9_.-]{0,31})\s*(?::|=|-)?\s*\$?(-?\d+(?:\.\d+)?)\s*%?",
    re.IGNORECASE,
)


def _normalized_color(value: str) -> str:
    color = re.sub(r"\s+", "", str(value or "")).casefold()
    named = {"white": "#ffffff", "black": "#000000", "transparent": "rgba(0,0,0,0)"}
    color = named.get(color, color)
    if re.fullmatch(r"#[0-9a-f]{3}", color):
        color = "#" + "".join(character * 2 for character in color[1:])
    return color


def _same_text_and_background_color(style: str) -> bool:
    declarations: dict[str, str] = {}
    for raw in str(style or "").split(";"):
        if ":" not in raw:
            continue
        name, value = raw.split(":", 1)
        declarations[name.strip().casefold()] = value.strip().removesuffix("!important").strip()
    foreground = declarations.get("color")
    background = declarations.get("background-color") or declarations.get("background")
    if not foreground or not background:
        return False
    # A complex background is not safely comparable here; simple color tokens are.
    if any(token in background.casefold() for token in ("gradient(", "url(", "var(")):
        return False
    return _normalized_color(foreground) == _normalized_color(background)


STYLE_BLOCK_RE = re.compile(r"<style\b[^>]*>(.*?)</style>", re.IGNORECASE | re.DOTALL)
SCRIPT_BLOCK_RE = re.compile(r"<script\b[^>]*>(.*?)</script>", re.IGNORECASE | re.DOTALL)
CSS_RULE_RE = re.compile(r"([^{}]+)\{([^{}]*)\}", re.DOTALL)
KEYFRAME_BLOCK_RE = re.compile(
    r"@(?:-webkit-)?keyframes\s+(?P<name>[\w-]+)\s*\{(?P<body>(?:[^{}]+|\{[^{}]*\})*)\}",
    re.IGNORECASE | re.DOTALL,
)
FINAL_HIDDEN_KEYFRAME_RE = re.compile(
    r"(?:\bto\b|100(?:\.0+)?%)\s*\{[^{}]*(?:display\s*:\s*none|visibility\s*:\s*hidden|"
    r"opacity\s*:\s*0(?:\.0+)?|filter\s*:\s*opacity\(\s*0(?:\.0+)?\s*\)|"
    r"transform\s*:[^;}]*(?:scale|scaleX|scaleY|scale3d)\(\s*0(?:\.0+)?)",
    re.IGNORECASE,
)


def css_custom_properties(style: str) -> dict[str, str]:
    """Return custom properties declared in one CSS declaration block."""

    return {match.group(1).casefold(): match.group(2).strip() for match in CUSTOM_PROPERTY_RE.finditer(style)}


def _resolve_css_variables(value: str, variables: dict[str, str]) -> str:
    resolved = str(value or "").strip()
    for _depth in range(8):
        match = CSS_VAR_RE.search(resolved)
        if not match:
            break
        name = match.group(1).casefold()
        replacement = variables.get(name, match.group(2) or "")
        if not replacement:
            return ""
        resolved = resolved[: match.start()] + str(replacement) + resolved[match.end() :]
    return resolved


def _css_number(value: str) -> float | None:
    expression = str(value or "").strip().removesuffix("!important").strip()
    if expression.casefold().startswith("calc(") and expression.endswith(")"):
        expression = expression[5:-1]
    expression = re.sub(r"(-?\d+(?:\.\d+)?)%", r"(\1/100)", expression)
    if len(expression) > 240 or not re.fullmatch(r"[\d\s.+*/()%-]+", expression):
        return None
    try:
        tree = ast.parse(expression, mode="eval")
    except (SyntaxError, ValueError):
        return None

    def calculate(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return calculate(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            number = calculate(node.operand)
            return number if isinstance(node.op, ast.UAdd) else -number
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            left, right = calculate(node.left), calculate(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            return left / right
        raise ValueError("unsupported CSS expression")

    try:
        return calculate(tree)
    except (TypeError, ValueError, ZeroDivisionError, OverflowError):
        return None


def _opacity_hides_content(style: str, variables: dict[str, str]) -> bool:
    match = OPACITY_VALUE_RE.search(str(style or ""))
    if not match:
        return False
    merged = {**variables, **css_custom_properties(style)}
    value = _css_number(_resolve_css_variables(match.group(1), merged))
    return value is not None and value <= 0


def style_hides_content(style: str, variables: dict[str, str] | None = None) -> bool:
    declaration = str(style or "")
    return bool(
        INLINE_HIDDEN_RE.search(declaration)
        or ZERO_FONT_RE.search(declaration)
        or OFFSCREEN_RE.search(declaration)
        or SCALE_ZERO_RE.search(declaration)
        or CLIPPED_RE.search(declaration)
        or (
            ZERO_WIDTH_RE.search(declaration)
            and ZERO_HEIGHT_RE.search(declaration)
            and CLIPPED_OVERFLOW_RE.search(declaration)
        )
        or (
            TINY_WIDTH_RE.search(declaration)
            and TINY_HEIGHT_RE.search(declaration)
            and CLIPPED_OVERFLOW_RE.search(declaration)
        )
        or TRANSPARENT_TEXT_RE.search(declaration)
        or FILTER_OPACITY_ZERO_RE.search(declaration)
        or CONTENT_VISIBILITY_HIDDEN_RE.search(declaration)
        or _same_text_and_background_color(declaration)
        or _opacity_hides_content(declaration, variables or {})
    )


def tokenize_prompt(prompt: str) -> set[str]:
    return {
        token.casefold()
        for token in re.findall(r"\b[\w.-]+\b", str(prompt or ""), re.UNICODE)
        if len(token) >= 2
        and token.casefold() not in PROMPT_STOPWORDS
        and not token.casefold().endswith((".csv", ".html", ".pdf", ".xlsx"))
    }


def tokenize_text(text: str) -> set[str]:
    return {token.casefold() for token in re.findall(r"\b[\w.-]+\b", str(text or ""), re.UNICODE)}


def chart_prompt_pairs(prompt: str) -> list[tuple[str, str]]:
    """Extract explicit ``label value`` pairs whose association must survive rendering."""

    blocked = PROMPT_STOPWORDS | {"dashboard", "data", "metric", "number", "value"}
    pairs: list[tuple[str, str]] = []
    for match in CHART_PAIR_RE.finditer(str(prompt or "")):
        label = match.group(1).casefold()
        label_parts = {part for part in re.split(r"[-_.]+", label) if part}
        if label in blocked or "marker" in label_parts:
            continue
        value = f"{float(match.group(2)):g}"
        pair = (label, value)
        if pair not in pairs:
            pairs.append(pair)
    return pairs[:20]


def element_hints(attributes: dict[str, object]) -> set[str]:
    values = " ".join(str(attributes.get(key, "")) for key in ("id", "class", "role", "aria-label"))
    return {token.casefold() for token in re.findall(r"[\w-]+", values)}


def is_transient(attributes: dict[str, object]) -> bool:
    return bool(element_hints(attributes) & TRANSIENT_HINTS)


def is_interactive(attributes: dict[str, object]) -> bool:
    return bool(
        str(attributes.get("__tag__", "")).casefold() in INTERACTIVE_TAGS
        or "onclick" in attributes
        or element_hints(attributes) & INTERACTIVE_HINTS
    )


def is_chart_request(prompt: str) -> bool:
    return bool(re.search(r"\b(?:bar|line|pie|donut|scatter|area)?\s*(?:chart|graph|plot)\b", str(prompt or ""), re.I))
