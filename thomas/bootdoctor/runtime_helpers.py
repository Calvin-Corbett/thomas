from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

from thomas.tools.base import Tool, ToolResult
from thomas.tools.code_search import register_code_search_tools
from thomas.tools.diff import register_diff_tools
from thomas.tools.filesystem import register_filesystem_tools
from thomas.tools.registry import ToolRegistry

DEFAULT_READ_DIRS = (
    "docs",
    "runtime/logs",
    "scripts",
    "thomas/bootdoctor",
    "thomas/cli",
    "thomas/core",
    "thomas/server",
    "thomas/agent",
    "thomas/tray_agent",
    "runtime/boot_doctor",
)

DEFAULT_WRITE_FILES = (
    "scripts/run-ui.ps1",
    "scripts/run-ui.cmd",
    "scripts/start-tray-agent.ps1",
    "scripts/run_boot_doctor_direct.py",
    "thomas/__main__.py",
    "thomas/bootdoctor/__main__.py",
    "thomas/cli/main.py",
    "thomas/core/boot_doctor.py",
    "thomas/tray_agent/agent.py",
)

DEFAULT_WRITE_DIRS = (
    "runtime/boot_doctor",
    "thomas/agent",
    "thomas/bootdoctor",
    "thomas/core",
    "thomas/server",
    "thomas/tray_agent",
)


def _is_within(path: Path, root: Path) -> bool:
    try:
        return os.path.commonpath(
            [os.path.normcase(str(path.resolve())), os.path.normcase(str(root.resolve()))]
        ) == os.path.normcase(str(root.resolve()))
    except ValueError:
        return False


class BootDoctorPathPolicy:
    """Allow-list policy for BootDoctor tool access."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.read_roots = [(self.root / rel).resolve() for rel in DEFAULT_READ_DIRS]
        self.write_files = {(self.root / rel).resolve() for rel in DEFAULT_WRITE_FILES}
        self.write_dirs = [(self.root / rel).resolve() for rel in DEFAULT_WRITE_DIRS]

    def resolve(self, raw_path: str) -> Path:
        path = Path(str(raw_path or "").strip()).expanduser()
        if not path.is_absolute():
            path = self.root / path
        return path.resolve()

    def is_read_allowed(self, path: Path) -> bool:
        resolved = path.resolve()
        if self.is_write_allowed(resolved):
            return True
        return any(_is_within(resolved, allowed_root) for allowed_root in self.read_roots)

    def is_write_allowed(self, path: Path) -> bool:
        resolved = path.resolve()
        if any(os.path.normcase(str(resolved)) == os.path.normcase(str(item)) for item in self.write_files):
            return True
        return any(_is_within(resolved, allowed_dir) for allowed_dir in self.write_dirs)

    def describe_write_scope(self) -> str:
        entries = []
        for path in sorted(self.write_files):
            try:
                entries.append(str(path.relative_to(self.root)).replace('\\', '/'))
            except ValueError:
                entries.append(str(path))
        for path in sorted(self.write_dirs):
            try:
                entries.append(str(path.relative_to(self.root)).replace('\\', '/') + '/**')
            except ValueError:
                entries.append(str(path))
        return ', '.join(entries)


def _extract_patch_targets(patch: str) -> list[str]:
    targets: list[str] = []
    for raw_line in str(patch or '').splitlines():
        line = raw_line.rstrip('\r\n')
        if not line.startswith('+++ '):
            continue
        candidate = line[4:].split('\t', 1)[0].strip()
        if candidate in {'/dev/null', 'nul', 'NUL'}:
            continue
        if candidate.startswith('b/'):
            candidate = candidate[2:]
        if candidate and candidate not in targets:
            targets.append(candidate)
    return targets


def _extract_repo_paths_from_text(raw_text: str, root: Path) -> list[str]:
    seen: set[str] = set()
    results: list[str] = []
    root_norm = str(root.resolve()).replace('\\', '/').rstrip('/')
    for match in re.finditer(r'File "([^"]+)"', str(raw_text or '')):
        candidate = str(match.group(1) or '').strip()
        if not candidate:
            continue
        normalized = candidate.replace('\\', '/')
        rel = ''
        if normalized.startswith(root_norm + '/'):
            rel = normalized[len(root_norm) + 1 :]
        elif normalized.startswith(('thomas/', 'scripts/', 'runtime/')):
            rel = normalized
        if not rel or rel in seen:
            continue
        seen.add(rel)
        results.append(rel)
    return results


class RestrictedTool(Tool):
    """Thin wrapper that enforces BootDoctor path policy."""

    def __init__(self, inner: Tool, policy: BootDoctorPathPolicy):
        self._inner = inner
        self._policy = policy
        self.name = inner.name
        self.category = inner.category
        self.description = inner.description
        self.parameters = inner.parameters

    def _deny(self, message: str) -> ToolResult:
        return ToolResult(ok=False, error=message)

    def _check_read_path(self, raw_path: str, *, label: str) -> ToolResult | None:
        candidate = self._policy.resolve(raw_path)
        if not self._policy.is_read_allowed(candidate):
            return self._deny(
                f"BootDoctor blocked read outside boot scope ({label}={raw_path}). "
                f"Allowed write scope: {self._policy.describe_write_scope()}"
            )
        return None

    def _check_write_path(self, raw_path: str, *, label: str) -> ToolResult | None:
        candidate = self._policy.resolve(raw_path)
        if not self._policy.is_write_allowed(candidate):
            return self._deny(
                f"BootDoctor blocked write outside boot scope ({label}={raw_path}). "
                f"Allowed write scope: {self._policy.describe_write_scope()}"
            )
        return None

    def _validate(self, args: dict[str, Any]) -> ToolResult | None:
        name = str(self.name or '').strip()
        if name in {'fs.read_file'}:
            return self._check_read_path(str(args.get('path', '')), label='path')
        if name in {'fs.write_file'}:
            return self._check_write_path(str(args.get('path', '')), label='path')
        if name in {'diff.create', 'diff.preview'}:
            checker = self._check_write_path if name == 'diff.create' else self._check_read_path
            return checker(str(args.get('file', '')), label='file')
        if name == 'diff.apply_patch':
            targets = _extract_patch_targets(str(args.get('patch', '')))
            if not targets:
                return self._deny('BootDoctor requires explicit patch targets in unified diff headers.')
            for target in targets:
                err = self._check_write_path(target, label='patch_target')
                if err is not None:
                    return err
            return None
        if name in {
            'fs.list_dir',
            'fs.search',
            'code.search',
            'code.find_definition',
            'code.find_references',
            'code.project_structure',
        }:
            raw = str(args.get('path', '')).strip()
            if not raw:
                raw = 'scripts'
                args['path'] = raw
            return self._check_read_path(raw, label='path')
        return None

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        mutable = dict(args or {})
        invalid = self._validate(mutable)
        if invalid is not None:
            return invalid
        return await self._inner.execute(mutable)


def build_restricted_tools(root: Path) -> tuple[ToolRegistry, BootDoctorPathPolicy]:
    base = ToolRegistry()
    register_filesystem_tools(base, root)
    register_code_search_tools(base, root)
    register_diff_tools(base, root)

    policy = BootDoctorPathPolicy(root)
    restricted = ToolRegistry()
    allowed = {
        'fs.read_file',
        'fs.write_file',
        'fs.list_dir',
        'fs.search',
        'code.search',
        'code.find_definition',
        'code.find_references',
        'code.project_structure',
        'diff.create',
        'diff.apply_patch',
        'diff.preview',
    }
    for name in sorted(allowed):
        tool = base.get(name)
        if tool is not None:
            restricted.register(RestrictedTool(tool, policy))
    return restricted, policy


def load_startup_context(raw_path: str, root: Path) -> dict[str, Any]:
    value = str(raw_path or '').strip()
    if not value:
        return {}
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {'context_path': str(path), 'parse_error': f'{type(exc).__name__}: {exc}'}
    if isinstance(payload, dict):
        payload.setdefault('context_path', str(path))
        return payload
    return {'context_path': str(path), 'payload': payload}


def read_report_excerpt(path: Path | None, *, max_chars: int = 2400) -> str:
    if path is None or not path.exists():
        return ''
    try:
        raw = path.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError) as exc:
        return f'Could not read report: {type(exc).__name__}: {exc}'
    raw = raw.strip()
    if len(raw) > max_chars:
        return raw[-max_chars:]
    return raw


def rescue_reason(args: argparse.Namespace, context: dict[str, Any]) -> str:
    explicit = str(args.reason or '').strip()
    if explicit and explicit.lower() != 'runtime not detected':
        return explicit
    for key in ('reason', 'failure_reason', 'message'):
        value = str(context.get(key, '')).strip()
        if value:
            return value
    return explicit or 'runtime not detected'


def build_rescue_prompt(
    *,
    args: argparse.Namespace,
    context: dict[str, Any],
    report_excerpt: str,
    root: Path,
    attempt_number: int,
    max_attempts: int,
) -> str:
    launch_mode = str(context.get('attempted_launch_mode') or context.get('launch_mode') or 'unknown').strip()
    stderr_tail = str(context.get('stderr_tail') or '').strip()
    health_status = str(context.get('current_health_status') or 'unhealthy').strip()
    ever_healthy = bool(context.get('ever_healthy_during_boot') or context.get('ever_healthy'))
    startup_log_paths = [str(item).strip() for item in list(context.get('startup_log_paths') or []) if str(item).strip()]
    traceback_targets = _extract_repo_paths_from_text(stderr_tail, root)
    lines = [
        'Thomas failed to become healthy during startup.',
        f'Attempt: {attempt_number}/{max_attempts}',
        f'Launch mode: {launch_mode}',
        f'Port: {int(args.port)}',
        f'Health status: {health_status}',
        f'Ever healthy this boot: {str(ever_healthy).lower()}',
        f'Failure reason: {rescue_reason(args, context)}',
        '',
        'Work only inside the BootDoctor writable scope.',
        'Diagnose the startup failure, apply one safe repair batch, then stop.',
        'Focus on launcher scripts, boot doctor files, startup-critical runtime files implicated by the traceback, dependency repair, Thomas-owned port cleanup, and model/config validation needed for startup.',
    ]
    if traceback_targets:
        lines.extend(['', 'Startup traceback points at:'])
        lines.extend([f'- {path}' for path in traceback_targets])
        lines.append(
            'If one of these is a monolith stub, inspect and edit the corresponding *_part*.py implementation file instead of the stub.'
        )
    if startup_log_paths:
        lines.extend(['', 'Startup log files:'])
        lines.extend([f'- {path}' for path in startup_log_paths])
    if stderr_tail:
        lines.extend(['', 'Recent stderr/stdout tail:', stderr_tail])
    if report_excerpt:
        lines.extend(['', 'Current BootDoctor report excerpt:', report_excerpt])
    lines.extend(['', 'After your repair batch, I will rerun startup checks automatically.'])
    return "`n".join(lines).strip()