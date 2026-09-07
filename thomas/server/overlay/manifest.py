"""The overlay manifest: the only source of truth for what a user overrides.

SHAPE: {"version": 1, "overlay": {header}, "records": [...]} - the same
envelope as docs/ops/accepted_risks.json. The header is written at birth and
never mutated. Records are append-only: nothing on disk is ever edited or
deleted; a retraction is a new record with op "clear". `resolve` is
newest-wins per address. rev is simply len(records), so every diff of this
file is "+N lines at the end". What a record may say lives in records.py;
the disk transaction (lock, limits, atomic write, birth) lives in store.py.

THE HONESTY CONTRACT (the repo's documented disease is absence-reads-as-clean):
  * a MISSING manifest is legitimately stock Thomas: `load` returns None and
    logs one INFO line so the absence is visible, never silent.
  * a manifest that EXISTS but fails to parse, has the wrong shape, or holds a
    header or record that does not pass FULL validation (types, grammar, ids
    in order, guarded values) is BROKEN, not empty: `load` raises
    ManifestBroken naming the file, pages fall open to stock (render.py puts
    the error in the view's notes), and every write refuses. Nothing that did
    not pass validation is ever rendered or written.

WHO WRITES: `append` is the only writer and it runs only on an explicit user
action arriving at POST /api/ui/overlay/records. It gives birth only for an
accepted `set` record, inside the locked write, and a refused write leaves no
trace. Startup, page serving, fingerprinting, plugin install, janitors,
migrations and updates never touch this directory (docs/OVERLAY.md).
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import secrets
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from thomas.server.overlay import paths, stock_tokens, store
from thomas.server.overlay.coherence import OverlayIncoherent, action_problems, history_problems, same_effect, themes_in
from thomas.server.overlay.records import birth_base, stock_value_for, validate_loaded, validate_record
from thomas.server.overlay.schema import (
    MANIFEST_KEYS,
    exact_keys,
    incoming_keys_for,
    validate_action,
    validate_base,
    validate_header,
)
from thomas.server.overlay.store import OverlayLimit, OverlayLocked, OverlayUnsafe, OverlayWriteFailed

__all__ = [
    "UNCHECKED", "ActionInvalid", "AppendResult", "Manifest", "ManifestBroken", "OverlayLimit", "OverlayLocked",
    "OverlayIncoherent", "OverlayMismatch", "OverlayUnsafe", "OverlayWriteFailed", "append", "birth_base",
    "load", "parse_json", "resolve", "validate_record",
]

log = logging.getLogger(__name__)

SCHEMA = 1
UNCHECKED = object()  # append() without an overlay-id precondition (library and CLI use; the route never does this)


class ManifestBroken(RuntimeError):
    """The manifest exists but cannot be trusted; the message names the file."""


class OverlayMismatch(RuntimeError):
    """The write's overlay-id precondition does not match what is on disk."""


class ActionInvalid(ValueError):
    """The action envelope or base stamp of a write is malformed; nothing was written."""


@dataclass(frozen=True)
class Manifest:
    path: Path
    header: dict[str, Any]
    records: tuple[dict[str, Any], ...]

    @property
    def rev(self) -> int:
        return len(self.records)

    @property
    def overlay_id(self) -> str:
        return str(self.header.get("id", ""))


@dataclass
class AppendResult:
    created: bool
    rev: int
    overlay_id: str
    accepted: list[str] = field(default_factory=list)
    rejected: list[dict[str, str]] = field(default_factory=list)


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _no_constants(name: str) -> Any:
    raise ValueError(f"non-finite number {name} is not allowed")


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate key {key!r}")
        out[key] = value
    return out


def parse_json(text: str) -> Any:
    """Strict JSON: no NaN/Infinity anywhere, no duplicate keys at any depth."""
    return json.loads(text, parse_constant=_no_constants, object_pairs_hook=_no_duplicates)


def load(path: Path | None = None) -> Manifest | None:
    """The manifest, None when absent, ManifestBroken when present but untrustworthy."""
    path = Path(path) if path else paths.manifest_path()
    if not path.exists():
        log.info("overlay: no manifest at %s (stock Thomas)", path)
        return None
    try:
        size = path.stat().st_size
        if size > store._MAX_MANIFEST_BYTES:
            raise ManifestBroken(f"overlay manifest exceeds {store._MAX_MANIFEST_BYTES} bytes: {path}")
        raw = parse_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ManifestBroken(f"overlay manifest is not readable JSON: {path} ({exc})") from exc
    if not isinstance(raw, dict) or type(raw.get("version")) is not int or raw.get("version") != SCHEMA:
        raise ManifestBroken(f"overlay manifest has the wrong shape or version: {path}")
    if set(raw) - MANIFEST_KEYS:
        raise ManifestBroken(f"overlay manifest has keys the overlay does not read: {path}")
    header, records = raw.get("overlay"), raw.get("records")
    if not isinstance(header, dict) or not isinstance(records, list):
        raise ManifestBroken(f"overlay manifest header or records are malformed: {path}")
    if len(records) > store._MAX_TOTAL_RECORDS:
        raise ManifestBroken(f"overlay manifest exceeds the total record limit of {store._MAX_TOTAL_RECORDS}: {path}")
    problems = validate_header(header)
    if problems:
        raise ManifestBroken(f"overlay manifest header is malformed ({'; '.join(problems)}): {path}")
    action_sizes: dict[str, int] = {}
    for index, record in enumerate(records):
        problems = validate_loaded(record, index)
        if problems:
            raise ManifestBroken(f"overlay manifest record {index} is malformed ({'; '.join(problems)}): {path}")
        action = record["by"]["action"]
        action_sizes[action] = action_sizes.get(action, 0) + 1
        if action_sizes[action] > store._MAX_RECORDS_PER_APPEND:
            raise ManifestBroken(f"overlay manifest has more than {store._MAX_RECORDS_PER_APPEND} records in one action: {path}")
    problems = history_problems(records)
    if problems:
        raise ManifestBroken(f"overlay manifest history is incoherent ({'; '.join(problems)}): {path}")
    if len(resolve(records)) > store._MAX_ACTIVE_OVERRIDES:
        raise ManifestBroken(f"overlay manifest exceeds the active override limit of {store._MAX_ACTIVE_OVERRIDES}: {path}")
    return Manifest(path=path, header=header, records=tuple(records))


def resolve(records: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """What is in effect: newest record per address, a clear retracts the address."""
    live: dict[str, dict[str, Any]] = {}
    for record in records:
        address = str(record.get("address", ""))
        if record.get("op") == "clear":
            live.pop(address, None)
        else:
            live[address] = record
    return live


def _entry(rec: dict[str, Any], number: int, action: dict[str, Any], action_id: str,
           base: dict[str, Any], stock: dict[str, dict[str, str]]) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "id": f"r{number:04d}",
        "at": _now(),
        "op": rec["op"],
        "kind": rec["kind"],
        "address": rec["address"],
        "by": {
            "actor": action["actor"],
            "action": action_id,
            "instruction": action["instruction"],
            "targets": action["targets"],
        },
        "base": base,
    }
    if entry["op"] == "set":
        entry["value"] = rec["value"]
        entry["stock_value"] = stock_value_for(rec["address"], stock)
        entry["anchor"] = rec["anchor"] if rec["kind"] == "element" else None
    return entry


def _triage(
    records: list[Any],
    stock: dict[str, dict[str, str]],
    live: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Validate each record against the state the records before it would leave.

    Accepted means effective: a clear only retracts an address that is in
    effect at that point, and a default theme must name a theme that exists
    once this write lands - including one defined earlier in the same action.
    """
    active = dict(live)
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    for rec in records:
        if not isinstance(rec, dict):
            rejected.append({"address": "", "reason": "record must be an object"})
            continue
        address = str(rec.get("address", ""))
        known = themes_in(active)
        op, kind = str(rec.get("op", "")), str(rec.get("kind", ""))
        errors = exact_keys("record", rec, incoming_keys_for(op, kind)) if op in ("set", "clear") else []
        errors += validate_record(rec, stock, known_themes=known)
        if not errors and rec.get("op") == "clear" and address not in active:
            errors = ["nothing to clear: that address is not in effect"]
        if not errors and rec["op"] == "set" and same_effect(active.get(address), rec):
            errors = ["already in effect: this set makes no durable change"]
        if errors:
            rejected.append({"address": address, "reason": "; ".join(errors)})
            continue
        accepted.append(rec)
        if rec.get("op") == "clear":
            active.pop(address, None)
        else:
            active[address] = rec
    problems = action_problems(live, accepted)
    if problems:
        raise OverlayIncoherent("; ".join(problems))
    return accepted, rejected


def append(
    records: list[dict[str, Any]],
    action: dict[str, Any],
    base: dict[str, Any],
    *,
    expected_overlay_id: Any = UNCHECKED,
    path: Path | None = None,
    stock: dict[str, dict[str, str]] | None = None,
) -> AppendResult:
    """Validate, then add the accepted records at the end of the manifest inside one locked write.

    The first accepted `set` record gives birth: the directory, README,
    .gitattributes, .gitignore and a manifest whose header records the stock
    it was born from, all created inside the write. A write with nothing
    accepted creates nothing. `expected_overlay_id` is a strict precondition
    when given: None means "no overlay exists yet" and a string must equal
    the id on disk (OverlayMismatch otherwise); UNCHECKED skips it. A broken
    manifest, a crossed limit, a held lock or a link inside the boundary
    refuse the write (ManifestBroken, OverlayLimit, OverlayLocked,
    OverlayUnsafe) and leave nothing behind.
    """
    path = Path(path) if path else paths.manifest_path()
    stock = stock if stock is not None else stock_tokens.load_stock()
    problems = validate_action(action) + validate_base(base)
    if problems:
        raise ActionInvalid("; ".join(problems))
    store.guard_boundary(path.parent, path, *(path.parent / name for name, _ in store.BIRTH_FILES))

    def precondition(existing: Manifest | None) -> None:
        # Checked on EVERY write, including one that records nothing: a stale
        # id must never learn the current one from a reply.
        if expected_overlay_id is UNCHECKED:
            return
        on_disk = existing.overlay_id if existing else None
        if expected_overlay_id != on_disk:
            raise OverlayMismatch(f"overlay id {expected_overlay_id!r} does not match the current overlay; refresh its view before retrying")

    with store.locked(store.lock_path_for(path)):
        # Load FIRST: what is already in effect decides whether a clear
        # retracts anything and whether a default theme names a theme that
        # exists, so validation cannot say yes to a record that does nothing.
        existing = load(path)
        precondition(existing)
        accepted, rejected = _triage(records, stock, resolve(existing.records) if existing else {})
        if not accepted:
            return AppendResult(created=False, rev=existing.rev if existing else 0,
                                overlay_id=existing.overlay_id if existing else "", accepted=[], rejected=rejected)
        if existing is None:
            header: dict[str, Any] = {"id": "ovl_" + secrets.token_hex(6), "schema": SCHEMA, "created_at": _now(), "created_from": base}
            current: list[dict[str, Any]] = []
        else:
            header, current = dict(existing.header), list(existing.records)
        action_id = "act_" + _now().replace("-", "").replace(":", "") + "_" + secrets.token_hex(2)
        entries = [_entry(rec, len(current) + 1 + i, action, action_id, base, stock) for i, rec in enumerate(accepted)]
        text = json.dumps({"version": SCHEMA, "overlay": header, "records": [*current, *entries]}, indent=1, ensure_ascii=False) + "\n"
        store.check_limits(len(current), len(entries), len(resolve([*current, *entries])), text)
        store.write_transaction(path, text, birth=existing is None)
    return AppendResult(
        created=existing is None, rev=len(current) + len(entries), overlay_id=str(header["id"]),
        accepted=[str(r["address"]) for r in accepted], rejected=rejected,
    )
