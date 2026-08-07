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
        return None, "path cannot be empty"

    if "\x00" in path_text:
        return None, "path cannot contain null bytes"

    if any(ord(ch) < 32 or ord(ch) == 127 for ch in path_text):
        return None, "path cannot contain control characters"

    if os.path.isabs(path_text) or path_text.startswith(("/", "\\")):
        if benchmark_root is None and file_access is None:
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


def _sanitize_write_tool_path(
    args: dict[str, Any],
    *,
    require_path: bool = True,
    sandbox_root: Path | None = None,
    benchmark_root: Path | None = None,
    file_access: int | None = None,
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
        args[key] = checked_path
        if validated_path is None:
            validated_path = checked_path

    if not saw_path_key and require_path:
        return None, "missing path argument (expected path, file, or filename)"

    return validated_path, None


__all__ = [
    "_WRITE_TOOL_PATH_KEYS",
    "_declares_a_path_parameter",
    "_sanitize_write_tool_path",
    "_validate_filesystem_path",
]
