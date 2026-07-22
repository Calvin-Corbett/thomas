"""Source annotations core: anchored notes that survive edits, open conversations, and emit diffs.

This is the backend CORE behind the inline-editor UI (the click-to-annotate
surface under ``thomas/server/web`` is owned by the UI/route layer and is NOT
part of this module). It provides the durable data model and the algorithms the
UI consumes:

1. **Create** a user-authored annotation *anchored* to a source region -- a file
   plus a 1-based inclusive line range -- capturing the exact text of the region
   and a small snippet of surrounding context ("anchor context"). Stored durably
   as JSON.
2. **Re-anchor** after edits: when the underlying file changes, the annotation is
   relocated by matching its captured region text (disambiguated by surrounding
   context and proximity to the original position), so an annotation survives an
   edit *above* it instead of pointing at the wrong line. If the anchored text is
   gone entirely, the annotation is marked ``orphaned`` -- never silently
   mis-pointed at unrelated code.
3. **Open a conversation**: link an annotation to a conversation/thread ref so the
   inline editor can spawn an agent thread from the note.
4. **Emit a source diff**: turn an annotation carrying a suggested edit into a
   valid unified diff that replaces the anchored region with the suggested text.

Everything is deterministic. The only external edge -- reading current file
content -- is behind an injectable ``reader`` seam (a real disk reader by default,
a hermetic dict-backed fake in tests). The clock and id factory are injectable too
so serialized output is byte-stable under test.

This module intentionally depends only on the standard library (tools-layer rule:
no imports from agent/server/cli).
"""

from __future__ import annotations

import difflib
import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

# Number of surrounding lines captured on each side of an anchored region and
# used to disambiguate re-anchoring when the region text appears more than once.
DEFAULT_CONTEXT_LINES = 3

STATUS_ANCHORED = "anchored"
STATUS_ORPHANED = "orphaned"

# Type aliases for the injectable seams.
Reader = Callable[[str], str]  # (file_path) -> full file text
Clock = Callable[[], str]  # () -> ISO-8601 timestamp string
IdFactory = Callable[[], str]  # () -> unique annotation id


# ---------------------------------------------------------------------------
# Errors -- concrete types so callers never need a broad ``except``.
# ---------------------------------------------------------------------------


class AnnotationError(Exception):
    """Base class for source-annotation failures."""


class AnnotationNotFoundError(AnnotationError):
    """Raised when an annotation id is not present in the store."""


class OrphanedAnchorError(AnnotationError):
    """Raised when an operation needs a live anchor but the region text is gone."""


class NoSuggestedEditError(AnnotationError):
    """Raised when a diff is requested from an annotation that carries no edit."""


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class SourceAnchor:
    """The captured location of an annotation within a file's text.

    Line numbers are 1-based and inclusive. ``region_lines`` is the exact text
    of the anchored lines at capture time; ``before_context`` / ``after_context``
    are the immediately surrounding lines used to disambiguate relocation.
    """

    line_start: int
    line_end: int
    region_lines: list[str]
    before_context: list[str] = field(default_factory=list)
    after_context: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> SourceAnchor:
        return cls(
            line_start=int(data["line_start"]),
            line_end=int(data["line_end"]),
            region_lines=list(data.get("region_lines", [])),
            before_context=list(data.get("before_context", [])),
            after_context=list(data.get("after_context", [])),
        )


@dataclass
class Annotation:
    """A durable, user-authored note anchored to a source region."""

    id: str
    file: str
    anchor: SourceAnchor
    body: str
    status: str = STATUS_ANCHORED
    suggested_edit: str | None = None
    conversation_ref: str | None = None
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        data = asdict(self)
        data["anchor"] = self.anchor.to_dict()
        return data

    @classmethod
    def from_dict(cls, data: dict) -> Annotation:
        return cls(
            id=str(data["id"]),
            file=str(data["file"]),
            anchor=SourceAnchor.from_dict(data["anchor"]),
            body=str(data.get("body", "")),
            status=str(data.get("status", STATUS_ANCHORED)),
            suggested_edit=data.get("suggested_edit"),
            conversation_ref=data.get("conversation_ref"),
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
        )


# ---------------------------------------------------------------------------
# Default injectable seams
# ---------------------------------------------------------------------------


def default_disk_reader(file_path: str) -> str:
    """Read a file's full text from disk as UTF-8 (the production ``reader``)."""
    return Path(file_path).read_text(encoding="utf-8")


def _default_clock() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_id_factory() -> str:
    return uuid.uuid4().hex


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------


def _split(text: str) -> list[str]:
    """Split file text into lines without terminators, reversible via ``_join``."""
    return text.split("\n")


def _join(lines: list[str]) -> str:
    return "\n".join(lines)


def _context_score(
    lines: list[str],
    start: int,
    length: int,
    before_ctx: list[str],
    after_ctx: list[str],
) -> int:
    """Count contiguous matching context lines around a candidate placement.

    ``start`` is the 0-based index where the region would begin; ``length`` is
    the number of region lines. Matching is greedy outward from the region and
    stops at the first mismatch on each side, so a candidate embedded in its
    original neighbourhood scores highest.
    """
    score = 0
    for offset, expected in enumerate(reversed(before_ctx), start=1):
        idx = start - offset
        if idx >= 0 and lines[idx] == expected:
            score += 1
        else:
            break
    for offset, expected in enumerate(after_ctx):
        idx = start + length + offset
        if idx < len(lines) and lines[idx] == expected:
            score += 1
        else:
            break
    return score


def _locate_region(current_lines: list[str], anchor: SourceAnchor) -> tuple[int, int] | None:
    """Find the anchored region in current file text.

    Returns a 1-based inclusive ``(line_start, line_end)`` for the best exact
    match of ``anchor.region_lines``, disambiguated by surrounding-context match
    count and then by proximity to the original position. Returns ``None`` when
    the region text no longer occurs anywhere (the anchor is orphaned).
    """
    needle = anchor.region_lines
    n = len(needle)
    if n == 0:
        return None
    total = len(current_lines)
    original_start0 = anchor.line_start - 1
    best: tuple[int, int, int] | None = None  # (score, -distance, start0)
    for i in range(0, total - n + 1):
        if current_lines[i : i + n] != needle:
            continue
        score = _context_score(current_lines, i, n, anchor.before_context, anchor.after_context)
        distance = abs(i - original_start0)
        candidate = (score, -distance, i)
        if best is None or candidate > best:
            best = candidate
    if best is None:
        return None
    start0 = best[2]
    return (start0 + 1, start0 + n)


# ---------------------------------------------------------------------------
# Unified diff apply -- used by callers to prove/emit round-trip edits.
# ---------------------------------------------------------------------------


def apply_unified_diff(original: str, diff: str) -> str:
    """Apply a unified diff produced by :meth:`AnnotationStore.emit_diff`.

    Deterministic hunk applier for the ``lineterm=""`` diffs this module emits.
    Context lines are copied from ``original`` (not the diff) so applying is
    faithful to the source. Raises :class:`AnnotationError` on a malformed hunk.
    """
    orig_lines = _split(original)
    diff_lines = diff.split("\n")
    result: list[str] = []
    orig_idx = 0
    k = 0
    # Skip file headers ("--- ", "+++ ") and anything before the first hunk.
    while k < len(diff_lines) and not diff_lines[k].startswith("@@"):
        k += 1
    while k < len(diff_lines):
        header = diff_lines[k]
        if not header.startswith("@@"):
            k += 1
            continue
        src_start = _parse_hunk_src_start(header)
        # Copy unchanged lines preceding this hunk.
        while orig_idx < src_start - 1:
            if orig_idx >= len(orig_lines):
                raise AnnotationError("hunk starts beyond end of source")
            result.append(orig_lines[orig_idx])
            orig_idx += 1
        k += 1
        while k < len(diff_lines) and not diff_lines[k].startswith("@@"):
            body = diff_lines[k]
            if body == "":
                # Trailing terminator artifact (diffs use lineterm=""; a genuine
                # blank context line is rendered as a single space " ").
                k += 1
                continue
            if body.startswith(" "):
                if orig_idx >= len(orig_lines):
                    raise AnnotationError("context line beyond end of source")
                result.append(orig_lines[orig_idx])
                orig_idx += 1
            elif body.startswith("-"):
                orig_idx += 1
            elif body.startswith("+"):
                result.append(body[1:])
            else:  # pragma: no cover - defensive
                raise AnnotationError(f"unrecognized diff line: {body!r}")
            k += 1
    while orig_idx < len(orig_lines):
        result.append(orig_lines[orig_idx])
        orig_idx += 1
    return _join(result)


def _parse_hunk_src_start(header: str) -> int:
    """Parse the source start line from an ``@@ -a,b +c,d @@`` hunk header."""
    try:
        minus = header.split("-", 1)[1]
        src_field = minus.split(" ", 1)[0]
        start_str = src_field.split(",", 1)[0]
        return int(start_str)
    except (IndexError, ValueError) as exc:
        raise AnnotationError(f"malformed hunk header: {header!r}") from exc


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class AnnotationStore:
    """Durable store and lifecycle for source annotations.

    Args:
        store_path: JSON file backing the store; created lazily on first save.
        reader: Injectable file-text reader. Defaults to :func:`default_disk_reader`.
            Tests inject a hermetic dict-backed reader.
        clock: Injectable timestamp source (returns an ISO string). Injected in
            tests for byte-stable serialization.
        id_factory: Injectable id generator. Injected in tests for determinism.
        context_lines: Surrounding lines captured per side for re-anchoring.
    """

    def __init__(
        self,
        store_path: str | Path,
        *,
        reader: Reader | None = None,
        clock: Clock | None = None,
        id_factory: IdFactory | None = None,
        context_lines: int = DEFAULT_CONTEXT_LINES,
    ) -> None:
        self._path = Path(store_path)
        self._reader: Reader = reader or default_disk_reader
        self._clock: Clock = clock or _default_clock
        self._id_factory: IdFactory = id_factory or _default_id_factory
        self._context_lines = max(0, int(context_lines))
        self._annotations: dict[str, Annotation] = {}
        self._load()

    # -- persistence -------------------------------------------------------

    def _load(self) -> None:
        if not self._path.exists():
            return
        raw = self._path.read_text(encoding="utf-8")
        if not raw.strip():
            return
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AnnotationError(f"corrupt annotation store at {self._path}: {exc}") from exc
        for item in data.get("annotations", []):
            ann = Annotation.from_dict(item)
            self._annotations[ann.id] = ann

    def _save(self) -> None:
        payload = {
            "version": 1,
            "annotations": [self._annotations[k].to_dict() for k in sorted(self._annotations)],
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    # -- reads -------------------------------------------------------------

    def get(self, annotation_id: str) -> Annotation:
        """Return the annotation for ``annotation_id`` or raise."""
        try:
            return self._annotations[annotation_id]
        except KeyError as exc:
            raise AnnotationNotFoundError(annotation_id) from exc

    def list_annotations(self, file: str | None = None) -> list[Annotation]:
        """Return annotations sorted by id, optionally filtered to one file."""
        items = [self._annotations[k] for k in sorted(self._annotations)]
        if file is not None:
            items = [a for a in items if a.file == file]
        return items

    # -- create ------------------------------------------------------------

    def create_annotation(
        self,
        file: str,
        line_start: int,
        line_end: int,
        body: str,
        *,
        suggested_edit: str | None = None,
        conversation_ref: str | None = None,
    ) -> Annotation:
        """Create and durably store an annotation anchored to ``file`` lines.

        The current text of ``file`` is read through the injected ``reader`` to
        capture the exact region text and surrounding context.

        Args:
            file: Path of the annotated file (as the UI/route layer refers to it).
            line_start: 1-based inclusive first line of the anchored region.
            line_end: 1-based inclusive last line of the anchored region.
            body: The user-authored note.
            suggested_edit: Optional replacement text for the region; when present
                :meth:`emit_diff` can produce a unified diff.
            conversation_ref: Optional conversation/thread ref to link immediately.

        Returns:
            The stored :class:`Annotation`.

        Raises:
            ValueError: If the line range is invalid for the file.
        """
        if line_start < 1 or line_end < line_start:
            raise ValueError(f"invalid line range: {line_start}..{line_end}")
        lines = _split(self._reader(file))
        if line_end > len(lines):
            raise ValueError(f"line_end {line_end} exceeds file length {len(lines)}")
        region = lines[line_start - 1 : line_end]
        before = lines[max(0, line_start - 1 - self._context_lines) : line_start - 1]
        after = lines[line_end : line_end + self._context_lines]
        anchor = SourceAnchor(
            line_start=line_start,
            line_end=line_end,
            region_lines=region,
            before_context=before,
            after_context=after,
        )
        now = self._clock()
        ann = Annotation(
            id=self._id_factory(),
            file=file,
            anchor=anchor,
            body=body,
            status=STATUS_ANCHORED,
            suggested_edit=suggested_edit,
            conversation_ref=conversation_ref,
            created_at=now,
            updated_at=now,
        )
        self._annotations[ann.id] = ann
        self._save()
        return ann

    # -- re-anchor ---------------------------------------------------------

    def reanchor(self, annotation_id: str) -> Annotation:
        """Relocate an annotation against the current text of its file.

        Reads the file through the injected ``reader`` and moves the anchor's
        line range to wherever the captured region text now lives (disambiguated
        by context and proximity). If the region text is gone, the annotation is
        marked :data:`STATUS_ORPHANED` and its last-known line range is left
        untouched rather than being pointed at unrelated code.

        Returns:
            The updated annotation.
        """
        ann = self.get(annotation_id)
        lines = _split(self._reader(ann.file))
        located = _locate_region(lines, ann.anchor)
        if located is None:
            if ann.status != STATUS_ORPHANED:
                ann.status = STATUS_ORPHANED
                ann.updated_at = self._clock()
                self._save()
            return ann
        start, end = located
        moved = start != ann.anchor.line_start or end != ann.anchor.line_end
        was_orphaned = ann.status == STATUS_ORPHANED
        if moved or was_orphaned:
            ann.anchor.line_start = start
            ann.anchor.line_end = end
            # Refresh captured context around the new location.
            ann.anchor.before_context = lines[max(0, start - 1 - self._context_lines) : start - 1]
            ann.anchor.after_context = lines[end : end + self._context_lines]
            ann.status = STATUS_ANCHORED
            ann.updated_at = self._clock()
            self._save()
        return ann

    def reanchor_file(self, file: str) -> list[Annotation]:
        """Re-anchor every annotation attached to ``file``; returns them sorted."""
        updated = [self.reanchor(a.id) for a in self.list_annotations(file=file)]
        return updated

    # -- conversation ------------------------------------------------------

    def open_conversation(self, annotation_id: str, conversation_ref: str) -> Annotation:
        """Link ``annotation_id`` to a conversation/thread ref and persist."""
        if not conversation_ref:
            raise ValueError("conversation_ref must be non-empty")
        ann = self.get(annotation_id)
        ann.conversation_ref = conversation_ref
        ann.updated_at = self._clock()
        self._save()
        return ann

    # -- diff --------------------------------------------------------------

    def emit_diff(self, annotation_id: str, *, context_lines: int = 3) -> str:
        """Emit a unified diff applying the annotation's suggested edit.

        The current file text is read through the injected ``reader``; the
        anchored region is located fresh (so the diff targets the correct current
        lines even after intervening edits) and replaced with the suggested edit.

        Returns:
            A unified diff string (``git``-style ``a/``/``b/`` headers).

        Raises:
            NoSuggestedEditError: If the annotation carries no suggested edit.
            OrphanedAnchorError: If the anchored region no longer exists.
        """
        ann = self.get(annotation_id)
        if ann.suggested_edit is None:
            raise NoSuggestedEditError(annotation_id)
        current_lines = _split(self._reader(ann.file))
        located = _locate_region(current_lines, ann.anchor)
        if located is None:
            raise OrphanedAnchorError(annotation_id)
        start, end = located
        replacement = _split(ann.suggested_edit)
        new_lines = current_lines[: start - 1] + replacement + current_lines[end:]
        diff = difflib.unified_diff(
            current_lines,
            new_lines,
            fromfile=f"a/{ann.file}",
            tofile=f"b/{ann.file}",
            n=context_lines,
            lineterm="",
        )
        return "\n".join(diff) + "\n"
