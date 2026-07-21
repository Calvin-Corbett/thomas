"""Durable-constraint retention across mid-session context compaction.

The problem this module solves
------------------------------
``thomas/agent/context_compaction.py`` shrinks a long conversation so it fits a
token budget by summarising or dropping older turns. That is exactly what you
want for chatty history -- but it means a *rule the user stated early* ("never
delete the prod table", "always use tabs") can be summarised away or dropped
before the agent takes its final action. The early constraint then no longer
governs the last step, which is a correctness/safety regression.

``ConstraintRetentionGovernor`` closes that gap. It is deterministic and
model-free: constraint extraction is rule/marker based on turn text, so the same
history always yields the same pinned set, and no LLM call is required.

Three responsibilities
-----------------------
1. :meth:`extract_constraints` -- scan turns for durable constraints using a
   documented marker grammar and PIN them into a protected set.
2. :meth:`compact` -- condense/drop old turns to fit a budget, but keep the
   pinned constraint turns **verbatim** and keep the most recent ``keep_recent``
   turns intact. Pinned constraints survive even a heavy 200-turn compaction and
   are never dropped to satisfy the budget.
3. :meth:`governs_final_action` -- given the still-pinned constraints and a
   proposed final action, return a :class:`ConstraintDecision` that flags when
   the action would violate an early constraint, so the early rule governs the
   last step.

Extraction grammar (the documented rule)
----------------------------------------
Each *line* of a governing turn (default roles: ``user`` and ``system``) is
matched, case-insensitively, against constraint markers:

* PROHIBIT markers -> ``never``, ``do not``, ``don't``, ``dont``, ``must not``,
  ``mustn't``, ``must never``, ``may not``, ``cannot``, ``can't``, ``shall not``.
* REQUIRE markers -> ``always``, ``must`` (only when it is not part of a
  ``must not`` phrase), ``ensure``, ``make sure``.

PROHIBIT markers are tested first so ``must not`` is never mis-read as a REQUIRE
``must``. The text following the marker is the constraint *subject*. The full
original line is retained verbatim as the pinned text.

Violation detection is token-based with a small, documented synonym and
mutual-exclusion vocabulary (e.g. ``drop``/``remove``/``truncate`` all canonical
to ``delete``; ``production`` -> ``prod``; ``tabs`` vs ``spaces`` are mutually
exclusive). See :data:`_SYNONYMS`, :data:`_STOPWORDS`, and
:data:`_EXCLUSIVE_GROUPS`.

This module depends only on the standard library and does not import any other
``thomas`` package, so it is safe to use from anywhere in the agent tier.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# Marker inserted for the condensed middle-region turn. Turns carrying this
# marker are treated as already-compacted and are never re-scanned for
# constraints (idempotency guard, mirrors context_compaction's approach).
RETENTION_SUMMARY_MARKER = "[constraint-retention-summary]"

# Rough token estimate: 1 token ~ 4 characters (same heuristic as
# context_compaction.estimate_tokens, replicated locally to avoid importing an
# over-cap module).
_CHARS_PER_TOKEN = 4

# Polarity constants.
PROHIBIT = "prohibit"
REQUIRE = "require"

# Prohibit markers, longest/most-specific first so "must not" wins over "must".
_PROHIBIT_MARKERS: tuple[str, ...] = (
    "must never",
    "must not",
    "mustn't",
    "shall not",
    "may not",
    "cannot",
    "can't",
    "do not",
    "don't",
    "dont",
    "never",
)

# Require markers, longest first.
_REQUIRE_MARKERS: tuple[str, ...] = (
    "make sure",
    "ensure that",
    "ensure",
    "always",
    "must",
)

# Words dropped before token comparison. Kept deliberately small so that
# meaningful verbs/nouns (delete, prod, table, tabs, use) are preserved.
_STOPWORDS: frozenset[str] = frozenset(
    {
        "the",
        "a",
        "an",
        "to",
        "of",
        "on",
        "in",
        "at",
        "for",
        "this",
        "that",
        "these",
        "those",
        "please",
        "ever",
        "will",
        "would",
        "should",
        "shall",
        "does",
        "did",
        "our",
        "your",
        "my",
        "is",
        "are",
        "be",
        "it",
        "and",
        "or",
        "any",
        "all",
        "now",
        "today",
        "just",
    }
)

# Synonym canonicalisation: every listed surface form maps to the group key so
# that "drop"/"remove"/"truncate" all compare equal to "delete", and
# "production" compares equal to "prod".
_SYNONYM_GROUPS: dict[str, tuple[str, ...]] = {
    "delete": (
        "delete",
        "deletes",
        "deleted",
        "deleting",
        "drop",
        "drops",
        "dropped",
        "dropping",
        "remove",
        "removes",
        "removed",
        "removing",
        "truncate",
        "truncated",
        "destroy",
        "destroyed",
        "wipe",
        "wiped",
        "erase",
        "erased",
        "purge",
        "purged",
    ),
    "prod": ("prod", "production"),
    "table": ("table", "tables"),
    "database": ("database", "databases", "db", "dbs"),
    "file": ("file", "files"),
}
_SYNONYMS: dict[str, str] = {surface: canonical for canonical, forms in _SYNONYM_GROUPS.items() for surface in forms}

# Negation tokens used when deciding whether an action contradicts a REQUIRE
# constraint (e.g. "use spaces not tabs" negates "always use tabs").
_NEGATIONS: frozenset[str] = frozenset({"no", "not", "without", "never", "dont", "cannot", "cant"})

# Mutually exclusive choices: satisfying one member violates a requirement to
# use another member of the same group.
_EXCLUSIVE_GROUPS: tuple[frozenset[str], ...] = (frozenset({"tabs", "spaces"}),)

_WORD_RE = re.compile(r"[a-z0-9']+")


@dataclass(frozen=True)
class PinnedConstraint:
    """A durable constraint extracted from a turn and exempt from compaction.

    Attributes:
        text: The verbatim line the constraint came from (retained as-is).
        polarity: ``PROHIBIT`` or ``REQUIRE``.
        subject: Normalised phrase following the marker (used for matching).
        marker: The marker that triggered extraction.
        source_turn: Index of the originating turn in the input history.
    """

    text: str
    polarity: str
    subject: str
    marker: str
    source_turn: int


@dataclass
class ConstraintDecision:
    """Outcome of checking a proposed final action against pinned constraints."""

    action: str
    allowed: bool
    violations: list[PinnedConstraint] = field(default_factory=list)
    reason: str = ""

    @property
    def violated(self) -> bool:
        """True when the action would violate at least one pinned constraint."""
        return not self.allowed


@dataclass
class RetentionResult:
    """Result of a :meth:`ConstraintRetentionGovernor.compact` call."""

    messages: list[dict[str, Any]]
    pinned: list[PinnedConstraint]
    original_count: int
    condensed_count: int
    retained_recent: int
    tokens: int


def _content_text(msg: dict[str, Any]) -> str:
    """Return the textual content of a message, flattening list-of-parts form."""
    content = msg.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict):
                text = part.get("text", "")
                if isinstance(text, str):
                    parts.append(text)
            elif isinstance(part, str):
                parts.append(part)
        return "\n".join(parts)
    return str(content)


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // _CHARS_PER_TOKEN)


def _estimate_messages_tokens(messages: list[dict[str, Any]]) -> int:
    return sum(_estimate_tokens(_content_text(m)) + 4 for m in messages)


def _canonical_tokens(text: str) -> list[str]:
    """Lowercase, tokenise, drop stopwords, and canonicalise synonyms.

    Ordering is preserved and duplicates are kept so that membership tests are
    stable and deterministic.
    """
    tokens: list[str] = []
    for raw in _WORD_RE.findall(text.lower()):
        word = raw.strip("'")
        if not word or word in _STOPWORDS:
            continue
        tokens.append(_SYNONYMS.get(word, word))
    return tokens


class ConstraintRetentionGovernor:
    """Pin durable constraints and keep them governing across compaction.

    The governor is stateless between calls except for optional configuration;
    every method is a pure function of its inputs, which makes results fully
    deterministic and easy to test.
    """

    def __init__(
        self,
        *,
        governing_roles: frozenset[str] | None = None,
        extra_prohibit_markers: tuple[str, ...] = (),
        extra_require_markers: tuple[str, ...] = (),
    ) -> None:
        """Initialise the governor.

        Args:
            governing_roles: Message roles scanned for constraints. Defaults to
                ``{"user", "system"}`` -- the roles that carry authoritative
                instructions.
            extra_prohibit_markers: Additional PROHIBIT markers to recognise.
            extra_require_markers: Additional REQUIRE markers to recognise.
        """
        self._roles = governing_roles if governing_roles is not None else frozenset({"user", "system"})
        # Keep specific markers first so multi-word markers match before their
        # prefixes (e.g. "must not" before "must").
        self._prohibit_markers = tuple(extra_prohibit_markers) + _PROHIBIT_MARKERS
        self._require_markers = tuple(extra_require_markers) + _REQUIRE_MARKERS

    # -- extraction ---------------------------------------------------------

    def _constraints_in_line(self, line: str, turn_index: int) -> PinnedConstraint | None:
        """Extract a single constraint from one line, or None."""
        lowered = line.lower()
        # Prohibit is tested first so "must not" is never read as require "must".
        for marker in self._prohibit_markers:
            pos = lowered.find(marker)
            if pos != -1:
                subject = line[pos + len(marker) :].strip(" \t:,-.—")
                return PinnedConstraint(
                    text=line.strip(),
                    polarity=PROHIBIT,
                    subject=subject,
                    marker=marker,
                    source_turn=turn_index,
                )
        for marker in self._require_markers:
            pos = lowered.find(marker)
            if pos != -1:
                subject = line[pos + len(marker) :].strip(" \t:,-.—")
                return PinnedConstraint(
                    text=line.strip(),
                    polarity=REQUIRE,
                    subject=subject,
                    marker=marker,
                    source_turn=turn_index,
                )
        return None

    def _constraints_in_turn(self, msg: dict[str, Any], turn_index: int) -> list[PinnedConstraint]:
        if msg.get("role") not in self._roles:
            return []
        content = _content_text(msg)
        if RETENTION_SUMMARY_MARKER in content:
            return []
        found: list[PinnedConstraint] = []
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            constraint = self._constraints_in_line(stripped, turn_index)
            if constraint is not None and constraint.subject:
                found.append(constraint)
        return found

    def extract_constraints(self, history: list[dict[str, Any]]) -> list[PinnedConstraint]:
        """Extract and pin every durable constraint in ``history``.

        Returns constraints in stable order (turn order, then line order).
        """
        pinned: list[PinnedConstraint] = []
        for i, msg in enumerate(history):
            pinned.extend(self._constraints_in_turn(msg, i))
        return pinned

    # -- compaction ---------------------------------------------------------

    def compact(
        self,
        history: list[dict[str, Any]],
        *,
        keep_recent: int = 6,
        budget: int | None = None,
    ) -> RetentionResult:
        """Compact ``history`` while retaining pinned constraints verbatim.

        The returned message list is::

            [ pinned constraint turns (verbatim, original order) ]
            [ one condensed-summary turn for the remaining middle turns ]
            [ the most recent ``keep_recent`` turns (verbatim) ]

        Pinned constraint turns that already fall inside the recent window are
        not duplicated. Pinned constraints are **never** dropped, even if that
        means exceeding ``budget`` -- an active safety rule outranks the token
        budget. When ``budget`` is set and the assembled result still exceeds
        it, the oldest *recent* (non-pinned) turns are folded into the summary
        until the budget is met or a single recent turn remains.

        Args:
            history: Full conversation turns (not mutated).
            keep_recent: Number of most-recent turns to preserve intact.
            budget: Optional token budget the result should try to fit.

        Returns:
            A :class:`RetentionResult`.
        """
        original_count = len(history)
        keep_recent = max(0, keep_recent)
        all_pinned = self.extract_constraints(history)
        pinned_turn_indices = {c.source_turn for c in all_pinned}

        recent_start = max(0, original_count - keep_recent)
        head = list(range(recent_start))
        recent_indices = list(range(recent_start, original_count))

        pinned_head_indices = [i for i in head if i in pinned_turn_indices]
        condensed_head_indices = [i for i in head if i not in pinned_turn_indices]

        # Optionally trim the oldest recent turns into the summary to fit budget.
        # Pinned turns inside the recent window are protected from trimming.
        trimmed_from_recent: list[int] = []
        if budget is not None:
            while len(recent_indices) > 1:
                candidate = recent_indices[0]
                if candidate in pinned_turn_indices:
                    break  # never fold a pinned constraint into the summary
                messages = self._assemble(
                    history,
                    pinned_head_indices,
                    condensed_head_indices + trimmed_from_recent,
                    recent_indices,
                )
                if _estimate_messages_tokens(messages) <= budget:
                    break
                trimmed_from_recent.append(candidate)
                recent_indices = recent_indices[1:]

        condensed_indices = condensed_head_indices + trimmed_from_recent
        messages = self._assemble(history, pinned_head_indices, condensed_indices, recent_indices)

        # Pinned constraints that survive in the compacted output (those pinned
        # anywhere -- head verbatim turns plus recent verbatim turns).
        surviving = [c for c in all_pinned if c.source_turn in pinned_head_indices or c.source_turn in recent_indices]

        return RetentionResult(
            messages=messages,
            pinned=surviving,
            original_count=original_count,
            condensed_count=len(condensed_indices),
            retained_recent=len(recent_indices),
            tokens=_estimate_messages_tokens(messages),
        )

    def _assemble(
        self,
        history: list[dict[str, Any]],
        pinned_head_indices: list[int],
        condensed_indices: list[int],
        recent_indices: list[int],
    ) -> list[dict[str, Any]]:
        """Build the compacted message list from index selections."""
        messages: list[dict[str, Any]] = [history[i] for i in pinned_head_indices]
        if condensed_indices:
            messages.append(self._summary_turn(len(condensed_indices)))
        messages.extend(history[i] for i in recent_indices)
        return messages

    @staticmethod
    def _summary_turn(count: int) -> dict[str, Any]:
        return {
            "role": "system",
            "content": (
                f"{RETENTION_SUMMARY_MARKER} {count} earlier turn(s) condensed to fit the "
                "context budget. Durable constraints from this region are pinned and preserved "
                "verbatim above; the remaining conversational detail was dropped."
            ),
        }

    # -- governance ---------------------------------------------------------

    def governs_final_action(
        self,
        constraints: list[PinnedConstraint],
        proposed_action: str,
    ) -> ConstraintDecision:
        """Check whether ``proposed_action`` violates any pinned constraint.

        Returns a decision flagging every violated constraint so the early rule
        governs the final step. An empty constraint list, or an action that does
        not touch any constrained subject, is allowed.
        """
        action_tokens = _canonical_tokens(proposed_action)
        action_set = set(action_tokens)
        violations: list[PinnedConstraint] = []

        for constraint in constraints:
            subject_tokens = _canonical_tokens(constraint.subject)
            if not subject_tokens:
                continue
            subject_set = set(subject_tokens)
            if constraint.polarity == PROHIBIT:
                if subject_set and subject_set.issubset(action_set):
                    violations.append(constraint)
            else:  # REQUIRE
                if self._violates_requirement(subject_tokens, subject_set, action_set):
                    violations.append(constraint)

        if violations:
            joined = "; ".join(c.text for c in violations)
            return ConstraintDecision(
                action=proposed_action,
                allowed=False,
                violations=violations,
                reason=f"final action violates pinned constraint(s): {joined}",
            )
        return ConstraintDecision(action=proposed_action, allowed=True, reason="no pinned constraint violated")

    @staticmethod
    def _violates_requirement(
        subject_tokens: list[str],
        subject_set: set[str],
        action_set: set[str],
    ) -> bool:
        """Decide whether an action contradicts a REQUIRE constraint.

        Two documented signals count as a contradiction:

        1. Negation: the action mentions the required subject but with a
           negation token (e.g. "use spaces not tabs" vs "always use tabs").
        2. Mutual exclusion: the action selects a competing member of a
           documented exclusive group instead of the required one (e.g.
           "use spaces" vs "always use tabs").
        """
        # (1) explicit negation of the required subject.
        if subject_set.issubset(action_set) and (_NEGATIONS & action_set):
            return True
        # (2) mutually exclusive alternative chosen.
        for group in _EXCLUSIVE_GROUPS:
            required = subject_set & group
            if not required:
                continue
            competing = (action_set & group) - required
            if competing and not (required & action_set):
                return True
        return False
