"""Diff and patch tools: targeted edits, unified diff apply, preview.

The diff.create tool is the primary way Thomas edits code — it finds an
exact string and replaces it, similar to Claude Code's Edit tool.
"""

from __future__ import annotations

import difflib
import re
from pathlib import Path
from typing import Any

from thomas.tools.base import Tool, ToolResult
from thomas.tools.diff_codex_format import convert_codex_patch
from thomas.tools.diff_transaction import (
    PatchFormatError,
    apply_patch_transactional,
    preflight_patch,
)
from thomas.tools.filesystem import _is_protected_runtime_path, _safe_path

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


_READ_FILE_LINE_PREFIX_RE = re.compile(r"^[ \t]*\d{1,7}\t")


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

    def __init__(self, sandbox_root: Path):
        self._root = sandbox_root.resolve()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        rel = args["file"]
        old_str = args["old_str"]
        new_str = args["new_str"]

        try:
            path = _safe_path(self._root, rel)
        except ValueError as e:
            return ToolResult(ok=False, error=str(e))

        if not path.exists():
            return ToolResult(ok=False, error=f"File not found: {rel}")
        if not path.is_file():
            return ToolResult(ok=False, error=f"Not a file: {rel}")

        # ── Runtime protection: block edits to Thomas's own code ──
        blocked = _is_protected_runtime_path(self._root, path)
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
            return ToolResult(
                ok=False,
                error=(f"old_str not found in {rel}. Make sure the text matches exactly including whitespace."),
            )

        count = content.count(old_str)
        if count > 1:
            return ToolResult(
                ok=False,
                error=(f"old_str appears {count} times in {rel}. Add more surrounding context to make it unique."),
            )

        new_content = content.replace(old_str, new_str, 1)
        with path.open("w", encoding="utf-8", newline="") as handle:
            handle.write(new_content.replace("\n", eol) if eol != "\n" else new_content)

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

    def __init__(self, sandbox_root: Path):
        self._root = sandbox_root.resolve()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        patch_text = args["patch"]
        selection = args.get("hunks")
        if isinstance(selection, (list, tuple)) and not selection:
            selection = None  # `hunks: []` means no restriction, not nothing (8 refusals in one day)

        # The model writes the Codex apply-patch envelope more often than a
        # numbered unified diff (35 of 88 calls rejected in one day); read both.
        try:
            conversion = convert_codex_patch(patch_text, self._root, create_files=True)
            report = apply_patch_transactional(conversion.unified, self._root, selection=selection)
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

    def __init__(self, sandbox_root: Path):
        self._root = sandbox_root.resolve()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        patch_text = args["patch"]

        try:
            unified = convert_codex_patch(patch_text, self._root, create_files=False).unified
            report = preflight_patch(unified, self._root)
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
            path = _safe_path(self._root, rel)
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


def register_diff_tools(registry: Any, sandbox_root: Path) -> None:
    """Register all diff tools with the registry."""
    registry.register(CreateDiffTool(sandbox_root))
    registry.register(ApplyPatchTool(sandbox_root))
    registry.register(PreviewPatchTool(sandbox_root))
    registry.register(PreviewDiffTool(sandbox_root))
