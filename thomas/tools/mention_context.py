"""At-mention context objects: resolver + budgeted relation retrieval core.

This is the backend CORE behind the chat ``@``-mention UI. It parses typed
at-mentions out of an utterance -- ``@file:<path>``, ``@thread:<id>``,
``@session:<id>`` -- resolves each into a typed :class:`ContextObject` through
an INJECTABLE resolver, then performs BUDGETED RELATION RETRIEVAL: given the
mentioned objects and a token budget it greedily pulls related context (a
file's neighbours, a thread's parent/replies, ...) in relevance order, filling
up to the budget and STOPPING at it -- never exceeding it -- and returns an
assembled :class:`ContextBundle` recording exactly what was included and what
was dropped (and why).

Design seams (all injectable so the module is hermetic and deterministic):

* ``MentionResolver`` -- turns a :class:`Mention` into a :class:`ContextObject`.
  The real default (:class:`DefaultMentionResolver`) reads a file off disk for
  ``@file`` and looks a thread/session up through caller-supplied maps; tests
  pass a hermetic fake.
* ``RelationProvider`` -- yields :class:`RelationCandidate` neighbours for a
  resolved object, each carrying a relevance score.
* ``TokenCounter`` -- estimates the token cost of text; the default counts
  whitespace-separated words so results are deterministic and dependency-free.

The ``@``-mention chat UI (under ``thomas/server/web``) is the peer-owned
remainder that consumes this core for a full end-to-end surface.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

__all__ = [
    "ContextBundle",
    "ContextObject",
    "DefaultMentionResolver",
    "DroppedEntry",
    "IncludedEntry",
    "Mention",
    "MentionResolver",
    "RelationCandidate",
    "RelationProvider",
    "TokenCounter",
    "assemble_context_bundle",
    "default_token_counter",
    "parse_mentions",
]

# ``@file:<ref>`` / ``@thread:<ref>`` / ``@session:<ref>``. The ref runs up to
# the next whitespace; a trailing run of sentence punctuation is trimmed so
# "see @thread:42." resolves thread "42", not "42.".
_MENTION_RE = re.compile(
    r"@(?P<kind>file|thread|session):(?P<ref>\S+)",
    re.IGNORECASE,
)
_TRAILING_PUNCT = ".,;:!?)]}\"'"


def default_token_counter(text: str) -> int:
    """Deterministic, dependency-free token estimate: whitespace word count."""

    return len(text.split())


@runtime_checkable
class TokenCounter(Protocol):
    def __call__(self, text: str) -> int: ...  # pragma: no cover - protocol


@dataclass(frozen=True)
class Mention:
    """A parsed at-mention token, before resolution."""

    kind: str
    ref: str
    raw: str


@dataclass(frozen=True)
class ContextObject:
    """A resolved (or failed) typed context object for one mention.

    ``resolved`` is False when the resolver could not produce content; ``error``
    then carries a human-readable reason. Such objects are REPORTED in the
    bundle's dropped list -- never silently discarded.
    """

    kind: str
    ref: str
    content: str = ""
    summary: str = ""
    resolved: bool = True
    error: str | None = None

    @property
    def key(self) -> str:
        """Stable identity used for de-duplication and ordering tiebreaks."""

        return f"{self.kind}:{self.ref}"


@dataclass(frozen=True)
class RelationCandidate:
    """A related object plus how relevant it is to its anchor (higher = more)."""

    obj: ContextObject
    relevance: float


@runtime_checkable
class MentionResolver(Protocol):
    def resolve(self, mention: Mention) -> ContextObject: ...  # pragma: no cover


@runtime_checkable
class RelationProvider(Protocol):
    def related(self, obj: ContextObject) -> Iterable[RelationCandidate]: ...  # pragma: no cover


@dataclass(frozen=True)
class IncludedEntry:
    """An object that made it into the bundle."""

    obj: ContextObject
    relation: str  # "mention" (an anchor) or "related"
    relevance: float
    tokens: int
    anchor: str | None = None  # key of the anchor this was retrieved for


@dataclass(frozen=True)
class DroppedEntry:
    """An object left out of the bundle, with the reason it was dropped."""

    kind: str
    ref: str
    reason: str  # "unresolvable" | "budget" | "duplicate"
    tokens: int = 0
    relevance: float = 0.0
    error: str | None = None
    anchor: str | None = None


@dataclass(frozen=True)
class ContextBundle:
    """Assembled result: what was included, what was dropped, and the accounting."""

    included: tuple[IncludedEntry, ...] = ()
    dropped: tuple[DroppedEntry, ...] = ()
    budget: int = 0
    total_tokens: int = 0

    def included_keys(self) -> list[str]:
        return [e.obj.key for e in self.included]

    def dropped_keys(self) -> list[str]:
        return [f"{e.kind}:{e.ref}" for e in self.dropped]


def parse_mentions(utterance: str) -> list[Mention]:
    """Parse typed at-mentions from ``utterance`` in first-seen order.

    Duplicates (same kind + ref) are collapsed to their first occurrence so the
    downstream resolver is not asked to resolve the same object twice.
    """

    seen: set[str] = set()
    out: list[Mention] = []
    for m in _MENTION_RE.finditer(utterance):
        kind = m.group("kind").lower()
        ref = m.group("ref").rstrip(_TRAILING_PUNCT)
        if not ref:
            continue
        key = f"{kind}:{ref}"
        if key in seen:
            continue
        seen.add(key)
        out.append(Mention(kind=kind, ref=ref, raw=m.group(0)))
    return out


class DefaultMentionResolver:
    """Real default resolver: files off disk, threads/sessions via lookup maps.

    ``@file`` reads the referenced path (relative paths are resolved under
    ``root``). ``@thread`` / ``@session`` are looked up through caller-supplied
    mappings or callables -- there is no ambient thread store at this tier, so
    the store is injected. A missing/unreadable target yields an *unresolved*
    :class:`ContextObject` carrying the reason (it is reported, never dropped
    silently).
    """

    def __init__(
        self,
        root: str | Path = ".",
        *,
        thread_lookup: Mapping[str, str] | Callable[[str], str | None] | None = None,
        session_lookup: Mapping[str, str] | Callable[[str], str | None] | None = None,
        max_bytes: int = 200_000,
    ) -> None:
        self._root = Path(root)
        self._thread_lookup = thread_lookup
        self._session_lookup = session_lookup
        self._max_bytes = max_bytes

    def resolve(self, mention: Mention) -> ContextObject:
        if mention.kind == "file":
            return self._resolve_file(mention.ref)
        if mention.kind == "thread":
            return self._resolve_lookup(mention.kind, mention.ref, self._thread_lookup)
        if mention.kind == "session":
            return self._resolve_lookup(mention.kind, mention.ref, self._session_lookup)
        return _unresolved(mention.kind, mention.ref, "unknown mention kind")

    def _resolve_file(self, ref: str) -> ContextObject:
        path = Path(ref)
        if not path.is_absolute():
            path = self._root / path
        try:
            data = path.read_bytes()[: self._max_bytes]
            text = data.decode("utf-8", errors="replace")
        except (OSError, ValueError) as exc:
            return _unresolved("file", ref, f"cannot read file: {exc}")
        summary = text.strip().splitlines()[0] if text.strip() else ""
        return ContextObject(kind="file", ref=ref, content=text, summary=summary[:200])

    def _resolve_lookup(
        self,
        kind: str,
        ref: str,
        lookup: Mapping[str, str] | Callable[[str], str | None] | None,
    ) -> ContextObject:
        if lookup is None:
            return _unresolved(kind, ref, f"no {kind} store configured")
        content: str | None
        if callable(lookup):
            content = lookup(ref)
        else:
            content = lookup.get(ref)
        if content is None:
            return _unresolved(kind, ref, f"{kind} not found")
        summary = content.strip().splitlines()[0] if content.strip() else ""
        return ContextObject(kind=kind, ref=ref, content=content, summary=summary[:200])


def _unresolved(kind: str, ref: str, reason: str) -> ContextObject:
    return ContextObject(kind=kind, ref=ref, content="", resolved=False, error=reason)


def _obj_tokens(obj: ContextObject, counter: TokenCounter) -> int:
    return counter(obj.content or obj.summary)


@dataclass
class _Candidate:
    """Internal working candidate before budget adjudication."""

    obj: ContextObject
    relation: str
    relevance: float
    tokens: int
    order: int
    anchor: str | None = None


def assemble_context_bundle(
    utterance: str,
    resolver: MentionResolver,
    *,
    budget: int,
    relation_provider: RelationProvider | None = None,
    token_counter: TokenCounter = default_token_counter,
    mentions: Sequence[Mention] | None = None,
) -> ContextBundle:
    """Resolve mentions in ``utterance`` and budget-fill related context.

    Anchors (the mentioned objects themselves) have top priority, in mention
    order; related objects then compete in descending relevance (ties broken by
    stable key). The assembler walks that fixed ordering and greedily includes
    each candidate whose tokens still fit, STOPPING at the first that would
    exceed ``budget`` -- that candidate and every later one are recorded as
    dropped for budget. The returned bundle's ``total_tokens`` is always
    ``<= budget``.

    Fully deterministic: identical inputs yield an identical bundle.
    """

    if budget < 0:
        raise ValueError("budget must be non-negative")

    parsed = list(mentions) if mentions is not None else parse_mentions(utterance)

    included: list[IncludedEntry] = []
    dropped: list[DroppedEntry] = []

    anchors: list[_Candidate] = []
    order = 0
    resolved_anchor_objs: list[ContextObject] = []
    for mention in parsed:
        obj = resolver.resolve(mention)
        if not obj.resolved:
            # Reported explicitly -- never silently dropped.
            dropped.append(
                DroppedEntry(
                    kind=obj.kind,
                    ref=obj.ref,
                    reason="unresolvable",
                    error=obj.error,
                )
            )
            continue
        anchors.append(
            _Candidate(
                obj=obj,
                relation="mention",
                relevance=float("inf"),
                tokens=_obj_tokens(obj, token_counter),
                order=order,
            )
        )
        resolved_anchor_objs.append(obj)
        order += 1

    # Gather related candidates from every resolved anchor.
    related: list[_Candidate] = []
    if relation_provider is not None:
        for anchor in anchors:
            for cand in relation_provider.related(anchor.obj):
                related.append(
                    _Candidate(
                        obj=cand.obj,
                        relation="related",
                        relevance=float(cand.relevance),
                        tokens=_obj_tokens(cand.obj, token_counter),
                        order=order,
                        anchor=anchor.obj.key,
                    )
                )
                order += 1

    # Related objects compete by descending relevance; ties broken by stable
    # key then discovery order for full determinism.
    related.sort(key=lambda c: (-c.relevance, c.obj.key, c.order))

    # Fixed priority ordering: anchors (mention order) then ranked related.
    ordering: list[_Candidate] = anchors + related

    seen_keys: set[str] = set()
    total = 0
    budget_exhausted = False
    for cand in ordering:
        if cand.obj.key in seen_keys:
            dropped.append(
                DroppedEntry(
                    kind=cand.obj.kind,
                    ref=cand.obj.ref,
                    reason="duplicate",
                    tokens=cand.tokens,
                    relevance=_finite(cand.relevance),
                    anchor=cand.anchor,
                )
            )
            continue
        if budget_exhausted or total + cand.tokens > budget:
            # Stop filling: this candidate and all later ones are budget drops.
            budget_exhausted = True
            dropped.append(
                DroppedEntry(
                    kind=cand.obj.kind,
                    ref=cand.obj.ref,
                    reason="budget",
                    tokens=cand.tokens,
                    relevance=_finite(cand.relevance),
                    anchor=cand.anchor,
                )
            )
            continue
        total += cand.tokens
        seen_keys.add(cand.obj.key)
        included.append(
            IncludedEntry(
                obj=cand.obj,
                relation=cand.relation,
                relevance=_finite(cand.relevance),
                tokens=cand.tokens,
                anchor=cand.anchor,
            )
        )

    return ContextBundle(
        included=tuple(included),
        dropped=tuple(dropped),
        budget=budget,
        total_tokens=total,
    )


def _finite(value: float) -> float:
    """Anchors carry +inf priority internally; expose 0.0 externally for them."""

    return value if value != float("inf") else 0.0
