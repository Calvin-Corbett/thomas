"""A read-only, secret-conscious catalogue of settings visible to Thomas.

Callers supply live state; absent state is represented by defaults or None, not
read from private runtime files. Nothing in this module changes a setting.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

_SECRET = re.compile(
    r"(?:password|passwd|credential|secret|api.?key|private.?key|access.?key|"
    r"auth(?:orization)?|bearer|cookie|session.?id|client.?secret|token)",
    re.I,
)
_SAFE_TOKEN = re.compile(
    r"(?:^|[_ .-])(?:max|context|input|output|budget|economy|usage|count|limit|total|prompt|completion|reasoning|cached)[_ .-]*tokens?(?:$|[_ .-])|^token[_ .-]*(?:economy|budget|usage|count|limit|cost|price|pricing)$",
    re.I,
)
_SECRET_VALUE = re.compile(
    r"(?:\bBearer\s+\S+|\b(?:sk|pk|ghp|github_pat|xox[baprs])[-_][A-Za-z0-9_-]{8,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)",
    re.I,
)
_MISSING = object()


def _secret(name: str) -> bool:
    # Keybindings are shortcuts, not cryptographic keys.
    text = re.sub(r"keybindings?", "shortcuts", str(name), flags=re.I)
    text = _SAFE_TOKEN.sub("budget", text)
    return bool(_SECRET.search(text) or re.search(r"(?:^|[_. -])key(?:$|[_. -])|key$", text, re.I))


def _safe(value: Any) -> Any:
    """Copy JSON-like values, dropping secret-bearing fields and unsafe strings."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if _SECRET_VALUE.search(value):
            return None
        if "://" in value:
            try:
                url = urlsplit(value)
                if url.username or url.password or url.query or url.fragment:
                    return None
            except ValueError:
                return None
        return value
    if isinstance(value, (list, tuple)):
        return [_safe(v) for v in value]
    if isinstance(value, Mapping):
        return {str(k): _safe(v) for k, v in value.items() if not _secret(str(k))}
    return None


def _label(key: str) -> str:
    return (
        re.sub(r"\s+", " ", re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", key).replace("_", " ").replace("-", " "))
        .strip()
        .capitalize()
    )


def _row(
    identifier: str,
    name: str,
    description: str,
    location: str,
    value: Any,
    requirement: str = "press",
    values: Any = _MISSING,
) -> dict:
    item = {
        "id": identifier,
        "name": _safe(name) or _label(identifier.split(":")[-1]),
        "description": _safe(description) or "",
        "location": location,
        "current_value": _safe(value),
        "requirement": requirement,
    }
    if values is not _MISSING:
        item["values"] = _safe(values)
    return item


def _source(root: Path, relative: str) -> str:
    try:
        return (root / relative).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def _project_root(root: Any) -> Path:
    return Path(root) if root is not None else Path(__file__).resolve().parents[2]


def _plugins(root: Path, supplied: Any) -> list:
    if supplied is None:
        text = _source(root, "thomas/server/rows/default.toml")
        try:
            supplied = tomllib.loads(text).get("row", []) if text else []
        except tomllib.TOMLDecodeError:
            supplied = []
    if isinstance(supplied, Mapping):
        supplied = supplied.get("rows", supplied.get("row", []))
    result = []
    for entry in supplied or []:
        if not isinstance(entry, Mapping):
            continue
        key = str(entry.get("id", ""))
        if not key or _secret(key):
            continue
        words = entry.get("words") if isinstance(entry.get("words"), Mapping) else entry
        result.append(
            _row(
                "plugin:" + key,
                str(words.get("title") or _label(key)),
                str(words.get("about") or "Enable or disable this plugin."),
                "Settings > Plugins",
                entry.get("state") == "active" if "state" in entry else entry.get("enabled"),
                "windows_sign_in" if entry.get("required") else "press",
                [True, False],
            )
        )
    return result


def _literal(text: str) -> Any:
    text = text.strip()
    if text in ("true", "false", "null"):
        return {"true": True, "false": False, "null": None}[text]
    try:
        return ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return None


def _browser_metadata(root: Path) -> tuple[dict, list]:
    text = _source(root, "thomas/server/web/js/chat_preferences.js")
    defaults = {}
    match = re.search(r"\bDIAL_DEFAULTS\s*=\s*\{([^}]*)\}", text, re.S)
    if match:
        for key, value in re.findall(
            r"([\w$]+)\s*:\s*('[^']*'|\"[^\"]*\"|true|false|null|-?\d+(?:\.\d+)?)", match.group(1)
        ):
            defaults[key] = _literal(value)
    match = re.search(r"\bDIAL_FIELDS\s*=\s*\[(.*?)\n\s*\];", text, re.S)
    result = []
    if match:
        body = match.group(1)
        starts = list(re.finditer(r"\{\s*key\s*:\s*['\"]([^'\"]+)['\"]", body))
        for i, start in enumerate(starts):
            chunk = body[start.start() : starts[i + 1].start() if i + 1 < len(starts) else len(body)]
            label = re.search(r"\blabel\s*:\s*(['\"])(.*?)\1", chunk)
            options = re.findall(r"\[\s*('[^']*'|\"[^\"]*\"|-?\d+(?:\.\d+)?|true|false)\s*,", chunk)
            result.append(
                {
                    "key": start.group(1),
                    "label": label.group(2) if label else _label(start.group(1)),
                    "values": [_literal(option) for option in options],
                }
            )
    known = {item["key"] for item in result}
    result.extend({"key": k, "label": _label(k)} for k in defaults if k not in known)
    return defaults, result


def _dials(root: Path, supplied: Any) -> list:
    defaults, descriptors = _browser_metadata(root)
    current = {}
    if isinstance(supplied, Mapping):
        current = supplied.get("dials", supplied.get("values", {}))
        if not isinstance(current, Mapping):
            current = {}
        metadata = supplied.get("fields", supplied.get("descriptors"))
        if metadata is not None:
            descriptors = metadata
        elif not any(k in supplied for k in ("dials", "values")):
            current = supplied
    elif isinstance(supplied, (list, tuple)):
        descriptors = supplied
    if isinstance(descriptors, Mapping):
        descriptors = [
            dict(v, key=k) if isinstance(v, Mapping) else {"key": k, "current_value": v} for k, v in descriptors.items()
        ]
    out = []
    for field in descriptors or []:
        if not isinstance(field, Mapping):
            continue
        key = str(field.get("key", field.get("id", "")))
        if not key or _secret(key):
            continue
        options = field.get("values", field.get("opts", _MISSING))
        if options is not _MISSING and isinstance(options, (list, tuple)):
            options = [v[0] if isinstance(v, (list, tuple)) and v else v for v in options]
        value = current.get(key, field.get("current_value", field.get("value", defaults.get(key))))
        out.append(
            _row(
                "dial:" + key,
                str(field.get("label", field.get("name", _label(key)))),
                str(field.get("description") or f"Controls {_label(key).lower()} in chat."),
                "Chat > AI settings",
                value,
                field.get("requirement")
                if field.get("requirement") in ("press", "windows_sign_in", "break_glass")
                else "press",
                options,
            )
        )
    return out


def _config_rows(config: Any) -> list:
    if config is None:
        try:
            from thomas.core.config import AppConfig

            config = AppConfig()
        except ImportError:
            return []
    result = []
    seen = set()

    def walk(value: Any, path: tuple[str, ...], metadata: Mapping | None = None) -> None:
        if any(_secret(part) for part in path):
            return
        if is_dataclass(value) and not isinstance(value, type):
            if id(value) in seen:
                return
            seen.add(id(value))
            for field in fields(value):
                if not _secret(field.name):
                    walk(getattr(value, field.name), (*path, field.name), field.metadata)
            seen.remove(id(value))
        elif isinstance(value, Mapping):
            if id(value) in seen:
                return
            seen.add(id(value))
            for key, child in value.items():
                if isinstance(key, str) and not _secret(key):
                    walk(child, (*path, key))
            seen.remove(id(value))
        elif path:
            joined = ".".join(path)
            info = metadata or {}
            result.append(
                _row(
                    "config:" + joined,
                    str(info.get("name") or _label(path[-1])),
                    str(info.get("description") or f"Configuration for {joined}."),
                    "thomas.toml > " + joined,
                    value,
                )
            )

    walk(config, ())
    return result


class _SettingsHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.items = []
        self.stack = []
        self.item = None
        self.capture = None

    def handle_starttag(self, tag: str, attrs: list) -> None:
        attrs = dict(attrs)
        classes = attrs.get("class", "").split()
        if "setting-item" in classes:
            self.item = {"depth": len(self.stack), "name": "", "description": "", "keys": []}
        if self.item is not None:
            if "setting-name" in classes:
                self.capture = ("name", len(self.stack))
            elif "setting-description" in classes:
                self.capture = ("description", len(self.stack))
            key = attrs.get("data-setting")
            if key and attrs.get("type", "").lower() != "password":
                self.item["keys"].append(key)
        if tag not in (
            "input",
            "img",
            "br",
            "hr",
            "meta",
            "link",
            "source",
            "wbr",
            "area",
            "embed",
            "param",
            "track",
            "base",
        ):
            self.stack.append(tag)

    def handle_data(self, data: str) -> None:
        if self.item is not None and self.capture:
            self.item[self.capture[0]] += data

    def handle_endtag(self, tag: str) -> None:
        if tag in self.stack:
            while self.stack:
                found = self.stack.pop()
                if found == tag:
                    break
        if self.capture and len(self.stack) <= self.capture[1]:
            self.capture = None
        if self.item is not None and len(self.stack) <= self.item["depth"]:
            self.items.append(self.item)
            self.item = None


def _preferences(root: Path, supplied: Any) -> list:
    parser = _SettingsHTML()
    parser.feed(_source(root, "thomas/server/web/settings.html"))
    values = supplied if isinstance(supplied, Mapping) else {}
    if isinstance(values.get("preferences"), Mapping):
        values = values["preferences"]
    descriptors = {}
    for item in parser.items:
        for key in item["keys"]:
            descriptors[key] = item
    for key in values:
        if isinstance(key, str):
            descriptors.setdefault(key, {})
    out = []
    for key, item in descriptors.items():
        if _secret(key):
            continue
        value = values.get(key)
        name = item.get("name", "").strip() or _label(key)
        description = item.get("description", "").strip() or f"Browser preference for {_label(key).lower()}."
        out.append(_row("preference:" + key, name, description, "Settings", value))
    return out


def build_index(
    *, plugin_rows=None, config=None, preferences=None, browser_settings=None, express=None, root=None
) -> list[dict]:
    """Build a fresh catalogue from public descriptors and caller-supplied state."""
    base = _project_root(root)
    state = express if isinstance(express, Mapping) else {}
    express_value = {k: state[k] for k in ("open", "since", "elapsed", "elapsed_seconds") if k in state}
    result = [
        _row(
            "express",
            "Express",
            "Temporarily opens Express mode; changing it may require Windows sign-in.",
            "Settings > Express",
            express_value or None,
            "windows_sign_in",
        )
    ]
    result.extend(_plugins(base, plugin_rows))
    result.extend(_dials(base, browser_settings))
    result.extend(_config_rows(config))
    result.extend(_preferences(base, preferences))
    return result


def find_settings(rows, query) -> list[dict]:
    """Find settings by natural words, prioritizing direct control aliases."""

    def normalize(value: Any) -> str:
        return " ".join(re.findall(r"[a-z0-9]+", str(value).lower()))

    phrase = normalize(query)
    if not phrase:
        return []
    stop = {
        "turn",
        "on",
        "off",
        "enable",
        "disable",
        "switch",
        "set",
        "change",
        "the",
        "a",
        "my",
        "please",
        "to",
        "how",
        "do",
        "i",
    }
    words = [word for word in phrase.split() if word not in stop]
    if not words:
        return []
    aliases = {
        "express": ("express",),
        "planner": ("planner", "planning"),
        "voice": ("voice", "speech", "microphone", "mic"),
        "guardrails": ("guardrails", "guardrail", "internet", "web access"),
    }
    targets = {key for key, terms in aliases.items() if any(normalize(term) in phrase for term in terms)}
    ranked = []
    for position, row in enumerate(rows or []):
        if not isinstance(row, Mapping):
            continue
        identifier = normalize(row.get("id", ""))
        title = normalize(row.get("name", ""))
        text = normalize(" ".join(str(row.get(k, "")) for k in ("id", "name", "description", "location")))
        direct = " ".join(words)
        score = 0
        if direct in (title, identifier):
            score = 1000
        elif direct in title or direct in identifier:
            score = 800
        for target in targets:
            if target in identifier.split() or target in title.split():
                score = max(score, 900 if identifier in (target, "dial " + target, "plugin " + target) else 750)
        matched = sum(1 for word in words if word in text.split() or word in text)
        if matched:
            score = max(score, 100 * matched // len(words))
        if score:
            ranked.append((-score, position, row))
    ranked.sort(key=lambda entry: (entry[0], entry[1]))
    return [row for _, _, row in ranked]
