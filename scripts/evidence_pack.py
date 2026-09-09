#!/usr/bin/env python3
"""Run commands and emit a portable evidence pack (logs + summary)."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_ROOT = ROOT / "artifacts" / "evidence"


@dataclass(frozen=True)
class StepResult:
    index: int
    command: str
    exit_code: int
    duration_s: float
    started_utc: str
    finished_utc: str
    stdout_path: str
    stderr_path: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "command": self.command,
            "exit_code": self.exit_code,
            "ok": self.ok,
            "duration_s": round(self.duration_s, 3),
            "started_utc": self.started_utc,
            "finished_utc": self.finished_utc,
            "stdout_path": self.stdout_path,
            "stderr_path": self.stderr_path,
        }


def _slug(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return text or "run"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _fmt_utc(ts: datetime) -> str:
    return ts.isoformat()


def _run_git(args: Sequence[str]) -> str | None:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    out = str(proc.stdout or "").strip()
    return out or None


def _repo_context() -> dict[str, str]:
    return {
        "repo_root": str(ROOT),
        "branch": _run_git(["rev-parse", "--abbrev-ref", "HEAD"]) or "",
        "commit": _run_git(["rev-parse", "HEAD"]) or "",
    }


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _format_markdown(summary: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Evidence Pack")
    lines.append("")
    lines.append(f"- name: `{summary['name']}`")
    lines.append(f"- generated_utc: `{summary['generated_utc']}`")
    lines.append(f"- repo_root: `{summary['repo']['repo_root']}`")
    lines.append(f"- branch: `{summary['repo']['branch']}`")
    lines.append(f"- commit: `{summary['repo']['commit']}`")
    lines.append(f"- overall_ok: `{summary['ok']}`")
    lines.append(f"- command_count: `{summary['command_count']}`")
    lines.append(f"- executed_count: `{summary['executed_count']}`")
    lines.append("")
    lines.append("## Steps")
    lines.append("")
    if not summary["steps"]:
        lines.append("- none")
        lines.append("")
        return "\n".join(lines) + "\n"

    for step in summary["steps"]:
        lines.append(
            f"- step {step['index']:03d}: ok={step['ok']} exit={step['exit_code']} duration_s={step['duration_s']}"
        )
        lines.append(f"  - command: `{step['command']}`")
        lines.append(f"  - stdout: `{step['stdout_path']}`")
        lines.append(f"  - stderr: `{step['stderr_path']}`")
    lines.append("")
    return "\n".join(lines) + "\n"


def _run_command(command: str, *, workdir: Path) -> tuple[int, str, str, float, str, str]:
    started = _utc_now()
    start_clock = time.monotonic()
    proc = subprocess.run(
        command,
        cwd=workdir,
        shell=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    duration = time.monotonic() - start_clock
    finished = _utc_now()
    return (
        int(proc.returncode),
        str(proc.stdout or ""),
        str(proc.stderr or ""),
        duration,
        _fmt_utc(started),
        _fmt_utc(finished),
    )


def build_evidence_pack(
    *,
    name: str,
    commands: Sequence[str],
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    continue_on_fail: bool = False,
    workdir: Path = ROOT,
) -> dict[str, Any]:
    pack_name = _slug(name)
    stamp = _utc_now().strftime("%Y%m%d-%H%M%S")
    pack_dir = output_root / f"{stamp}-{pack_name}"
    pack_dir.mkdir(parents=True, exist_ok=True)

    step_results: list[StepResult] = []
    stopped_early = False
    for idx, command in enumerate(commands, start=1):
        exit_code, stdout_text, stderr_text, duration, started_utc, finished_utc = _run_command(
            command,
            workdir=workdir,
        )
        step_dir = pack_dir / "steps" / f"{idx:03d}"
        stdout_path = step_dir / "stdout.txt"
        stderr_path = step_dir / "stderr.txt"
        _write_text(stdout_path, stdout_text)
        _write_text(stderr_path, stderr_text)

        step = StepResult(
            index=idx,
            command=command,
            exit_code=exit_code,
            duration_s=duration,
            started_utc=started_utc,
            finished_utc=finished_utc,
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
        )
        _write_text(step_dir / "step.json", json.dumps(step.to_dict(), sort_keys=True, indent=2) + "\n")
        step_results.append(step)
        if exit_code != 0 and not continue_on_fail:
            stopped_early = True
            break

    summary: dict[str, Any] = {
        "name": name,
        "slug": pack_name,
        "generated_utc": _fmt_utc(_utc_now()),
        "output_dir": str(pack_dir),
        "repo": _repo_context(),
        "ok": all(item.ok for item in step_results) and len(step_results) == len(commands),
        "continue_on_fail": bool(continue_on_fail),
        "stopped_early": bool(stopped_early),
        "command_count": len(commands),
        "executed_count": len(step_results),
        "steps": [item.to_dict() for item in step_results],
    }
    summary_path = pack_dir / "summary.json"
    _write_text(summary_path, json.dumps(summary, sort_keys=True, indent=2) + "\n")
    _write_text(pack_dir / "SUMMARY.md", _format_markdown(summary))
    summary["summary_path"] = str(summary_path)
    summary["summary_markdown_path"] = str(pack_dir / "SUMMARY.md")
    return summary


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run commands and emit an evidence pack (logs + JSON + markdown summary)."
    )
    parser.add_argument("--name", required=True, help="Evidence pack name.")
    parser.add_argument(
        "--command",
        action="append",
        default=[],
        help="Command to execute (repeatable).",
    )
    parser.add_argument(
        "--output-root",
        default=str(DEFAULT_OUTPUT_ROOT),
        help="Root directory for evidence packs (default: artifacts/evidence).",
    )
    parser.add_argument(
        "--workdir",
        default=str(ROOT),
        help="Working directory for command execution (default: repository root).",
    )
    parser.add_argument(
        "--continue-on-fail",
        action="store_true",
        help="Continue executing remaining commands after a failure.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    args = parser.parse_args(argv)

    commands = [str(item or "").strip() for item in list(args.command or []) if str(item or "").strip()]
    if not commands:
        message = "at least one --command is required"
        if args.json:
            print(json.dumps({"ok": False, "error": message}, sort_keys=True))
        else:
            print("Evidence pack: FAIL")
            print(f"- {message}")
        return 1

    output_root = Path(args.output_root).expanduser()
    if not output_root.is_absolute():
        output_root = (ROOT / output_root).resolve()
    workdir = Path(args.workdir).expanduser()
    if not workdir.is_absolute():
        workdir = (ROOT / workdir).resolve()
    if not workdir.exists() or not workdir.is_dir():
        message = f"invalid workdir: {workdir}"
        if args.json:
            print(json.dumps({"ok": False, "error": message}, sort_keys=True))
        else:
            print("Evidence pack: FAIL")
            print(f"- {message}")
        return 1

    summary = build_evidence_pack(
        name=args.name,
        commands=commands,
        output_root=output_root,
        continue_on_fail=bool(args.continue_on_fail),
        workdir=workdir,
    )

    if args.json:
        print(json.dumps(summary, sort_keys=True))
    else:
        print("Evidence pack: PASS" if summary["ok"] else "Evidence pack: FAIL")
        print(f"- output: {summary['output_dir']}")
        print(f"- summary: {summary['summary_path']}")
        print(f"- steps executed: {summary['executed_count']}/{summary['command_count']}")
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))
