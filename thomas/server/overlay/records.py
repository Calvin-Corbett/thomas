"""Six kinds, one address grammar each, validated before anything is written so
the manifest only ever holds records the rest of Thomas knows how to read:
  theme:<name>                             a derived theme (never a stock name)
  element:<workspace>:<breakpoint>:<ui_id> a layout-book entry, whitelisted style
  setting:default_theme                    the default theme name
`validate_record` returns every reason a record may not be written; an empty list means it may.
`birth_base` stamps the stock a write happened against on the header and every record.
"""

from __future__ import annotations

import functools
import re
import subprocess
from pathlib import Path
from typing import Any

from thomas.server.overlay import stock_tokens
from thomas.server.overlay.schema import (
    RECORD_ID,
    REQUIRED_KEYS,
    exact_keys,
    persisted_keys_for,
    short_text,
    stamp_ok,
    validate_base,
    validate_by,
)
from thomas.server.overlay.style_whitelist import attribute_value_ok, canonical_style_errors, value_ok

KINDS = ("token", "theme", "element", "identity", "setting", "asset")
# Exactly the applied surfaces; an unused field is reserved and refused with a reason.
IDENTITY_FIELDS = ("name", "welcome.title", "welcome.sub", "placeholder", "title")
RESERVED_IDENTITY_FIELDS = ("tagline", "mark")
THEME_NAME = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
ELEMENT_ADDRESS = re.compile(r"^element:([a-z0-9_-]+):(desktop|tablet|mobile):(.+)$")
TOKEN_ADDRESS = re.compile(r"^token:([a-z][a-z0-9-]{1,31}|\*):(--[a-z0-9-]+)$")
PROTECTED_POLICIES = frozenset({"protected", "no-edit"})
ADDRESS_TEXT = re.compile(r"^[a-z]+:[^\x00-\x1f\x7f]{1,400}$")  # printable, bounded; kinds add their own grammar
_REPO_ROOT = Path(__file__).resolve().parents[3]


def validate_loaded(rec: Any, index: int) -> list[str]:
    """Every reason a record already on disk cannot be trusted: full types, ids in order, grammar and guarded values."""
    if not isinstance(rec, dict):
        return ["record must be an object"]
    errors = [f"missing {key}" for key in REQUIRED_KEYS if key not in rec]
    if errors:
        return errors
    errors = exact_keys("record", rec, persisted_keys_for(str(rec.get("op"))))
    if errors:
        return errors
    if not isinstance(rec["id"], str) or not RECORD_ID.match(rec["id"]) or int(rec["id"][1:]) != index + 1:
        errors.append(f"id must be r{index + 1:04d}")
    if not stamp_ok(rec["at"]):
        errors.append("at must be a real ISO-8601 UTC stamp")
    errors += validate_by(rec["by"])
    errors += validate_base(rec["base"])
    if rec["op"] == "set":
        kind, anchor, stock_value = rec["kind"], rec["anchor"], rec["stock_value"]
        if kind != "element" and anchor is not None:
            errors.append("persisted provenance requires a null anchor outside element records")
        if kind == "token":
            if not isinstance(stock_value, str) or stock_value != stock_value.strip() or not value_ok(stock_value):
                errors.append("persisted provenance requires canonical stock_value text for a token")
        elif stock_value is not None:
            errors.append("persisted provenance requires a null stock_value outside token records")
    errors += validate_record(rec, None)
    return errors


def policy_protected(anchor: Any) -> bool:
    """True when the target's data-ui-policy forbids editing it."""
    policy = str(anchor.get("policy", "")) if isinstance(anchor, dict) else ""
    return bool(set(policy.split()) & PROTECTED_POLICIES)


def address_errors(kind: str, address: str) -> list[str]:
    """The address grammar per kind; a clear must pass it too, or a bad address is appended as a retraction."""
    if kind == "token":
        return [] if TOKEN_ADDRESS.match(address) else ["token address must be token:<theme>:<--key>"]
    if kind == "theme":
        name = address.split(":", 1)[1]
        if not THEME_NAME.match(name) or name in stock_tokens.STOCK_THEMES:
            return ["theme name must match ^[a-z][a-z0-9-]{1,31}$ and not be a stock theme name"]
        return []
    if kind == "element":
        return (
            []
            if ELEMENT_ADDRESS.match(address)
            else ["element address must be element:<workspace>:<breakpoint>:<ui_id>"]
        )
    if kind == "identity":
        field = address.split(":", 1)[1]
        if field in RESERVED_IDENTITY_FIELDS:
            return [f"identity field {field} is reserved: no surface applies it yet"]
        return [] if field in IDENTITY_FIELDS else ["identity field is not one the overlay renames"]
    if kind == "setting":
        return [] if address == "setting:default_theme" else ["only setting:default_theme is a setting"]
    return ["assets land in phase 3 with export"]


def _validate_token(
    address: str, value: Any, stock: dict[str, dict[str, str]] | None, known_themes: set[str] | None = None
) -> list[str]:
    errors: list[str] = []
    match = TOKEN_ADDRESS.match(address)
    if match and stock is not None and not stock_tokens.is_stock_key(match.group(2), stock):
        errors.append(f"{match.group(2)} is not a stock token on tokens.css :root")
    if match and known_themes is not None and match.group(1) != "*" and match.group(1) not in known_themes:
        errors.append(f"{match.group(1)} is not a theme this Thomas has")
    if not isinstance(value, str):
        errors.append("token value must be text")
    elif value != value.strip():
        errors.append("token value must be canonical guarded text without surrounding whitespace")
    elif not value_ok(value):
        errors.append("token value refused by the style guard")
    return errors


THEME_KEYS = frozenset({"derives_from", "color_scheme", "label", "tagline", "swatches", "world", "meta"})
META_STRINGS = ("trim", "fontHead", "fontLabel", "rCard", "rComposer", "menuBg", "composerAccent", "msgRule")
META_KEYS = frozenset(META_STRINGS) | {"bot", "welcome"}
COLOUR = re.compile(r"^(#[0-9a-fA-F]{3,8}|(rgb|hsl)a?\([0-9.,\s%]+\)|[a-z]{3,24})$")


def _text_ok(value: Any, limit: int = 80, attribute: bool = False) -> bool:
    guard = attribute_value_ok if attribute else value_ok
    return isinstance(value, str) and value == value.strip() and 0 < len(value) <= limit and guard(value)


def _validate_theme(value: Any) -> list[str]:
    """A theme value reaches chat.html's own theme menu and message markup, so every field is grammar-checked."""
    errors: list[str] = []
    if not isinstance(value, dict) or value.get("derives_from") not in stock_tokens.STOCK_THEMES:
        return errors + ["theme value needs derives_from naming a stock theme"]
    if value.get("color_scheme") not in ("dark", "light"):
        errors.append("theme value needs color_scheme dark or light")
    unknown = sorted(set(value) - THEME_KEYS)
    if unknown:
        errors.append(f"theme value has keys the overlay does not read: {', '.join(unknown)}")
    for field in ("label", "tagline"):
        if field in value and not _text_ok(value[field], attribute=True):
            errors.append(f"theme {field} must be canonical markup-safe text of 1-80 characters")
    if "world" in value and value["world"] not in stock_tokens.STOCK_THEMES:
        errors.append("theme world must name a stock theme")
    swatches = value.get("swatches")
    if swatches is not None and not (
        isinstance(swatches, list)
        and len(swatches) == 3
        and all(isinstance(s, str) and s == s.strip() and COLOUR.match(s) for s in swatches)
    ):
        errors.append("theme swatches must be three canonical markup-safe colours")
    meta = value.get("meta")
    if meta is not None:
        if not isinstance(meta, dict) or set(meta) - META_KEYS:
            errors.append("theme meta may only carry the known META fields")
        else:
            if any(
                key in meta and not _text_ok(meta[key], 160, key in ("msgRule", "composerAccent"))
                for key in META_STRINGS
            ):
                errors.append("theme meta text must be canonical and markup-safe for its sink")
            if "bot" in meta and not (
                isinstance(meta["bot"], list)
                and len(meta["bot"]) == 3
                and all(isinstance(c, str) and c == c.strip() and COLOUR.match(c) for c in meta["bot"])
            ):
                errors.append("theme meta bot must be three colours")
            if "welcome" in meta and not (
                isinstance(meta["welcome"], list)
                and len(meta["welcome"]) == 2
                and all(_text_ok(line, 160, True) for line in meta["welcome"])
            ):
                errors.append("theme meta welcome must be two canonical markup-safe lines")
    return errors


ELEMENT_NUMBERS = ("x", "y", "width", "height", "z")
ELEMENT_KEYS = frozenset({*ELEMENT_NUMBERS, "hidden", "icon", "style", "locked", "text"})
TEXT_LIMIT = 120  # what an element says: a label, a heading, a button; not a paragraph
ELEMENT_LIMIT = 20000  # pixels; anything past this is a runaway, not a layout
ICON_NAME = re.compile(r"^ph-[a-z0-9-]+$")
ANCHOR_KEYS = frozenset({"exact", "fragile", "component", "label", "policy", "path"})
MINTED = "~~"  # ui_redesign_target.js mints "<owner id>~~<path inside it>" for an element with no id


def _bounded(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and abs(value) <= ELEMENT_LIMIT
        and value == value
    )


def _validate_anchor(address: str, anchor: Any) -> list[str]:
    """How the element was found. The client refuses to restyle a replaced node;
    missing or unreadable evidence would apply blindly and is refused here."""
    if not isinstance(anchor, dict):
        return ["element anchor must be an object recording how the target was found"]
    errors: list[str] = exact_keys("anchor", anchor, ANCHOR_KEYS)
    if errors:
        return errors
    for flag in ("exact", "fragile"):
        if not isinstance(anchor.get(flag), bool):
            errors.append(f"anchor.{flag} must be true or false")
    for field in ("component", "label", "policy", "path"):
        if field in anchor and not short_text(anchor[field], 200):
            errors.append(f"anchor.{field} must be text of at most 200 characters")
    parts = address.split(":", 3)
    ui_id = parts[3] if len(parts) > 3 else ""
    minted = MINTED in ui_id
    if minted:
        owner, suffix = ui_id.split(MINTED, 1)
        if anchor.get("exact") or not anchor.get("fragile"):
            errors.append("a minted address needs fragile true and exact false")
        if not owner or not suffix or not anchor.get("path"):
            errors.append("a minted address needs a nonempty owner, suffix and path")
        elif anchor.get("path") != suffix:
            errors.append("a minted address needs the path it was minted from")
    if not minted and (anchor.get("fragile") or not anchor.get("exact")):
        errors.append("an address with its own ui id needs exact true and fragile false")
    return errors


def _validate_element(address: str, value: Any, anchor: Any) -> list[str]:
    errors: list[str] = _validate_anchor(address, anchor)
    if policy_protected(anchor) or stock_tokens.is_protected_ui_id(address.rsplit(":", 1)[-1]):
        errors.append("this region is protected")
    if not isinstance(value, dict):
        return errors + ["element value must be a layout entry"]
    unknown = sorted(set(value) - ELEMENT_KEYS)
    if unknown:
        errors.append(f"element value has keys the overlay does not apply: {', '.join(unknown)}")
    for key in ELEMENT_NUMBERS:
        if key in value and not _bounded(value[key]):
            errors.append(f"element {key} must be a finite number within {ELEMENT_LIMIT}")
    for flag in ("hidden", "locked"):
        if flag in value and not isinstance(value[flag], bool):
            errors.append(f"element {flag} must be true or false")
    if "icon" in value and not (isinstance(value["icon"], str) and ICON_NAME.match(value["icon"])):
        errors.append("element icon must be a ph- icon name")
    # What the element says. Redesign turned a button green and dropped "change
    # its label" because there was no channel for it; one line of plain text is.
    if "text" in value and not (_text_ok(value["text"], TEXT_LIMIT) and chr(10) not in value["text"]):
        errors.append(f"element text must be one line of plain canonical text, at most {TEXT_LIMIT} characters")
    style = value.get("style", {})
    if "style" in value:
        errors += canonical_style_errors(style)
    if not (style or any(key in value for key in (*ELEMENT_NUMBERS, "hidden", "icon", "locked", "text"))):
        errors.append("element value records nothing the overlay would apply")
    return errors


def _validate_identity(value: Any) -> list[str]:
    if not isinstance(value, str) or value != value.strip() or not 0 < len(value) <= 80:
        return ["identity value must be canonical text of 1-80 characters"]
    return []


def validate_record(
    rec: dict[str, Any],
    stock: dict[str, dict[str, str]] | None,
    known_themes: set[str] | None = None,
) -> list[str]:
    """Every reason this record may not be written; an empty list means it may.

    ``stock`` None skips the "is this a stock token" check (used when
    validating a manifest already on disk: a token whose key later left
    tokens.css is a phase-4 finding for `check`, not a broken manifest).
    ``known_themes`` None skips the "does this theme exist" check for the same
    reason; a write passes the themes that will exist once it lands.
    """
    kind, address, op = rec.get("kind"), str(rec.get("address", "")), rec.get("op")
    errors: list[str] = [] if op in ("set", "clear") else ["op must be stated as set or clear"]
    if kind not in KINDS or not address.startswith(f"{kind}:") or not ADDRESS_TEXT.match(address):
        return errors + ["kind and address disagree"]
    errors += address_errors(kind, address)
    if op == "clear" or errors:
        return errors
    value = rec.get("value")
    if kind == "token":
        errors += _validate_token(address, value, stock, known_themes)
    elif kind == "theme":
        errors += _validate_theme(value)
    elif kind == "element":
        errors += _validate_element(address, value, rec.get("anchor"))
    elif kind == "identity":
        errors += _validate_identity(value)
    elif kind == "setting":
        if not isinstance(value, str):
            errors.append("setting:default_theme takes a theme name")
        elif known_themes is not None and value not in known_themes:
            errors.append(f"{value} is not a theme this Thomas has")
    return errors


def stock_value_for(address: str, stock: dict[str, dict[str, str]]) -> str | None:
    """What stock declares at a token address today; None for every other kind."""
    match = TOKEN_ADDRESS.match(address)
    if not match:
        return None
    theme = "nebula" if match.group(1) == "*" else match.group(1)
    return stock.get(theme, {}).get(match.group(2)) or stock.get("nebula", {}).get(match.group(2))


@functools.lru_cache(maxsize=1)
def _git_short_sha() -> str | None:
    """Memoised per process: the running build does not change under a live server."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            cwd=str(_REPO_ROOT),
        )
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def birth_base(web_build: str = "") -> dict[str, Any]:
    """The stock a write happened against: version, git, web build, tokens hash."""
    from thomas import __version__

    return {
        "thomas_version": __version__,
        "git": _git_short_sha(),
        "web_build": web_build or None,
        "tokens_sha1": stock_tokens.tokens_sha1(),
    }
