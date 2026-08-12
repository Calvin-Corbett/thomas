"""HTTP surface for at-mention context objects (CAP-148).

Exposes the ``thomas.tools.mention_context`` core -- the typed ``@file:`` /
``@thread:`` / ``@session:`` mention parser/resolver plus budgeted relation
retrieval -- over JSON so the composer UI can resolve an utterance into a
:class:`~thomas.tools.mention_context.ContextBundle` and show exactly what was
INCLUDED, what was DROPPED (unresolvable / budget / duplicate) and the running
TOTAL TOKENS against the budget.

Routes
------
``POST /api/mention-context/resolve``
    Body ``{"utterance": str, "budget": int, "max_relations": int?}`` ->
    the resolved bundle as JSON. ``total_tokens`` is always ``<= budget``.

``POST /api/mention-context/objects``
    Register a ``thread``/``session`` context object (there is no ambient
    thread store at this tier, so the store is supplied by the caller), with
    optional related objects used for budgeted relation retrieval.

``GET /api/mention-context/objects``
    The currently registered thread/session objects plus the file root.

State
-----
A module-level singleton (:func:`get_mention_context_state`) holds the file
root and the thread/session registry so every route shares one store.
``@file`` mentions are read off disk through the core's
:class:`DefaultMentionResolver`, CONTAINED to the configured root: a mention
that escapes the root resolves *unresolved* (and is therefore reported in the
bundle's dropped list) rather than reading an arbitrary path.

The matching UI panel is ``thomas/server/web/js/mention_context_panel.js``
(served at ``/static/js/mention_context_panel.js``).
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aiohttp import web

from thomas.tools.mention_context import (
    ContextBundle,
    ContextObject,
    DefaultMentionResolver,
    Mention,
    RelationCandidate,
    assemble_context_bundle,
    parse_mentions,
)

__all__ = [
    "MENTION_CONTEXT_STATE_KEY",
    "MentionContextState",
    "get_mention_context_state",
    "register_mention_context_routes",
    "reset_mention_context_state",
    "set_mention_context_state",
]

_log = logging.getLogger(__name__)

MENTION_CONTEXT_STATE_KEY = web.AppKey("mention_context_state", object)

_STORE_KINDS = ("thread", "session")
_MAX_UTTERANCE_CHARS = 20_000
_MAX_CONTENT_CHARS = 200_000
_MAX_BUDGET = 1_000_000
_MAX_RELATIONS_CAP = 32
_DEFAULT_MAX_RELATIONS = 6
_MAX_STORE_OBJECTS = 500
_PREVIEW_CHARS = 240
_NEIGHBOUR_MAX_BYTES = 20_000

# Errors raised by filesystem / decoding work we handle inline. Deliberately a
# wide SPECIFIC tuple rather than a bare ``except Exception``.
_IO_ERRORS = (OSError, ValueError, UnicodeError)


@dataclass
class MentionContextState:
    """Shared store behind the mention routes.

    ``threads``/``sessions`` map a ref to its text content; ``relations`` maps a
    context-object key (``"thread:42"``) to the neighbours that budgeted
    relation retrieval may pull in for it.
    """

    root: Path
    threads: dict[str, str] = field(default_factory=dict)
    sessions: dict[str, str] = field(default_factory=dict)
    relations: dict[str, list[tuple[ContextObject, float]]] = field(default_factory=dict)

    def store_for(self, kind: str) -> dict[str, str]:
        return self.threads if kind == "thread" else self.sessions

    def snapshot(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "threads": sorted(self.threads),
            "sessions": sorted(self.sessions),
            "relations": {key: len(vals) for key, vals in sorted(self.relations.items())},
        }


_state: MentionContextState | None = None


def _resolve_root(config: Any) -> Path:
    """File root for ``@file`` mentions: env override, then config, then cwd."""

    env_root = str(os.environ.get("THOMAS_MENTION_CONTEXT_ROOT") or "").strip()
    candidates = [env_root, _deep_get(config, ["workspace", "root"]), _deep_get(config, ["memory", "root_path"])]
    for candidate in candidates:
        text = str(candidate or "").strip()
        if not text:
            continue
        try:
            path = Path(text).expanduser().resolve()
        except _IO_ERRORS:
            continue
        if path.is_dir():
            return path
    return Path.cwd().resolve()


def get_mention_context_state(config: Any = None) -> MentionContextState:
    """Module-level singleton accessor shared by every route in this module."""

    global _state
    if _state is None:
        _state = MentionContextState(root=_resolve_root(config))
    return _state


def set_mention_context_state(state: MentionContextState) -> MentionContextState:
    """Install ``state`` as the singleton (used at registration and in tests)."""

    global _state
    _state = state
    return _state


def reset_mention_context_state() -> None:
    """Drop the singleton so the next accessor call rebuilds it."""

    global _state
    _state = None


def register_mention_context_routes(app: web.Application, config: Any) -> None:
    """Register the at-mention context-object routes on ``app``."""

    state = set_mention_context_state(MentionContextState(root=_resolve_root(config)))
    app[MENTION_CONTEXT_STATE_KEY] = state
    app.router.add_post("/api/mention-context/resolve", handle_resolve_mentions)
    app.router.add_post("/api/mention-context/objects", handle_register_object)
    app.router.add_get("/api/mention-context/objects", handle_list_objects)


# --------------------------------------------------------------------------- #
# Resolver / relation seams
# --------------------------------------------------------------------------- #


class _ContainedResolver:
    """Core resolver with ``@file`` reads contained to the configured root."""

    def __init__(self, state: MentionContextState) -> None:
        self._root = state.root
        self._inner = DefaultMentionResolver(
            state.root,
            thread_lookup=state.threads,
            session_lookup=state.sessions,
        )

    def resolve(self, mention: Mention) -> ContextObject:
        if mention.kind == "file" and not self._within_root(mention.ref):
            return ContextObject(
                kind="file",
                ref=mention.ref,
                resolved=False,
                error="outside project root",
            )
        return self._inner.resolve(mention)

    def _within_root(self, ref: str) -> bool:
        try:
            path = Path(ref)
            if not path.is_absolute():
                path = self._root / path
            return path.resolve().is_relative_to(self._root)
        except _IO_ERRORS:
            return False


class _StateRelations:
    """Relation provider: registered neighbours, plus sibling files for ``@file``."""

    def __init__(self, state: MentionContextState, *, max_relations: int) -> None:
        self._state = state
        self._max = max(0, int(max_relations))

    def related(self, obj: ContextObject) -> list[RelationCandidate]:
        if self._max <= 0:
            return []
        out: list[RelationCandidate] = []
        for related_obj, relevance in self._state.relations.get(obj.key, []):
            out.append(RelationCandidate(obj=related_obj, relevance=float(relevance)))
            if len(out) >= self._max:
                return out
        if obj.kind == "file":
            for candidate in self._file_neighbours(obj):
                out.append(candidate)
                if len(out) >= self._max:
                    break
        return out

    def _file_neighbours(self, obj: ContextObject) -> Iterator[RelationCandidate]:
        anchor = Path(obj.ref)
        base = anchor if anchor.is_absolute() else self._state.root / anchor
        try:
            directory = base.resolve().parent
            names = sorted(p.name for p in directory.iterdir() if p.is_file())
        except _IO_ERRORS as exc:
            _log.debug("mention-context: cannot list neighbours of %s: %s", obj.ref, exc)
            return
        for name in names:
            if name == base.name or name.startswith("."):
                continue
            sibling = directory / name
            text = _read_text(sibling)
            if text is None:
                continue
            try:
                ref = str(sibling.relative_to(self._state.root)).replace(os.sep, "/")
            except ValueError:
                ref = name
            summary = text.strip().splitlines()[0] if text.strip() else ""
            yield RelationCandidate(
                obj=ContextObject(kind="file", ref=ref, content=text, summary=summary[:200]),
                relevance=_name_affinity(base.name, name),
            )


def _read_text(path: Path) -> str | None:
    try:
        return path.read_bytes()[:_NEIGHBOUR_MAX_BYTES].decode("utf-8", errors="replace")
    except _IO_ERRORS as exc:
        _log.debug("mention-context: unreadable neighbour %s: %s", path, exc)
        return None


def _name_affinity(anchor_name: str, other_name: str) -> float:
    """Deterministic 0..1 relevance for a sibling file.

    Two cheap, stable signals: how much of the file name the two share (up to
    0.7) plus a 0.3 bonus for sharing a suffix -- a neighbouring ``.py`` beside
    a ``.py`` anchor is more relevant than an unrelated ``.png``.
    """

    same_suffix = 0.3 if Path(anchor_name).suffix.lower() == Path(other_name).suffix.lower() else 0.0
    shared = 0
    for a, b in zip(anchor_name.lower(), other_name.lower()):
        if a != b:
            break
        shared += 1
    longest = max(len(anchor_name), len(other_name), 1)
    return round(same_suffix + 0.7 * (shared / longest), 6)


# --------------------------------------------------------------------------- #
# Handlers
# --------------------------------------------------------------------------- #


def _state_for(request: web.Request) -> MentionContextState:
    state = request.app.get(MENTION_CONTEXT_STATE_KEY)
    if isinstance(state, MentionContextState):
        return state
    return get_mention_context_state()


async def handle_resolve_mentions(request: web.Request) -> web.Response:
    """POST /api/mention-context/resolve -- utterance + budget -> context bundle."""

    body = await _read_json_object(request)
    utterance = body.get("utterance", "")
    if not isinstance(utterance, str):
        raise web.HTTPBadRequest(text="utterance must be a string")
    if len(utterance) > _MAX_UTTERANCE_CHARS:
        raise web.HTTPBadRequest(text=f"utterance must be at most {_MAX_UTTERANCE_CHARS} characters")

    budget = _require_int(body.get("budget"), "budget", minimum=0, maximum=_MAX_BUDGET)
    raw_relations = body.get("max_relations")
    max_relations = (
        _DEFAULT_MAX_RELATIONS
        if raw_relations is None
        else _require_int(raw_relations, "max_relations", minimum=0, maximum=_MAX_RELATIONS_CAP)
    )

    state = _state_for(request)
    mentions = parse_mentions(utterance)
    bundle = assemble_context_bundle(
        utterance,
        _ContainedResolver(state),
        budget=budget,
        relation_provider=_StateRelations(state, max_relations=max_relations),
        mentions=mentions,
    )
    return web.json_response(_bundle_payload(bundle, mentions, max_relations, state.root))


async def handle_register_object(request: web.Request) -> web.Response:
    """POST /api/mention-context/objects -- register a thread/session object."""

    body = await _read_json_object(request)
    kind = str(body.get("kind") or "").strip().lower()
    if kind not in _STORE_KINDS:
        raise web.HTTPBadRequest(text=f"kind must be one of: {', '.join(_STORE_KINDS)}")
    ref = str(body.get("ref") or "").strip()
    if not ref:
        raise web.HTTPBadRequest(text="ref is required")
    content = body.get("content", "")
    if not isinstance(content, str):
        raise web.HTTPBadRequest(text="content must be a string")
    if len(content) > _MAX_CONTENT_CHARS:
        raise web.HTTPBadRequest(text=f"content must be at most {_MAX_CONTENT_CHARS} characters")

    state = _state_for(request)
    store = state.store_for(kind)
    if ref not in store and len(store) >= _MAX_STORE_OBJECTS:
        raise web.HTTPBadRequest(text=f"too many registered {kind} objects (max {_MAX_STORE_OBJECTS})")
    store[ref] = content

    key = f"{kind}:{ref}"
    relations = _parse_relations(body.get("relations"))
    if relations:
        state.relations[key] = relations
    else:
        state.relations.pop(key, None)

    return web.json_response(
        {
            "ok": True,
            "object": {"kind": kind, "ref": ref, "key": key, "chars": len(content)},
            "relations": len(relations),
            "store": state.snapshot(),
        },
        status=201,
    )


async def handle_list_objects(request: web.Request) -> web.Response:
    """GET /api/mention-context/objects -- what the resolver can currently see."""

    state = _state_for(request)
    return web.json_response({"ok": True, "store": state.snapshot()})


# --------------------------------------------------------------------------- #
# Payload / validation helpers
# --------------------------------------------------------------------------- #


def _parse_relations(raw: Any) -> list[tuple[ContextObject, float]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise web.HTTPBadRequest(text="relations must be a list")
    if len(raw) > _MAX_RELATIONS_CAP:
        raise web.HTTPBadRequest(text=f"at most {_MAX_RELATIONS_CAP} relations may be registered")
    out: list[tuple[ContextObject, float]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise web.HTTPBadRequest(text="each relation must be an object")
        kind = str(entry.get("kind") or "").strip().lower()
        if kind not in ("file", *_STORE_KINDS):
            raise web.HTTPBadRequest(text="relation kind must be file, thread or session")
        ref = str(entry.get("ref") or "").strip()
        if not ref:
            raise web.HTTPBadRequest(text="relation ref is required")
        content = entry.get("content", "")
        if not isinstance(content, str):
            raise web.HTTPBadRequest(text="relation content must be a string")
        if len(content) > _MAX_CONTENT_CHARS:
            raise web.HTTPBadRequest(text="relation content is too large")
        relevance = _require_float(entry.get("relevance", 0.5), "relation relevance")
        summary = content.strip().splitlines()[0] if content.strip() else ""
        out.append(
            (
                ContextObject(kind=kind, ref=ref, content=content, summary=summary[:200]),
                relevance,
            )
        )
    return out


def _scrub_error(error: str | None, root: Path) -> str | None:
    """Keep the reason but not the server's absolute paths.

    ``str(OSError)`` renders the filename through ``repr``, so on Windows the
    root shows up backslash-escaped -- both spellings are scrubbed.
    """

    if not error:
        return error
    text = str(error)
    root_text = str(root)
    for needle in (root_text.replace("\\", "\\\\"), root_text):
        if needle:
            text = text.replace(needle, "<root>")
    return text


def _bundle_payload(
    bundle: ContextBundle,
    mentions: list[Mention],
    max_relations: int,
    root: Path,
) -> dict[str, Any]:
    included = [
        {
            "kind": entry.obj.kind,
            "ref": entry.obj.ref,
            "key": entry.obj.key,
            "relation": entry.relation,
            "relevance": entry.relevance,
            "tokens": entry.tokens,
            "anchor": entry.anchor,
            "summary": entry.obj.summary,
            "preview": entry.obj.content[:_PREVIEW_CHARS],
        }
        for entry in bundle.included
    ]
    dropped = [
        {
            "kind": entry.kind,
            "ref": entry.ref,
            "key": f"{entry.kind}:{entry.ref}",
            "reason": entry.reason,
            "tokens": entry.tokens,
            "relevance": entry.relevance,
            "error": _scrub_error(entry.error, root),
            "anchor": entry.anchor,
        }
        for entry in bundle.dropped
    ]
    reasons = {
        reason: sum(1 for d in dropped if d["reason"] == reason) for reason in ("unresolvable", "budget", "duplicate")
    }
    return {
        "ok": True,
        "budget": bundle.budget,
        "total_tokens": bundle.total_tokens,
        "remaining_tokens": max(0, bundle.budget - bundle.total_tokens),
        "within_budget": bundle.total_tokens <= bundle.budget,
        "max_relations": max_relations,
        "mentions": [{"kind": m.kind, "ref": m.ref, "raw": m.raw} for m in mentions],
        "included": included,
        "dropped": dropped,
        "counts": {
            "mentions": len(mentions),
            "included": len(included),
            "dropped": len(dropped),
            "dropped_by_reason": reasons,
        },
    }


def _require_int(value: Any, name: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise web.HTTPBadRequest(text=f"{name} must be an integer")
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise web.HTTPBadRequest(text=f"{name} must be an integer") from exc
    if parsed < minimum or parsed > maximum:
        raise web.HTTPBadRequest(text=f"{name} must be between {minimum} and {maximum}")
    return parsed


def _require_float(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise web.HTTPBadRequest(text=f"{name} must be a number")
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise web.HTTPBadRequest(text=f"{name} must be a number") from exc
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        raise web.HTTPBadRequest(text=f"{name} must be a finite number")
    return parsed


async def _read_json_object(request: web.Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except (ValueError, UnicodeError) as exc:
        _log.debug("mention-context: invalid json body: %s", type(exc).__name__)
        raise web.HTTPBadRequest(text="invalid json body") from exc
    if not isinstance(payload, dict):
        raise web.HTTPBadRequest(text="json body must be an object")
    return payload


def _deep_get(obj: Any, keys: list[str]) -> Any:
    cur = obj
    for key in keys:
        if cur is None:
            return None
        cur = cur.get(key) if isinstance(cur, dict) else getattr(cur, key, None)
    return cur
