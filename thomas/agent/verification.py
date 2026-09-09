"""Post-edit verification hooks for Thomas agent loop.

Comprehensive verification system with:
  - Multiple verifiers (syntax, lint, import, boot, diff-based)
  - Verification pipeline with short-circuit on failure
  - Auto-remediation with error context
  - Structured result tracking
  - Configuration for selective verification

Inspired by Claude Code's verification-first architecture:
after every tool execution that modifies files, run lightweight
checks to catch errors before they compound.

Main hooks:
  - Python syntax check (py_compile) on .py files
  - Import smoke test on modified Python modules
  - File size guard (GUARDRAILS.md limits)
  - Lint check via ruff (configurable)
  - Boot test via `python -m thomas serve --port 0`
  - Diff analysis for destructive operations
"""

from __future__ import annotations

import asyncio
import logging
import py_compile
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from thomas.core.py_compile_safe import compile_no_repo_pyc

log = logging.getLogger(__name__)

# A valid dotted Python module name. Used to gate the post-write import probe so
# a model-controlled filename that is not a real module (containing ';', spaces,
# quotes, ...) is never handed to the interpreter.
_MODULE_NAME_RE = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*")

# File size limits from GUARDRAILS.md
_SIZE_LIMITS = {
    ".py": {"soft": 800, "hard": 1200},
    ".js": {"soft": 800, "hard": 2000},
    ".mjs": {"soft": 800, "hard": 2000},
    ".css": {"soft": 600, "hard": 1200},
    ".html": {"soft": 2000, "hard": 3000},
}


@dataclass
class VerificationResult:
    """Result from a single verification check."""

    passed: bool
    verifier_name: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for logging/serialization."""
        return {
            "passed": self.passed,
            "verifier": self.verifier_name,
            "message": self.message,
            "details": self.details,
            "duration_ms": self.duration_ms,
        }


@dataclass
class VerificationConfig:
    """Configuration for verification pipeline."""

    enabled: bool = True
    auto_lint: bool = False
    auto_test: bool = False
    auto_remediate: bool = False
    max_retries: int = 1


class Verifier(ABC):
    """Base class for verification checks."""

    @abstractmethod
    async def verify(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        tool_result: dict[str, Any],
    ) -> VerificationResult:
        """Run verification on tool output.

        Args:
            tool_name: Name of the tool that ran
            tool_args: Arguments passed to the tool
            tool_result: Result returned by the tool

        Returns:
            VerificationResult with pass/fail status
        """
        ...


class SyntaxVerifier(Verifier):
    """Verify Python syntax on edited .py files."""

    async def verify(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        tool_result: dict[str, Any],
    ) -> VerificationResult:
        """Check Python syntax."""
        file_path = self._extract_file_path(tool_args)
        if not file_path or not file_path.endswith(".py"):
            return VerificationResult(True, "SyntaxVerifier", "Skipped (not Python)")

        path = Path(file_path)
        if not path.exists():
            return VerificationResult(True, "SyntaxVerifier", "Skipped (file not found)")

        try:
            compile_no_repo_pyc(path, doraise=True)
            return VerificationResult(True, "SyntaxVerifier", f"{path.name}: Syntax OK")
        except py_compile.PyCompileError as e:
            return VerificationResult(
                False,
                "SyntaxVerifier",
                f"{path.name}: Syntax error",
                {"error": str(e), "line": getattr(e, "exc_value", None)},
            )

    @staticmethod
    def _extract_file_path(args: dict[str, Any]) -> str | None:
        """Extract file path from tool args."""
        for key in ("path", "file", "filename", "filepath", "file_path", "target"):
            val = args.get(key)
            if val and isinstance(val, str):
                return val
        return None


class LintVerifier(Verifier):
    """Run ruff linter on Python files."""

    async def verify(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        tool_result: dict[str, Any],
    ) -> VerificationResult:
        """Run ruff check."""
        file_path = self._extract_file_path(tool_args)
        if not file_path or not file_path.endswith(".py"):
            return VerificationResult(True, "LintVerifier", "Skipped (not Python)")

        path = Path(file_path)
        if not path.exists():
            return VerificationResult(True, "LintVerifier", "Skipped (file not found)")

        try:
            proc = await asyncio.create_subprocess_exec(
                "python",
                "-m",
                "ruff",
                "check",
                "--select=E,F",
                str(path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)

            if proc.returncode == 0:
                return VerificationResult(True, "LintVerifier", f"{path.name}: No lint issues")
            else:
                output = stdout.decode("utf-8", errors="replace").strip()
                error_lines = output.split("\n") if output else []
                return VerificationResult(
                    False,
                    "LintVerifier",
                    f"{path.name}: Lint issues found",
                    {"errors": error_lines[:10]},
                )
        except (asyncio.TimeoutError, FileNotFoundError, OSError) as e:
            return VerificationResult(
                False,
                "LintVerifier",
                "Lint check failed",
                {"error": str(e)},
            )

    @staticmethod
    def _extract_file_path(args: dict[str, Any]) -> str | None:
        """Extract file path from tool args."""
        for key in ("path", "file", "filename", "filepath", "file_path", "target"):
            val = args.get(key)
            if val and isinstance(val, str):
                return val
        return None


class ImportVerifier(Verifier):
    """Verify Python module can be imported."""

    async def verify(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        tool_result: dict[str, Any],
    ) -> VerificationResult:
        """Test import of edited module."""
        file_path = self._extract_file_path(tool_args)
        if not file_path or not file_path.endswith(".py"):
            return VerificationResult(True, "ImportVerifier", "Skipped (not Python)")

        path = Path(file_path)
        if not path.exists():
            return VerificationResult(True, "ImportVerifier", "Skipped (file not found)")

        # Construct module name from directory structure
        module_parts = []
        for parent in reversed(path.parents):
            init = parent / "__init__.py"
            if init.exists():
                module_parts.insert(0, parent.name)
            else:
                break

        if not module_parts:
            return VerificationResult(True, "ImportVerifier", "Not a package module")

        module_name = ".".join(module_parts + [path.stem])

        try:
            proc = await asyncio.create_subprocess_exec(
                "python",
                "-c",
                f"import {module_name}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)

            if proc.returncode == 0:
                return VerificationResult(True, "ImportVerifier", f"{module_name}: Import OK")
            else:
                err_text = stderr.decode("utf-8", errors="replace").strip()
                # Filter out common missing dep errors
                if "ModuleNotFoundError" not in err_text:
                    return VerificationResult(
                        False,
                        "ImportVerifier",
                        f"{module_name}: Import failed",
                        {"error": err_text[:200]},
                    )
                return VerificationResult(True, "ImportVerifier", "Skipped (missing dependency)")
        except (asyncio.TimeoutError, OSError) as e:
            return VerificationResult(
                False,
                "ImportVerifier",
                "Import check failed",
                {"error": str(e)},
            )

    @staticmethod
    def _extract_file_path(args: dict[str, Any]) -> str | None:
        """Extract file path from tool args."""
        for key in ("path", "file", "filename", "filepath", "file_path", "target"):
            val = args.get(key)
            if val and isinstance(val, str):
                return val
        return None


class BootVerifier(Verifier):
    """Verify application boots after structural changes."""

    async def verify(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        tool_result: dict[str, Any],
    ) -> VerificationResult:
        """Test boot with `python -m thomas serve --port 0`."""
        # Only run if this looks like a structural change
        if not self._is_structural_change(tool_name, tool_args):
            return VerificationResult(True, "BootVerifier", "Skipped (not structural)")

        try:
            proc = await asyncio.create_subprocess_exec(
                "python",
                "-m",
                "thomas",
                "serve",
                "--port",
                "0",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            # Give it a few seconds to start or fail
            try:
                _stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
            except asyncio.TimeoutError:
                # If timeout, kill it (likely booted successfully)
                proc.kill()
                await asyncio.wait_for(proc.wait(), timeout=2)
                return VerificationResult(True, "BootVerifier", "Boot successful (timeout)")

            if proc.returncode == 0:
                return VerificationResult(True, "BootVerifier", "Boot successful")
            else:
                err_text = stderr.decode("utf-8", errors="replace").strip()
                return VerificationResult(
                    False,
                    "BootVerifier",
                    "Boot failed",
                    {"error": err_text[:300]},
                )
        except OSError as e:
            return VerificationResult(
                False,
                "BootVerifier",
                "Boot test failed",
                {"error": str(e)},
            )

    @staticmethod
    def _is_structural_change(tool_name: str, args: dict[str, Any]) -> bool:
        """Check if this looks like a structural change."""
        patterns = {"__init__", "__main__", "setup", "config", "boot"}
        file_path = args.get("path") or args.get("file") or args.get("filepath") or ""
        file_path_str = str(file_path).lower()
        return any(p in file_path_str for p in patterns)


class DiffVerifier(Verifier):
    """Analyze diff for destructive operations."""

    async def verify(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        tool_result: dict[str, Any],
    ) -> VerificationResult:
        """Check for dangerous diff patterns."""
        import re

        file_path = self._extract_file_path(tool_args)
        if not file_path:
            return VerificationResult(True, "DiffVerifier", "No file path")

        path = Path(file_path)
        if not path.exists():
            return VerificationResult(True, "DiffVerifier", "File not found")

        try:
            # Read current content
            content = path.read_text(errors="replace")

            # Flag dangerous patterns
            dangerous_patterns = [
                (r"^[^#]*exec\s*\(", "exec() statement"),
                (r"^[^#]*eval\s*\(", "eval() statement"),
                (r"^[^#]*__import__\s*\(", "__import__() call"),
                (r"import\s+subprocess|from\s+subprocess", "subprocess without guards"),
                (r"\.shell\s*=|shell\s*=\s*True", "shell=True in subprocess"),
            ]

            warnings = []
            for pattern, name in dangerous_patterns:
                if re.search(pattern, content, re.MULTILINE):
                    warnings.append(name)

            if warnings:
                return VerificationResult(
                    False,
                    "DiffVerifier",
                    f"{path.name}: Dangerous patterns detected",
                    {"patterns": warnings},
                )

            return VerificationResult(True, "DiffVerifier", f"{path.name}: Diff OK")
        except OSError as e:
            return VerificationResult(
                False,
                "DiffVerifier",
                "Diff check failed",
                {"error": str(e)},
            )

    @staticmethod
    def _extract_file_path(args: dict[str, Any]) -> str | None:
        """Extract file path from tool args."""
        for key in ("path", "file", "filename", "filepath", "file_path", "target"):
            val = args.get(key)
            if val and isinstance(val, str):
                return val
        return None


class VerificationPipeline:
    """Chain multiple verifiers with configurable behavior."""

    def __init__(
        self,
        verifiers: list[Verifier] | None = None,
        config: VerificationConfig | None = None,
    ):
        """Initialize pipeline.

        Args:
            verifiers: List of verifiers to run (default: all)
            config: Verification configuration
        """
        self.verifiers = verifiers or [
            SyntaxVerifier(),
            ImportVerifier(),
            LintVerifier(),
            DiffVerifier(),
        ]
        self.config = config or VerificationConfig()

    async def verify(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        tool_result: dict[str, Any],
    ) -> tuple[bool, list[VerificationResult]]:
        """Run verification pipeline.

        Short-circuits on first failure if configured.

        Args:
            tool_name: Tool that executed
            tool_args: Tool arguments
            tool_result: Tool result

        Returns:
            Tuple of (all_passed, list_of_results)
        """
        if not self.config.enabled:
            return True, []

        if not self._should_verify(tool_name, tool_args):
            return True, []

        results: list[VerificationResult] = []

        for verifier in self.verifiers:
            try:
                result = await verifier.verify(tool_name, tool_args, tool_result)
                results.append(result)

                if not result.passed:
                    log.warning(
                        "Verification failed: %s - %s",
                        result.verifier_name,
                        result.message,
                    )
                    # Short-circuit if configured
                    break

            except Exception as e:
                log.error("Verifier %s crashed: %s", verifier.__class__.__name__, e)
                result = VerificationResult(
                    False,
                    verifier.__class__.__name__,
                    f"Verifier crashed: {e}",
                )
                results.append(result)
                break

        all_passed = all(r.passed for r in results)
        return all_passed, results

    @staticmethod
    def _should_verify(tool_name: str, tool_args: dict[str, Any]) -> bool:
        """Check if this tool call should be verified."""
        write_patterns = {
            "fs.write",
            "fs.create",
            "fs.edit",
            "fs.append",
            "fs.replace",
            "fs.rename",
            "fs.move",
            "fs.delete",
            "fs.mkdir",
            "shell.exec",
            "shell.run",
            "git.commit",
            "git.apply",
        }
        name_lower = tool_name.lower()
        return any(p in name_lower for p in write_patterns)


class AutoRemediator:
    """Generate remediation prompts when verification fails."""

    @staticmethod
    def generate_remediation_prompt(
        tool_name: str,
        results: list[VerificationResult],
    ) -> str:
        """Generate a remediation prompt with error context.

        Args:
            tool_name: Tool that failed
            results: Verification results with failures

        Returns:
            Remediation prompt for agent
        """
        failures = [r for r in results if not r.passed]
        if not failures:
            return ""

        parts = ["[VERIFICATION FAILED]"]
        parts.append(f"Tool: {tool_name}")
        parts.append("")

        for failure in failures:
            parts.append(f"Verifier: {failure.verifier_name}")
            parts.append(f"Issue: {failure.message}")
            if failure.details:
                for key, val in list(failure.details.items())[:3]:
                    parts.append(f"  - {key}: {val}")
            parts.append("")

        parts.append("Please fix the issues and try again.")

        return "\n".join(parts)


def should_verify(tool_name: str, tool_args: dict[str, Any]) -> bool:
    """Check if a tool call should be verified.

    Convenience function.

    Args:
        tool_name: Tool being called
        tool_args: Tool arguments

    Returns:
        True if should verify
    """
    write_patterns = {
        "fs.write",
        "fs.create",
        "fs.edit",
        "fs.append",
        "fs.replace",
        "fs.rename",
        "fs.move",
        "fs.delete",
        "fs.mkdir",
        "shell.exec",
        "shell.run",
        "git.commit",
        "git.apply",
    }
    name_lower = tool_name.lower()
    return any(p in name_lower for p in write_patterns)


async def verify_after_tool(
    tool_name: str,
    args: dict[str, Any],
    result_ok: bool,
    sandbox_root: str | None = None,
    *,
    enable_lint: bool = False,
) -> list[dict[str, Any]]:
    """Legacy verification function (backward compatible).

    Runs basic checks (syntax, size, import).

    Args:
        tool_name: Tool that executed
        args: Tool arguments
        result_ok: Whether tool succeeded
        sandbox_root: Root directory for relative paths
        enable_lint: Whether to run lint

    Returns:
        List of issue dicts
    """
    if not result_ok or not should_verify(tool_name, args):
        return []

    file_path = None
    for key in ("path", "file", "filename", "filepath", "file_path", "target"):
        val = args.get(key)
        if val and isinstance(val, str):
            file_path = val
            break

    if not file_path:
        return []

    issues: list[dict[str, Any]] = []
    path = Path(file_path)

    if sandbox_root and not path.is_absolute():
        path = Path(sandbox_root) / path

    if not path.exists():
        return []

    # Check file size
    try:
        line_count = len(path.read_bytes().split(b"\n"))
        suffix = path.suffix.lower()
        limits = _SIZE_LIMITS.get(suffix)
        if limits:
            if line_count > limits["hard"]:
                issues.append(
                    {
                        "level": "error",
                        "check": "file_size",
                        "message": (
                            f"{path.name}: {line_count} lines exceeds hard limit "
                            f"of {limits['hard']} for {suffix} files. "
                            f"Split this file before proceeding."
                        ),
                    }
                )
            elif line_count > limits["soft"]:
                issues.append(
                    {
                        "level": "warning",
                        "check": "file_size",
                        "message": (
                            f"{path.name}: {line_count} lines exceeds soft limit "
                            f"of {limits['soft']} for {suffix} files. "
                            f"Consider splitting."
                        ),
                    }
                )
    except OSError as oe:
        log.debug("File size check failed for %s: %s", path, oe)

    # Python syntax check
    if path.suffix.lower() == ".py":
        try:
            compile_no_repo_pyc(path, doraise=True)
        except py_compile.PyCompileError as pce:
            issues.append(
                {
                    "level": "error",
                    "check": "syntax",
                    "message": f"{path.name}: Syntax error — {pce}",
                }
            )

    # Python import check
    if path.suffix.lower() == ".py" and not any(i["check"] == "syntax" for i in issues):
        module_parts = []
        for parent in reversed(path.parents):
            init = parent / "__init__.py"
            if init.exists():
                module_parts.insert(0, parent.name)
            else:
                break
        module_name = ".".join(module_parts + [path.stem]) if module_parts else ""
        # Only probe a genuinely valid dotted module name. A path component or
        # stem with non-identifier characters (';', spaces, ...) is never a real
        # importable module -- and must not reach the interpreter, since the name
        # is passed to `python` as DATA (sys.argv[1]) below rather than spliced
        # into the source, but the regex is a defense-in-depth second layer.
        if module_parts and _MODULE_NAME_RE.fullmatch(module_name):
            try:
                proc = await asyncio.create_subprocess_exec(
                    "python",
                    "-c",
                    "import importlib, sys; importlib.import_module(sys.argv[1])",
                    module_name,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=sandbox_root or ".",
                )
                _stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
                if proc.returncode != 0:
                    err_text = stderr.decode("utf-8", errors="replace").strip()
                    if "ModuleNotFoundError" not in err_text:
                        issues.append(
                            {
                                "level": "warning",
                                "check": "import",
                                "message": f"{path.name}: Import check failed — {err_text[:200]}",
                            }
                        )
            except (asyncio.TimeoutError, OSError) as exc:
                log.debug("Import check timed out for %s: %s", path, exc)

    # Optional lint
    if enable_lint and path.suffix.lower() == ".py":
        try:
            proc = await asyncio.create_subprocess_exec(
                "python",
                "-m",
                "ruff",
                "check",
                "--select=E,F",
                str(path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
            if proc.returncode != 0:
                lint_out = stdout.decode("utf-8", errors="replace").strip()
                error_count = lint_out.count("\n") + 1 if lint_out else 0
                if error_count > 0:
                    issues.append(
                        {
                            "level": "warning",
                            "check": "lint",
                            "message": f"{path.name}: {error_count} lint issues found",
                        }
                    )
        except (asyncio.TimeoutError, FileNotFoundError, OSError):
            pass

    return issues


def format_verification_feedback(issues: list[dict[str, Any]]) -> str | None:
    """Format verification issues into a message for the agent.

    Returns None if no issues, or a formatted string to inject
    as system feedback into the conversation.
    """
    if not issues:
        return None

    errors = [i for i in issues if i["level"] == "error"]
    warnings = [i for i in issues if i["level"] == "warning"]

    parts = ["[VERIFICATION]"]
    if errors:
        parts.append(f"ERRORS ({len(errors)}):")
        for e in errors:
            parts.append(f"  - {e['message']}")
    if warnings:
        parts.append(f"WARNINGS ({len(warnings)}):")
        for w in warnings:
            parts.append(f"  - {w['message']}")

    if errors:
        parts.append("Fix the errors above before proceeding.")

    return "\n".join(parts)
