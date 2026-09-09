"""In-flow PR review model (CAP-149, Level 2).

The service CORE behind an in-flow PR review surface. This module owns the
data model and mechanics the review UI consumes; it renders nothing and reaches
no network. Everything is deterministic and stdlib-only so the exact
acceptance-line behavior is provable offline.

Capabilities
------------
1. **Ingest + split**: parse a unified PR diff into per-file :class:`Hunk` s.
2. **Risk-rank**: score every hunk deterministically from concrete signals --
   lines changed, whether it touches tests, whether it touches a
   security/critical-path marker, and its deletion ratio -- then order hunks
   highest-risk-first with a stable, deterministic tie-break.
3. **Threaded comments**: add root comments on a hunk, reply to a comment
   (threading), and resolve a whole thread.
4. **Approval gate**: a PR cannot be approved while any *unresolved blocking*
   comment remains on a *high-risk* hunk; once resolved, approval is permitted.
5. **Fix handoff**: turn an unresolved comment into a structured fix task
   (file / hunk / instruction + risk context) that an agent can execute.

Determinism
-----------
No wall-clock and no RNG. IDs are assigned from monotonic counters and every
event carries a sequence number from an injectable clock (default: a private
monotonic counter). Ranking ties break on ``(file_path, parse_index)``. Running
the same diff + same operations always yields byte-identical output.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, field, replace

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class PrReviewError(RuntimeError):
    """Base error for the PR review model."""


class DiffParseError(PrReviewError):
    """Raised when a diff cannot be parsed into hunks."""


class UnknownHunkError(PrReviewError):
    """Raised when an operation names a hunk that does not exist."""


class UnknownCommentError(PrReviewError):
    """Raised when an operation names a comment that does not exist."""


class ApprovalBlockedError(PrReviewError):
    """Raised when approval is attempted while blocking comments remain."""

    def __init__(self, reasons: Sequence[str]) -> None:
        self.reasons: tuple[str, ...] = tuple(reasons)
        joined = "; ".join(self.reasons) or "unspecified blocking condition"
        super().__init__(f"Approval blocked: {joined}")


# ---------------------------------------------------------------------------
# Risk signals + scoring
# ---------------------------------------------------------------------------

# Files whose *path* marks them as tests.
_TEST_PATH_RE = re.compile(
    r"(^|/)tests?/|(^|/)test_[^/]*\.py$|_test\.py$|\.test\.[jt]sx?$|(^|/)conftest\.py$",
    re.IGNORECASE,
)

# Default security / critical-path markers. Matched case-insensitively against
# the file path and against the content of added lines.
DEFAULT_SECURITY_MARKERS: frozenset[str] = frozenset(
    {
        "auth",
        "login",
        "password",
        "passwd",
        "secret",
        "token",
        "credential",
        "api_key",
        "apikey",
        "private_key",
        "crypto",
        "encrypt",
        "decrypt",
        "security",
        "payment",
        "billing",
        "session",
        "oauth",
        "permission",
        "sudo",
        "privilege",
    }
)


@dataclass(frozen=True)
class RiskWeights:
    """Deterministic weights for the risk score. All integer-valued."""

    # Contribution per changed line, before the size cap is applied.
    per_line: int = 1
    # Maximum contribution the raw change size may make (keeps size from
    # drowning out categorical signals on huge mechanical diffs).
    size_cap: int = 40
    # Flat bonus when the hunk touches a security / critical-path marker.
    security: int = 50
    # Flat bonus when the hunk touches test code.
    tests: int = 20
    # Maximum contribution from the deletion ratio (0..deletion_max).
    deletion_max: int = 20
    # Score at/above which a hunk is "high" risk.
    high_threshold: int = 50
    # Score at/above which a hunk is "medium" risk (below high_threshold).
    medium_threshold: int = 20


@dataclass(frozen=True)
class RiskSignals:
    """The concrete, inspectable signals a risk score is computed from."""

    lines_changed: int
    added: int
    removed: int
    touches_tests: bool
    touches_security: bool
    deletion_ratio: float
    security_markers: tuple[str, ...] = ()


def _risk_band(score: int, weights: RiskWeights) -> str:
    if score >= weights.high_threshold:
        return "high"
    if score >= weights.medium_threshold:
        return "medium"
    return "low"


def compute_risk(signals: RiskSignals, weights: RiskWeights) -> int:
    """Deterministically fold ``signals`` into an integer risk score."""

    size_component = min(signals.lines_changed * weights.per_line, weights.size_cap)
    security_component = weights.security if signals.touches_security else 0
    test_component = weights.tests if signals.touches_tests else 0
    deletion_component = int(signals.deletion_ratio * weights.deletion_max)
    return size_component + security_component + test_component + deletion_component


# ---------------------------------------------------------------------------
# Hunk model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Hunk:
    """One diff hunk against one file, plus its computed risk."""

    hunk_id: str
    file_path: str
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    header: str
    lines: tuple[str, ...]
    parse_index: int
    signals: RiskSignals
    risk_score: int
    risk_band: str

    @property
    def added(self) -> int:
        return self.signals.added

    @property
    def removed(self) -> int:
        return self.signals.removed

    @property
    def is_high_risk(self) -> bool:
        return self.risk_band == "high"


# ---------------------------------------------------------------------------
# Comment model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Comment:
    """A single review comment. Root comments anchor a thread on a hunk;
    replies carry a ``parent_id`` and inherit the thread's hunk."""

    comment_id: str
    hunk_id: str
    author: str
    body: str
    blocking: bool
    resolved: bool
    parent_id: str | None
    seq: int

    @property
    def is_reply(self) -> bool:
        return self.parent_id is not None


# ---------------------------------------------------------------------------
# Fix handoff model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FixTask:
    """A structured fix task handed to an agent, bound to a specific hunk."""

    task_id: str
    comment_id: str
    hunk_id: str
    file_path: str
    hunk_header: str
    instruction: str
    risk_score: int
    risk_band: str
    blocking: bool
    seq: int

    def as_dict(self) -> dict[str, object]:
        """A plain-dict view for JSON/route serialization."""

        return {
            "task_id": self.task_id,
            "comment_id": self.comment_id,
            "hunk_id": self.hunk_id,
            "file_path": self.file_path,
            "hunk_header": self.hunk_header,
            "instruction": self.instruction,
            "risk_score": self.risk_score,
            "risk_band": self.risk_band,
            "blocking": self.blocking,
            "seq": self.seq,
        }


# ---------------------------------------------------------------------------
# Diff parsing
# ---------------------------------------------------------------------------

_DIFF_GIT_RE = re.compile(r"^diff --git a/(?P<a>.+?) b/(?P<b>.+?)\s*$")
_PLUS_FILE_RE = re.compile(r"^\+\+\+ (?:b/)?(?P<path>.+?)\s*$")
_MINUS_FILE_RE = re.compile(r"^--- (?:a/)?(?P<path>.+?)\s*$")
_HUNK_HEADER_RE = re.compile(
    r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? "
    r"\+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@(?P<section>.*)$"
)


@dataclass
class _RawHunk:
    file_path: str
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    header: str
    lines: list[str] = field(default_factory=list)


def _resolve_file_path(minus: str | None, plus: str | None) -> str:
    """Pick the human-facing path for a file section, tolerating /dev/null."""

    if plus and plus != "/dev/null":
        return plus
    if minus and minus != "/dev/null":
        return minus
    return plus or minus or "<unknown>"


def _iter_raw_hunks(diff_text: str) -> Iterator[_RawHunk]:
    minus_path: str | None = None
    plus_path: str | None = None
    current: _RawHunk | None = None

    for line in diff_text.splitlines():
        git_match = _DIFF_GIT_RE.match(line)
        if git_match:
            if current is not None:
                yield current
                current = None
            # A new file section: reset both sides to the git header's b/ path.
            minus_path = git_match.group("a")
            plus_path = git_match.group("b")
            continue

        if line.startswith("--- "):
            m = _MINUS_FILE_RE.match(line)
            if m:
                if current is not None:
                    yield current
                    current = None
                minus_path = m.group("path")
            continue

        if line.startswith("+++ "):
            m = _PLUS_FILE_RE.match(line)
            if m:
                plus_path = m.group("path")
            continue

        hunk_match = _HUNK_HEADER_RE.match(line)
        if hunk_match:
            if current is not None:
                yield current
            file_path = _resolve_file_path(minus_path, plus_path)
            current = _RawHunk(
                file_path=file_path,
                old_start=int(hunk_match.group("old_start")),
                old_count=int(hunk_match.group("old_count") or "1"),
                new_start=int(hunk_match.group("new_start")),
                new_count=int(hunk_match.group("new_count") or "1"),
                header=line,
            )
            continue

        if current is not None:
            # Body of a hunk: context (" "), addition ("+"), deletion ("-"),
            # or the "\ No newline at end of file" marker.
            if line.startswith(("+", "-", " ")) or line.startswith("\\"):
                current.lines.append(line)
            else:
                # A non-diff line ends the current hunk (e.g. trailing prose).
                yield current
                current = None

    if current is not None:
        yield current


def _signals_for(raw: _RawHunk, security_markers: frozenset[str]) -> RiskSignals:
    added = 0
    removed = 0
    added_blob_parts: list[str] = []
    for line in raw.lines:
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
            added_blob_parts.append(line[1:])
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    lines_changed = added + removed
    deletion_ratio = (removed / lines_changed) if lines_changed else 0.0

    touches_tests = bool(_TEST_PATH_RE.search(raw.file_path))

    haystack = (raw.file_path + "\n" + "\n".join(added_blob_parts)).lower()
    hit_markers = tuple(sorted(m for m in security_markers if m in haystack))
    touches_security = bool(hit_markers)

    return RiskSignals(
        lines_changed=lines_changed,
        added=added,
        removed=removed,
        touches_tests=touches_tests,
        touches_security=touches_security,
        deletion_ratio=deletion_ratio,
        security_markers=hit_markers,
    )


# ---------------------------------------------------------------------------
# The review model
# ---------------------------------------------------------------------------


def _default_clock() -> Callable[[], int]:
    """A private monotonic sequence source (deterministic, no wall clock)."""

    state = {"n": 0}

    def _tick() -> int:
        state["n"] += 1
        return state["n"]

    return _tick


@dataclass
class PrReview:
    """In-flow PR review state machine for a single PR diff.

    Parameters
    ----------
    diff_text:
        The unified PR diff to ingest.
    security_markers:
        Case-insensitive markers that flag a hunk as security/critical-path.
        Defaults to :data:`DEFAULT_SECURITY_MARKERS`.
    weights:
        Risk-score weights. Defaults to :class:`RiskWeights`.
    clock:
        Injectable monotonic sequence source used to stamp events. Defaults to
        a private per-review counter so runs are deterministic and hermetic.
    """

    diff_text: str
    security_markers: frozenset[str] = field(default_factory=lambda: DEFAULT_SECURITY_MARKERS)
    weights: RiskWeights = field(default_factory=RiskWeights)
    clock: Callable[[], int] = field(default_factory=_default_clock)

    _hunks: dict[str, Hunk] = field(default_factory=dict, init=False, repr=False)
    _order: list[str] = field(default_factory=list, init=False, repr=False)
    _comments: dict[str, Comment] = field(default_factory=dict, init=False, repr=False)
    _comment_order: list[str] = field(default_factory=list, init=False, repr=False)
    _fix_tasks: dict[str, FixTask] = field(default_factory=dict, init=False, repr=False)
    _comment_seq: int = field(default=0, init=False, repr=False)
    _task_seq: int = field(default=0, init=False, repr=False)
    _approved_by: str | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self.security_markers = frozenset(m.lower() for m in self.security_markers)
        self._ingest()

    # -- ingest + rank -----------------------------------------------------

    def _ingest(self) -> None:
        raws = list(_iter_raw_hunks(self.diff_text))
        if not raws:
            raise DiffParseError("no hunks found in diff (expected at least one @@ header)")

        scored: list[Hunk] = []
        for index, raw in enumerate(raws):
            signals = _signals_for(raw, self.security_markers)
            score = compute_risk(signals, self.weights)
            band = _risk_band(score, self.weights)
            hunk_id = f"h{index + 1}"
            scored.append(
                Hunk(
                    hunk_id=hunk_id,
                    file_path=raw.file_path,
                    old_start=raw.old_start,
                    old_count=raw.old_count,
                    new_start=raw.new_start,
                    new_count=raw.new_count,
                    header=raw.header,
                    lines=tuple(raw.lines),
                    parse_index=index,
                    signals=signals,
                    risk_score=score,
                    risk_band=band,
                )
            )

        # Highest risk first; deterministic tie-break on (file_path, parse_index).
        ranked = sorted(
            scored,
            key=lambda h: (-h.risk_score, h.file_path, h.parse_index),
        )
        for hunk in scored:
            self._hunks[hunk.hunk_id] = hunk
        self._order = [h.hunk_id for h in ranked]

    @property
    def ranked_hunks(self) -> tuple[Hunk, ...]:
        """All hunks ordered highest-risk-first (deterministic)."""

        return tuple(self._hunks[hid] for hid in self._order)

    def hunk(self, hunk_id: str) -> Hunk:
        try:
            return self._hunks[hunk_id]
        except KeyError as exc:
            raise UnknownHunkError(f"no such hunk: {hunk_id!r}") from exc

    # -- comments ----------------------------------------------------------

    def add_comment(
        self,
        hunk_id: str,
        author: str,
        body: str,
        *,
        blocking: bool = False,
    ) -> Comment:
        """Add a root comment anchored to ``hunk_id``."""

        hunk = self.hunk(hunk_id)  # validates existence
        self._comment_seq += 1
        comment = Comment(
            comment_id=f"c{self._comment_seq}",
            hunk_id=hunk.hunk_id,
            author=author,
            body=body,
            blocking=blocking,
            resolved=False,
            parent_id=None,
            seq=self.clock(),
        )
        self._comments[comment.comment_id] = comment
        self._comment_order.append(comment.comment_id)
        return comment

    def reply(
        self,
        parent_comment_id: str,
        author: str,
        body: str,
        *,
        blocking: bool = False,
    ) -> Comment:
        """Reply to an existing comment; the reply joins the parent's thread."""

        parent = self.comment(parent_comment_id)
        self._comment_seq += 1
        reply = Comment(
            comment_id=f"c{self._comment_seq}",
            hunk_id=parent.hunk_id,
            author=author,
            body=body,
            blocking=blocking,
            resolved=False,
            parent_id=parent.comment_id,
            seq=self.clock(),
        )
        self._comments[reply.comment_id] = reply
        self._comment_order.append(reply.comment_id)
        return reply

    def comment(self, comment_id: str) -> Comment:
        try:
            return self._comments[comment_id]
        except KeyError as exc:
            raise UnknownCommentError(f"no such comment: {comment_id!r}") from exc

    def _thread_root(self, comment_id: str) -> str:
        seen: set[str] = set()
        current = self.comment(comment_id)
        while current.parent_id is not None and current.parent_id not in seen:
            seen.add(current.comment_id)
            current = self.comment(current.parent_id)
        return current.comment_id

    def resolve_comment(self, comment_id: str) -> tuple[Comment, ...]:
        """Resolve a comment's entire thread (root + all replies).

        Returns the resolved comments. Resolving is idempotent.
        """

        root_id = self._thread_root(comment_id)
        resolved: list[Comment] = []
        for cid in self._comment_order:
            existing = self._comments[cid]
            if existing.comment_id == root_id or existing.parent_id == root_id:
                if not existing.resolved:
                    updated = replace(existing, resolved=True)
                    self._comments[cid] = updated
                    resolved.append(updated)
                else:
                    resolved.append(existing)
        return tuple(resolved)

    def thread(self, comment_id: str) -> tuple[Comment, ...]:
        """The full thread (root then replies in insertion order) for a comment."""

        root_id = self._thread_root(comment_id)
        out = [self._comments[root_id]]
        out.extend(self._comments[cid] for cid in self._comment_order if self._comments[cid].parent_id == root_id)
        return tuple(out)

    def comments_for(self, hunk_id: str) -> tuple[Comment, ...]:
        self.hunk(hunk_id)  # validate
        return tuple(self._comments[cid] for cid in self._comment_order if self._comments[cid].hunk_id == hunk_id)

    def _iter_comments(self) -> Iterable[Comment]:
        return (self._comments[cid] for cid in self._comment_order)

    # -- approval gate -----------------------------------------------------

    def blocking_reasons(self) -> tuple[str, ...]:
        """Reasons approval is currently blocked (empty means approvable).

        Approval is blocked while any *unresolved blocking* comment sits on a
        *high-risk* hunk.
        """

        reasons: list[str] = []
        for comment in self._iter_comments():
            if comment.resolved or not comment.blocking:
                continue
            hunk = self._hunks.get(comment.hunk_id)
            if hunk is not None and hunk.is_high_risk:
                reasons.append(
                    f"unresolved blocking comment {comment.comment_id} on high-risk "
                    f"hunk {hunk.hunk_id} ({hunk.file_path})"
                )
        return tuple(reasons)

    def can_approve(self) -> bool:
        return not self.blocking_reasons()

    @property
    def approved(self) -> bool:
        return self._approved_by is not None

    @property
    def approved_by(self) -> str | None:
        return self._approved_by

    def approve(self, approver: str) -> None:
        """Approve the PR, or raise :class:`ApprovalBlockedError` if gated."""

        reasons = self.blocking_reasons()
        if reasons:
            raise ApprovalBlockedError(reasons)
        self._approved_by = approver

    # -- fix handoff -------------------------------------------------------

    def create_fix_task(self, comment_id: str, *, instruction: str | None = None) -> FixTask:
        """Turn an unresolved comment into a structured fix task bound to its hunk.

        The task carries the file, hunk header, the instruction (the comment
        body unless overridden), and the hunk's risk context.
        """

        comment = self.comment(comment_id)
        if comment.resolved:
            raise PrReviewError(f"cannot hand off resolved comment {comment_id!r}; nothing to fix")
        hunk = self.hunk(comment.hunk_id)
        self._task_seq += 1
        task = FixTask(
            task_id=f"fix{self._task_seq}",
            comment_id=comment.comment_id,
            hunk_id=hunk.hunk_id,
            file_path=hunk.file_path,
            hunk_header=hunk.header,
            instruction=(instruction if instruction is not None else comment.body),
            risk_score=hunk.risk_score,
            risk_band=hunk.risk_band,
            blocking=comment.blocking,
            seq=self.clock(),
        )
        self._fix_tasks[task.task_id] = task
        return task

    @property
    def fix_tasks(self) -> tuple[FixTask, ...]:
        return tuple(self._fix_tasks.values())

    # -- serialization seam for the UI/route layer -------------------------

    def snapshot(self) -> dict[str, object]:
        """A plain-dict view of the whole review for the (peer-owned) UI layer."""

        return {
            "approved": self.approved,
            "approved_by": self.approved_by,
            "can_approve": self.can_approve(),
            "blocking_reasons": list(self.blocking_reasons()),
            "hunks": [
                {
                    "hunk_id": h.hunk_id,
                    "file_path": h.file_path,
                    "header": h.header,
                    "risk_score": h.risk_score,
                    "risk_band": h.risk_band,
                    "added": h.added,
                    "removed": h.removed,
                    "touches_tests": h.signals.touches_tests,
                    "touches_security": h.signals.touches_security,
                    "security_markers": list(h.signals.security_markers),
                }
                for h in self.ranked_hunks
            ],
            "comments": [
                {
                    "comment_id": c.comment_id,
                    "hunk_id": c.hunk_id,
                    "author": c.author,
                    "body": c.body,
                    "blocking": c.blocking,
                    "resolved": c.resolved,
                    "parent_id": c.parent_id,
                }
                for c in self._iter_comments()
            ],
            "fix_tasks": [t.as_dict() for t in self.fix_tasks],
        }
