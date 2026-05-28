"""Filesystem tools: read, write, list, search files."""

from __future__ import annotations

import fnmatch
import hmac
import json
import logging
import os
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any

from thomas.tools.base import Tool, ToolResult

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Hardcoded protected directories — the last line of defence.
# Even if agent_safety.toml is corrupted or unreadable, these stay active.
# Every directory listed here (relative to sandbox root) is read-only for
# agent-spawned tools.  The list is deliberately minimal: only Thomas's own
# runtime, enforcement scripts, and top-level policy files.
# ---------------------------------------------------------------------------
_HARDCODED_PROTECTED_DIRS: tuple[str, ...] = (
    "thomas/tools",
    "thomas/agent",
    "thomas/core",
    "thomas/server",
    "scripts",
)

# Protected file paths (relative to sandbox root, forward-slash).
# Two categories:
#  - Top-level policy files an agent must not modify.
#  - The runtime-protection toggle flag + its signing key.  These live
#    inside the otherwise-writable runtime/ tree, but they are the
#    *bypass mechanism* — if an agent could write them via fs.write_file
#    they could disable all runtime protection.  See PR runtime-protection-
#    fix-2026-05-27 for the historical bug this closes.
_HARDCODED_PROTECTED_FILES: tuple[str, ...] = (
    "agent_safety.toml",
    "AGENTS.md",
    "GUARDRAILS.md",
    ".pre-commit-config.yaml",
    "pyproject.toml",
    "thomas.toml",
    "thomas.prod.toml",
    "runtime/.runtime_protection_disabled",
    "runtime/.runtime_protection_key",
)

# ---------------------------------------------------------------------------
# Runtime-protection toggle flag — signed-content validation.
#
# The flag file is created by ``scripts/runtime_protection_toggle.py`` after
# a successful Windows credential prompt.  The toggle script writes a JSON
# document signed with HMAC-SHA256 using a per-install key that lives in
# ``runtime/.runtime_protection_key`` (also a protected file).  Validation
# is fail-closed: any parse, IO, or signature error means the flag is
# treated as absent and runtime protection stays on.
#
# This is defense-in-depth on top of the path protection above.  Path
# protection alone blocks ``fs.write_file`` / ``diff.create`` /
# ``diff.apply_patch`` from writing either file.  Signature validation
# additionally rejects forged flags that might slip through some other
# future write path (e.g. an enabled ``shell.exec``).
# ---------------------------------------------------------------------------
_RUNTIME_FLAG_REL = "runtime/.runtime_protection_disabled"
_RUNTIME_KEY_REL = "runtime/.runtime_protection_key"
_RUNTIME_FLAG_VERSION = 1


def _runtime_signing_payload(version: int, issued_at: str, issued_by: str, repo: str) -> bytes:
    """Canonical byte string signed by the toggle script.  Order matters."""
    return f"{int(version)}|{issued_at}|{issued_by}|{repo}".encode()


def _load_runtime_protection_key(sandbox_root: Path) -> bytes | None:
    key_file = sandbox_root / _RUNTIME_KEY_REL
    try:
        raw = key_file.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not raw:
        return None
    try:
        key = bytes.fromhex(raw)
    except ValueError:
        return None
    return key or None


def _is_runtime_protection_disabled(sandbox_root: Path) -> bool:
    """Return True iff a *validly signed* disable-flag is present.

    The flag is signed by ``scripts/runtime_protection_toggle.py`` after a
    successful Windows credential prompt.  This function never prompts —
    it only verifies the signature against the per-install HMAC key.

    Fail-closed: any IO error, parse error, missing key, missing/invalid
    signature, or sandbox-root mismatch returns False (protection stays on).
    """
    resolved_root = sandbox_root.resolve()
    flag_file = resolved_root / _RUNTIME_FLAG_REL
    if not flag_file.is_file():
        return False

    try:
        raw = flag_file.read_text(encoding="utf-8")
    except OSError as exc:
        log.warning("runtime-protection flag unreadable; treating as absent: %s", exc)
        return False

    try:
        doc = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        log.warning("runtime-protection flag is not valid JSON; ignoring: %s", exc)
        return False
    if not isinstance(doc, dict):
        log.warning("runtime-protection flag root is not an object; ignoring")
        return False

    try:
        version = int(doc.get("version", 0))
    except (TypeError, ValueError):
        version = 0
    if version != _RUNTIME_FLAG_VERSION:
        log.warning("runtime-protection flag version %r unsupported; ignoring", doc.get("version"))
        return False

    issued_at = str(doc.get("issued_at") or "")
    issued_by = str(doc.get("issued_by") or "")
    repo = str(doc.get("repo") or "")
    signature_hex = str(doc.get("signature") or "")
    if not issued_at or not issued_by or not repo or not signature_hex:
        log.warning("runtime-protection flag missing required fields; ignoring")
        return False

    expected_repo = str(resolved_root)
    # Compare resolved paths case-insensitively on Windows.
    if os.name == "nt":
        if repo.lower() != expected_repo.lower():
            log.warning(
                "runtime-protection flag repo mismatch (flag=%r, sandbox=%r); ignoring",
                repo,
                expected_repo,
            )
            return False
    elif repo != expected_repo:
        log.warning(
            "runtime-protection flag repo mismatch (flag=%r, sandbox=%r); ignoring",
            repo,
            expected_repo,
        )
        return False

    key = _load_runtime_protection_key(resolved_root)
    if key is None:
        log.warning("runtime-protection signing key missing/invalid; ignoring flag")
        return False

    try:
        signature = bytes.fromhex(signature_hex)
    except ValueError:
        log.warning("runtime-protection flag signature is not hex; ignoring")
        return False

    expected = hmac.new(
        key,
        _runtime_signing_payload(version, issued_at, issued_by, repo),
        sha256,
    ).digest()
    if not hmac.compare_digest(expected, signature):
        log.warning("runtime-protection flag signature mismatch; ignoring")
        return False

    return True


def _is_protected_runtime_path(
    sandbox_root: Path,
    target: Path,
    *,
    allow_native_auth_override: bool = False,
    action_description: str = "",
) -> str | None:
    """Check if *target* falls inside a protected runtime directory or matches
    a protected file.

    Returns a human-readable reason string if the path is protected, or
    ``None`` if the write is allowed.

    The check is intentionally independent of any config file so that an agent
    cannot neutralise it by editing ``agent_safety.toml`` — that file is
    itself inside the protected set.

    Two bypass mechanisms (both require physical human presence at the OS):

    1. *Persistent* — a human runs ``python scripts/runtime_protection_toggle.py off``
       which requires Windows credential authentication and creates a flag
       file that disables runtime protection until toggled back on.

    2. *Per-operation* — set ``allow_native_auth_override=True`` to make this
       call attempt a one-shot native OS auth prompt (Win Hello / Touch ID /
       polkit) when the path would otherwise be refused. If the prompt is
       approved, this single call returns ``None`` (the operation is allowed).
       If denied/cancelled/unavailable, the refusal reason is returned as
       before.  This is the architecture extension landed in
       gate-architecture-2026-05-26 (see docs/SAFETY_ARCHITECTURE.md).
       Existing callers that don't pass the kwarg get unchanged behavior.

    The two *runtime-protection control files* (the disable flag and the HMAC
    key) are **absolutely protected**: the persistent-disable bypass does NOT
    apply to them.  Otherwise an active disable state could be used to
    overwrite the key with attacker-controlled bytes and persist a bypass
    across the next toggle cycle (Codex hardening review, msg-20260527214458).
    Calvin can still write them via the per-operation native-auth override.
    """
    try:
        rel = target.resolve().relative_to(sandbox_root.resolve())
    except ValueError:
        # Outside sandbox entirely — _safe_path already handles this.
        return None

    # Normalise to forward-slash for consistent matching on all platforms.
    rel_posix = PurePosixPath(rel)
    rel_posix_str = str(rel_posix)

    # ── Always-protected: runtime-protection control files ────────────────
    # These must never be bypassed by the disable flag itself.  Calvin can
    # still reach them through the per-operation native-auth override below.
    if rel_posix_str in {_RUNTIME_FLAG_REL, _RUNTIME_KEY_REL}:
        reason = (
            f"BLOCKED: '{rel_posix_str}' is a runtime-protection control file. "
            "Only scripts/runtime_protection_toggle.py (Windows-auth required) "
            "may write here, regardless of the persistent disable flag."
        )
        return _maybe_apply_native_auth_override(
            reason=reason,
            rel_posix=rel_posix,
            allow_native_auth_override=allow_native_auth_override,
            action_description=action_description,
        )

    # Allow bypass when a human has explicitly disabled protection
    # (control files above are exempt from this bypass).
    if _is_runtime_protection_disabled(sandbox_root):
        return None

    reason: str | None = None

    # Check protected directories (any file *inside* these).
    for pdir in _HARDCODED_PROTECTED_DIRS:
        protected = PurePosixPath(pdir)
        try:
            rel_posix.relative_to(protected)
            reason = (
                f"BLOCKED: '{rel_posix}' is inside protected runtime "
                f"directory '{pdir}/'. Agent-spawned tools cannot modify "
                f"Thomas's own runtime code."
            )
            break
        except ValueError:
            continue

    if reason is None:
        # Check individual protected files at the repo root.
        for pfile in _HARDCODED_PROTECTED_FILES:
            if rel_posix == PurePosixPath(pfile):
                reason = f"BLOCKED: '{rel_posix}' is a protected policy file. Agent-spawned tools cannot modify it."
                break

    if reason is None:
        return None

    return _maybe_apply_native_auth_override(
        reason=reason,
        rel_posix=rel_posix,
        allow_native_auth_override=allow_native_auth_override,
        action_description=action_description,
    )


def _maybe_apply_native_auth_override(
    *,
    reason: str,
    rel_posix: PurePosixPath,
    allow_native_auth_override: bool,
    action_description: str,
) -> str | None:
    """Per-operation native-auth gate: if approved, return None (allow)."""
    if not allow_native_auth_override:
        return reason

    # Import lazily so filesystem.py doesn't drag GUI/credential-dialog
    # dependencies into every import path.
    try:
        from thomas.tools.native_auth import request_native_authorization
    except (ImportError, OSError, RuntimeError) as exc:
        log.warning(
            "Protected path '%s': native-auth module unavailable (%s); honoring refusal",
            rel_posix,
            exc,
        )
        return reason

    action_text = action_description or f"Modify protected runtime path: {rel_posix}"
    auth_reason = (
        "An agent-spawned tool is attempting to modify a protected Thomas "
        "runtime path. Approve only if you initiated this operation.\n\n"
        f"{reason}"
    )

    try:
        approved = request_native_authorization(action_text, auth_reason)
    except (OSError, RuntimeError) as exc:
        log.warning(
            "Protected path '%s': native-auth raised (%s); honoring refusal",
            rel_posix,
            exc,
        )
        return reason

    if approved:
        log.warning(
            "Protected path '%s' APPROVED via native OS auth override (%s)",
            rel_posix,
            action_text,
        )
        return None

    log.info(
        "Protected path '%s' REFUSED — native OS auth not granted",
        rel_posix,
    )
    return reason


def _is_read_protected_path(sandbox_root: Path, target: Path) -> str | None:
    """Return a refusal reason if *target* must not be readable by agent tools.

    Currently scoped to the HMAC signing key.  The disable-flag file is
    metadata only (timestamp + user + signature) and is harmless to read —
    forging it requires the key.  Protecting the key's read path is
    defense-in-depth alongside the write-side path protection (Codex
    hardening review msg-20260527214458).
    """
    try:
        rel = target.resolve().relative_to(sandbox_root.resolve())
    except ValueError:
        return None
    rel_posix_str = str(PurePosixPath(rel))
    if rel_posix_str == _RUNTIME_KEY_REL:
        return (
            f"BLOCKED: '{rel_posix_str}' is the runtime-protection signing key. "
            "Agent tools cannot read it; doing so would let an attacker mint "
            "valid disable flags."
        )
    return None


def _safe_path(root: Path, rel: str) -> Path:
    """Resolve path and ensure it doesn't escape the sandbox root.

    Uses os.path.commonpath for case-insensitive comparison on Windows,
    which handles case differences (C:\\Users vs c:\\users) and prevents
    symlink/junction escapes.
    """
    resolved_root = root.resolve()
    p = (resolved_root / rel).resolve()
    try:
        common = Path(os.path.commonpath([str(resolved_root), str(p)]))
        # On Windows, paths are case-insensitive
        if os.name == "nt":
            if common.resolve() != resolved_root:
                raise ValueError(f"Path escapes sandbox: {rel}")
        else:
            if common != resolved_root:
                raise ValueError(f"Path escapes sandbox: {rel}")
    except ValueError:
        raise ValueError(f"Path escapes sandbox: {rel}") from None
    return p


class ReadFileTool(Tool):
    name = "fs.read_file"
    category = "filesystem"
    description = (
        "Read the contents of a text file. Supports optional line range "
        "(start_line, end_line) for reading portions of large files."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative or absolute path to the file",
            },
            "start_line": {
                "type": "integer",
                "description": "First line to read (1-based). Omit to read from start.",
            },
            "end_line": {
                "type": "integer",
                "description": "Last line to read (inclusive). Omit to read to end.",
            },
        },
        "required": ["path"],
    }

    def __init__(self, sandbox_root: Path, max_file_size: int = 5_000_000):
        self._root = sandbox_root.resolve()
        self._max_size = max_file_size

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        rel = args["path"]
        try:
            path = _safe_path(self._root, rel)
        except ValueError as e:
            return ToolResult(ok=False, error=str(e))

        # ── Read protection: refuse the runtime-protection signing key ──
        read_blocked = _is_read_protected_path(self._root, path)
        if read_blocked:
            log.warning("Read refused: %s", read_blocked)
            return ToolResult(ok=False, error=read_blocked)

        if not path.exists():
            return ToolResult(ok=False, error=f"File not found: {rel}")
        if not path.is_file():
            return ToolResult(ok=False, error=f"Not a file: {rel}")

        size = path.stat().st_size
        if size > self._max_size:
            return ToolResult(
                ok=False,
                error=f"File too large ({size:,} bytes, max {self._max_size:,}). "
                f"Use start_line/end_line to read a portion.",
            )

        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines(keepends=True)

        start = args.get("start_line")
        end = args.get("end_line")
        if start is not None or end is not None:
            s = (start or 1) - 1
            e = end or len(lines)
            lines = lines[s:e]
            # Add line numbers
            numbered = []
            for i, ln in enumerate(lines, start=s + 1):
                numbered.append(f"{i:>6}\t{ln}")
            text = "".join(numbered)
        else:
            # Add line numbers for full file
            numbered = []
            for i, ln in enumerate(lines, start=1):
                numbered.append(f"{i:>6}\t{ln}")
            text = "".join(numbered)

        return ToolResult(ok=True, data=text)


class WriteFileTool(Tool):
    name = "fs.write_file"
    category = "filesystem"
    description = "Write content to a file. Creates parent directories if needed."
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative or absolute path for the file",
            },
            "content": {
                "type": "string",
                "description": "The text content to write",
            },
        },
        "required": ["path", "content"],
    }

    def __init__(self, sandbox_root: Path):
        self._root = sandbox_root.resolve()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        rel = args["path"]
        try:
            path = _safe_path(self._root, rel)
        except ValueError as e:
            return ToolResult(ok=False, error=str(e))

        # ── Runtime protection: block writes to Thomas's own code ──
        blocked = _is_protected_runtime_path(self._root, path)
        if blocked:
            log.warning("Runtime protection triggered: %s", blocked)
            return ToolResult(ok=False, error=blocked)

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(args["content"], encoding="utf-8")
        return ToolResult(ok=True, data=f"Wrote {len(args['content'])} chars to {rel}")


class WriteProtectedFileTool(Tool):
    """Write a file at a runtime-protected path with native OS authorization.

    Standard ``fs.write_file`` refuses writes inside protected paths
    (``thomas/tools/``, ``thomas/agent/``, ``thomas/core/``, ``thomas/server/``,
    ``scripts/``, top-level policy files, the runtime-protection flag).

    This tool wraps the *same* write logic but flips the
    ``allow_native_auth_override`` kwarg on the protection check.  When the
    target path is protected, the call attempts a one-shot native OS auth
    prompt (Windows Hello / Touch ID / polkit).  If a human at the physical
    device approves, this single write is allowed and audit-logged.  If
    denied/cancelled/unavailable, the standard refusal is returned.

    Headless sessions (no interactive desktop) cannot satisfy the prompt,
    so this tool is effectively unusable for protected paths in that
    context — which is the point.
    """

    name = "fs.write_protected_file"
    category = "filesystem"
    description = (
        "Write a file at a runtime-protected path. Requires a native OS "
        "authorization prompt (Windows Hello/PIN, Touch ID, or polkit) for "
        "any path inside thomas/tools/, thomas/agent/, thomas/core/, "
        "thomas/server/, scripts/, or any top-level policy file. Use only "
        "when an interactive human is present at the device. For unprotected "
        "paths this tool behaves like fs.write_file."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative or absolute path for the file",
            },
            "content": {
                "type": "string",
                "description": "The text content to write",
            },
            "reason": {
                "type": "string",
                "description": (
                    "Short human-readable reason shown in the OS auth prompt "
                    "(e.g. 'Apply emergency fix to thomas/tools/filesystem.py')."
                ),
            },
        },
        "required": ["path", "content", "reason"],
    }

    def __init__(self, sandbox_root: Path):
        self._root = sandbox_root.resolve()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        rel = args["path"]
        reason = str(args.get("reason") or "").strip()
        if not reason:
            return ToolResult(
                ok=False,
                error="fs.write_protected_file requires a non-empty 'reason' for the OS auth prompt.",
            )

        try:
            path = _safe_path(self._root, rel)
        except ValueError as e:
            return ToolResult(ok=False, error=str(e))

        action_description = f"Write protected runtime path: {rel} — {reason}"
        blocked = _is_protected_runtime_path(
            self._root,
            path,
            allow_native_auth_override=True,
            action_description=action_description,
        )
        if blocked:
            log.warning("Runtime protection refused (even with OS auth override): %s", blocked)
            return ToolResult(ok=False, error=blocked)

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(args["content"], encoding="utf-8")
        log.warning(
            "fs.write_protected_file: wrote %d chars to '%s' (reason=%r)",
            len(args["content"]),
            rel,
            reason,
        )
        return ToolResult(
            ok=True,
            data=f"Wrote {len(args['content'])} chars to {rel} (via OS-auth override)",
        )


class ListDirTool(Tool):
    name = "fs.list_dir"
    category = "filesystem"
    description = (
        "List files and directories. Supports glob patterns. Returns file names with type indicators (/ for dirs)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Directory to list (default: current directory)",
            },
            "pattern": {
                "type": "string",
                "description": "Glob pattern to filter results (e.g. '*.py', '**/*.ts')",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum entries to return (default: 200)",
            },
        },
    }

    def __init__(self, sandbox_root: Path):
        self._root = sandbox_root.resolve()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        rel = args.get("path", ".")
        pattern = args.get("pattern", "*")
        max_results = args.get("max_results", 200)

        try:
            base = _safe_path(self._root, rel)
        except ValueError as e:
            return ToolResult(ok=False, error=str(e))

        if not base.exists():
            return ToolResult(ok=False, error=f"Directory not found: {rel}")
        if not base.is_dir():
            return ToolResult(ok=False, error=f"Not a directory: {rel}")

        entries: list[str] = []
        try:
            for p in sorted(base.glob(pattern)):
                if len(entries) >= max_results:
                    entries.append(f"... (truncated at {max_results} results)")
                    break
                rel_path = p.relative_to(self._root)
                suffix = "/" if p.is_dir() else ""
                entries.append(f"{rel_path}{suffix}")
        except (OSError, ValueError) as e:
            return ToolResult(ok=False, error=f"Glob error: {e}")

        if not entries:
            return ToolResult(ok=True, data="(empty directory)")
        return ToolResult(ok=True, data="\n".join(entries))


class SearchFilesTool(Tool):
    name = "fs.search"
    category = "filesystem"
    description = (
        "Search for text in files using regex or literal match. "
        "Returns matching lines with file paths and line numbers."
    )
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Text or regex pattern to search for",
            },
            "path": {
                "type": "string",
                "description": "Directory to search in (default: project root)",
            },
            "glob": {
                "type": "string",
                "description": "File pattern to search within (e.g. '*.py')",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum matches to return (default: 50)",
            },
        },
        "required": ["pattern"],
    }

    def __init__(self, sandbox_root: Path):
        self._root = sandbox_root.resolve()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        import re

        pattern_str = args["pattern"]
        rel = args.get("path", ".")
        file_glob = args.get("glob", "*")
        max_results = args.get("max_results", 50)

        try:
            base = _safe_path(self._root, rel)
        except ValueError as e:
            return ToolResult(ok=False, error=str(e))

        try:
            regex = re.compile(pattern_str, re.IGNORECASE)
        except re.error as e:
            return ToolResult(ok=False, error=f"Invalid regex: {e}")

        matches: list[str] = []
        files_searched = 0
        _skip_dirs = {".git", "node_modules", "__pycache__", ".venv", "venv", ".tox"}

        for dirpath, dirnames, filenames in os.walk(base):
            # Skip common non-content directories
            dirnames[:] = [d for d in dirnames if d not in _skip_dirs]

            for fname in filenames:
                if not fnmatch.fnmatch(fname, file_glob):
                    continue
                fpath = Path(dirpath) / fname
                # Never search the contents of read-protected files
                # (would leak the HMAC key).
                if _is_read_protected_path(self._root, fpath):
                    continue
                files_searched += 1

                try:
                    text = fpath.read_text(encoding="utf-8", errors="replace")
                except (OSError, UnicodeDecodeError):
                    continue

                for lineno, line in enumerate(text.splitlines(), 1):
                    if regex.search(line):
                        rel_path = fpath.relative_to(self._root)
                        matches.append(f"{rel_path}:{lineno}: {line.rstrip()}")
                        if len(matches) >= max_results:
                            break
                if len(matches) >= max_results:
                    break
            if len(matches) >= max_results:
                break

        if not matches:
            return ToolResult(
                ok=True,
                data=f"No matches found (searched {files_searched} files)",
            )
        header = f"Found {len(matches)} matches (searched {files_searched} files):\n"
        return ToolResult(ok=True, data=header + "\n".join(matches))


def register_filesystem_tools(registry: Any, sandbox_root: Path, max_file_size: int = 5_000_000) -> None:
    """Register all filesystem tools with the registry."""
    registry.register(ReadFileTool(sandbox_root, max_file_size))
    registry.register(WriteFileTool(sandbox_root))
    registry.register(WriteProtectedFileTool(sandbox_root))
    registry.register(ListDirTool(sandbox_root))
    registry.register(SearchFilesTool(sandbox_root))
