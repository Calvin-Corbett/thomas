#!/usr/bin/env python3
"""Run the Thomas step-up pytest protocol.

Default flow:
1. collect-only sanity check
2. deterministic small shards
3. deterministic larger shard bundles
4. optional monolithic full-suite run

This keeps repo-wide verification repeatable without making a single brittle
`pytest tests -q` invocation the only broad regression path.
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
TESTS_ROOT = ROOT / "tests"
PY = sys.executable

DEFAULT_ISOLATED_TOKEN_THRESHOLD = 12
DEFAULT_SMALL_SHARD_MAX_FILES = 24
DEFAULT_LARGE_SHARD_COUNT = 3

COLLECT_TIMEOUT_SECONDS = 600
SMALL_TIMEOUT_SECONDS = 1800
LARGE_TIMEOUT_SECONDS = 3600
FULL_TIMEOUT_SECONDS = 7200

_STAGE_ORDER = {"collect": 0, "small": 1, "large": 2, "full": 3}


@dataclass(frozen=True)
class Shard:
    name: str
    targets: tuple[str, ...]
    size: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _posix_relpath(path: Path, root: Path) -> str:
    return str(path.relative_to(root)).replace("\\", "/")


def _test_token(path: Path) -> str:
    parts = path.stem.split("_")
    if len(parts) >= 2 and parts[0] == "test":
        return parts[1]
    return path.stem


def discover_test_targets(repo_root: Path = ROOT) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    tests_root = repo_root / "tests"
    directory_groups: dict[str, list[str]] = {}
    token_groups: dict[str, list[str]] = {}

    for path in sorted(tests_root.rglob("test_*.py")):
        if "__pycache__" in path.parts:
            continue
        relpath = _posix_relpath(path, repo_root)
        rel_to_tests = path.relative_to(tests_root)
        if len(rel_to_tests.parts) > 1:
            top_dir = rel_to_tests.parts[0]
            directory_groups.setdefault(top_dir, []).append(relpath)
            continue
        token = _test_token(path)
        token_groups.setdefault(token, []).append(relpath)

    sorted_directories = {
        key: sorted(values) for key, values in sorted(directory_groups.items(), key=lambda item: item[0])
    }
    sorted_tokens = {key: sorted(values) for key, values in sorted(token_groups.items(), key=lambda item: item[0])}
    return sorted_directories, sorted_tokens


def _make_shard(name: str, targets: list[str]) -> Shard:
    ordered_targets = tuple(sorted(targets))
    return Shard(name=name, targets=ordered_targets, size=len(ordered_targets))


def build_small_shards(
    directory_groups: dict[str, list[str]],
    token_groups: dict[str, list[str]],
    *,
    isolated_token_threshold: int = DEFAULT_ISOLATED_TOKEN_THRESHOLD,
    small_shard_max_files: int = DEFAULT_SMALL_SHARD_MAX_FILES,
) -> list[Shard]:
    isolated: list[Shard] = []
    remaining_token_groups: list[tuple[str, list[str]]] = []

    for directory, targets in sorted(directory_groups.items(), key=lambda item: item[0]):
        isolated.append(_make_shard(directory.replace("_", "-"), targets))

    for token, targets in sorted(token_groups.items(), key=lambda item: item[0]):
        if len(targets) >= isolated_token_threshold:
            isolated.append(_make_shard(token.replace("_", "-"), targets))
        else:
            remaining_token_groups.append((token, targets))

    packed: list[Shard] = []
    current_targets: list[str] = []
    current_index = 1

    for _token, targets in remaining_token_groups:
        if current_targets and len(current_targets) + len(targets) > small_shard_max_files:
            packed.append(_make_shard(f"mixed-{current_index:02d}", current_targets))
            current_index += 1
            current_targets = []
        current_targets.extend(targets)

    if current_targets:
        packed.append(_make_shard(f"mixed-{current_index:02d}", current_targets))

    return sorted(isolated, key=lambda shard: shard.name) + packed


def build_large_shards(
    small_shards: list[Shard],
    *,
    large_shard_count: int = DEFAULT_LARGE_SHARD_COUNT,
) -> list[Shard]:
    if not small_shards:
        return []

    bin_count = max(1, min(int(large_shard_count), len(small_shards)))
    bins = [{"names": [], "targets": [], "size": 0} for _ in range(bin_count)]

    for shard in sorted(small_shards, key=lambda item: (-item.size, item.name)):
        target_bin = min(
            range(bin_count),
            key=lambda idx: (bins[idx]["size"], len(bins[idx]["names"]), idx),
        )
        bins[target_bin]["names"].append(shard.name)
        bins[target_bin]["targets"].extend(shard.targets)
        bins[target_bin]["size"] += shard.size

    large_shards: list[Shard] = []
    for index, bucket in enumerate(bins, start=1):
        if not bucket["targets"]:
            continue
        large_shards.append(
            _make_shard(
                f"large-{index:02d}",
                list(bucket["targets"]),
            )
        )
    return large_shards


def build_plan(
    *,
    repo_root: Path = ROOT,
    max_stage: str = "large",
    isolated_token_threshold: int = DEFAULT_ISOLATED_TOKEN_THRESHOLD,
    small_shard_max_files: int = DEFAULT_SMALL_SHARD_MAX_FILES,
    large_shard_count: int = DEFAULT_LARGE_SHARD_COUNT,
    collect_timeout_seconds: int = COLLECT_TIMEOUT_SECONDS,
    small_timeout_seconds: int = SMALL_TIMEOUT_SECONDS,
    large_timeout_seconds: int = LARGE_TIMEOUT_SECONDS,
    full_timeout_seconds: int = FULL_TIMEOUT_SECONDS,
) -> list[dict[str, Any]]:
    if max_stage not in _STAGE_ORDER:
        raise ValueError(f"Unknown max stage: {max_stage}")

    directory_groups, token_groups = discover_test_targets(repo_root)
    small_shards = build_small_shards(
        directory_groups,
        token_groups,
        isolated_token_threshold=isolated_token_threshold,
        small_shard_max_files=small_shard_max_files,
    )
    large_shards = build_large_shards(
        small_shards,
        large_shard_count=large_shard_count,
    )

    plan: list[dict[str, Any]] = [
        {
            "stage": "collect",
            "label": "collect-only",
            "command": [PY, "-m", "pytest", "--collect-only", "-q", "tests"],
            "targets": ["tests"],
            "target_count": 1,
            "timeout_seconds": int(collect_timeout_seconds),
        }
    ]

    if _STAGE_ORDER[max_stage] >= _STAGE_ORDER["small"]:
        for shard in small_shards:
            plan.append(
                {
                    "stage": "small",
                    "label": shard.name,
                    "command": [PY, "-m", "pytest", "-q", *shard.targets],
                    "targets": list(shard.targets),
                    "target_count": shard.size,
                    "timeout_seconds": int(small_timeout_seconds),
                    "shard": shard.to_dict(),
                }
            )

    if _STAGE_ORDER[max_stage] >= _STAGE_ORDER["large"]:
        for shard in large_shards:
            plan.append(
                {
                    "stage": "large",
                    "label": shard.name,
                    "command": [PY, "-m", "pytest", "-q", *shard.targets],
                    "targets": list(shard.targets),
                    "target_count": shard.size,
                    "timeout_seconds": int(large_timeout_seconds),
                    "shard": shard.to_dict(),
                }
            )

    if _STAGE_ORDER[max_stage] >= _STAGE_ORDER["full"]:
        plan.append(
            {
                "stage": "full",
                "label": "full-suite",
                "command": [PY, "-m", "pytest", "-q", "tests"],
                "targets": ["tests"],
                "target_count": 1,
                "timeout_seconds": int(full_timeout_seconds),
            }
        )

    return plan


def _command_text(command: list[str]) -> str:
    return shlex.join([str(part) for part in command])


def _tail(text: str, *, limit: int = 4000) -> str:
    clean = str(text or "").strip()
    if len(clean) <= limit:
        return clean
    return clean[-limit:]


def _execute_step(
    step: dict[str, Any],
    *,
    repo_root: Path = ROOT,
    capture_output: bool = False,
) -> dict[str, Any]:
    started = time.monotonic()
    kwargs: dict[str, Any] = {
        "cwd": repo_root,
        "check": False,
        "timeout": int(step["timeout_seconds"]),
    }
    if capture_output:
        kwargs.update({"capture_output": True, "text": True})

    try:
        completed = subprocess.run(list(step["command"]), **kwargs)
        combined_output = ""
        if capture_output:
            combined_output = ((completed.stdout or "") + (completed.stderr or "")).strip()
        elapsed = time.monotonic() - started
        return {
            "stage": str(step["stage"]),
            "label": str(step["label"]),
            "ok": completed.returncode == 0,
            "returncode": int(completed.returncode),
            "command": list(step["command"]),
            "target_count": int(step["target_count"]),
            "timeout_seconds": int(step["timeout_seconds"]),
            "elapsed_seconds": round(elapsed, 2),
            "output_tail": _tail(combined_output),
        }
    except subprocess.TimeoutExpired as exc:
        combined_output = ""
        if capture_output:
            combined_output = ((exc.stdout or "") + (exc.stderr or "")).strip()
        elapsed = time.monotonic() - started
        return {
            "stage": str(step["stage"]),
            "label": str(step["label"]),
            "ok": False,
            "returncode": 124,
            "command": list(step["command"]),
            "target_count": int(step["target_count"]),
            "timeout_seconds": int(step["timeout_seconds"]),
            "elapsed_seconds": round(elapsed, 2),
            "output_tail": _tail(combined_output or f"Command timed out after {step['timeout_seconds']}s"),
        }


def _print_plan(plan: list[dict[str, Any]]) -> None:
    current_stage = ""
    for step in plan:
        stage = str(step["stage"])
        if stage != current_stage:
            print(f"[{stage}]")
            current_stage = stage
        print(f"- {step['label']}: {step['target_count']} target(s)")


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--max-stage",
        choices=("collect", "small", "large", "full"),
        default="large",
        help="Highest step-up stage to execute. Default: large.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON output.")
    parser.add_argument(
        "--list", action="store_true", help="List the planned stages and shard counts without running them."
    )
    parser.add_argument(
        "--continue-on-fail",
        action="store_true",
        help="Continue through later stages even if an earlier step fails.",
    )
    parser.add_argument(
        "--isolated-token-threshold",
        type=int,
        default=DEFAULT_ISOLATED_TOKEN_THRESHOLD,
        help="Isolate any top-level token group with at least this many files.",
    )
    parser.add_argument(
        "--small-shard-max-files",
        type=int,
        default=DEFAULT_SMALL_SHARD_MAX_FILES,
        help="Maximum number of files to pack into a mixed small shard.",
    )
    parser.add_argument(
        "--large-shard-count",
        type=int,
        default=DEFAULT_LARGE_SHARD_COUNT,
        help="Number of larger bundle shards to build from the small shards.",
    )
    args = parser.parse_args(argv)

    plan = build_plan(
        max_stage=str(args.max_stage),
        isolated_token_threshold=int(args.isolated_token_threshold),
        small_shard_max_files=int(args.small_shard_max_files),
        large_shard_count=int(args.large_shard_count),
    )

    if args.list:
        print(f"Thomas pytest step-up plan ({args.max_stage})")
        _print_plan(plan)
        return 0

    if not args.json:
        print(f"[stepup] Root: {ROOT}")
        print(f"[stepup] Max stage: {args.max_stage}")
        print(f"[stepup] Planned steps: {len(plan)}")

    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for step in plan:
        if not args.json:
            print(f"\n[stepup] {step['stage']} -> {step['label']} ({step['target_count']} target(s))")
            print(f"[stepup] $ {_command_text(list(step['command']))}")
        result = _execute_step(step, repo_root=ROOT, capture_output=bool(args.json))
        results.append(result)
        if not args.json:
            status = "PASS" if result["ok"] else "FAIL"
            print(f"[stepup] {status} {step['stage']} -> {step['label']} ({result['elapsed_seconds']:.2f}s)")
        if not result["ok"]:
            failures.append(result)
            if not args.continue_on_fail:
                break

    ok = not failures

    if args.json:
        print(
            json.dumps(
                {
                    "ok": ok,
                    "max_stage": str(args.max_stage),
                    "results": results,
                },
                sort_keys=True,
            )
        )
        return 0 if ok else 1

    print("\n[stepup] Summary: PASS" if ok else "\n[stepup] Summary: FAILED")
    if failures:
        for failure in failures:
            print(f"[stepup] - {failure['stage']} -> {failure['label']}: " f"exit {failure['returncode']}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(run())
