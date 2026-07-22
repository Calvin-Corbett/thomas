"""Visual click-to-edit -> reviewable source-code diffs (CAP-113).

A *visual edit* is a structured change a user makes to a rendered UI element --
for example, recoloring a button, retyping its label, or nudging its spacing.
This module turns such edits into **reviewable source-code diffs** against the
element's real source definition, rather than opaque live DOM mutations.

The pipeline has three stages:

1. **Map** the visually-edited element back to its source location. This is done
   through an injectable :class:`ElementIndex`. The real default
   (:class:`ProjectElementIndex`) parses component/style files (CSS custom
   properties, CSS rules, and ``id=``-tagged markup elements) to build an
   element -> source location map. Tests can inject a hermetic
   :class:`DictElementIndex` instead.

2. **Apply** the property change to the source. A color/spacing/size edit is
   located as a style *declaration* whose current value equals the edit's
   ``from`` value; a text edit is located as the element's text content. The
   matching line is rewritten from ``from`` to ``to``.

3. **Diff** -- the rewrite is emitted as a unified diff hunk against the real
   source file (before/after, ``file:line``). An unmapped or mismatched element
   is *reported*, never silently applied. Multiple visual edits batch into one
   coherent :class:`DiffSet` -- one unified diff per touched file.

The whole converter is deterministic and depends only on the standard library,
so it runs hermetically over a fixture project with no network or external
tools.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

__all__ = [
    "PROP_COLOR",
    "PROP_TEXT",
    "PROP_SPACING",
    "PROP_SIZE",
    "VisualEdit",
    "Declaration",
    "ElementLocation",
    "EditResult",
    "FileDiff",
    "DiffSet",
    "ElementIndex",
    "DictElementIndex",
    "ProjectElementIndex",
    "convert_edit",
    "convert_edits",
]

# ---------------------------------------------------------------------------
# Property categories
# ---------------------------------------------------------------------------

PROP_COLOR = "color"
PROP_TEXT = "text"
PROP_SPACING = "spacing"
PROP_SIZE = "size"

# A visual property category maps to the concrete CSS property names it may
# touch. This disambiguates when a rule has several declarations sharing the
# same value. Custom-property (token) declarations -- names starting with
# ``--`` -- are always eligible regardless of category.
_CATEGORY_PROPERTIES: dict[str, frozenset[str]] = {
    PROP_COLOR: frozenset(
        {
            "color",
            "background",
            "background-color",
            "border-color",
            "outline-color",
            "fill",
            "stroke",
        }
    ),
    PROP_SPACING: frozenset(
        {
            "margin",
            "margin-top",
            "margin-right",
            "margin-bottom",
            "margin-left",
            "padding",
            "padding-top",
            "padding-right",
            "padding-bottom",
            "padding-left",
            "gap",
            "row-gap",
            "column-gap",
        }
    ),
    PROP_SIZE: frozenset(
        {
            "width",
            "height",
            "min-width",
            "max-width",
            "min-height",
            "max-height",
            "font-size",
            "line-height",
        }
    ),
}


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VisualEdit:
    """A structured change to a rendered UI element.

    ``element`` is the identifier the renderer knows the element by -- a CSS
    selector (``.btn``, ``#save``), a bare markup id (``save``), or a design
    token name (``--btn-color``). ``prop`` is one of the ``PROP_*`` categories.
    ``from_value`` / ``to_value`` are the rendered before/after values.
    """

    element: str
    prop: str
    from_value: str
    to_value: str
    edit_id: str = ""

    def __post_init__(self) -> None:
        if self.prop not in (PROP_COLOR, PROP_TEXT, PROP_SPACING, PROP_SIZE):
            raise ValueError(f"unknown visual-edit property category: {self.prop!r}")


@dataclass(frozen=True)
class Declaration:
    """A single ``property: value`` style declaration and its source line."""

    property: str
    value: str
    line: int  # 1-indexed line within the source file


@dataclass(frozen=True)
class ElementLocation:
    """Where an element lives in source and what it exposes for editing."""

    element: str
    file: str
    declarations: tuple[Declaration, ...] = ()
    text_value: str | None = None
    text_line: int | None = None


@dataclass(frozen=True)
class EditResult:
    """Outcome of converting one visual edit.

    When ``mapped`` is true a source diff was produced (``file``/``line`` point
    at the change). When false, ``reason`` explains why the edit was reported
    rather than applied.
    """

    edit: VisualEdit
    mapped: bool
    reason: str | None = None
    file: str | None = None
    line: int | None = None
    before: str | None = None
    after: str | None = None

    @property
    def location(self) -> str | None:
        """``file:line`` for a mapped edit, else ``None``."""
        if self.mapped and self.file is not None and self.line is not None:
            return f"{self.file}:{self.line}"
        return None


@dataclass(frozen=True)
class FileDiff:
    """A unified diff for a single source file plus the lines it touched."""

    file: str
    diff_text: str
    changed_lines: tuple[int, ...]


@dataclass
class DiffSet:
    """The coherent, reviewable result of a batch of visual edits."""

    results: list[EditResult] = field(default_factory=list)
    file_diffs: list[FileDiff] = field(default_factory=list)

    @property
    def mapped(self) -> list[EditResult]:
        return [r for r in self.results if r.mapped]

    @property
    def unmapped(self) -> list[EditResult]:
        return [r for r in self.results if not r.mapped]

    def unified_text(self) -> str:
        """All file diffs concatenated in deterministic (path) order."""
        return "\n".join(fd.diff_text for fd in self.file_diffs)


# ---------------------------------------------------------------------------
# Element index protocol + implementations
# ---------------------------------------------------------------------------


@runtime_checkable
class ElementIndex(Protocol):
    """Maps a visually-edited element back to its source definition."""

    def lookup(self, element: str) -> ElementLocation | None:
        """Return the element's source location, or ``None`` if unmapped."""
        ...

    def read_source(self, file: str) -> str:
        """Return the current text of a source file the index produced."""
        ...


class DictElementIndex:
    """A hermetic, in-memory index -- inject this in tests.

    ``locations`` maps element key -> :class:`ElementLocation`. ``sources`` maps
    file key -> full source text.
    """

    def __init__(
        self,
        locations: dict[str, ElementLocation],
        sources: dict[str, str],
    ) -> None:
        self._locations = dict(locations)
        self._sources = dict(sources)

    def lookup(self, element: str) -> ElementLocation | None:
        return self._locations.get(element)

    def read_source(self, file: str) -> str:
        return self._sources[file]


# CSS a rule header: one-or-more comma-separated selectors then ``{``.
_CSS_DECL_RE = re.compile(r"^\s*([-A-Za-z][-A-Za-z0-9]*)\s*:\s*(.+?)\s*;?\s*$")
# Markup element carrying an id and (optionally) same-line text content.
_MARKUP_ID_RE = re.compile(r"""<([A-Za-z][A-Za-z0-9]*)\b[^>]*\bid\s*=\s*["']([^"']+)["'][^>]*>""")
_INLINE_STYLE_RE = re.compile(r"""\bstyle\s*=\s*["']([^"']*)["']""")

_CSS_EXTS = {".css"}
_MARKUP_EXTS = {".html", ".htm", ".jsx", ".tsx", ".vue", ".svelte"}

_SKIP_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    "build",
    ".next",
    ".cache",
}


class ProjectElementIndex:
    """Real default: parse component/style files under a project directory.

    Registers three kinds of editable element:

    * **CSS rules** keyed by each selector (``.btn``, ``#save``), exposing their
      declarations.
    * **Design tokens** -- CSS custom properties (``--btn-color``) keyed by the
      property name, exposing the single declaration.
    * **Markup elements** keyed by both the bare id (``save``) and its selector
      form (``#save``), exposing inline-style declarations and text content.
    """

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        self._locations: dict[str, ElementLocation] = {}
        self._sources: dict[str, str] = {}
        self._build()

    # -- public API --------------------------------------------------------

    def lookup(self, element: str) -> ElementLocation | None:
        return self._locations.get(element)

    def read_source(self, file: str) -> str:
        return self._sources[file]

    def elements(self) -> list[str]:
        """Sorted list of every element key the index knows (deterministic)."""
        return sorted(self._locations)

    # -- construction ------------------------------------------------------

    def _build(self) -> None:
        for path in sorted(self._iter_files()):
            rel = path.relative_to(self._root).as_posix()
            text = path.read_text(encoding="utf-8")
            self._sources[rel] = text
            ext = path.suffix.lower()
            if ext in _CSS_EXTS:
                self._parse_css(rel, text)
            elif ext in _MARKUP_EXTS:
                self._parse_markup(rel, text)

    def _iter_files(self):
        for path in self._root.rglob("*"):
            if not path.is_file():
                continue
            if any(part in _SKIP_DIRS for part in path.parts):
                continue
            if path.suffix.lower() in _CSS_EXTS or path.suffix.lower() in _MARKUP_EXTS:
                yield path

    def _register(self, key: str, location: ElementLocation) -> None:
        # First definition wins -- keeps mapping deterministic and stable.
        if key not in self._locations:
            self._locations[key] = location

    def _parse_css(self, rel: str, text: str) -> None:
        lines = text.splitlines()
        selectors: list[str] = []
        decls: list[Declaration] = []
        in_block = False
        for idx, raw in enumerate(lines, start=1):
            line = raw.strip()
            if not line or line.startswith("/*"):
                continue
            if not in_block:
                if "{" in line:
                    header = line.split("{", 1)[0].strip()
                    selectors = [s.strip() for s in header.split(",") if s.strip()]
                    decls = []
                    in_block = True
                continue
            # inside a block
            if "}" in line:
                self._flush_css_rule(rel, selectors, decls)
                selectors = []
                decls = []
                in_block = False
                continue
            match = _CSS_DECL_RE.match(raw)
            if match:
                prop, value = match.group(1), match.group(2).strip()
                decls.append(Declaration(property=prop, value=value, line=idx))

    def _flush_css_rule(self, rel: str, selectors: list[str], decls: list[Declaration]) -> None:
        decl_tuple = tuple(decls)
        for selector in selectors:
            self._register(
                selector,
                ElementLocation(element=selector, file=rel, declarations=decl_tuple),
            )
        # Register each custom property as its own token element.
        for decl in decls:
            if decl.property.startswith("--"):
                self._register(
                    decl.property,
                    ElementLocation(
                        element=decl.property,
                        file=rel,
                        declarations=(decl,),
                    ),
                )

    def _parse_markup(self, rel: str, text: str) -> None:
        lines = text.splitlines()
        for idx, raw in enumerate(lines, start=1):
            match = _MARKUP_ID_RE.search(raw)
            if not match:
                continue
            element_id = match.group(2)
            decls: list[Declaration] = []
            style_match = _INLINE_STYLE_RE.search(raw)
            if style_match:
                decls = self._parse_inline_style(style_match.group(1), idx)
            text_value, text_line = self._extract_text(raw, idx)
            location = ElementLocation(
                element=element_id,
                file=rel,
                declarations=tuple(decls),
                text_value=text_value,
                text_line=text_line,
            )
            self._register(element_id, location)
            self._register(
                f"#{element_id}",
                ElementLocation(
                    element=f"#{element_id}",
                    file=rel,
                    declarations=tuple(decls),
                    text_value=text_value,
                    text_line=text_line,
                ),
            )

    @staticmethod
    def _parse_inline_style(style: str, line: int) -> list[Declaration]:
        decls: list[Declaration] = []
        for part in style.split(";"):
            part = part.strip()
            if not part or ":" not in part:
                continue
            prop, value = part.split(":", 1)
            decls.append(Declaration(property=prop.strip(), value=value.strip(), line=line))
        return decls

    @staticmethod
    def _extract_text(raw: str, line: int) -> tuple[str | None, int | None]:
        # Capture same-line text between the opening tag's ``>`` and ``</``.
        close = raw.find(">")
        end = raw.find("</", close + 1)
        if close != -1 and end != -1 and end > close:
            content = raw[close + 1 : end].strip()
            if content and "<" not in content:
                return content, line
        return None, None


# ---------------------------------------------------------------------------
# Conversion
# ---------------------------------------------------------------------------


def _find_declaration(
    location: ElementLocation,
    category: str,
    from_value: str,
) -> Declaration | None:
    """Pick the declaration whose value matches, disambiguated by category."""
    matches = [d for d in location.declarations if d.value == from_value]
    if not matches:
        return None
    prop_set = _CATEGORY_PROPERTIES.get(category)
    if prop_set is not None:
        filtered = [d for d in matches if d.property in prop_set or d.property.startswith("--")]
        if filtered:
            matches = filtered
    # Deterministic: earliest source line wins.
    return min(matches, key=lambda d: d.line)


def _resolve_change(
    edit: VisualEdit,
    location: ElementLocation,
) -> tuple[int, str] | str:
    """Return (line, new_value) to apply, or an error string to report."""
    if edit.prop == PROP_TEXT:
        if location.text_line is None or location.text_value is None:
            return f"element {edit.element!r} has no editable text content"
        if location.text_value != edit.from_value:
            return (
                f"text mismatch on {edit.element!r}: "
                f"source is {location.text_value!r}, edit expected {edit.from_value!r}"
            )
        return location.text_line, edit.to_value
    decl = _find_declaration(location, edit.prop, edit.from_value)
    if decl is None:
        return f"no {edit.prop} declaration on {edit.element!r} with value {edit.from_value!r}"
    return decl.line, edit.to_value


def _rewrite_line(line_text: str, from_value: str, to_value: str) -> str | None:
    """Replace the first occurrence of ``from_value`` in the line."""
    if from_value not in line_text:
        return None
    return line_text.replace(from_value, to_value, 1)


@dataclass
class _PendingChange:
    edit: VisualEdit
    line: int  # 1-indexed
    before_line: str
    after_line: str


def _plan_edit(
    edit: VisualEdit,
    index: ElementIndex,
) -> tuple[str, _PendingChange] | EditResult:
    """Resolve one edit to a concrete line change, or an unmapped result."""
    location = index.lookup(edit.element)
    if location is None:
        return EditResult(
            edit=edit,
            mapped=False,
            reason=f"element {edit.element!r} is not mapped to any source location",
        )
    resolved = _resolve_change(edit, location)
    if isinstance(resolved, str):
        return EditResult(edit=edit, mapped=False, reason=resolved, file=location.file)
    line_no, _new_value = resolved
    source = index.read_source(location.file)
    source_lines = source.splitlines()
    if line_no < 1 or line_no > len(source_lines):
        return EditResult(
            edit=edit,
            mapped=False,
            reason=f"resolved line {line_no} is out of range for {location.file!r}",
            file=location.file,
        )
    before_line = source_lines[line_no - 1]
    after_line = _rewrite_line(before_line, edit.from_value, edit.to_value)
    if after_line is None:
        return EditResult(
            edit=edit,
            mapped=False,
            reason=(f"value {edit.from_value!r} not found on {location.file}:{line_no}"),
            file=location.file,
            line=line_no,
        )
    return location.file, _PendingChange(
        edit=edit,
        line=line_no,
        before_line=before_line,
        after_line=after_line,
    )


def _build_file_diff(
    file: str,
    original: str,
    changes: list[_PendingChange],
) -> FileDiff:
    """Apply all line changes to one file and emit a single unified diff."""
    before_lines = original.splitlines()
    after_lines = list(before_lines)
    for change in sorted(changes, key=lambda c: c.line):
        after_lines[change.line - 1] = change.after_line
    diff_text = "\n".join(
        difflib.unified_diff(
            before_lines,
            after_lines,
            fromfile=f"a/{file}",
            tofile=f"b/{file}",
            lineterm="",
        )
    )
    changed = tuple(sorted(c.line for c in changes))
    return FileDiff(file=file, diff_text=diff_text, changed_lines=changed)


def convert_edits(edits: list[VisualEdit], index: ElementIndex) -> DiffSet:
    """Convert a batch of visual edits into one coherent reviewable diff set.

    Edits that map to source produce unified diffs grouped by file (one diff per
    file even when several edits touch it). Edits that cannot be mapped or whose
    value does not match the source are *reported* in ``results`` with a reason
    and never applied. Fully deterministic for a fixed input.
    """
    results: list[EditResult] = []
    per_file: dict[str, list[_PendingChange]] = {}

    for edit in edits:
        planned = _plan_edit(edit, index)
        if isinstance(planned, EditResult):
            results.append(planned)
            continue
        file, change = planned
        per_file.setdefault(file, []).append(change)
        results.append(
            EditResult(
                edit=edit,
                mapped=True,
                file=file,
                line=change.line,
                before=change.before_line,
                after=change.after_line,
            )
        )

    file_diffs: list[FileDiff] = []
    for file in sorted(per_file):
        original = index.read_source(file)
        file_diffs.append(_build_file_diff(file, original, per_file[file]))

    return DiffSet(results=results, file_diffs=file_diffs)


def convert_edit(edit: VisualEdit, index: ElementIndex) -> EditResult:
    """Convert a single visual edit and return its result.

    The produced source diff (when mapped) is available on the returned
    :class:`DiffSet` via :func:`convert_edits`; this convenience wrapper returns
    just the per-edit :class:`EditResult` for callers editing one element.
    """
    diff_set = convert_edits([edit], index)
    return diff_set.results[0]
