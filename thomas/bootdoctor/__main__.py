"""Standalone BootDoctor CLI.

This module intentionally avoids importing ``thomas.cli.main`` so it can run
even when the main CLI command tree is broken.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import socket
import sys
import traceback
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from thomas.core.boot_doctor import run_boot_doctor
from thomas.core.config import AppConfig, load_config
from thomas.tools.base import Tool, ToolResult
from thomas.tools.code_search import register_code_search_tools
from thomas.tools.diff import register_diff_tools
from thomas.tools.filesystem import register_filesystem_tools
from thomas.tools.registry import ToolRegistry

DEFAULT_READ_DIRS = (
    "scripts",
    "thomas/bootdoctor",
    "thomas/cli",
    "thomas/core",
    "thomas/server",
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
    "thomas/bootdoctor",
)


def _is_within(path: Path, root: Path) -> bool:
    try:
        return os.path.commonpath(
            [os.path.normcase(str(path.resolve())), os.path.normcase(str(root.resolve()))]
        ) == os.path.normcase(str(root.resolve()))
    except ValueError:
        return False


def _resolve_repo_root(raw_root: str) -> Path:
    if str(raw_root or "").strip():
        candidate = Path(raw_root).expanduser()
        if not candidate.is_absolute():
            candidate = Path.cwd() / candidate
        return candidate.resolve()

    cwd = Path.cwd().resolve()
    if (cwd / "thomas").is_dir():
        return cwd

    module_root = Path(__file__).resolve().parents[2]
    if (module_root / "thomas").is_dir():
        return module_root

    return cwd


def _parse_report_path(raw_report: str, root: Path) -> Path | None:
    value = str(raw_report or "").strip()
    if not value:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = root / path
    return path.resolve()


def _write_fallback_report(path: Path, *, reason: str, port: int, error: BaseException) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "Thomas Boot Doctor Report (Fallback)",
        f"Generated (UTC): {datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')}",
        f"Reason: {reason}",
        f"Port: {int(port)}",
        "",
        f"Failure: {type(error).__name__}: {error}",
        "",
        "Traceback:",
        traceback.format_exc().rstrip(),
        "",
        "Offline Recovery Steps:",
        f"- Run `run-ui.cmd -NoTray -Port {int(port)}`.",
        f"- Run `python -m thomas.bootdoctor report --port {int(port)} --force`.",
        "- If this repeats, inspect syntax errors in optional CLI modules.",
    ]
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _runtime_healthy(host: str, port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://{host}:{int(port)}/api/models", timeout=1.5) as response:
            status = int(getattr(response, "status", 0) or 0)
            return 200 <= status < 500
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _port_listening(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=0.5):
            return True
    except OSError:
        return False


def _runtime_detected(host: str, port: int) -> bool:
    return _runtime_healthy(host, port) or _port_listening(host, port)


def _load_config_safe(config_path: str) -> tuple[AppConfig, str]:
    try:
        path_obj = Path(config_path).expanduser().resolve() if str(config_path or "").strip() else None
        cfg = load_config(path_obj)
        return cfg, ""
    except Exception as exc:
        return AppConfig(), f"config load failed ({type(exc).__name__}: {exc}); using defaults"


def _run_report(
    *,
    config: AppConfig,
    root: Path,
    port: int,
    reason: str,
    report_path: Path | None,
    auto_repair: bool,
    allow_ai: bool,
) -> Path:
    try:
        return run_boot_doctor(
            config=config,
            root=root,
            port=int(port),
            reason=str(reason or "").strip() or "startup failure",
            report_path=report_path,
            auto_repair=bool(auto_repair),
            allow_ai=bool(allow_ai),
        )
    except Exception as exc:
        fallback = report_path
        if fallback is None:
            stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            fallback = (root / "runtime" / "boot_doctor" / f"boot_doctor_{stamp}.txt").resolve()
        _write_fallback_report(
            fallback,
            reason=str(reason or "").strip() or "startup failure",
            port=int(port),
            error=exc,
        )
        return fallback


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
                entries.append(str(path.relative_to(self.root)).replace("\\", "/"))
            except ValueError:
                entries.append(str(path))
        for path in sorted(self.write_dirs):
            try:
                entries.append(str(path.relative_to(self.root)).replace("\\", "/") + "/**")
            except ValueError:
                entries.append(str(path))
        return ", ".join(entries)


def _extract_patch_targets(patch: str) -> list[str]:
    targets: list[str] = []
    for raw_line in str(patch or "").splitlines():
        line = raw_line.rstrip("\r\n")
        if not line.startswith("+++ "):
            continue
        candidate = line[4:].split("\t", 1)[0].strip()
        if candidate in {"/dev/null", "nul", "NUL"}:
            continue
        if candidate.startswith("b/"):
            candidate = candidate[2:]
        if candidate and candidate not in targets:
            targets.append(candidate)
    return targets


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
        name = str(self.name or "").strip()
        if name in {"fs.read_file"}:
            return self._check_read_path(str(args.get("path", "")), label="path")
        if name in {"fs.write_file"}:
            return self._check_write_path(str(args.get("path", "")), label="path")
        if name in {"diff.create", "diff.preview"}:
            checker = self._check_write_path if name == "diff.create" else self._check_read_path
            return checker(str(args.get("file", "")), label="file")
        if name == "diff.apply_patch":
            targets = _extract_patch_targets(str(args.get("patch", "")))
            if not targets:
                return self._deny("BootDoctor requires explicit patch targets in unified diff headers.")
            for target in targets:
                err = self._check_write_path(target, label="patch_target")
                if err is not None:
                    return err
            return None
        if name in {
            "fs.list_dir",
            "fs.search",
            "code.search",
            "code.find_definition",
            "code.find_references",
            "code.project_structure",
        }:
            raw = str(args.get("path", "")).strip()
            if not raw:
                raw = "scripts"
                args["path"] = raw
            return self._check_read_path(raw, label="path")
        return None

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        mutable = dict(args or {})
        invalid = self._validate(mutable)
        if invalid is not None:
            return invalid
        return await self._inner.execute(mutable)


def _build_restricted_tools(root: Path) -> tuple[ToolRegistry, BootDoctorPathPolicy]:
    base = ToolRegistry()
    register_filesystem_tools(base, root)
    register_code_search_tools(base, root)
    register_diff_tools(base, root)

    policy = BootDoctorPathPolicy(root)
    restricted = ToolRegistry()
    allowed = {
        "fs.read_file",
        "fs.write_file",
        "fs.list_dir",
        "fs.search",
        "code.search",
        "code.find_definition",
        "code.find_references",
        "code.project_structure",
        "diff.create",
        "diff.apply_patch",
        "diff.preview",
    }
    for name in sorted(allowed):
        tool = base.get(name)
        if tool is not None:
            restricted.register(RestrictedTool(tool, policy))
    return restricted, policy


async def _run_chat(args: argparse.Namespace, *, config: AppConfig, root: Path) -> int:
    from thomas.agent.loop import AgentLoop
    from thomas.core.events import EventType
    from thomas.core.llm import LLMClient

    if not config.models:
        report = _run_report(
            config=config,
            root=root,
            port=int(args.port),
            reason=str(args.reason or "").strip() or "runtime not detected",
            report_path=_parse_report_path(args.report, root),
            auto_repair=not bool(args.no_auto_repair),
            allow_ai=not bool(args.no_ai),
        )
        print("[bootdoctor] no model profiles configured; chat disabled.")
        print(f"[bootdoctor] report: {report}")
        return 0

    profile = str(args.model or "").strip() or str(config.default_model or "").strip()
    if profile not in config.models:
        profile = next(iter(config.models.keys()))
        print(f"[bootdoctor] selected model profile not found; using '{profile}'.")

    model_cfg = config.get_model(profile)
    llm = LLMClient(
        model_cfg,
        fallback_configs=config.failover_chain(profile),
        failover_enabled=bool(config.failover.enabled and getattr(config.failover, "chat_auto_failover", False)),
        failover_cooldown_s=config.failover.cooldown_seconds,
        failover_on_auth_error=config.failover.fallback_on_auth_error,
    )
    tools, policy = _build_restricted_tools(root)

    system_prompt = (
        "You are BootDoctor, a startup-recovery specialist for Thomas.\n"
        "Primary objective: restore boot/runtime health.\n"
        "Hard rules:\n"
        "1) Only investigate startup and boot failures.\n"
        "2) Refuse unrelated requests.\n"
        "3) Keep edits tightly scoped to boot files.\n"
        "4) Prefer diagnostics before edits.\n"
        "5) Avoid destructive actions.\n"
        f"Writable scope: {policy.describe_write_scope()}\n"
    )
    agent = AgentLoop(
        config,
        llm,
        tools,
        system_prompt=system_prompt,
        thread_id="bootdoctor",
        autonomy_level=2,
        max_parallel_tools=2,
    )

    report = _run_report(
        config=config,
        root=root,
        port=int(args.port),
        reason=str(args.reason or "").strip() or "runtime not detected",
        report_path=_parse_report_path(args.report, root),
        auto_repair=not bool(args.no_auto_repair),
        allow_ai=not bool(args.no_ai),
    )
    print(f"[bootdoctor] initial report: {report}")
    print("[bootdoctor] commands: /report [reason], /status, /scope, /quit")

    try:
        while True:
            try:
                prompt = input("bootdoctor> ").strip()
            except (KeyboardInterrupt, EOFError):
                print("")
                break

            if not prompt:
                continue

            lower = prompt.lower()
            if lower in {"/quit", "quit", "exit"}:
                break
            if lower.startswith("/report"):
                custom_reason = prompt[len("/report") :].strip()
                report = _run_report(
                    config=config,
                    root=root,
                    port=int(args.port),
                    reason=custom_reason or "manual bootdoctor report request",
                    report_path=_parse_report_path(args.report, root),
                    auto_repair=not bool(args.no_auto_repair),
                    allow_ai=not bool(args.no_ai),
                )
                print(f"[bootdoctor] report: {report}")
                continue
            if lower == "/scope":
                print(f"[bootdoctor] writable scope: {policy.describe_write_scope()}")
                continue
            if lower == "/status":
                detected = _runtime_detected(str(args.host), int(args.port))
                print(f"[bootdoctor] runtime_detected={str(detected).lower()} host={args.host} port={int(args.port)}")
                if detected and not bool(args.force):
                    print("[bootdoctor] runtime is up; BootDoctor is locking.")
                    break
                continue

            if _runtime_detected(str(args.host), int(args.port)) and not bool(args.force):
                print("[bootdoctor] runtime detected; refusing further chat without --force.")
                break

            printed_text = False
            async for event in agent.run(prompt):
                if event.type == EventType.TEXT_DELTA:
                    printed_text = True
                    sys.stdout.write(str(event.data.get("text", "")))
                    sys.stdout.flush()
                elif event.type == EventType.TOOL_CALL_START:
                    name = str(event.data.get("tool_name", "tool"))
                    sys.stdout.write(f"\n[tool] {name} ...")
                    sys.stdout.flush()
                elif event.type == EventType.TOOL_RESULT:
                    ok = bool(event.data.get("ok", False))
                    ms = float(event.data.get("duration_ms", 0.0) or 0.0)
                    status = "ok" if ok else "fail"
                    sys.stdout.write(f" {status} ({ms:.0f}ms)\n")
                    sys.stdout.flush()
                elif event.type == EventType.AGENT_ERROR:
                    sys.stdout.write(f"\n[bootdoctor] error: {event.data.get('error')}\n")
                    sys.stdout.flush()
            if printed_text:
                sys.stdout.write("\n")
                sys.stdout.flush()
    finally:
        await llm.close()

    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bootdoctor",
        description="Standalone BootDoctor runtime recovery CLI.",
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="chat",
        choices=("chat", "report"),
        help="Use 'report' for one-shot diagnostics or 'chat' for interactive repair.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Runtime host to check.")
    parser.add_argument("--port", type=int, default=8899, help="Runtime port to check.")
    parser.add_argument("--reason", default="runtime not detected", help="Boot failure reason to include in reports.")
    parser.add_argument("--report", default="", help="Optional report output path.")
    parser.add_argument("--config", default="", help="Optional config file path.")
    parser.add_argument("--root", default="", help="Repository root. Defaults to cwd.")
    parser.add_argument("--model", default="", help="Model profile for chat mode.")
    parser.add_argument("--force", action="store_true", help="Allow BootDoctor even when runtime is detected.")
    parser.add_argument("--no-ai", action="store_true", help="Skip AI summary generation in diagnostic reports.")
    parser.add_argument("--no-auto-repair", action="store_true", help="Collect findings only; skip auto-repairs.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    root = _resolve_repo_root(args.root)
    runtime_detected = _runtime_detected(str(args.host), int(args.port))
    if runtime_detected and not bool(args.force):
        print(f"[bootdoctor] runtime detected on {args.host}:{int(args.port)}; " "refusing activation without --force.")
        return 2

    config, warning = _load_config_safe(args.config)
    if warning:
        print(f"[bootdoctor] warning: {warning}")

    report_path = _parse_report_path(args.report, root)

    if args.command == "report":
        report = _run_report(
            config=config,
            root=root,
            port=int(args.port),
            reason=str(args.reason or "").strip() or "runtime not detected",
            report_path=report_path,
            auto_repair=not bool(args.no_auto_repair),
            allow_ai=not bool(args.no_ai),
        )
        print(report)
        return 0

    try:
        return asyncio.run(_run_chat(args, config=config, root=root))
    except KeyboardInterrupt:
        print("")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
