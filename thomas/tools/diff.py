"""Diff and patch tools: targeted edits, unified diff apply, preview.

The diff.create tool is the primary way Thomas edits code — it finds an
exact string and replaces it, similar to Claude Code's Edit tool.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from thomas.core.session_scope import active_tool_state
from thomas.tools.base import Tool, ToolResult
from thomas.tools.diff_codex_format import convert_codex_patch
from thomas.tools.diff_transaction import (
    PatchFormatError,
    apply_patch_transactional,
    preflight_patch,
)
from thomas.tools.filesystem import (
    _PROJECT_ROOT,
    _is_protected_runtime_path,
    _runtime_protection_roots,
)
from thomas.tools.fs_scope import scopes

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


def _protected(sandbox_root: Path, project_root: Path, path: Path) -> str | None:
    """A refusal reason if *path* is protected, checked the way fs.write_file
    does: against the real project (and the sandbox only when it sits INSIDE
    that tree), never against the sandbox alone. Checking the sandbox alone
    refused every thomas/server|tools|agent|core and scripts/ path inside a
    self-fix green -- a green is a private copy outside the project tree
    (C2, review of ce9f2f43)."""
    for protection_root in _runtime_protection_roots(sandbox_root, project_root):
        blocked = _is_protected_runtime_path(protection_root, path)
        if blocked:
            return blocked
    return None


_READ_FILE_LINE_PREFIX_RE = re.compile(r"^[ \t]*\d{1,7}\t")


def _closest_text(content: str, old_str: str, most: int = 40) -> str:
    """The file's lines where *old_str* most likely is, numbered as ``fs.read_file`` numbers them; "" when nothing is
    close. On 2026-10-26 three Build teams each missed the same edit three times or more in an hour: a model edits
    from a reading of the file that its own earlier edits have since changed, and "not found" told it nothing."""
    first = next((line.strip() for line in old_str.splitlines() if line.strip()), "")
    lines = content.splitlines()
    best = difflib.get_close_matches(first, [line.strip() for line in lines], n=1, cutoff=0.6) if first else []
    if not best:
        return ""
    start = max(0, next(i for i, line in enumerate(lines) if line.strip() == best[0]) - 1)
    span = min(most, len(old_str.splitlines()) + 2)
    return "\n".join(f"{start + i + 1:6d}\t{text}" for i, text in enumerate(lines[start : start + span]))


def _match_ignoring_trailing_whitespace(content: str, old_str: str) -> str | None:
    """The span of ``content`` that equals ``old_str`` once trailing spaces and
    tabs on each line are ignored, or None when there is no such span or more
    than one. Returned as the file's own text so the exact replace below works."""
    lines = old_str.split("\n")
    if not any(line.strip() for line in lines):
        return None
    parts = [re.escape(line.rstrip()) + r"[ \t]*" for line in lines]
    pattern = re.compile("\n".join(parts))
    matches = list(pattern.finditer(content))
    if len(matches) != 1:
        return None
    return matches[0].group(0)


def _strip_read_file_line_numbers(text: str) -> str:
    """Remove prefixes added by fs.read_file numbered output."""
    return "".join(_READ_FILE_LINE_PREFIX_RE.sub("", line) for line in str(text or "").splitlines(keepends=True))


@dataclass
class _EditHistory:
    misses: dict[tuple[Path, str], int] = field(default_factory=dict)
    locations: dict[tuple[Path, str], tuple[int, bool]] = field(default_factory=dict)
    other_first_lines: dict[tuple[Path, str], set[tuple[str, ...]]] = field(default_factory=dict)
    replacement_blocks: dict[tuple[Path, str], tuple[int, tuple[str, ...]]] = field(default_factory=dict)
    observed_first_lines: set[tuple[Path, str]] = field(default_factory=set)


class CreateDiffTool(Tool):
    name = "diff.create"
    category = "diff"
    description = (
        "Make a targeted edit to a file by replacing exact text. "
        "Provide the exact string to find (old_str) and its replacement (new_str). "
        "The old_str must match exactly one location, including whitespace and indentation. "
        "Snippets copied from fs.read_file numbered output are accepted."
    )
    parameters = {
        "type": "object",
        "properties": {
            "file": {
                "type": "string",
                "description": "File path to edit",
            },
            "old_str": {
                "type": "string",
                "description": "Exact string to find and replace (must match precisely)",
            },
            "new_str": {
                "type": "string",
                "description": "Replacement string",
            },
        },
        "required": ["file", "old_str", "new_str"],
    }

    def __init__(self, sandbox_root: Path, project_root: Path | None = None):
        self._root = sandbox_root.resolve()
        self._project_root = (project_root or _PROJECT_ROOT).resolve()
        self._direct_history = _EditHistory()

    def _history(self) -> _EditHistory:
        state = active_tool_state()
        if state is not None:
            return state.setdefault(self, _EditHistory())
        return self._direct_history

    def _remember_location(
        self, path: Path, content: str, old_str: str, *, matched_str: str | None = None
    ) -> tuple[int, bool] | None:
        source_str = _strip_read_file_line_numbers(old_str)
        first = next((line.strip() for line in source_str.splitlines() if line.strip()), "")
        if not first:
            return None
        history = self._history()
        key = (path, old_str)
        lines = [line.strip() for line in content.splitlines()]
        needle = source_str if matched_str is None else matched_str
        match = content.find(needle)
        if match >= 0 and content.count(needle) > 1:
            return history.locations.get(key)
        if match >= 0:
            history.observed_first_lines.add(key)
            offset = next(i for i, line in enumerate(source_str.splitlines()) if line.strip())
            anchor = content.count("\n", 0, match) + offset
            history.locations[key] = (anchor, True)
            history.other_first_lines[key] = {
                tuple(lines[i : i + 2]) for i, line in enumerate(lines) if line == first and i != anchor
            }
        else:
            numbered = next((line for line in old_str.splitlines() if _strip_read_file_line_numbers(line).strip()), "")
            prefix = _READ_FILE_LINE_PREFIX_RE.match(numbered)
            if key not in history.locations and prefix and int(prefix[0].strip()) > 0:
                history.locations[key] = (int(prefix[0].strip()) - 1, True)
            candidate = lines.index(first) if lines.count(first) == 1 else None
            replacement = history.replacement_blocks.get(key)
            if replacement is not None:
                start, block = replacement
                current_lines = content.splitlines()
                if block and tuple(current_lines[start : start + len(block)]) != block:
                    matches = [
                        i
                        for i in range(len(current_lines) - len(block) + 1)
                        if tuple(current_lines[i : i + len(block)]) == block
                    ]
                    if len(matches) == 1:
                        moved = matches[0]
                        anchor, exact = history.locations[key]
                        history.locations[key] = (anchor + moved - start, exact)
                        history.replacement_blocks[key] = (moved, block)
                        start = moved
                header = next(((i, line.strip()) for i, line in enumerate(block) if line.strip()), None)
                header_present = header is not None and lines[start + header[0] : start + header[0] + 1] == [header[1]]
                if not block or header_present or tuple(current_lines[start : start + len(block)]) == block:
                    candidate = None
            if prefix and history.locations.get(key) == (candidate, True):
                history.observed_first_lines.add(key)
            if (
                candidate is not None
                and (prefix is None or key in history.observed_first_lines)
                and tuple(lines[candidate : candidate + 2]) not in history.other_first_lines.get(key, set())
            ):
                history.locations[key] = (candidate, True)
            elif key not in history.locations:
                best = difflib.get_close_matches(first, lines, n=1, cutoff=0.6)
                if best:
                    history.locations[key] = (lines.index(best[0]), False)
        return history.locations.get(key)

    def _not_found(self, path: Path, rel: str, content: str, old_str: str) -> ToolResult:
        history = self._history()
        key = (path, old_str)
        misses = history.misses[key] = history.misses.get(key, 0) + 1
        error = f"old_str not found in {rel}."
        location = self._remember_location(path, content, old_str)
        if misses < 2:
            nearby = _closest_text(content, old_str)
            hint = (
                f" The closest text in the file now (it may have changed since you read it):\n{nearby}"
                if nearby
                else ""
            )
            return ToolResult(
                ok=False, error=error + " Make sure the text matches exactly including whitespace." + hint
            )

        error += " This text is not in the file now. You must read it again with fs.read_file before the next edit."
        lines = content.splitlines()
        if not lines:
            return ToolResult(ok=False, error=error + " The file is empty now.")
        if location is None:
            error += " No previous location is known for the first line; current lines from the start of the file:"
            anchor = 0
        else:
            anchor, exact = location
            label = "was last found" if exact else "had its closest match"
            error += f" Current lines around where old_str's first nonblank line {label} (line {anchor + 1}):"
        start = max(0, min(anchor, len(lines) - 1) - 1)
        span = min(40, max(3, len(old_str.splitlines()) + 2))
        nearby = "\n".join(f"{i + 1:6d}\t{lines[i][:500]}" for i in range(start, min(len(lines), start + span)))
        return ToolResult(ok=False, error=error + "\n" + nearby)

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        rel = args["file"]
        old_str = args["old_str"]
        new_str = args["new_str"]

        try:
            path = scopes().scope(self._root).resolve(rel)
        except ValueError as e:
            return ToolResult(ok=False, error=str(e))

        if not path.exists():
            return ToolResult(ok=False, error=f"File not found: {rel}")
        if not path.is_file():
            return ToolResult(ok=False, error=f"Not a file: {rel}")

        # ── Runtime protection: block edits to Thomas's own code ──
        blocked = _protected(self._root, self._project_root, path)
        if blocked:
            return ToolResult(ok=False, error=blocked)

        # Raw bytes in, raw bytes out: read with universal newlines and write
        # with the platform default turned every CRLF file into LF on Linux and
        # every LF file into CRLF on Windows, one whole-file line-ending flip
        # per edit. The file keeps whatever it had; matching is done on LF.
        try:
            with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
                raw = handle.read()
        except OSError as e:
            return ToolResult(ok=False, error=f"Cannot read file: {e}")
        crlf = raw.count("\r\n")
        eol = "\r\n" if crlf and crlf >= raw.count("\n") - crlf else "\n"
        content = raw.replace("\r\n", "\n")
        old_str = old_str.replace("\r\n", "\n")
        requested_old_str = old_str
        new_str = new_str.replace("\r\n", "\n")
        notes: list[str] = []
        if eol == "\r\n":
            notes.append("line endings: the file keeps CRLF")

        if old_str not in content:
            normalized_old = _strip_read_file_line_numbers(old_str)
            if normalized_old != old_str and normalized_old in content:
                old_str = normalized_old
                new_str = _strip_read_file_line_numbers(new_str)

        if old_str not in content:
            # Fifteen misses in one day were trailing whitespace: the text the
            # model meant, with spaces the file happened to carry at line ends.
            loose = _match_ignoring_trailing_whitespace(content, old_str)
            if loose is not None:
                old_str = loose
                notes.append("trailing whitespace ignored when matching")

        if old_str not in content:
            return self._not_found(path, rel, content, old_str)

        count = content.count(old_str)
        if count > 1:
            return ToolResult(
                ok=False,
                error=(f"old_str appears {count} times in {rel}. Add more surrounding context to make it unique."),
            )

        for tracked_path, tracked_old in tuple(self._history().locations):
            if tracked_path == path:
                self._remember_location(path, content, tracked_old)
        self._remember_location(path, content, requested_old_str, matched_str=old_str)
        new_content = content.replace(old_str, new_str, 1)
        with path.open("w", encoding="utf-8", newline="") as handle:
            handle.write(new_content.replace("\n", eol) if eol != "\n" else new_content)
        old_first = next((line.strip() for line in old_str.splitlines() if line.strip()), "")
        new_first = next((line.strip() for line in new_str.splitlines() if line.strip()), "")
        key = (path, requested_old_str)
        if old_first != new_first:
            offset = content.index(old_str)
            start = content.count("\n", 0, offset)
            end = start + new_str.count("\n") + (0 if new_str.endswith("\n") else 1)
            if not new_str and (offset == 0 or content[offset - 1] == "\n"):
                if old_str.endswith("\n") or offset + len(old_str) == len(content):
                    end = start
            self._history().replacement_blocks[key] = (start, tuple(new_content.splitlines()[start:end]))
        else:
            self._history().replacement_blocks.pop(key, None)

        old_lines = old_str.splitlines()
        new_lines = new_str.splitlines()
        summary = f"Replaced {len(old_lines)} line(s) with {len(new_lines)} line(s) in {rel}"
        if notes:
            summary += " (" + "; ".join(notes) + ")"
        return ToolResult(ok=True, data=summary)


class ApplyPatchTool(Tool):
    name = "diff.apply_patch"
    category = "diff"
    description = (
        "Apply a unified diff patch to files, atomically. Every hunk is "
        "preflighted against current file content first — if any hunk "
        "conflicts, NOTHING is applied and the conflicting hunks are named. "
        "Affected files are snapshotted before writing and all of them are "
        "restored if a write fails mid-apply. Pass 'hunks' (ids from "
        "diff.preview_patch, e.g. 'src/app.py#2', or 1-based indices) to "
        "apply only an accepted subset; omit it to apply every hunk."
    )
    parameters = {
        "type": "object",
        "properties": {
            "patch": {
                "type": "string",
                "description": "Unified diff patch content",
            },
            "hunks": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Optional accepted-hunk selection: stable hunk ids from "
                    "diff.preview_patch (e.g. 'src/app.py#2') or 1-based "
                    "global hunk indices. Omit to apply all hunks."
                ),
            },
        },
        "required": ["patch"],
    }

    def __init__(self, sandbox_root: Path, project_root: Path | None = None):
        self._root = sandbox_root.resolve()
        self._project_root = (project_root or _PROJECT_ROOT).resolve()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        patch_text = args["patch"]
        selection = args.get("hunks")
        if isinstance(selection, (list, tuple)) and not selection:
            selection = None  # `hunks: []` means no restriction, not nothing (8 refusals in one day)

        # The model writes the Codex apply-patch envelope more often than a
        # numbered unified diff (35 of 88 calls rejected in one day); read both.
        try:
            conversion = convert_codex_patch(patch_text, self._root, create_files=True)
            report = apply_patch_transactional(
                conversion.unified, self._root, selection=selection, project_root=self._project_root
            )
        except PatchFormatError as e:
            return ToolResult(ok=False, error=f"Patch failed: {e}")

        if not report.ok:
            for made in conversion.created:  # an Add that never applied leaves no empty file behind
                made.unlink(missing_ok=True)
            lines = [f"  conflict: {c.hunk_id or c.file} — {c.reason}" for c in report.conflicts]
            return ToolResult(ok=False, data="\n".join(lines) or None, error=report.error)
        for gone in conversion.to_delete:  # the transaction emptied it; a Delete means gone
            gone.unlink(missing_ok=True)

        lines = [f"  patched: {filepath}" for filepath in report.files_written]
        lines.append(f"  applied hunks: {', '.join(report.applied_hunks)}")
        if report.skipped_hunks:
            lines.append(f"  skipped hunks: {', '.join(report.skipped_hunks)}")
        return ToolResult(ok=True, data="\n".join(lines))


class PreviewPatchTool(Tool):
    name = "diff.preview_patch"
    category = "diff"
    description = (
        "Preview a unified diff patch without applying it. Runs the same "
        "preflight as diff.apply_patch and lists every hunk with a stable id "
        "(e.g. 'src/app.py#2') and whether it applies cleanly against current "
        "file content. Accept a subset by passing the clean ids to "
        "diff.apply_patch via its 'hunks' parameter."
    )
    parameters = {
        "type": "object",
        "properties": {
            "patch": {
                "type": "string",
                "description": "Unified diff patch content",
            },
        },
        "required": ["patch"],
    }

    def __init__(self, sandbox_root: Path, project_root: Path | None = None):
        self._root = sandbox_root.resolve()
        self._project_root = (project_root or _PROJECT_ROOT).resolve()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        patch_text = args["patch"]

        try:
            unified = convert_codex_patch(patch_text, self._root, create_files=False).unified
            report = preflight_patch(unified, self._root, project_root=self._project_root)
        except PatchFormatError as e:
            return ToolResult(ok=False, error=f"Patch failed: {e}")

        if not report.hunks:
            return ToolResult(ok=False, error="No valid hunks found in patch")

        lines: list[str] = []
        for hunk in report.hunks:
            conflict = report.conflict_for(hunk.hunk_id)
            if conflict is None:
                lines.append(f"  {hunk.hunk_id} [clean] {hunk.header}")
            else:
                lines.append(f"  {hunk.hunk_id} [conflict] {hunk.header} — {conflict.reason}")
        clean = sum(1 for h in report.hunks if report.conflict_for(h.hunk_id) is None)
        lines.append(f"  {clean}/{len(report.hunks)} hunks apply cleanly")
        return ToolResult(ok=True, data="\n".join(lines))


class PreviewDiffTool(Tool):
    name = "diff.preview"
    category = "diff"
    description = (
        "Preview what a targeted edit would change without applying it. "
        "Returns a unified diff showing the proposed change."
    )
    parameters = {
        "type": "object",
        "properties": {
            "file": {
                "type": "string",
                "description": "File path to preview edit for",
            },
            "old_str": {
                "type": "string",
                "description": "Exact string that would be replaced",
            },
            "new_str": {
                "type": "string",
                "description": "Replacement string",
            },
        },
        "required": ["file", "old_str", "new_str"],
    }

    def __init__(self, sandbox_root: Path):
        self._root = sandbox_root.resolve()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        rel = args["file"]
        old_str = args["old_str"]
        new_str = args["new_str"]

        try:
            path = scopes().scope(self._root).resolve(rel)
        except ValueError as e:
            return ToolResult(ok=False, error=str(e))

        if not path.exists():
            return ToolResult(ok=False, error=f"File not found: {rel}")

        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return ToolResult(ok=False, error=f"Cannot read file: {e}")

        # The same forgiveness as diff.create, or a preview says "not found"
        # for an edit that create would apply and sends the model off to
        # rewrite a search string that was already right.
        old_str = old_str.replace("\r\n", "\n")
        new_str = new_str.replace("\r\n", "\n")
        if old_str not in content:
            normalized_old = _strip_read_file_line_numbers(old_str)
            if normalized_old != old_str and normalized_old in content:
                old_str, new_str = normalized_old, _strip_read_file_line_numbers(new_str)
        if old_str not in content:
            loose = _match_ignoring_trailing_whitespace(content, old_str)
            if loose is not None:
                old_str = loose
        if old_str not in content:
            return ToolResult(ok=False, error=f"old_str not found in {rel}")

        new_content = content.replace(old_str, new_str, 1)

        diff_lines = list(
            difflib.unified_diff(
                content.splitlines(keepends=True),
                new_content.splitlines(keepends=True),
                fromfile=f"a/{rel}",
                tofile=f"b/{rel}",
            )
        )

        if not diff_lines:
            return ToolResult(ok=True, data="(no changes)")
        return ToolResult(ok=True, data="".join(diff_lines))


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_diff_tools(registry: Any, sandbox_root: Path, *, project_root: Path | None = None) -> None:
    """Register all diff tools with the registry."""
    registry.register(CreateDiffTool(sandbox_root, project_root))
    registry.register(ApplyPatchTool(sandbox_root, project_root))
    registry.register(PreviewPatchTool(sandbox_root, project_root))
    registry.register(PreviewDiffTool(sandbox_root))
