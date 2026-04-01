"""Diff and patch tools: targeted edits, unified diff apply, preview.

The diff.create tool is the primary way Thomas edits code — it finds an
exact string and replaces it, similar to Claude Code's Edit tool.
"""

from __future__ import annotations

import difflib
from pathlib import Path
from typing import Any

from thomas.tools.base import Tool, ToolResult
from thomas.tools.filesystem import _is_protected_runtime_path, _safe_path

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


class CreateDiffTool(Tool):
    name = "diff.create"
    category = "diff"
    description = (
        "Make a targeted edit to a file by replacing exact text. "
        "Provide the exact string to find (old_str) and its replacement (new_str). "
        "The old_str must match exactly one location, including whitespace and indentation."
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

        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return ToolResult(ok=False, error=f"Cannot read file: {e}")

        if old_str not in content:
            return ToolResult(
                ok=False,
                error=(f"old_str not found in {rel}. " f"Make sure the text matches exactly including whitespace."),
            )

        count = content.count(old_str)
        if count > 1:
            return ToolResult(
                ok=False,
                error=(f"old_str appears {count} times in {rel}. " f"Add more surrounding context to make it unique."),
            )

        new_content = content.replace(old_str, new_str, 1)
        path.write_text(new_content, encoding="utf-8")

        old_lines = old_str.splitlines()
        new_lines = new_str.splitlines()
        summary = f"Replaced {len(old_lines)} line(s) with {len(new_lines)} line(s) in {rel}"
        return ToolResult(ok=True, data=summary)


class ApplyPatchTool(Tool):
    name = "diff.apply_patch"
    category = "diff"
    description = (
        "Apply a unified diff patch to files. The patch should be in standard "
        "unified diff format (from git diff or diff -u). For complex patches, "
        "consider using shell.exec with 'git apply' instead."
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
            results = _apply_unified_diff(patch_text, self._root)
        except Exception as e:
            return ToolResult(ok=False, error=f"Patch failed: {e}")

        if not results:
            return ToolResult(ok=False, error="No valid hunks found in patch")

        summary_lines: list[str] = []
        for filepath, applied, error in results:
            if applied:
                summary_lines.append(f"  patched: {filepath}")
            else:
                summary_lines.append(f"  failed:  {filepath} — {error}")

        all_ok = all(applied for _, applied, _ in results)
        return ToolResult(
            ok=all_ok,
            data="\n".join(summary_lines),
            error=None if all_ok else "Some hunks failed to apply",
        )


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
# Patch application helpers
# ---------------------------------------------------------------------------


def _apply_unified_diff(patch_text: str, root: Path) -> list[tuple[str, bool, str]]:
    """Parse and apply a unified diff patch.

    Returns list of (filepath, success, error_message).
    This is a simplified implementation — for complex patches with
    fuzzy matching, use `git apply` via shell.exec instead.
    """
    results: list[tuple[str, bool, str]] = []
    chunks = _split_file_diffs(patch_text)

    for filename, hunks_text in chunks:
        try:
            fpath = _safe_path(root, filename)
        except ValueError as e:
            results.append((filename, False, str(e)))
            continue

        # ── Runtime protection: block patches to Thomas's own code ──
        blocked = _is_protected_runtime_path(root, fpath)
        if blocked:
            results.append((filename, False, blocked))
            continue

        try:
            if fpath.exists():
                content = fpath.read_text(encoding="utf-8", errors="replace")
            else:
                content = ""
                fpath.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            results.append((filename, False, str(e)))
            continue

        try:
            new_content = _apply_hunks(content, hunks_text)
            fpath.write_text(new_content, encoding="utf-8")
            results.append((filename, True, ""))
        except Exception as e:
            results.append((filename, False, str(e)))

    return results


def _split_file_diffs(patch_text: str) -> list[tuple[str, str]]:
    """Split a multi-file patch into (filename, hunks_text) pairs."""
    chunks: list[tuple[str, str]] = []
    lines = patch_text.splitlines(keepends=True)
    i = 0

    while i < len(lines):
        # Find --- / +++ pair
        if lines[i].startswith("--- ") and i + 1 < len(lines) and lines[i + 1].startswith("+++ "):
            plus_line = lines[i + 1].rstrip()
            fname = plus_line[4:].split("\t")[0].strip()
            if fname.startswith("b/"):
                fname = fname[2:]
            i += 2

            # Collect all hunk lines until next file or end
            hunk_start = i
            while i < len(lines) and not (lines[i].startswith("--- ") or lines[i].startswith("diff --git")):
                i += 1
            hunks_text = "".join(lines[hunk_start:i])
            chunks.append((fname, hunks_text))
        else:
            i += 1

    return chunks


def _apply_hunks(content: str, hunks_text: str) -> str:
    """Apply hunks from a single file's diff to its content."""
    original_lines = content.splitlines(keepends=True)
    result_lines = list(original_lines)
    offset = 0  # Track line offset from previous hunk applications

    for hunk_header, hunk_lines in _parse_hunks(hunks_text):
        # Parse @@ -old_start,old_count +new_start,new_count @@
        parts = hunk_header.split()
        old_spec = parts[1]  # -start,count
        old_start = int(old_spec.split(",")[0].lstrip("-")) - 1  # 0-indexed

        # Apply offset from previous hunks
        pos = old_start + offset

        # Process hunk lines
        new_lines: list[str] = []
        remove_count = 0
        for line in hunk_lines:
            if not line:
                continue
            op = line[0]
            text = line[1:] if len(line) > 1 else ""
            # Ensure trailing newline
            if text and not text.endswith("\n"):
                text += "\n"
            if op == " ":
                new_lines.append(text)
                remove_count += 1
            elif op == "-":
                remove_count += 1
            elif op == "+":
                new_lines.append(text)

        # Replace old lines with new lines
        result_lines[pos : pos + remove_count] = new_lines
        offset += len(new_lines) - remove_count

    return "".join(result_lines)


def _parse_hunks(hunks_text: str) -> list[tuple[str, list[str]]]:
    """Parse hunk headers and their lines from a chunk of diff text."""
    hunks: list[tuple[str, list[str]]] = []
    lines = hunks_text.splitlines()
    i = 0

    while i < len(lines):
        if lines[i].startswith("@@"):
            header = lines[i]
            hunk_lines: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].startswith("@@"):
                hunk_lines.append(lines[i])
                i += 1
            hunks.append((header, hunk_lines))
        else:
            i += 1

    return hunks


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_diff_tools(registry: Any, sandbox_root: Path) -> None:
    """Register all diff tools with the registry."""
    registry.register(CreateDiffTool(sandbox_root))
    registry.register(ApplyPatchTool(sandbox_root))
    registry.register(PreviewDiffTool(sandbox_root))
