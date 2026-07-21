"""Cross-tool skill/format compatibility (CAP-133).

This module lives in the ``thomas.skills`` tier and depends only on the
standard library, so it never violates the ``thomas/_architecture.py``
dependency hierarchy.

It proves *lossless* live compatibility between Thomas's internal
representations and two major external formats:

1. **The Anthropic / Claude ``SKILL.md`` skill format** - a YAML-style
   frontmatter block delimited by ``---`` lines carrying ``name`` and
   ``description``, followed by a free-form instruction body. :func:`import_skill`
   parses one into an internal :class:`Skill`; :func:`export_skill` serializes it
   back. For a document that only uses the fields the internal model supports,
   ``export_skill(import_skill(text)) == text`` byte-for-byte.

2. **Major external instruction formats** - ``CLAUDE.md`` (Claude Code) and
   ``.cursorrules`` (Cursor). :func:`import_instruction` captures one into an
   internal :class:`Instruction`; :func:`export_instruction` emits it back
   byte-for-byte.

3. :func:`compat_report` classifies an arbitrary external document, converts it
   through the matching internal representation and back, and reports whether the
   round-trip was lossless. When it is *not* lossless (for example, the skill
   frontmatter carries a field the internal model does not represent), the report
   surfaces a unified ``diff`` and the offending ``unsupported_fields`` so the
   incompatibility is made explicit rather than silently swallowed.

Everything here is deterministic (no clocks, no randomness, no I/O) and depends
on the standard library only.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field

__all__ = [
    "FORMAT_ANTHROPIC_SKILL",
    "FORMAT_CLAUDE_MD",
    "FORMAT_CURSORRULES",
    "SUPPORTED_SKILL_KEYS",
    "CompatReport",
    "FormatCompatError",
    "Instruction",
    "Skill",
    "classify_format",
    "compat_report",
    "export_instruction",
    "export_skill",
    "import_instruction",
    "import_skill",
]

# ---------------------------------------------------------------------------
# Format identifiers
# ---------------------------------------------------------------------------
FORMAT_ANTHROPIC_SKILL = "anthropic-skill"  # SKILL.md with frontmatter
FORMAT_CLAUDE_MD = "claude-md"  # CLAUDE.md / AGENTS.md style instructions
FORMAT_CURSORRULES = "cursorrules"  # .cursorrules instructions

# Frontmatter keys the internal Skill model can faithfully represent. Any other
# key is "unsupported": it survives import (nothing is dropped silently) but
# cannot be re-emitted by :func:`export_skill`, which is exactly the loss that
# :func:`compat_report` surfaces.
SUPPORTED_SKILL_KEYS: tuple[str, ...] = ("name", "description")

_FRONTMATTER_DELIM = "---"


class FormatCompatError(ValueError):
    """Raised when a document cannot be parsed into the expected format."""


# ---------------------------------------------------------------------------
# Internal representations
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Skill:
    """Internal representation of an external skill document.

    ``field_order`` records the supported frontmatter keys in the exact order
    they appeared, so :func:`export_skill` re-emits them byte-identically.
    ``unsupported`` holds ``(key, value)`` pairs for frontmatter fields the
    internal model does not represent; they are preserved for inspection but are
    intentionally *not* re-emitted, which is how loss is surfaced rather than
    hidden.
    """

    name: str = ""
    description: str = ""
    body: str = ""
    field_order: tuple[str, ...] = ()
    unsupported: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class Instruction:
    """Internal representation of an external instruction document."""

    fmt: str
    body: str


# ---------------------------------------------------------------------------
# Frontmatter parsing helpers (deterministic, stdlib only)
# ---------------------------------------------------------------------------
def _split_frontmatter(text: str) -> tuple[list[str], str] | None:
    """Split ``text`` into (frontmatter_lines, body).

    Returns ``None`` when ``text`` does not open with a ``---`` delimiter line
    followed by a matching closing ``---`` delimiter line.
    """

    opener = _FRONTMATTER_DELIM + "\n"
    if not text.startswith(opener):
        return None

    rest = text[len(opener) :]
    lines = rest.split("\n")
    fm_lines: list[str] = []
    close_index: int | None = None
    for index, line in enumerate(lines):
        if line == _FRONTMATTER_DELIM:
            close_index = index
            break
        fm_lines.append(line)

    if close_index is None:
        return None

    body = "\n".join(lines[close_index + 1 :])
    return fm_lines, body


def _parse_kv(line: str) -> tuple[str, str] | None:
    """Parse a ``key: value`` frontmatter line.

    A single leading space after the colon is treated as the canonical
    separator so that ``export`` re-emits ``key: value`` byte-identically.
    Returns ``None`` for lines that are not ``key: value`` pairs.
    """

    if ":" not in line:
        return None
    key, _, value = line.partition(":")
    if key != key.strip() or not key:
        # Indented or empty keys are not part of the canonical top-level schema.
        return None
    if value.startswith(" "):
        value = value[1:]
    return key, value


# ---------------------------------------------------------------------------
# Skill format: import / export
# ---------------------------------------------------------------------------
def import_skill(text: str) -> Skill:
    """Parse a Claude/Anthropic ``SKILL.md`` document into a :class:`Skill`.

    Raises :class:`FormatCompatError` when ``text`` is not a frontmatter-bearing
    skill document.
    """

    split = _split_frontmatter(text)
    if split is None:
        raise FormatCompatError("SKILL.md requires a YAML frontmatter block delimited by '---' lines.")

    fm_lines, body = split
    values: dict[str, str] = {}
    field_order: list[str] = []
    unsupported: list[tuple[str, str]] = []

    for line in fm_lines:
        kv = _parse_kv(line)
        if kv is None:
            # A frontmatter line the model cannot structure (blank line, list
            # item, indented block). Preserve it so the loss is visible.
            unsupported.append(("", line))
            continue
        key, value = kv
        if key in SUPPORTED_SKILL_KEYS and key not in values:
            values[key] = value
            field_order.append(key)
        else:
            unsupported.append((key, value))

    return Skill(
        name=values.get("name", ""),
        description=values.get("description", ""),
        body=body,
        field_order=tuple(field_order),
        unsupported=tuple(unsupported),
    )


def export_skill(skill: Skill) -> str:
    """Serialize a :class:`Skill` back into ``SKILL.md`` text.

    Only the supported, modeled fields are emitted. When ``field_order`` is
    empty (a freshly constructed skill), the canonical ``name`` then
    ``description`` order is used for whichever fields are non-empty.
    """

    values = {"name": skill.name, "description": skill.description}
    order = skill.field_order or tuple(key for key in SUPPORTED_SKILL_KEYS if values[key])
    fm_body = "\n".join(f"{key}: {values[key]}" for key in order)
    return f"{_FRONTMATTER_DELIM}\n{fm_body}\n{_FRONTMATTER_DELIM}\n{skill.body}"


# ---------------------------------------------------------------------------
# Instruction format: import / export
# ---------------------------------------------------------------------------
def import_instruction(text: str, fmt: str = FORMAT_CLAUDE_MD) -> Instruction:
    """Capture an instruction document (CLAUDE.md / .cursorrules) verbatim."""

    return Instruction(fmt=fmt, body=text)


def export_instruction(instruction: Instruction) -> str:
    """Emit an :class:`Instruction` back to text byte-identically."""

    return instruction.body


# ---------------------------------------------------------------------------
# Classification + compatibility report
# ---------------------------------------------------------------------------
def _basename(filename: str) -> str:
    return filename.replace("\\", "/").rsplit("/", 1)[-1]


def classify_format(text: str, filename: str | None = None) -> str:
    """Classify ``text`` as one of the known external formats.

    A ``filename`` hint (``SKILL.md``, ``CLAUDE.md``, ``.cursorrules``, ...) wins
    when provided. Otherwise the classifier inspects the content: a frontmatter
    block carrying a ``name`` key is a skill; anything else is treated as a
    Claude-style instruction document.
    """

    if filename:
        low = _basename(filename).lower()
        if low == "skill.md":
            return FORMAT_ANTHROPIC_SKILL
        if low == ".cursorrules":
            return FORMAT_CURSORRULES
        if low in ("claude.md", "agents.md", "thomas.md", ".thomas.md"):
            return FORMAT_CLAUDE_MD

    split = _split_frontmatter(text)
    if split is not None:
        keys = {kv[0] for line in split[0] if (kv := _parse_kv(line))}
        if "name" in keys:
            return FORMAT_ANTHROPIC_SKILL

    return FORMAT_CLAUDE_MD


def _unified_diff(original: str, rebuilt: str, fmt: str) -> str:
    diff_lines = difflib.unified_diff(
        original.splitlines(keepends=True),
        rebuilt.splitlines(keepends=True),
        fromfile=f"{fmt}:original",
        tofile=f"{fmt}:round-trip",
        lineterm="",
    )
    return "".join(diff_lines)


@dataclass(frozen=True, slots=True)
class CompatReport:
    """Result of classifying and round-tripping an external document.

    ``lossless_round_trip`` is ``True`` only when re-exporting the internal
    representation reproduces the source byte-for-byte. When it is ``False``,
    ``diff`` holds a unified diff and ``unsupported_fields`` names the frontmatter
    fields the internal model could not represent.
    """

    source_format: str
    kind: str  # "skill" | "instruction"
    lossless_round_trip: bool
    exported: str
    diff: str = ""
    unsupported_fields: tuple[str, ...] = ()
    skill: Skill | None = None
    instruction: Instruction | None = None
    _notes: tuple[str, ...] = field(default=(), repr=False)


def compat_report(external_doc: str, filename: str | None = None) -> CompatReport:
    """Classify ``external_doc``, convert it, and report lossless compatibility.

    The document is routed to the skill or instruction converter based on
    :func:`classify_format`, imported into the matching internal representation,
    and exported back. The returned :class:`CompatReport` asserts
    ``lossless_round_trip`` and, when it is ``False``, carries the unified diff
    and the list of unsupported fields so incompatibility is surfaced, never
    hidden.
    """

    fmt = classify_format(external_doc, filename)

    if fmt == FORMAT_ANTHROPIC_SKILL:
        skill = import_skill(external_doc)
        exported = export_skill(skill)
        unsupported = tuple(key for key, _ in skill.unsupported if key)
        lossless = exported == external_doc
        return CompatReport(
            source_format=fmt,
            kind="skill",
            lossless_round_trip=lossless,
            exported=exported,
            diff="" if lossless else _unified_diff(external_doc, exported, fmt),
            unsupported_fields=unsupported,
            skill=skill,
        )

    instruction = import_instruction(external_doc, fmt)
    exported = export_instruction(instruction)
    lossless = exported == external_doc
    return CompatReport(
        source_format=fmt,
        kind="instruction",
        lossless_round_trip=lossless,
        exported=exported,
        diff="" if lossless else _unified_diff(external_doc, exported, fmt),
        unsupported_fields=(),
        instruction=instruction,
    )
