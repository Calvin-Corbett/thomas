"""The shapes a manifest must have: exact key sets, typed envelopes, real stamps.

Separate from records.py on purpose. That module answers "what may a record
SAY" (the address grammar and the per-kind value rules); this one answers
"what shape is a manifest, a header, an action envelope", which is what makes
a file on disk trustworthy at all.

Every mapping here is checked against an EXACT key set. A field nothing
downstream reads is never silently dropped and never silently kept: it is
refused by name, so what a caller sent and what the manifest holds can never
differ, and a manifest that grew a field some other tool wrote is broken
rather than quietly half-understood.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

ACTION_ID = re.compile(r"^act_[0-9A-Za-z]{1,40}_[0-9a-f]{4}$")
RECORD_ID = re.compile(r"^r\d{4,}$")
OVERLAY_ID = re.compile(r"^ovl_[0-9a-f]{12}$")
STAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

REQUIRED_KEYS = ("id", "at", "op", "kind", "address", "by", "base")
BASE_KEYS = frozenset({"thomas_version", "git", "web_build", "tokens_sha1"})
HEADER_KEYS = frozenset({"id", "schema", "created_at", "created_from"})
ACTION_KEYS = frozenset({"actor", "instruction", "targets"})
BY_KEYS = frozenset({"actor", "action", "instruction", "targets"})
MANIFEST_KEYS = frozenset({"version", "overlay", "records"})
# Exactly what each operation and kind takes. An element set is the only
# incoming record with an anchor, a clear carries no value at all, and a
# persisted set always carries value, stock_value and anchor, so accepted
# input and stored manifest can never describe different things.
INCOMING_CLEAR_KEYS = frozenset({"op", "kind", "address"})
INCOMING_SET_KEYS = frozenset({"op", "kind", "address", "value"})
INCOMING_SET_ELEMENT_KEYS = frozenset({*INCOMING_SET_KEYS, "anchor"})
PERSISTED_CLEAR_KEYS = frozenset(REQUIRED_KEYS)
PERSISTED_SET_KEYS = frozenset({*REQUIRED_KEYS, "value", "stock_value", "anchor"})


def incoming_keys_for(op: str, kind: str) -> frozenset[str]:
    if op == "clear":
        return INCOMING_CLEAR_KEYS
    return INCOMING_SET_ELEMENT_KEYS if kind == "element" else INCOMING_SET_KEYS


def persisted_keys_for(op: str) -> frozenset[str]:
    return PERSISTED_CLEAR_KEYS if op == "clear" else PERSISTED_SET_KEYS


def exact_keys(name: str, mapping: Any, allowed: frozenset[str]) -> list[str]:
    """Both directions: a key nothing reads is refused, and a key the shape needs cannot be left out."""
    if not isinstance(mapping, dict):
        return [f"{name} must be an object"]
    errors: list[str] = []
    extra = sorted(set(mapping) - allowed)
    missing = sorted(allowed - set(mapping))
    if extra:
        errors.append(f"{name} has keys the overlay does not read: {', '.join(extra)}")
    if missing:
        errors.append(f"{name} is missing: {', '.join(missing)}")
    return errors


def unknown_keys(name: str, mapping: Any, allowed: frozenset[str]) -> list[str]:
    """Every key in a mapping that nothing downstream reads, named so the caller can drop it."""
    if not isinstance(mapping, dict):
        return []
    extra = sorted(set(mapping) - allowed)
    return [f"{name} has keys the overlay does not read: {', '.join(extra)}"] if extra else []


def stamp_ok(value: Any) -> bool:
    """A real ISO-8601 UTC instant, not merely digits in the right places."""
    if not isinstance(value, str) or not STAMP.match(value):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return False
    return True


def short_text(value: Any, limit: int, allow_none: bool = False) -> bool:
    if value is None:
        return allow_none
    return isinstance(value, str) and len(value) <= limit


def validate_base(base: Any) -> list[str]:
    """The stock stamp a write happened against: four known keys, short text."""
    errors: list[str] = exact_keys("base", base, BASE_KEYS)
    if errors:
        return errors
    if not short_text(base.get("thomas_version"), 40):
        errors.append("base.thomas_version must be short text")
    if not short_text(base.get("git"), 64, allow_none=True) or not short_text(base.get("web_build"), 64, allow_none=True):
        errors.append("base.git and base.web_build must be short text or null")
    if not short_text(base.get("tokens_sha1"), 64):
        errors.append("base.tokens_sha1 must be short text")
    return errors


def validate_by(by: Any) -> list[str]:
    """Who wrote a record and why: typed, bounded, never markup-bearing by shape."""
    errors: list[str] = exact_keys("by", by, BY_KEYS)
    if errors:
        return errors
    if not short_text(by.get("actor"), 80) or not by.get("actor"):
        errors.append("by.actor must be short text")
    if not isinstance(by.get("action"), str) or not ACTION_ID.match(by["action"]):
        errors.append("by.action must be an action id")
    if not short_text(by.get("instruction", ""), 2000):
        errors.append("by.instruction must be text of at most 2000 characters")
    targets = by.get("targets", [])
    if not isinstance(targets, list) or len(targets) > 50 or not all(short_text(t, 200) for t in targets):
        errors.append("by.targets must be a list of at most 50 short strings")
    return errors


def validate_header(header: Any) -> list[str]:
    """Every reason a manifest header cannot be trusted."""
    errors: list[str] = exact_keys("header", header, HEADER_KEYS)
    if errors:
        return errors
    if not OVERLAY_ID.match(str(header.get("id", ""))):
        errors.append("overlay id must be ovl_ plus twelve hex digits")
    if type(header.get("schema")) is not int or header.get("schema") != 1:
        errors.append("schema must be the integer 1")
    if not stamp_ok(header.get("created_at")):
        errors.append("created_at must be a real ISO-8601 UTC stamp")
    errors += validate_base(header.get("created_from"))
    return errors


def validate_action(action: Any) -> list[str]:
    """The action envelope a write arrives with, checked before anything is written so it can never poison the manifest."""
    if not isinstance(action, dict):
        return ["action must be an object"]
    errors: list[str] = exact_keys("action", action, ACTION_KEYS)
    if not short_text(action.get("actor"), 80) or not str(action.get("actor") or "").strip():
        errors.append("action.actor must be 1-80 characters of text")
    if not short_text(action.get("instruction"), 2000):
        errors.append("action.instruction must be text of at most 2000 characters")
    targets = action.get("targets")
    if not isinstance(targets, list) or len(targets) > 50 or not all(short_text(t, 200) for t in targets):
        errors.append("action.targets must be a list of at most 50 short strings")
    return errors
