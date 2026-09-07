"""Read the stock design tokens out of tokens.css so an override can name what it overrides.

tokens.css (thomas/server/web/css/tokens.css) is the single design source:
one :root block carries the nebula tokens and one
html[data-thomas-theme="x"], html[data-theme="x"] block per other stock
theme. This reads those blocks with a small regex, deliberately not a CSS
parser: the file is ours, the grammar is flat, and a parser dependency for
five blocks would be debt. Anything nested (the reduced-motion guard) never
matches a theme selector and is skipped.

A token record's stock_value comes from here at record time, so a later
stock change is visible as a difference between stock_value and the current
stock (the phase-4 collision signal), and is_stock_key is the whitelist
that keeps an overlay from minting tokens nothing reads.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

TOKENS_CSS = Path(__file__).resolve().parents[1] / "web" / "css" / "tokens.css"
WEB_ROOT = TOKENS_CSS.parents[1]
STOCK_THEMES: tuple[str, ...] = ("nebula", "dark", "light", "aurora", "sandstone")
_DECL = re.compile(r"(--[a-z0-9-]+)\s*:\s*([^;]+);")
_BLOCK = re.compile(r"(?P<selector>[^{}]+)\{(?P<body>[^{}]*)\}", re.DOTALL)
_NAMED = re.compile(r'data-thomas-theme="([a-z]+)"')
_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_UI_TAG = re.compile(r'''<[^>]*\bdata-ui-id=["']([a-z0-9_.-]+)["'][^>]*>''', re.IGNORECASE)
_UI_POLICY = re.compile(r'''\bdata-ui-policy=["']([^"']*)["']''', re.IGNORECASE)


def _load_protected_ui_ids() -> frozenset[str]:
    """Literal stock UI ids whose source-owned policy forbids overlay edits."""
    protected: set[str] = set()
    for pattern in ("*.html", "*.js"):
        for path in WEB_ROOT.rglob(pattern):
            for tag in _UI_TAG.finditer(path.read_text(encoding="utf-8")):
                policy = _UI_POLICY.search(tag.group(0))
                if policy and {"protected", "no-edit"} & set(re.split(r"[\s,]+", policy.group(1))):
                    protected.add(tag.group(1))
    return frozenset(protected)


PROTECTED_UI_IDS = _load_protected_ui_ids()


def is_protected_ui_id(ui_id: str) -> bool:
    """Server-owned stock policy wins over a caller-supplied anchor policy."""
    return ui_id.split("~~", 1)[0] in PROTECTED_UI_IDS


def parse(css_text: str) -> dict[str, dict[str, str]]:
    """{theme: {--key: value}} for the five stock themes; nebula is the :root block."""
    themes: dict[str, dict[str, str]] = {name: {} for name in STOCK_THEMES}
    for match in _BLOCK.finditer(_COMMENT.sub("", css_text)):
        # The text before a block may carry @import statements; the selector is the last one.
        selector = " ".join(match.group("selector").split(";")[-1].split())
        target = None
        if selector == ":root" and not themes["nebula"]:
            target = "nebula"
        else:
            named = _NAMED.search(selector)
            if named and named.group(1) in themes:
                target = named.group(1)
        if target is None:
            continue
        for key, value in _DECL.findall(match.group("body")):
            themes[target].setdefault(key, " ".join(value.split()))
    return themes


def load_stock(path: Path = TOKENS_CSS) -> dict[str, dict[str, str]]:
    return parse(path.read_text(encoding="utf-8"))


def tokens_sha1(path: Path = TOKENS_CSS) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()


def is_stock_key(key: str, stock: dict[str, dict[str, str]]) -> bool:
    """A token an overlay may override: one declared on tokens.css :root."""
    return key in stock.get("nebula", {})
