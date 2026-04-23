from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _run(args: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=REPO_ROOT,
        check=False,
        text=True,
        capture_output=capture,
    )


def _staged_python_files() -> list[str]:
    result = _run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "--", "*.py"],
        capture=True,
    )
    if result.returncode != 0:
        if result.stdout:
            sys.stdout.write(result.stdout)
        if result.stderr:
            sys.stderr.write(result.stderr)
        raise SystemExit(result.returncode)
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def main() -> int:
    files = _staged_python_files()
    if not files:
        print("ruff pre-commit: no staged Python files")
        return 0

    commands = [
        [sys.executable, "-m", "ruff", "format", *files],
        [sys.executable, "-m", "ruff", "check", "--fix", "--unsafe-fixes", *files],
        [sys.executable, "-m", "ruff", "format", *files],
    ]
    for command in commands:
        result = _run(command)
        if result.returncode != 0:
            return result.returncode

    stage_result = _run(["git", "add", "--", *files])
    if stage_result.returncode != 0:
        return stage_result.returncode

    final_check = _run([sys.executable, "-m", "ruff", "check", *files])
    return final_check.returncode


if __name__ == "__main__":
    raise SystemExit(main())
