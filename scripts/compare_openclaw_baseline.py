"""Deterministic Thomas-vs-OpenClaw comparison runner.

Uses one canonical baseline artifact:
  demo/baselines/openclaw.current.json

This script is intentionally local and deterministic so repeated requests use
the same comparison source and rules unless the baseline artifact changes.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASELINE = ROOT / "demo" / "baselines" / "openclaw.current.json"
DEFAULT_WRITE_PATH = ROOT / "docs" / "openclaw_gap_runs" / "latest_compare.json"

CODE_EXTENSIONS = {
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".c",
    ".cpp",
    ".h",
    ".cs",
    ".swift",
    ".php",
    ".rb",
    ".lua",
    ".m",
    ".mm",
    ".dart",
    ".sh",
    ".ps1",
    ".bat",
    ".sql",
    ".css",
    ".scss",
    ".html",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
}

SKIP_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "dist",
    "build",
    "target",
    "coverage",
    ".next",
    ".nuxt",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
}


@dataclass(frozen=True)
class BaselineSpec:
    baseline_path: Path
    commit: str
    local_snapshot_path: Path
    thomas_roots: list[str]
    openclaw_roots: list[str]
    openclaw_top_level_commands: int
    openclaw_subcommand_depth: dict[str, int]


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"missing baseline artifact: {path}") from exc
    except Exception as exc:
        raise SystemExit(f"invalid baseline artifact JSON ({path}): {type(exc).__name__}: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"baseline artifact must be a JSON object: {path}")
    return data


def _load_baseline(path: Path) -> BaselineSpec:
    raw = _read_json(path)
    system = str(raw.get("system") or "").strip().lower()
    if system != "openclaw":
        raise SystemExit(f"baseline artifact must declare system=openclaw: {path}")

    commit = str(raw.get("commit") or "").strip().lower()
    if re.fullmatch(r"[0-9a-f]{7,40}", commit) is None:
        raise SystemExit(f"baseline artifact must include valid commit hash: {path}")

    comparison = raw.get("comparison") or {}
    if not isinstance(comparison, dict):
        raise SystemExit(f"baseline artifact field 'comparison' must be an object: {path}")

    snapshot_env = str(os.environ.get("OPENCLAW_SNAPSHOT_PATH") or "").strip()
    snapshot_raw = snapshot_env or str(raw.get("local_snapshot_path") or "").strip()
    if not snapshot_raw:
        raise SystemExit(
            "baseline artifact is missing local_snapshot_path; "
            "set OPENCLAW_SNAPSHOT_PATH or add local_snapshot_path to baseline artifact"
        )
    local_snapshot_path = Path(snapshot_raw).resolve()
    if not local_snapshot_path.exists():
        raise SystemExit(f"openclaw snapshot path does not exist: {local_snapshot_path}")

    thomas_roots = comparison.get("thomas_roots") or ["thomas", "tests"]
    openclaw_roots = comparison.get("openclaw_roots") or ["src", "test", "tests"]
    if not isinstance(thomas_roots, list) or not all(isinstance(x, str) for x in thomas_roots):
        raise SystemExit("comparison.thomas_roots must be a list[str]")
    if not isinstance(openclaw_roots, list) or not all(isinstance(x, str) for x in openclaw_roots):
        raise SystemExit("comparison.openclaw_roots must be a list[str]")

    openclaw_top = int(comparison.get("openclaw_top_level_commands", 44))
    depth_raw = comparison.get("openclaw_subcommand_depth") or {}
    if not isinstance(depth_raw, dict):
        raise SystemExit("comparison.openclaw_subcommand_depth must be an object")
    openclaw_depth: dict[str, int] = {}
    for k, v in depth_raw.items():
        key = str(k).strip()
        if not key:
            continue
        openclaw_depth[key] = int(v)
    if not openclaw_depth:
        raise SystemExit("comparison.openclaw_subcommand_depth is empty")

    return BaselineSpec(
        baseline_path=path,
        commit=commit,
        local_snapshot_path=local_snapshot_path,
        thomas_roots=list(thomas_roots),
        openclaw_roots=list(openclaw_roots),
        openclaw_top_level_commands=openclaw_top,
        openclaw_subcommand_depth=openclaw_depth,
    )


def _count_code(root_paths: Iterable[Path]) -> dict[str, int]:
    files = 0
    loc = 0
    for p in _iter_code_files(root_paths):
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        non_empty = sum(1 for ln in text.splitlines() if ln.strip())
        files += 1
        loc += non_empty
    return {"files": files, "loc": loc}


def _iter_code_files(root_paths: Iterable[Path]) -> Iterable[Path]:
    seen: set[str] = set()
    for root in root_paths:
        if not root.exists():
            continue
        if root.is_file():
            if root.suffix.lower() not in CODE_EXTENSIONS:
                continue
            key = str(root.resolve())
            if key in seen:
                continue
            seen.add(key)
            yield root
            continue

        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for filename in filenames:
                p = Path(dirpath) / filename
                if p.suffix.lower() not in CODE_EXTENSIONS:
                    continue
                key = str(p.resolve())
                if key in seen:
                    continue
                seen.add(key)
                yield p


def _count_text_occurrences(root_paths: Iterable[Path], needle: str) -> dict[str, int]:
    files = 0
    occurrences = 0
    for p in _iter_code_files(root_paths):
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        hits = int(text.count(needle))
        if hits > 0:
            files += 1
            occurrences += hits
    return {"files_with_hits": files, "occurrences": occurrences}


def _count_immediate_dirs(path: Path) -> int:
    if not path.exists() or not path.is_dir():
        return 0
    return sum(1 for child in path.iterdir() if child.is_dir() and not child.name.startswith("."))


def _count_mobile_surface_dirs(base: Path) -> int:
    names = ("android", "ios", "macos", "shared")
    hits: set[str] = set()
    for name in names:
        for parent in (base, base / "apps"):
            p = parent / name
            if p.exists() and p.is_dir():
                hits.add(name)
    return len(hits)


def _metric_row(
    *,
    metric: str,
    thomas: int | float,
    openclaw: int | float,
    preference: str,
    rationale: str,
) -> dict[str, Any]:
    winner = "tie"
    if preference == "higher_is_better":
        if float(thomas) > float(openclaw):
            winner = "thomas"
        elif float(openclaw) > float(thomas):
            winner = "openclaw"
    elif preference == "lower_is_better":
        if float(thomas) < float(openclaw):
            winner = "thomas"
        elif float(openclaw) < float(thomas):
            winner = "openclaw"
    else:
        raise ValueError(f"unknown metric preference: {preference}")

    delta = float(thomas) - float(openclaw)
    delta_value: int | float
    if float(thomas).is_integer() and float(openclaw).is_integer():
        delta_value = int(delta)
    else:
        delta_value = round(delta, 3)

    return {
        "metric": metric,
        "thomas": thomas,
        "openclaw": openclaw,
        "preference": preference,
        "winner": winner,
        "delta_thomas_minus_openclaw": delta_value,
        "rationale": rationale,
    }


def _is_test_file(path: Path) -> bool:
    parts = [segment.lower() for segment in path.parts]
    if any(part in {"test", "tests", "__tests__"} for part in parts):
        return True
    name = path.name.lower()
    if ".test." in name or ".spec." in name:
        return True
    if name.startswith("test_") or name.startswith("test.") or name.endswith("_test.py"):
        return True
    return False


def _count_test_code(root_paths: Iterable[Path]) -> dict[str, int]:
    files = 0
    loc = 0
    for p in _iter_code_files(root_paths):
        if not _is_test_file(p):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        non_empty = sum(1 for ln in text.splitlines() if ln.strip())
        files += 1
        loc += non_empty
    return {"files": files, "loc": loc}


def _run_help(args: list[str]) -> str:
    proc = subprocess.run(
        [sys.executable, "-m", "thomas"] + args,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    out = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    return out


def _parse_click_commands(help_text: str) -> list[str]:
    lines = help_text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip().startswith("Commands:"):
            start = i + 1
            break
    if start is None:
        return []

    names: list[str] = []
    for line in lines[start:]:
        stripped = line.strip()
        if not stripped:
            if names:
                break
            continue
        if stripped.startswith(("Options:", "Arguments:", "Usage:")):
            if names:
                break
            continue
        match = re.match(r"^([a-zA-Z0-9][a-zA-Z0-9_-]*)\b", stripped)
        if match is None:
            if names:
                break
            continue
        names.append(match.group(1))
    return names


def _count_subcommands(command: str) -> int:
    help_text = _run_help([command, "--help"])
    return len(_parse_click_commands(help_text))


def _build_result(spec: BaselineSpec) -> dict[str, Any]:
    thomas_root_paths = [ROOT / rel for rel in spec.thomas_roots]
    openclaw_root_paths = [spec.local_snapshot_path / rel for rel in spec.openclaw_roots]

    thomas_code = _count_code(thomas_root_paths)
    openclaw_code = _count_code(openclaw_root_paths)

    thomas_top_level = len(_parse_click_commands(_run_help(["--help"])))
    thomas_depth = {cmd: _count_subcommands(cmd) for cmd in spec.openclaw_subcommand_depth.keys()}

    thomas_depth_sum = int(sum(thomas_depth.values()))
    openclaw_depth_sum = int(sum(int(v) for v in spec.openclaw_subcommand_depth.values()))
    depth_parity_pct = round((thomas_depth_sum / openclaw_depth_sum) * 100, 1) if openclaw_depth_sum > 0 else 0.0

    thomas_loc = int(thomas_code["loc"])
    openclaw_loc = int(openclaw_code["loc"])
    loc_ratio = round((openclaw_loc / thomas_loc), 2) if thomas_loc > 0 else 0.0

    thomas_test_code = _count_test_code(thomas_root_paths)
    openclaw_test_code = _count_test_code(openclaw_root_paths)

    thomas_browser_code = _count_code(
        [
            ROOT / "thomas" / "browser",
            ROOT / "thomas" / "cli" / "commands" / "browser",
            ROOT / "thomas" / "cli" / "live_browser.py",
            ROOT / "thomas" / "tools" / "browser.py",
        ]
    )
    openclaw_browser_code = _count_code([spec.local_snapshot_path / "src" / "browser"])

    thomas_plugin_code = _count_code([ROOT / "thomas" / "plugins", ROOT / "thomas" / "cli" / "commands" / "plugins"])
    openclaw_plugin_code = _count_code(
        [spec.local_snapshot_path / "src" / "plugins", spec.local_snapshot_path / "packages" / "plugin-sdk"]
    )

    thomas_extension_dirs = _count_immediate_dirs(ROOT / "extensions")
    openclaw_extension_dirs = _count_immediate_dirs(spec.local_snapshot_path / "extensions")

    thomas_mobile_dirs = _count_mobile_surface_dirs(ROOT)
    openclaw_mobile_dirs = _count_mobile_surface_dirs(spec.local_snapshot_path)

    thomas_gateway_paths = [ROOT / "thomas" / "server" / "routes", ROOT / "thomas" / "cli" / "commands" / "gateway"]
    openclaw_gateway_paths = [spec.local_snapshot_path / "src" / "gateway", spec.local_snapshot_path / "src" / "cli"]
    thomas_chat_compat = _count_text_occurrences(thomas_gateway_paths, "/v1/chat/completions")
    openclaw_chat_compat = _count_text_occurrences(openclaw_gateway_paths, "/v1/chat/completions")
    thomas_responses_compat = _count_text_occurrences(thomas_gateway_paths, "/v1/responses")
    openclaw_responses_compat = _count_text_occurrences(openclaw_gateway_paths, "/v1/responses")

    metric_board: list[dict[str, Any]] = [
        _metric_row(
            metric="loc.total_files",
            thomas=int(thomas_code["files"]),
            openclaw=int(openclaw_code["files"]),
            preference="higher_is_better",
            rationale="Larger total code surface is treated as broader capability coverage for this competitive board.",
        ),
        _metric_row(
            metric="loc.total_loc",
            thomas=thomas_loc,
            openclaw=openclaw_loc,
            preference="higher_is_better",
            rationale="Higher LOC is treated as broader implemented capability for this competitive board.",
        ),
        _metric_row(
            metric="tests.files",
            thomas=int(thomas_test_code["files"]),
            openclaw=int(openclaw_test_code["files"]),
            preference="higher_is_better",
            rationale="More test files usually indicate broader regression coverage.",
        ),
        _metric_row(
            metric="tests.loc",
            thomas=int(thomas_test_code["loc"]),
            openclaw=int(openclaw_test_code["loc"]),
            preference="higher_is_better",
            rationale="More test LOC generally reflects deeper scenario coverage.",
        ),
        _metric_row(
            metric="cli.top_level_commands",
            thomas=thomas_top_level,
            openclaw=spec.openclaw_top_level_commands,
            preference="higher_is_better",
            rationale="Top-level command breadth indicates operator entry-point coverage.",
        ),
        _metric_row(
            metric="cli.depth_total",
            thomas=thomas_depth_sum,
            openclaw=openclaw_depth_sum,
            preference="higher_is_better",
            rationale="Subcommand depth tracks operational task coverage.",
        ),
        _metric_row(
            metric="browser.files",
            thomas=int(thomas_browser_code["files"]),
            openclaw=int(openclaw_browser_code["files"]),
            preference="higher_is_better",
            rationale="Browser subsystem file breadth approximates functional surface area.",
        ),
        _metric_row(
            metric="browser.loc",
            thomas=int(thomas_browser_code["loc"]),
            openclaw=int(openclaw_browser_code["loc"]),
            preference="higher_is_better",
            rationale="Browser subsystem LOC indicates depth of implementation paths.",
        ),
        _metric_row(
            metric="plugins.files",
            thomas=int(thomas_plugin_code["files"]),
            openclaw=int(openclaw_plugin_code["files"]),
            preference="higher_is_better",
            rationale="Plugin runtime breadth signals extensibility maturity.",
        ),
        _metric_row(
            metric="plugins.loc",
            thomas=int(thomas_plugin_code["loc"]),
            openclaw=int(openclaw_plugin_code["loc"]),
            preference="higher_is_better",
            rationale="Plugin runtime LOC tracks depth of lifecycle and hook support.",
        ),
        _metric_row(
            metric="extensions.directories",
            thomas=thomas_extension_dirs,
            openclaw=openclaw_extension_dirs,
            preference="higher_is_better",
            rationale="Extension directory count approximates ecosystem/catalog breadth.",
        ),
        _metric_row(
            metric="mobile_surface.directories",
            thomas=thomas_mobile_dirs,
            openclaw=openclaw_mobile_dirs,
            preference="higher_is_better",
            rationale="Mobile/shared directory presence reflects cross-platform scope.",
        ),
        _metric_row(
            metric="gateway.openai_chat_completions.files",
            thomas=int(thomas_chat_compat["files_with_hits"]),
            openclaw=int(openclaw_chat_compat["files_with_hits"]),
            preference="higher_is_better",
            rationale="Presence across files indicates endpoint compatibility integration depth.",
        ),
        _metric_row(
            metric="gateway.openai_chat_completions.occurrences",
            thomas=int(thomas_chat_compat["occurrences"]),
            openclaw=int(openclaw_chat_compat["occurrences"]),
            preference="higher_is_better",
            rationale="Occurrences capture endpoint wiring breadth across modules.",
        ),
        _metric_row(
            metric="gateway.responses.files",
            thomas=int(thomas_responses_compat["files_with_hits"]),
            openclaw=int(openclaw_responses_compat["files_with_hits"]),
            preference="higher_is_better",
            rationale="Presence of /v1/responses support across files reflects compat breadth.",
        ),
        _metric_row(
            metric="gateway.responses.occurrences",
            thomas=int(thomas_responses_compat["occurrences"]),
            openclaw=int(openclaw_responses_compat["occurrences"]),
            preference="higher_is_better",
            rationale="Occurrences capture breadth of OpenResponses wiring.",
        ),
    ]

    for command_name in sorted(spec.openclaw_subcommand_depth.keys()):
        metric_board.append(
            _metric_row(
                metric=f"cli.depth.{command_name}",
                thomas=int(thomas_depth.get(command_name) or 0),
                openclaw=int(spec.openclaw_subcommand_depth.get(command_name) or 0),
                preference="higher_is_better",
                rationale=f"Subcommand depth for `{command_name}` command family.",
            )
        )

    metric_summary = {"thomas_wins": 0, "openclaw_wins": 0, "ties": 0, "total": len(metric_board)}
    openclaw_leads: list[dict[str, Any]] = []
    for row in metric_board:
        winner = str(row.get("winner") or "tie")
        if winner == "thomas":
            metric_summary["thomas_wins"] += 1
        elif winner == "openclaw":
            metric_summary["openclaw_wins"] += 1
            openclaw_leads.append(row)
        else:
            metric_summary["ties"] += 1

    return {
        "computed_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "comparison_source": {
            "baseline_file": str(spec.baseline_path),
            "openclaw_commit": spec.commit,
            "openclaw_snapshot_path": str(spec.local_snapshot_path),
            "thomas_roots": spec.thomas_roots,
            "openclaw_roots": spec.openclaw_roots,
        },
        "loc": {
            "thomas": thomas_code,
            "openclaw": openclaw_code,
            "openclaw_over_thomas_ratio": loc_ratio,
        },
        "tests": {
            "thomas": thomas_test_code,
            "openclaw": openclaw_test_code,
        },
        "subsystems": {
            "browser": {"thomas": thomas_browser_code, "openclaw": openclaw_browser_code},
            "plugins": {"thomas": thomas_plugin_code, "openclaw": openclaw_plugin_code},
            "extensions": {
                "thomas_directories": thomas_extension_dirs,
                "openclaw_directories": openclaw_extension_dirs,
            },
            "mobile_surface": {
                "thomas_directories": thomas_mobile_dirs,
                "openclaw_directories": openclaw_mobile_dirs,
            },
        },
        "gateway_compat": {
            "chat_completions": {"thomas": thomas_chat_compat, "openclaw": openclaw_chat_compat},
            "responses": {"thomas": thomas_responses_compat, "openclaw": openclaw_responses_compat},
        },
        "cli": {
            "thomas_top_level_commands": thomas_top_level,
            "openclaw_top_level_commands": spec.openclaw_top_level_commands,
            "thomas_subcommand_depth": thomas_depth,
            "openclaw_subcommand_depth": spec.openclaw_subcommand_depth,
            "thomas_depth_total": thomas_depth_sum,
            "openclaw_depth_total": openclaw_depth_sum,
            "depth_parity_percent": depth_parity_pct,
        },
        "metric_board": metric_board,
        "metric_board_summary": metric_summary,
        "openclaw_leads": openclaw_leads,
    }


def _print_human(result: Mapping[str, Any]) -> None:
    src = result["comparison_source"]
    loc = result["loc"]
    tests = result.get("tests") or {}
    cli = result["cli"]
    board = result.get("metric_board_summary") or {}
    leads = list(result.get("openclaw_leads") or [])

    print("OpenClaw Baseline Compare")
    print(f"- baseline file: {src['baseline_file']}")
    print(f"- openclaw commit: {src['openclaw_commit']}")
    print(f"- openclaw snapshot path: {src['openclaw_snapshot_path']}")
    print(f"- computed at: {result['computed_at_utc']}")
    print("")
    print("Code Footprint")
    print(f"- Thomas:   {loc['thomas']['loc']:,} LOC across {loc['thomas']['files']:,} files")
    print(f"- OpenClaw: {loc['openclaw']['loc']:,} LOC across {loc['openclaw']['files']:,} files")
    print(f"- ratio (OpenClaw/Thomas): {loc['openclaw_over_thomas_ratio']:.2f}x")
    if isinstance(tests, dict):
        t_tests = tests.get("thomas") or {}
        o_tests = tests.get("openclaw") or {}
        if isinstance(t_tests, dict) and isinstance(o_tests, dict):
            print(
                f"- tests: Thomas {int(t_tests.get('loc') or 0):,} LOC / {int(t_tests.get('files') or 0):,} files, "
                f"OpenClaw {int(o_tests.get('loc') or 0):,} LOC / {int(o_tests.get('files') or 0):,} files"
            )
    print("")
    print("CLI Surface")
    print(
        f"- top-level commands: Thomas {cli['thomas_top_level_commands']} vs OpenClaw {cli['openclaw_top_level_commands']}"
    )
    print(
        "- tracked subcommand depth: "
        f"Thomas {cli['thomas_depth_total']} vs OpenClaw {cli['openclaw_depth_total']} "
        f"({cli['depth_parity_percent']:.1f}% parity)"
    )
    print("")
    print("Metric Board")
    print(
        f"- wins: Thomas {int(board.get('thomas_wins') or 0)} | "
        f"OpenClaw {int(board.get('openclaw_wins') or 0)} | ties {int(board.get('ties') or 0)}"
    )
    if leads:
        print("- open gaps (OpenClaw-leading metrics):")
        for row in leads[:10]:
            print(
                f"  - {row.get('metric')}: Thomas {row.get('thomas')} vs OpenClaw {row.get('openclaw')} "
                f"({row.get('preference')})"
            )
        if len(leads) > 10:
            print(f"  - ... and {len(leads) - 10} more")


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare Thomas against pinned OpenClaw baseline.")
    parser.add_argument(
        "--baseline",
        default=str(DEFAULT_BASELINE),
        help=f"Baseline artifact path (default: {DEFAULT_BASELINE})",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON output.")
    parser.add_argument(
        "--write",
        action="store_true",
        help=f"Write JSON report to {DEFAULT_WRITE_PATH}",
    )
    parser.add_argument(
        "--write-path",
        default=str(DEFAULT_WRITE_PATH),
        help=f"Output path for --write (default: {DEFAULT_WRITE_PATH})",
    )
    args = parser.parse_args(argv)

    baseline_path = Path(args.baseline)
    if not baseline_path.is_absolute():
        baseline_path = (ROOT / baseline_path).resolve()
    spec = _load_baseline(baseline_path)
    result = _build_result(spec)

    if args.write:
        write_path = Path(args.write_path)
        if not write_path.is_absolute():
            write_path = (ROOT / write_path).resolve()
        write_path.parent.mkdir(parents=True, exist_ok=True)
        write_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        _print_human(result)

    return 0


if __name__ == "__main__":
    raise SystemExit(run())
