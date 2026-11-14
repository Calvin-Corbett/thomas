"""Run ratchet proofs through the shared proof runner inside the cage.

Reports and isolated Thomas data live beside the green, never in its work tree.
An interrupted, missing, or unsafe report cannot establish a passing proof.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shlex
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path

from thomas.server import proof as shared_proof
from thomas.server.green_checkout import Green
from thomas.server.proof.environment import NOT_STARTED, TIMED_OUT, sandbox_env
from thomas.server.ratchet.proof_set import SHARD_FILES
from thomas.server.ratchet.results import SideResult, Verdict, compare, parse_junit
from thomas.tools.cage_shell import CagedResult

log = logging.getLogger(__name__)

SHARD_TIMEOUT_S = 1800.0
BOOT_TIMEOUT_S = 300.0
RERUN_LIMIT = 20
BOOT_MODULES = ("thomas", "thomas.core", "thomas.core.config", "thomas.memory", "thomas.agent", "thomas.server")
CagedRun = Callable[..., CagedResult]


def proof_folder(green: Green) -> Path:
    """Beside the green's work folder, never in its submitted work tree."""
    return green.work.parent / f"{green.execution_id}.proof"


def _tail(text: str, limit: int = 300) -> str:
    return " ".join(str(text or "").split())[-limit:]


def _own_data(green: Green) -> str:
    """Give a cage command a separate Thomas data folder beside the green."""
    data = proof_folder(green) / "data"
    data.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        return f'set "THOMAS_DATA_DIR={data}" && '
    return f"THOMAS_DATA_DIR={shlex.quote(str(data))} "


def boot_check(green: Green, run: CagedRun, *, modules: Sequence[str] = BOOT_MODULES) -> str:
    """Return a reason if imports in the green would use the running checkout."""
    code = f"import {', '.join(modules)}; print(thomas.__file__)"
    done = run(f'python -c "{code}"', cwd=str(green.work), timeout_s=BOOT_TIMEOUT_S)
    if done.outcome != "ok" or done.returncode != 0:
        return f"Thomas does not import in the green ({done.outcome}, exit {done.returncode}): {_tail(done.output)}"
    lines = done.output.strip().splitlines()
    where = Path(lines[-1].strip()) if lines else Path()
    try:
        inside = where.resolve().is_relative_to(green.work.resolve())
    except OSError:
        inside = False
    return "" if inside else f"the tests would import the running Thomas ({where}), not the green"


def _shell_command(argv: Sequence[str], env: Mapping[str, str]) -> str:
    """Adapt the shared runner's argv and sandbox settings to a cage shell line."""
    # The cage inherits its own environment, not the server's. Forward only
    # isolation settings, never the server's inherited credentials.
    isolated = {key: value for key, value in env.items() if key.startswith("THOMAS_")}
    isolated.update(
        {
            key: env[key]
            for key in (
                "PYTHONPATH",
                "PYTHONDONTWRITEBYTECODE",
                "PYTHONIOENCODING",
                "PYTHONUTF8",
            )
        }
    )
    if os.name == "nt":
        # cmd expands % inside double quotes; delayed expansion expands !.
        # Refuse such inputs instead of interpreting a path or test id as code.
        if any(any(ch in value for ch in ("%", "!", '"', "^", "\r", "\n")) for value in (*isolated.values(), *argv)):
            raise ValueError("unsafe cmd shell argument")
        prefix = " && ".join(f'set "{key}={value}"' for key, value in isolated.items())
        # Quote all arguments: cmd metacharacters in paths/node ids then cannot
        # act as shell separators; none of these arguments contain literal quotes.
        return prefix + " && " + " ".join(f'"{arg}"' for arg in argv)
    prefix = " ".join(f"{key}={shlex.quote(value)}" for key, value in isolated.items())
    return prefix + " " + shlex.join(argv)


def _cage_adapter(
    run: CagedRun,
    report_name: Path,
    outcomes: list[CagedResult],
    invalid: list[str],
) -> shared_proof.Run:
    """Run a shared proof command in the cage, checking its report before sharing it."""

    def execute(command: Sequence[str], *, cwd: Path, env: Mapping[str, str], timeout_s: float) -> tuple[int, str]:
        args = list(command)
        report_arg = next((arg for arg in args if arg.startswith("--junit-xml=")), None)
        report = Path(report_arg.split("=", 1)[1]) if report_arg else None
        if report is not None:
            report.unlink(missing_ok=True)
            report_name.unlink(missing_ok=True)
            args[args.index(report_arg)] = f"--junitxml={report_name}"
        try:
            line = _shell_command(args, env)
        except ValueError as exc:
            return NOT_STARTED, str(exc)
        done = run(line, cwd=str(cwd), timeout_s=timeout_s)
        outcomes.append(done)
        if report is not None and report_name.is_file():
            try:
                text = report_name.read_text(encoding="utf-8", errors="replace")
                # Shared junit.read_report parses the copy; gate untrusted XML
                # before the shared service can inspect it.
                if "<!DOCTYPE" in text or "<!ENTITY" in text:
                    invalid.append("the report declares a DOCTYPE or an entity")
                else:
                    report.parent.mkdir(parents=True, exist_ok=True)
                    report.write_text(text, encoding="utf-8")
            except OSError as exc:
                invalid.append(f"report cannot be read: {exc}")
        if invalid:
            return NOT_STARTED, invalid[0]
        if done.outcome == "timeout":
            return TIMED_OUT, done.output
        if done.outcome != "ok":
            return NOT_STARTED, done.output
        if report is not None:
            if not report_name.is_file():
                return NOT_STARTED, "the JUnit report is missing"
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_bytes(report_name.read_bytes())
        return done.returncode, done.output

    return execute


def run_side(green: Green, files: Iterable[str], label: str, run: CagedRun) -> SideResult:
    """Run selected files in cage shards, retaining failures, passes, and skips."""
    wanted = tuple(files)
    folder = proof_folder(green)
    folder.mkdir(parents=True, exist_ok=True)
    failing: dict[str, str] = {}
    passing: dict[str, str] = {}
    skipped: set[str] = set()
    unrunnable: list[str] = []
    ran = 0
    for start in range(0, len(wanted), SHARD_FILES):
        shard, number = wanted[start : start + SHARD_FILES], start // SHARD_FILES + 1
        missing = [path for path in shard if not (green.work / path).is_file()]
        data = folder / f"{label}-{number}.data"
        report_name = folder / f"{label}-{number}.xml"
        report = data / "reports" / "shard-1.xml"
        report.unlink(missing_ok=True)
        outcomes: list[CagedResult] = []
        invalid: list[str] = []
        adapter = _cage_adapter(run, report_name, outcomes, invalid)
        result = shared_proof.run_tests(
            green.work,
            shard,
            python="python",
            data_dir=data,
            shard_files=SHARD_FILES,
            timeout_s=SHARD_TIMEOUT_S,
            run=adapter,
        )
        if not outcomes:
            # The shared runner skips absent files. A selected file that is
            # missing must still produce a cage outcome, not a silent pass.
            env = sandbox_env(green.work, data)
            report.parent.mkdir(parents=True, exist_ok=True)
            report.unlink(missing_ok=True)
            adapter(
                shared_proof.pytest_command("python", green.work, report, shard),
                cwd=green.work,
                env=env,
                timeout_s=SHARD_TIMEOUT_S,
            )
        done = outcomes[-1] if outcomes else None
        text = report.read_text(encoding="utf-8", errors="replace") if report.is_file() else ""
        if invalid:
            unrunnable.append(f"{label} shard {number} wrote a report that cannot be read: {invalid[0]}")
            continue
        if (
            done is None
            or done.outcome != "ok"
            or done.returncode not in (0, 1, 5)
            or not text
            or (outcomes and not result.ran and result.why)
        ):
            outcome = done.outcome if done else "not started"
            exit_code = done.returncode if done else NOT_STARTED
            output = done.output if done else result.why
            unrunnable.append(
                f"{label} shard {number} ({len(shard)} files) could not run: "
                f"{outcome}, exit {exit_code}: {_tail(output)}"
            )
            continue
        try:
            shard_failing, shard_passing, shard_skipped = parse_junit(text)
        except ET.ParseError as exc:
            unrunnable.append(f"{label} shard {number} wrote a report that cannot be read: {exc}")
            continue
        failing.update(shard_failing)
        passing.update(shard_passing)
        skipped |= shard_skipped
        ran += len(shard_failing) + len(shard_passing)
        if missing:
            unrunnable.append(f"{label} shard {number} is missing selected test files: {', '.join(missing)}")
    return SideResult(wanted, failing, passing, ran, tuple(unrunnable), frozenset(skipped))


def rerun_alone(green: Green, node_ids: Iterable[str], run: CagedRun) -> tuple[set[str], set[str]]:
    """Re-run at most twenty nodes alone; unknown outcomes count for neither side."""
    passed: set[str] = set()
    failed: set[str] = set()
    folder = proof_folder(green)
    for number, node in enumerate(node_ids):
        if number >= RERUN_LIMIT:
            break
        data = folder / f"rerun-{number}.data"
        outcomes: list[CagedResult] = []
        invalid: list[str] = []
        adapter = _cage_adapter(run, folder / f"rerun-{number}.xml", outcomes, invalid)
        answer = shared_proof.run_one(
            green.work,
            node,
            python="python",
            data_dir=data,
            timeout_s=SHARD_TIMEOUT_S,
            run=adapter,
        )
        if invalid or not outcomes or outcomes[-1].outcome != "ok":
            continue
        if answer == shared_proof.PASSED:
            passed.add(node)
        elif answer == shared_proof.FAILED:
            failed.add(node)
    return passed, failed


def cached(folder: Path, dev_sha: str, files: Iterable[str]) -> tuple[Path, SideResult | None]:
    """Find the base result for precisely these files and this dev tip."""
    digest = hashlib.sha256("\n".join(sorted(files)).encode("utf-8")).hexdigest()[:16]
    path = folder / f"{dev_sha[:12]}-{digest}.json"
    try:
        return path, SideResult.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError, AttributeError):
        return path, None


def remember(path: Path, result: SideResult) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result.as_dict()), encoding="utf-8")
    except OSError:
        log.debug("could not keep the base proof at %s; the next attempt runs it again", path, exc_info=True)


__all__ = [
    "BOOT_MODULES",
    "CagedRun",
    "SideResult",
    "Verdict",
    "boot_check",
    "cached",
    "compare",
    "parse_junit",
    "proof_folder",
    "remember",
    "rerun_alone",
    "run_side",
]
