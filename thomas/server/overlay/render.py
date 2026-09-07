"""Turn the manifest into what a page needs: a stylesheet block, a JSON view, three tags.

`inject` is called by the handlers that already rewrite served HTML
(app_middleware_helpers.py for /, /classic, /settings, /companion and
mission_support._serve_versioned_page for /mission), so every document,
including every tab iframe the browser shell opens, carries the overlay at
parse and chat.html / settings.html stay untouched. The stylesheet uses the
exact selector grammar of tokens.css (":root" for nebula,
'html[data-thomas-theme="x"], html[data-theme="x"]' for the others) so later
source order wins over the stock sheet and over the literal re-declarations
in settings.style01.css and mission.style01.css.

The view JSON and the runtime script are injected even when no overlay
exists (present:false) so the first write can fan out to documents that were
open before it: the cost on a stock install is one script tag and a few
dozen bytes of JSON. Identity strings reach the page only through this JSON
(with every "<" escaped so a value can neither close the script nor change
how the tags after it parse) and are placed by the runtime with textContent.

The view is cached by manifest mtime for two seconds (the same idiom as the
web-build fingerprint cache) so a page load never re-reads the file per
request storm; `invalidate` drops it after a write.
"""

from __future__ import annotations

import html as html_lib
import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from thomas.server.overlay import manifest as m
from thomas.server.overlay import paths, stock_tokens
from thomas.server.overlay.records import THEME_NAME
from thomas.server.overlay.style_whitelist import value_ok

log = logging.getLogger(__name__)

_CACHE_SECONDS = 2.0
_cache: dict[str, Any] = {"key": None, "view": None, "at": 0.0}
RUNTIME_SRC = "/static/js/overlay_runtime.js"
STYLE_ID = "thomas-overlay-css"
VIEW_ID = "thomas-overlay-view"


def empty_view(path: Path, notes: list[str] | None = None) -> dict[str, Any]:
    return {
        "present": False, "overlay_id": None, "rev": 0, "path": str(path.parent),
        "themes": {}, "tokens": {}, "elements": {}, "anchors": {}, "identity": {}, "default_theme": None,
        "overrides": [], "notes": list(notes or []),
    }


def build_view(loaded: m.Manifest) -> dict[str, Any]:
    """Resolve the records and group what is in effect by kind."""
    view = empty_view(loaded.path)
    view.update(present=True, overlay_id=loaded.overlay_id, rev=loaded.rev)
    for address, rec in m.resolve(loaded.records).items():
        kind, value = rec.get("kind"), rec.get("value")
        parts = address.split(":")
        if kind == "token" and len(parts) == 3:
            view["tokens"].setdefault(parts[1], {})[parts[2]] = value
        elif kind == "theme" and len(parts) == 2:
            view["themes"][parts[1]] = value
        elif kind == "element" and len(parts) >= 4:
            ui_id = ":".join(parts[3:])
            view["elements"].setdefault(parts[1], {}).setdefault(parts[2], {})[ui_id] = value
            if isinstance(rec.get("anchor"), dict):  # how the target was found; the client refuses a replaced node
                view["anchors"][f"{parts[1]}:{parts[2]}:{ui_id}"] = rec["anchor"]
        elif kind == "identity" and len(parts) == 2:
            view["identity"][parts[1]] = value
        elif kind == "setting" and address == "setting:default_theme":
            view["default_theme"] = value
        else:
            view["notes"].append(f"record {rec.get('id')} has an address this Thomas does not read: {address}")
            continue
        view["overrides"].append(address)
    return view


def current_view(path: Path | None = None) -> dict[str, Any]:
    """The view for the manifest on disk; a broken manifest is stock with a note."""
    path = Path(path) if path else paths.manifest_path()
    try:
        key: tuple[str, int | None] = (str(path), path.stat().st_mtime_ns)
    except OSError:
        key = (str(path), None)
    now = time.monotonic()
    if _cache["key"] == key and now - _cache["at"] < _CACHE_SECONDS:
        return _cache["view"]
    try:
        loaded = m.load(path)
        view = build_view(loaded) if loaded else empty_view(path)
    except m.ManifestBroken as exc:
        log.warning("overlay: %s", exc)
        view = empty_view(path, notes=[str(exc)])
    _cache.update(key=key, view=view, at=now)
    return view


def invalidate() -> None:
    _cache.update(key=None, view=None, at=0.0)


_TOKEN_KEY = re.compile(r"^--[a-z0-9-]+$")
_THEME_NAME = THEME_NAME


def _block(selector: str, tokens: dict[str, Any], notes: list[str]) -> str:
    decls = []
    for key, value in tokens.items():
        if not _TOKEN_KEY.match(str(key)) and key != "color-scheme":
            notes.append(f"{key} is not a token and was not rendered")
            continue
        if not value_ok(value):
            notes.append(f"{key} has a value the style guard refuses and was not rendered")
            continue
        decls.append(f"{key}:{str(value).strip()};")
    return f"{selector}{{{''.join(decls)}}}\n" if decls else ""


def _theme_selector(name: str) -> str:
    return f'html[data-thomas-theme="{name}"], html[data-theme="{name}"]'


def render_css(view: dict[str, Any], notes: list[str] | None = None) -> str:
    """The overlay stylesheet: token overrides per theme, then full blocks for overlay themes.

    Render-time notes (a value or name the renderer refused) go into the
    ``notes`` list the caller passes, never into the view: the view may be the
    shared cached object, and appending to it would duplicate the note into
    every page served within the cache window.
    """
    if not view.get("present"):
        return ""
    notes = notes if notes is not None else []
    out: list[str] = []
    tokens_by_theme: dict[str, dict[str, Any]] = view.get("tokens") or {}
    overlay_themes: dict[str, Any] = view.get("themes") or {}
    wildcard = tokens_by_theme.get("*", {})
    if wildcard:
        out.append(_block(":root", wildcard, notes))
        for name in stock_tokens.STOCK_THEMES:
            if name != "nebula":
                out.append(_block(_theme_selector(name), wildcard, notes))
    for theme, tokens in tokens_by_theme.items():
        if theme == "*" or theme in overlay_themes:
            continue  # merged into that theme's derived block below
        if theme != "nebula" and not _THEME_NAME.match(str(theme)):
            notes.append(f"theme {theme!r} is not a valid theme name and was not rendered")
            continue
        selector = ":root" if theme == "nebula" else _theme_selector(theme)
        out.append(_block(selector, tokens or {}, notes))
    if view.get("themes"):
        stock = stock_tokens.load_stock()
        for name, spec in (view.get("themes") or {}).items():
            if not _THEME_NAME.match(str(name)) or name in stock_tokens.STOCK_THEMES:
                notes.append(f"theme {name!r} is not a valid overlay theme name and was not rendered")
                continue
            spec = spec if isinstance(spec, dict) else {}
            base = spec.get("derives_from", "nebula")
            merged: dict[str, Any] = dict(stock.get("nebula", {}))
            merged.update(stock.get(base, {}))
            merged.update(tokens_by_theme.get("*", {}))
            merged.update(tokens_by_theme.get(base, {}))
            merged.update(tokens_by_theme.get(name, {}))
            merged["color-scheme"] = spec.get("color_scheme", "dark")
            out.append(_block(_theme_selector(name), merged, notes))
    return "".join(out)


def render_view(view: dict[str, Any]) -> str:
    """The view as JSON that can sit inside a script element without changing how the page parses.

    Every ``<`` becomes ``\\u003c`` (which JSON.parse restores), so no value can
    close the element (``</script``) or move the HTML tokenizer into the
    escaped script states (``<!--``, ``<script``) that would swallow the tags
    after it; U+2028/2029 are escaped for the same reason on the JS side.
    """
    text = json.dumps(view, ensure_ascii=False, separators=(",", ":"))
    return text.replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def rendered(view: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """The stylesheet and the view to publish, with render-time notes folded into a copy of the view."""
    notes: list[str] = []
    css = render_css(view, notes)
    published = dict(view, notes=[*(view.get("notes") or []), *notes]) if notes else view
    return css, published


def inject(html: str, stamp_token: str, view: dict[str, Any] | None = None) -> str:
    """Insert the overlay style (when present), the view JSON and the runtime before </head>, exactly once."""
    at = html.find("</head>")
    if at < 0 or f'id="{VIEW_ID}"' in html:
        return html
    css, view = rendered(view if view is not None else current_view())
    parts: list[str] = []
    if css:
        parts.append(f'<style id="{STYLE_ID}">\n{css}</style>\n')
    parts.append(f'<script id="{VIEW_ID}" type="application/json">{render_view(view)}</script>\n')
    parts.append(f'<script src="{RUNTIME_SRC}?v={html_lib.escape(stamp_token, quote=True)}" defer></script>\n')
    return html[:at] + "".join(parts) + html[at:]
