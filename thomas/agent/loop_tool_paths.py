"""Filesystem path safety for tool arguments, extracted from thomas.agent.loop_tool_exec.

Every name here answers a question about a filesystem path that arrived inside
a tool call's arguments: which argument keys are paths at all, whether a tool
even accepts one, and whether a given path value is safe to hand to the
filesystem (no traversal, no absolute escape, no benchmark-root escape).

``loop_tool_exec`` calls into this module after it has parsed a tool call's
arguments and before it lets the tool run.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from thomas.core.file_access import authorize_write, is_file_access_refusal

# Same anchor filesystem.WriteFileTool uses for its own ladder check, so the
# sanitizer and the tool can never disagree about where "the project" is.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]

_WRITE_TOOL_PATH_KEYS = (
    "path",
    "file",
    "filename",
    "filepath",
    "file_path",
    "source_path",
    "destination_path",
    "payload_path",
    "auth_path",
    "auth_payload_path",
)


def _declares_a_path_parameter(registry: Any, name: str) -> bool:
    """Does this tool's own schema accept a path at all?

    Whether a tool writes was decided by looking for words in its name, and
    "patch" is one of them -- so `diff.preview_patch`, whose entire purpose is
    to preview a patch WITHOUT applying it, was classified as a write and then
    rejected for not supplying a path argument. It does not have one: its only
    parameter is the diff text, and the paths live inside that. The tool could
    therefore never be called successfully by anyone, and every attempt cost the
    model a turn and printed a technical failure into the run.

    The tool's declared parameters are the authority on what it accepts. A name
    is a label; the schema is the contract. When a tool publishes no schema we
    fall back to requiring the path, which keeps the guard closed by default.
    """

    tool = None
    getter = getattr(registry, "get", None)
    if callable(getter):
        try:
            tool = getter(name)
        except (KeyError, TypeError, ValueError):
            tool = None
    schema = getattr(tool, "parameters", None)
    if not isinstance(schema, dict):
        return True
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return True
    return any(key in properties for key in _WRITE_TOOL_PATH_KEYS)


def _absolute_path_within(path_text: str, root: Path) -> tuple[str | None, str | None]:
    """Accept an absolute path only when it resolves under ``root``."""
    try:
        resolved = Path(path_text).expanduser().resolve()
        resolved_root = root.resolve()
    except OSError as exc:
        return None, f"absolute path could not be resolved: {exc}"
    try:
        common = Path(os.path.commonpath([str(resolved_root), str(resolved)]))
    except ValueError:
        common = None
    if common is None or common.resolve() != resolved_root:
        return None, (
            f"absolute paths are not allowed outside the sandbox root {resolved_root}; this path resolves outside it"
        )
    return str(resolved), None


def _validate_filesystem_path(
    path_value: Any,
    *,
    sandbox_root: Path | None = None,
    benchmark_root: Path | None = None,
    file_access: int | None = None,
) -> tuple[str | None, str | None]:
    """(validated_path, error) for one path argument.

    ``file_access`` threads the file-access LADDER level in for absolute paths.
    Measured live (exec-c3adbfcfa341, 2026-08-07 08:50): a chat worker's Desktop
    write died here as "absolute paths are not allowed" BEFORE ``fs.write_file``
    could run its own ladder check — even though the tool documents "absolute
    paths are taken as-is (the ladder ... decides if they're allowed)". The
    ladder's refusal carries the one sentence the user can act on ("Raise the
    file-access level ..."), and this guard starved it, so the user was told
    the command failed with no mention of the setting they control.

    With a level provided, absolute paths are judged by ``authorize_write`` —
    what the ladder allows passes (the tool re-checks identically), and what it
    refuses returns the ladder's own refusal text verbatim so the remedy
    reaches the run. Without a level (``None``) behavior is unchanged: absolute
    paths are rejected outright, keeping the benchmark lane and legacy callers
    byte-identical.
    """
    if path_value is None:
        return None, "missing path value"

    try:
        path_text = os.fspath(path_value)
    except TypeError:
        return None, "path must be a string or path-like value"

    if not isinstance(path_text, str):
        return None, "path must be a string or path-like value"

    path_text = str(path_text).strip()

    if path_text == "":
        # The project root. Counted on one day's Build transcripts: 23 calls to
        # code.project_structure and code.search were refused here for asking
        # for the root with an empty path. The tool decides what "." means for
        # it; a write to a directory fails on its own terms.
        return ".", None

    if "\x00" in path_text:
        return None, "path cannot contain null bytes"

    if any(ord(ch) < 32 or ord(ch) == 127 for ch in path_text):
        return None, "path cannot contain control characters"

    if os.path.isabs(path_text) or path_text.startswith(("/", "\\")):
        if benchmark_root is None and file_access is None:
            # No ladder level and no benchmark lane: the sandbox root is the only
            # authority left. Measured on TB-4.0 run 3 (2026-09-04): 26 first calls
            # (fs.read_file, fs.list_dir, code.project_structure, eng.lint ...) were
            # refused with a bare "absolute paths are not allowed" for paths that sat
            # INSIDE the sandbox root, which the tools themselves would have accepted.
            # An absolute path that resolves under the root passes; one outside it is
            # refused with the root named so the model can rewrite the path.
            if sandbox_root is not None:
                return _absolute_path_within(path_text, sandbox_root)
            return None, "absolute paths are not allowed"
        try:
            resolved = Path(path_text).expanduser().resolve()
        except OSError as exc:
            return None, f"absolute path could not be resolved: {exc}"
        if benchmark_root is None:
            allowed, reason = authorize_write(
                file_access,
                resolved,
                workspace_root=sandbox_root,
                project_root=_PROJECT_ROOT,
            )
            if not allowed:
                return None, reason
            return str(resolved), None
        try:
            common = Path(os.path.commonpath([str(benchmark_root.resolve()), str(resolved)]))
        except ValueError:
            return None, "absolute path is outside the benchmark root"
        if common.resolve() != benchmark_root.resolve():
            return None, "absolute path is outside the benchmark root"
        return str(resolved), None

    if re.match(r"^[A-Za-z]:", path_text) or re.match(r"^[/\\]{2,}", path_text):
        return None, "disallowed root/path prefix in file path"

    if "://" in path_text:
        return None, "path cannot contain URI-like prefixes"

    parts = re.split(r"[\\/]", path_text)
    if ".." in parts:
        return None, "path traversal via '..' segment is not allowed"

    if any(part == "" for part in parts):
        return None, "path segments cannot be empty"

    # Reject any attempts to normalise into an ancestor path
    if ".." in Path(path_text).parts:
        return None, "path traversal via parent directory reference is not allowed"

    if benchmark_root is not None:
        if sandbox_root is None:
            return None, "sandbox root is required for benchmark path validation"
        try:
            candidate = (sandbox_root.resolve() / path_text).resolve()
        except OSError as exc:
            return None, f"path could not be resolved: {exc}"
        try:
            common = Path(os.path.commonpath([str(benchmark_root.resolve()), str(candidate)]))
        except ValueError:
            return None, "path is outside the benchmark root"
        if common.resolve() != benchmark_root.resolve():
            return None, "path is outside the benchmark root"

    return path_text, None


_PATCH_TEXT_KEYS = ("patch", "diff", "unified_diff")
_UNIFIED_HEADER_RE = re.compile(r"^(?:\+\+\+|---)\s+(?:[ab]/)?(?P<path>[^\t\r\n]+?)\s*(?:\t.*)?$", re.MULTILINE)
_GIT_HEADER_RE = re.compile(r"^diff --git a/(?P<a>\S+) b/(?P<b>\S+)", re.MULTILINE)
_RENAME_RE = re.compile(r"^rename (?:from|to) (?P<path>\S+)", re.MULTILINE)
_CODEX_HEADER_RE = re.compile(r"^\*\*\* (?:Update|Add|Delete) File: (?P<path>.+?)\s*$", re.MULTILINE)
_CODEX_MOVE_RE = re.compile(r"^\*\*\* Move to: (?P<path>.+?)\s*$", re.MULTILINE)


def patch_target_paths(text: str) -> list[str]:
    """Every file a patch names, in either format the patch tool accepts.

    Unified diffs name files in ``---``/``+++`` headers (``/dev/null`` is not a
    file), ``diff --git`` lines and renames; the codex format names them in
    ``*** Update/Add/Delete File:`` and ``*** Move to:`` lines.
    """

    found: list[str] = []
    body = str(text or "")
    for regex in (_UNIFIED_HEADER_RE, _GIT_HEADER_RE, _RENAME_RE, _CODEX_HEADER_RE, _CODEX_MOVE_RE):
        for match in regex.finditer(body):
            for key in ("path", "a", "b"):
                try:
                    value = match.group(key)
                except IndexError:
                    continue
                if not value:
                    continue
                value = value.strip().replace("\\", "/")
                if value and value != "/dev/null" and value not in found:
                    found.append(value)
    return found


def fenced_patch_target(args: Any, sandbox_root: Path | None, protected_paths: Any) -> str | None:
    """The fenced file a patch argument targets, or None.

    A patch carries its targets in its text, not in a path argument, so the
    path sanitizer never sees them; an audit drove the real patch tool through
    the fence that way (2026-09-07). Same fence, read from the patch.
    """

    if not protected_paths or not isinstance(args, dict):
        return None
    for key in _PATCH_TEXT_KEYS:
        text = args.get(key)
        if not isinstance(text, str) or not text.strip():
            continue
        for target in patch_target_paths(text):
            fence = _fenced_by(target, sandbox_root, protected_paths)
            if fence is not None:
                return fence
    return None


def _fenced_by(checked_path: str, sandbox_root: Path | None, protected_paths: Any) -> str | None:
    """The fenced entry ``checked_path`` falls under, or None. Entries are relative to the sandbox root."""

    if not protected_paths:
        return None
    root = Path(sandbox_root).resolve() if sandbox_root else None
    try:
        raw = Path(checked_path)
        # The sanitizer hands relative targets back relative to the sandbox;
        # judge them there, never against the process cwd.
        target = (raw if raw.is_absolute() or root is None else root / raw).resolve()
    except OSError:
        return None
    for entry in protected_paths:
        text = str(entry or "").strip().replace("\\", "/")
        if not text:
            continue
        candidate = Path(text)
        if not candidate.is_absolute():
            if root is None:
                continue
            candidate = root / candidate
        try:
            fenced = candidate.resolve()
        except OSError:
            continue
        if target == fenced or fenced in target.parents:
            return text
    return None


def _sanitize_write_tool_path(
    args: dict[str, Any],
    *,
    require_path: bool = True,
    sandbox_root: Path | None = None,
    benchmark_root: Path | None = None,
    file_access: int | None = None,
    protected_paths: list[str] | tuple[str, ...] | None = None,
) -> tuple[str | None, str | None]:
    if not isinstance(args, dict):
        return None, "tool arguments must be an object"

    validated_path: str | None = None
    saw_path_key = False

    for key in _WRITE_TOOL_PATH_KEYS:
        if key not in args:
            continue
        saw_path_key = True
        path_value = args.get(key)
        if not isinstance(path_value, (str, os.PathLike)):
            return None, f"{key} must be a string or path-like value"
        checked_path, error = _validate_filesystem_path(
            path_value,
            sandbox_root=sandbox_root,
            benchmark_root=benchmark_root,
            file_access=file_access,
        )
        if error is not None:
            if is_file_access_refusal(error):
                # A ladder refusal is a complete sentence for the model AND the
                # user (it starts with 'BLOCKED:' and may carry the user's
                # remedy). Wrapping it as "invalid path: ..." buried both the
                # shape the worker prompt names and the sentence the user needs.
                return None, error
            return None, f"invalid {key}: {error}"
        fence = _fenced_by(checked_path, sandbox_root, protected_paths)
        if fence is not None:
            # A run's file fence is enforced here, not in its brief: a Build
            # run told in prose not to edit another agent's files edited two
            # of them anyway (2026-09-06). The refusal names the fence so the
            # model can say so instead of trying again.
            return None, (
                f"BLOCKED: {fence} is fenced off for this run (another agent or the run's brief holds it); "
                "write elsewhere or report the change as not yours to make."
            )
        args[key] = checked_path
        if validated_path is None:
            validated_path = checked_path

    if not saw_path_key and require_path:
        return None, "missing path argument (expected path, file, or filename)"

    return validated_path, None


__all__ = [
    "_WRITE_TOOL_PATH_KEYS",
    "_fenced_by",
    "fenced_patch_target",
    "patch_target_paths",
    "_declares_a_path_parameter",
    "_sanitize_write_tool_path",
    "_validate_filesystem_path",
]
