from __future__ import annotations

import argparse
import ast
import fnmatch
import glob
import json
import math
import os
import re
import subprocess
import sys
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

from thomas.plugins.benchmark_program import evaluate_benchmark_program
from thomas.plugins.competitor_evo_scope import build_prediction_evo_scope
from thomas.plugins.competitor_intel_store import load_registry, render_registry_markdown
from thomas.plugins.test_suite_contract import evaluate_test_suite_contract, load_test_suite_contract

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SUITE_CONFIG = ROOT / "demo" / "baselines" / "agent_comparison_suite.current.json"
DEFAULT_WRITE_PATH = ROOT / "docs" / "openclaw_gap_runs" / "latest_full_suite_compare.json"
DEFAULT_WRITE_MD_PATH = ROOT / "docs" / "openclaw_gap_runs" / "latest_full_suite_compare.md"
DEFAULT_REGISTRY_PATH = ROOT / "docs" / "openclaw_gap_runs" / "competitor_registry.json"
DEFAULT_REGISTRY_MD_PATH = ROOT / "docs" / "openclaw_gap_runs" / "competitor_registry.md"
DEFAULT_TEST_SUITE_CONTRACT_PATH = ROOT / "demo" / "baselines" / "agent_test_suite_full_coverage.contract.json"
DEFAULT_EXECUTION_POLICY = {
    "quality_is_king": True,
    "cycle_limit_disabled": True,
    "stop_condition": "Continue until no known meaningful gaps remain or user explicitly stops.",
}

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

DEFAULT_GATEWAY_PATTERNS = {
    "chat_completions": "/v1/chat/completions",
    "responses": "/v1/responses",
}

DEFAULT_CATEGORY_WEIGHTS = {
    "code_surface": 1.0,
    "test_rigor": 1.2,
    "cli_surface": 1.15,
    "compatibility": 1.15,
    "performance_load": 1.35,
    "resilience": 1.35,
    "security": 1.45,
    "cost_efficiency": 1.35,
    "production_readiness": 1.4,
    "benchmark_execution": 1.5,
    "reliability": 1.35,
    "integrity": 1.3,
    "maintainability": 0.9,
}

DEFAULT_COMPETITOR_SOURCE_ROOTS = ["src", "lib", "app", "packages", "."]
DEFAULT_COMPETITOR_TEST_ROOTS = ["test", "tests", "spec", "__tests__"]
DEFAULT_COMPETITOR_BROWSER_ROOTS = ["src/browser", "browser", "web", "ui"]
DEFAULT_COMPETITOR_PLUGIN_ROOTS = ["src/plugins", "plugins", "extensions", "packages/plugin-sdk"]
DEFAULT_COMPETITOR_GATEWAY_ROOTS = ["src/gateway", "gateway", "server", "api"]
DEFAULT_COMPETITOR_CLI_ROOTS = ["src/cli", "cli", "bin"]


@dataclass(frozen=True)
class MetricSpec:
    metric: str
    category: str
    preference: str
    weight: float
    rationale: str
    test_mode: str = "quick"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"suite config not found: {path}") from exc
    except Exception as exc:
        raise ValueError(f"invalid JSON ({path}): {type(exc).__name__}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object at {path}")
    return payload


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _safe_float(value: Any) -> float | None:
    try:
        out = float(value)
    except json.JSONDecodeError:
        return None
    if not math.isfinite(out):
        return None
    return out


def _is_number(value: Any) -> bool:
    return _safe_float(value) is not None


def _resolve(base: Path, raw: str) -> Path:
    p = Path(str(raw or "").strip())
    if p.is_absolute():
        return p
    return (base / p).resolve()


def _iter_files(root_paths: Iterable[Path], *, suffixes: set[str] | None = None) -> Iterable[Path]:
    seen: set[str] = set()
    lowered_suffixes = {s.lower() for s in (suffixes or set())}
    for root in root_paths:
        if not root.exists():
            continue
        if root.is_file():
            if lowered_suffixes and root.suffix.lower() not in lowered_suffixes:
                continue
            key = str(root.resolve())
            if key in seen:
                continue
            seen.add(key)
            yield root
            continue
        for dirpath, dirnames, filenames in os.walk(root, onerror=lambda _err: None):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for filename in filenames:
                p = Path(dirpath) / filename
                if lowered_suffixes and p.suffix.lower() not in lowered_suffixes:
                    continue
                key = str(p.resolve())
                if key in seen:
                    continue
                seen.add(key)
                yield p


def _count_non_empty_lines(path: Path) -> int:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except (OSError, FileNotFoundError):
        return 0
    return sum(1 for line in text.splitlines() if line.strip())


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


def _count_code(root_paths: Iterable[Path]) -> dict[str, int]:
    files = 0
    loc = 0
    for path in _iter_files(root_paths, suffixes=CODE_EXTENSIONS):
        files += 1
        loc += _count_non_empty_lines(path)
    return {"files": files, "loc": loc}


def _count_test_code(
    root_paths: Iterable[Path],
    *,
    include_all: bool = False,
    seen_files: set[str] | None = None,
) -> dict[str, int]:
    files = 0
    loc = 0
    seen = seen_files if seen_files is not None else set()
    for path in _iter_files(root_paths, suffixes=CODE_EXTENSIONS):
        try:
            key = str(path.resolve())
        except (ValueError, TypeError):
            key = str(path)
        if key in seen:
            continue
        if not include_all and not _is_test_file(path):
            continue
        seen.add(key)
        files += 1
        loc += _count_non_empty_lines(path)
    return {"files": files, "loc": loc}


def _count_files(root_paths: Iterable[Path], suffixes: set[str]) -> int:
    return sum(1 for _ in _iter_files(root_paths, suffixes=suffixes))


def _count_large_code_files(root_paths: Iterable[Path], *, threshold: int = 800) -> int:
    count = 0
    for path in _iter_files(root_paths, suffixes=CODE_EXTENSIONS):
        if _count_non_empty_lines(path) > threshold:
            count += 1
    return count


def _count_empty_code_files(root_paths: Iterable[Path]) -> int:
    empty = 0
    for path in _iter_files(root_paths, suffixes=CODE_EXTENSIONS):
        # Empty __init__.py is a common intentional package marker.
        if path.name == "__init__.py":
            continue
        try:
            if path.stat().st_size == 0:
                empty += 1
        except Exception:  # REVIEWED: broad catch
            continue
    return empty


def _count_python_syntax_errors(root_paths: Iterable[Path]) -> int:
    failures = 0
    for path in _iter_files(root_paths, suffixes={".py"}):
        try:
            # Use utf-8-sig so BOM-prefixed files are parsed correctly.
            text = path.read_text(encoding="utf-8-sig", errors="ignore")
            ast.parse(text)
        except (OSError, FileNotFoundError):
            failures += 1
    return failures


def _count_invalid_json_files(root_paths: Iterable[Path]) -> int:
    failures = 0
    for path in _iter_files(root_paths, suffixes={".json"}):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            failures += 1
    return failures


def _count_text_occurrences(root_paths: Iterable[Path], needle: str) -> dict[str, int]:
    files = 0
    occurrences = 0
    for path in _iter_files(root_paths, suffixes=CODE_EXTENSIONS):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except json.JSONDecodeError:
            continue
        hits = int(text.count(needle))
        if hits > 0:
            files += 1
            occurrences += hits
    return {"files_with_hits": files, "occurrences": occurrences}


def _count_immediate_dirs(path: Path) -> int:
    if not path.exists() or not path.is_dir():
        return 0
    try:
        return sum(1 for child in path.iterdir() if child.is_dir() and not child.name.startswith("."))
    except (OSError, FileNotFoundError):
        return 0


def _count_mobile_surface_dirs(base: Path, parent_candidates: Sequence[str]) -> int:
    names = ("android", "ios", "macos", "shared")
    hits: set[str] = set()
    for parent_rel in parent_candidates:
        parent = _resolve(base, parent_rel)
        for name in names:
            p = parent / name
            if p.exists() and p.is_dir():
                hits.add(name)
    return len(hits)


def _count_empty_files(root_paths: Iterable[Path]) -> int:
    empty = 0
    for path in _iter_files(root_paths):
        try:
            if path.is_file() and path.stat().st_size == 0:
                empty += 1
        except (OSError, FileNotFoundError):
            continue
    return empty


def _parse_click_commands(help_text: str) -> list[str]:
    lines = help_text.splitlines()
    start = None
    for idx, line in enumerate(lines):
        if line.strip().startswith("Commands:"):
            start = idx + 1
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


def _materialize_command(parts: Sequence[str]) -> list[str]:
    out: list[str] = []
    for part in parts:
        text = str(part)
        if text == "{python}":
            out.append(sys.executable)
        else:
            out.append(text)
    return out


def _run_command(command: Sequence[str], *, cwd: Path, timeout_seconds: float = 60.0) -> dict[str, Any]:
    cmd = _materialize_command(command)
    started = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=False,
            timeout=max(1.0, float(timeout_seconds)),
        )
        elapsed = round(max(0.0, time.monotonic() - started), 3)
        return {
            "ok": int(proc.returncode) == 0,
            "returncode": int(proc.returncode),
            "stdout": str(proc.stdout or ""),
            "stderr": str(proc.stderr or ""),
            "elapsed_seconds": elapsed,
            "command": cmd,
        }
    except Exception as exc:
        elapsed = round(max(0.0, time.monotonic() - started), 3)
        return {
            "ok": False,
            "returncode": -999,
            "stdout": "",
            "stderr": f"{type(exc).__name__}: {exc}",
            "elapsed_seconds": elapsed,
            "command": cmd,
        }


def _first_line(text: Any) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    return raw.splitlines()[0].strip()


def _collect_git_version_info(agent_root: Path, *, sync_cfg: Mapping[str, Any]) -> dict[str, Any]:
    enabled = bool(sync_cfg.get("enabled") or False)
    remote = str(sync_cfg.get("remote") or "origin").strip() or "origin"
    branch = str(sync_cfg.get("branch") or "main").strip() or "main"
    fetch = bool(sync_cfg.get("fetch", True))
    pull_ff_only = bool(sync_cfg.get("pull_ff_only", False))
    timeout_seconds = float(sync_cfg.get("timeout_seconds") or 120.0)
    out: dict[str, Any] = {
        "kind": "git",
        "root": str(agent_root),
        "enabled": enabled,
        "remote": remote,
        "branch": branch,
        "fetched": False,
        "pulled": False,
        "local_head": "",
        "remote_head": "",
        "local_branch": "",
        "ahead": None,
        "behind": None,
        "is_up_to_date": None,
        "errors": [],
    }
    if not (agent_root / ".git").exists():
        return {
            "kind": "none",
            "root": str(agent_root),
            "enabled": enabled,
            "errors": [],
        }
    local_branch_run = _run_command(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=agent_root,
        timeout_seconds=timeout_seconds,
    )
    if local_branch_run["ok"]:
        out["local_branch"] = _first_line(local_branch_run.get("stdout"))
        if not branch:
            out["branch"] = str(out["local_branch"] or "main")
    else:
        out["errors"].append(f"git branch query failed: {_first_line(local_branch_run.get('stderr'))}")
    local_head_before = _run_command(["git", "rev-parse", "HEAD"], cwd=agent_root, timeout_seconds=timeout_seconds)
    if local_head_before["ok"]:
        out["local_head_before"] = _first_line(local_head_before.get("stdout"))
    else:
        out["errors"].append(f"git HEAD query failed: {_first_line(local_head_before.get('stderr'))}")
    if enabled and fetch:
        fetch_run = _run_command(
            ["git", "fetch", remote, out["branch"], "--quiet"],
            cwd=agent_root,
            timeout_seconds=timeout_seconds,
        )
        out["fetched"] = bool(fetch_run["ok"])
        if not fetch_run["ok"]:
            out["errors"].append(f"git fetch failed: {_first_line(fetch_run.get('stderr'))}")
    remote_ref = f"{remote}/{out['branch']}"
    remote_head_run = _run_command(["git", "rev-parse", remote_ref], cwd=agent_root, timeout_seconds=timeout_seconds)
    if remote_head_run["ok"]:
        out["remote_head"] = _first_line(remote_head_run.get("stdout"))
    else:
        out["errors"].append(f"git remote head query failed: {_first_line(remote_head_run.get('stderr'))}")
    if enabled and pull_ff_only:
        pull_run = _run_command(
            ["git", "pull", "--ff-only", remote, out["branch"]],
            cwd=agent_root,
            timeout_seconds=max(120.0, timeout_seconds),
        )
        out["pulled"] = bool(pull_run["ok"])
        if not pull_run["ok"]:
            out["errors"].append(f"git pull failed: {_first_line(pull_run.get('stderr'))}")
    local_head_after = _run_command(["git", "rev-parse", "HEAD"], cwd=agent_root, timeout_seconds=timeout_seconds)
    if local_head_after["ok"]:
        out["local_head"] = _first_line(local_head_after.get("stdout"))
    else:
        out["errors"].append(f"git HEAD query (after sync) failed: {_first_line(local_head_after.get('stderr'))}")
    if out["local_head"] and out["remote_head"]:
        ahead_behind_run = _run_command(
            ["git", "rev-list", "--left-right", "--count", f"HEAD...{remote_ref}"],
            cwd=agent_root,
            timeout_seconds=timeout_seconds,
        )
        if ahead_behind_run["ok"]:
            text = _first_line(ahead_behind_run.get("stdout"))
            parts = [p for p in text.split() if p.strip()]
            if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
                out["ahead"] = int(parts[0])
                out["behind"] = int(parts[1])
                out["is_up_to_date"] = bool(out["ahead"] == 0 and out["behind"] == 0)
        else:
            out["errors"].append(f"git ahead/behind query failed: {_first_line(ahead_behind_run.get('stderr'))}")
    return out


def _collect_model_snapshot(agent: Mapping[str, Any], *, agent_root: Path) -> dict[str, Any]:
    captured_at = _now_iso()
    day_utc = captured_at[:10]
    aid = str(agent.get("id") or "").strip()
    required = bool(agent.get("model_snapshot_required") or (aid == "thomas"))
    snapshot: dict[str, Any] = {
        "captured_at_utc": captured_at,
        "day_utc": day_utc,
        "required": required,
        "ok": False,
    }
    command = agent.get("model_snapshot_command") or []
    if isinstance(command, list) and command:
        timeout_seconds = float(agent.get("model_snapshot_timeout_seconds") or 45.0)
        run = _run_command([str(item) for item in command], cwd=agent_root, timeout_seconds=timeout_seconds)
        snapshot["source"] = "command"
        snapshot["command"] = list(run.get("command") or [])
        run_returncode = run.get("returncode")
        snapshot["returncode"] = int(run_returncode) if _is_number(run_returncode) else -999
        snapshot["stderr"] = _first_line(run.get("stderr"))
        stdout_raw = str(run.get("stdout") or "").strip()
        if run["ok"]:
            parsed: Any = None
            if stdout_raw:
                try:
                    parsed = json.loads(stdout_raw)
                except json.JSONDecodeError:
                    parsed = None
            if isinstance(parsed, dict):
                snapshot["ok"] = True
                snapshot["payload"] = parsed
                model = str(parsed.get("model") or parsed.get("model_id") or "").strip()
                provider = str(parsed.get("provider") or "").strip()
                profile = str(parsed.get("profile") or parsed.get("default_model_name") or "").strip()
                if model:
                    snapshot["model"] = model
                if provider:
                    snapshot["provider"] = provider
                if profile:
                    snapshot["profile"] = profile
            elif stdout_raw:
                snapshot["ok"] = True
                snapshot["raw_output"] = _first_line(stdout_raw)
            else:
                snapshot["error"] = "model snapshot command returned empty output"
        else:
            snapshot["error"] = "model snapshot command failed"
        return snapshot
    # Built-in Thomas snapshot path for daily model capture.
    if aid == "thomas":
        try:
            from thomas.core.config import load_config

            cfg = load_config()
            profile = str(cfg.default_model or "").strip()
            model_cfg = cfg.models.get(profile)
            snapshot["source"] = "thomas.core.config"
            snapshot["profile"] = profile
            if model_cfg is not None:
                snapshot["provider"] = str(getattr(model_cfg, "provider", "") or "").strip()
                snapshot["model"] = str(getattr(model_cfg, "model", "") or "").strip()
                snapshot["context_window"] = getattr(model_cfg, "context_window", None)
                snapshot["max_tokens"] = getattr(model_cfg, "max_tokens", None)
                snapshot["ok"] = bool(snapshot.get("model"))
            else:
                snapshot["error"] = "default model profile not found in config"
        except Exception as exc:
            snapshot["error"] = f"{type(exc).__name__}: {exc}"
        return snapshot
    snapshot["source"] = "none"
    snapshot["error"] = "no model snapshot command configured"
    return snapshot


def _update_competitor_registry(
    *,
    result: Mapping[str, Any],
    registry_path: Path,
    registry_md_path: Path,
    result_json_path: Path | None,
    result_md_path: Path | None,
) -> None:
    registry = load_registry(registry_path)
    computed_at = str(result.get("computed_at_utc") or _now_iso())
    suite = dict(result.get("suite") or {})
    suite_id = str(suite.get("id") or "")
    prediction_scope = dict(result.get("prediction_evo_scope") or {})
    prediction_by_competitor = dict(prediction_scope.get("competitors") or {})
    ranking_by_id = {
        str(item.get("agent") or "").strip(): dict(item)
        for item in (dict(result.get("scoreboard") or {}).get("ranking") or [])
        if str(item.get("agent") or "").strip()
    }
    competitors = dict(registry.get("competitors") or {})
    for agent in list(result.get("agents") or []):
        aid = str(agent.get("id") or "").strip()
        if not aid:
            continue
        rank_row = ranking_by_id.get(aid, {})
        entry = dict(competitors.get(aid) or {})
        entry["id"] = aid
        entry["label"] = str(agent.get("label") or aid)
        entry["root"] = str(agent.get("root") or "")
        entry["last_tested_at_utc"] = computed_at
        entry["last_suite_id"] = suite_id
        entry["last_composite_score"] = rank_row.get("composite_score")
        entry["last_rank"] = rank_row.get("rank")
        entry["last_wins"] = rank_row.get("wins")
        entry["version"] = dict(agent.get("version_info") or {})
        entry["model_snapshot"] = dict(agent.get("model_snapshot") or {})
        if aid in prediction_by_competitor:
            entry["prediction_evo_scope"] = dict(prediction_by_competitor.get(aid) or {})
        if result_json_path is not None:
            entry["last_result_json"] = str(result_json_path)
        if result_md_path is not None:
            entry["last_result_markdown"] = str(result_md_path)
        competitors[aid] = entry
    run_record = {
        "computed_at_utc": computed_at,
        "suite_id": suite_id,
        "result_json_path": (str(result_json_path) if result_json_path is not None else ""),
        "result_md_path": (str(result_md_path) if result_md_path is not None else ""),
        "scoreboard": {
            "total_metrics": dict(result.get("scoreboard") or {}).get("total_metrics"),
            "measured_metrics": dict(result.get("scoreboard") or {}).get("measured_metrics"),
            "tie_metrics": dict(result.get("scoreboard") or {}).get("tie_metrics"),
        },
        "ranking": list(dict(result.get("scoreboard") or {}).get("ranking") or []),
        "focus": dict(result.get("focus") or {}),
        "prediction_evo_scope": prediction_scope,
    }
    runs = list(registry.get("runs") or [])
    runs.append(run_record)
    runs = runs[-200:]
    registry["updated_at_utc"] = computed_at
    registry["competitors"] = competitors
    registry["runs"] = runs
    _write_json(registry_path, registry)
    registry_md_path.parent.mkdir(parents=True, exist_ok=True)
    registry_md_path.write_text(render_registry_markdown(registry), encoding="utf-8")


def _existing_rel_roots(root: Path, candidates: Sequence[str]) -> list[str]:
    out: list[str] = []
    for rel in candidates:
        text = str(rel or "").strip()
        if not text:
            continue
        if (root / text).exists():
            out.append(text)
    return out


def _default_competitor_agent(entry: Mapping[str, Any], *, suite_root: Path) -> dict[str, Any]:
    cid = str(entry.get("id") or "").strip()
    label = str(entry.get("label") or cid).strip() or cid
    root_text = str(entry.get("root") or f"runtime/competitors/{cid}").strip()
    root_abs = _resolve(suite_root, root_text)
    source_roots = _existing_rel_roots(
        root_abs, [str(x) for x in (entry.get("source_roots") or DEFAULT_COMPETITOR_SOURCE_ROOTS)]
    )
    if not source_roots:
        source_roots = ["."]
    test_roots = _existing_rel_roots(
        root_abs, [str(x) for x in (entry.get("test_roots") or DEFAULT_COMPETITOR_TEST_ROOTS)]
    )
    browser_roots = _existing_rel_roots(
        root_abs, [str(x) for x in (entry.get("browser_roots") or DEFAULT_COMPETITOR_BROWSER_ROOTS)]
    )
    plugin_roots = _existing_rel_roots(
        root_abs, [str(x) for x in (entry.get("plugin_roots") or DEFAULT_COMPETITOR_PLUGIN_ROOTS)]
    )
    gateway_roots = _existing_rel_roots(
        root_abs, [str(x) for x in (entry.get("gateway_roots") or DEFAULT_COMPETITOR_GATEWAY_ROOTS)]
    )
    cli_roots = _existing_rel_roots(
        root_abs, [str(x) for x in (entry.get("cli_roots") or DEFAULT_COMPETITOR_CLI_ROOTS)]
    )
    return {
        "id": cid,
        "label": label,
        "root": str(root_abs),
        "source_roots": source_roots,
        "test_roots": (test_roots or source_roots),
        "browser_roots": browser_roots,
        "plugin_roots": plugin_roots,
        "gateway_roots": gateway_roots,
        "cli_roots": cli_roots,
        "extensions_root": "extensions",
        "mobile_roots": [".", "apps"],
        "required_paths": [],
        "production_asset_roots": [],
        "cli": {},
        "gateway_patterns": dict(DEFAULT_GATEWAY_PATTERNS),
        "strict_checks": [],
        "benchmark_scorecard_globs": [],
        "benchmark_raw_globs": [],
        "benchmark_evidence_globs": [],
        "benchmark_aliases": [cid],
        "repo_sync": {
            "enabled": True,
            "remote": str(entry.get("remote") or "origin"),
            "branch": str(entry.get("branch") or "main"),
            "fetch": bool(entry.get("fetch", True)),
            "pull_ff_only": bool(entry.get("pull_ff_only", True)),
        },
        "model_snapshot_required": False,
    }


def _materialize_competitor_catalog_agents(
    *,
    suite_config: Mapping[str, Any],
    suite_root: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    agents = [dict(a) for a in (suite_config.get("agents") or []) if isinstance(a, dict)]
    by_id: dict[str, dict[str, Any]] = {
        str(a.get("id") or "").strip(): a for a in agents if str(a.get("id") or "").strip()
    }
    prep: list[dict[str, Any]] = []
    catalog = [c for c in (suite_config.get("competitor_catalog") or []) if isinstance(c, dict)]
    for raw in catalog:
        cid = str(raw.get("id") or "").strip()
        if not cid:
            continue
        enabled = bool(raw.get("enabled", True))
        if not enabled:
            prep.append({"id": cid, "status": "disabled"})
            continue
        root_text = str(raw.get("root") or f"runtime/competitors/{cid}").strip()
        root_abs = _resolve(suite_root, root_text)
        repo_url = str(raw.get("repo_url") or "").strip()
        branch = str(raw.get("branch") or "main").strip() or "main"
        clone_timeout_seconds = float(raw.get("clone_timeout_seconds") or 600.0)
        cloned = False
        clone_error = ""
        if not root_abs.exists() and repo_url:
            root_abs.parent.mkdir(parents=True, exist_ok=True)
            clone_run = _run_command(
                ["git", "clone", "--depth", "1", "--branch", branch, repo_url, str(root_abs)],
                cwd=suite_root,
                timeout_seconds=clone_timeout_seconds,
            )
            cloned = bool(clone_run.get("ok"))
            if not cloned:
                clone_error = _first_line(clone_run.get("stderr"))
        prep.append(
            {
                "id": cid,
                "root": str(root_abs),
                "repo_url": repo_url,
                "branch": branch,
                "cloned": cloned,
                "status": ("ok" if root_abs.exists() else "missing_root"),
                "error": clone_error,
            }
        )
        if cid not in by_id:
            auto_agent = _default_competitor_agent(raw, suite_root=suite_root)
            agents.append(auto_agent)
            by_id[cid] = auto_agent
        else:
            agent = by_id[cid]
            if not str(agent.get("root") or "").strip():
                agent["root"] = str(root_abs)
            if not isinstance(agent.get("repo_sync"), dict):
                agent["repo_sync"] = {
                    "enabled": True,
                    "remote": str(raw.get("remote") or "origin"),
                    "branch": branch,
                    "fetch": bool(raw.get("fetch", True)),
                    "pull_ff_only": bool(raw.get("pull_ff_only", True)),
                }
            if "model_snapshot_required" not in agent:
                agent["model_snapshot_required"] = False
            if not isinstance(agent.get("benchmark_aliases"), list):
                agent["benchmark_aliases"] = [cid]
    return agents, prep


def _resolve_path_value(payload: Any, path: str) -> Any:
    current = payload
    for token in [part for part in str(path).split(".") if part]:
        if isinstance(current, dict):
            if token not in current:
                raise KeyError(token)
            current = current[token]
            continue
        if isinstance(current, list):
            if not token.isdigit():
                raise KeyError(token)
            idx = int(token)
            if idx < 0 or idx >= len(current):
                raise KeyError(token)
            current = current[idx]
            continue
        raise KeyError(token)
    return current


def _assertion_ok(actual: Any, op: str, expected: Any) -> bool:
    op_name = str(op or "eq").strip().lower()
    if op_name == "truthy":
        return bool(actual)
    if op_name == "falsy":
        return not bool(actual)
    if op_name in {"eq", "ne"}:
        if op_name == "eq":
            return actual == expected
        return actual != expected
    actual_num = _safe_float(actual)
    expected_num = _safe_float(expected)
    if actual_num is None or expected_num is None:
        return False
    if op_name == "gt":
        return actual_num > expected_num
    if op_name == "gte":
        return actual_num >= expected_num
    if op_name == "lt":
        return actual_num < expected_num
    if op_name == "lte":
        return actual_num <= expected_num
    return False


def _run_strict_checks(agent: Mapping[str, Any], *, agent_root: Path) -> dict[str, Any]:
    checks = list(agent.get("strict_checks") or [])
    rows: list[dict[str, Any]] = []
    passed = 0
    failed = 0
    elapsed_values: list[float] = []
    assertion_failures = 0
    command_failures = 0

    for raw in checks:
        if not isinstance(raw, dict):
            continue
        cid = str(raw.get("id") or "").strip() or f"check_{len(rows) + 1:02d}"
        cmd = raw.get("command") or []
        if not isinstance(cmd, list) or not cmd:
            rows.append(
                {
                    "id": cid,
                    "pass": False,
                    "error": "missing command list",
                    "assertions": [],
                }
            )
            failed += 1
            command_failures += 1
            continue

        timeout_seconds = float(raw.get("timeout_seconds") or 60.0)
        expect_returncode = int(raw.get("expect_returncode") or 0)
        run = _run_command([str(item) for item in cmd], cwd=agent_root, timeout_seconds=timeout_seconds)
        elapsed_values.append(float(run.get("elapsed_seconds") or 0.0))
        cmd_ok = int(run.get("returncode") or 0) == expect_returncode

        assertion_rows: list[dict[str, Any]] = []
        all_assertions_ok = True
        assertions = raw.get("assertions") or []
        if assertions:
            payload = None
            parse_error = ""
            try:
                payload = json.loads(str(run.get("stdout") or ""))
            except Exception as exc:
                parse_error = f"{type(exc).__name__}: {exc}"
                all_assertions_ok = False
                assertion_rows.append(
                    {
                        "path": "",
                        "op": "json_parse",
                        "expected": "valid_json",
                        "actual": "",
                        "pass": False,
                        "error": parse_error,
                    }
                )
            if parse_error:
                assertion_failures += 1
            else:
                for item in assertions:
                    if not isinstance(item, dict):
                        continue
                    path = str(item.get("path") or "").strip()
                    op = str(item.get("op") or "eq").strip().lower()
                    expected = item.get("value")
                    actual: Any = None
                    path_error = ""
                    try:
                        actual = _resolve_path_value(payload, path)
                    except Exception as exc:
                        path_error = f"{type(exc).__name__}: {exc}"
                    ok = False if path_error else _assertion_ok(actual, op, expected)
                    if not ok:
                        all_assertions_ok = False
                        assertion_failures += 1
                    assertion_rows.append(
                        {
                            "path": path,
                            "op": op,
                            "expected": expected,
                            "actual": actual,
                            "pass": ok,
                            "error": path_error,
                        }
                    )

        passed_now = bool(cmd_ok and all_assertions_ok)
        if passed_now:
            passed += 1
        else:
            failed += 1
            if not cmd_ok:
                command_failures += 1
        rows.append(
            {
                "id": cid,
                "pass": passed_now,
                "command_ok": cmd_ok,
                "returncode": int(run.get("returncode") or -999),
                "elapsed_seconds": float(run.get("elapsed_seconds") or 0.0),
                "assertions": assertion_rows,
                "command": list(run.get("command") or []),
                "stdout_preview": str(run.get("stdout") or "")[:1200],
                "stderr_preview": str(run.get("stderr") or "")[:1200],
            }
        )

    total = passed + failed
    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "pass_rate": (round(passed / total, 6) if total > 0 else None),
        "avg_elapsed_seconds": (round(mean(elapsed_values), 3) if elapsed_values else None),
        "assertion_failures": assertion_failures,
        "command_failures": command_failures,
        "results": rows,
    }


def _percentile(values: Sequence[float], pct: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return round(float(values[0]), 6)
    ordered = sorted(float(v) for v in values)
    q = max(0.0, min(100.0, float(pct)))
    idx = (len(ordered) - 1) * (q / 100.0)
    lo = int(math.floor(idx))
    hi = int(math.ceil(idx))
    if lo == hi:
        return round(float(ordered[lo]), 6)
    frac = idx - lo
    val = ordered[lo] + (ordered[hi] - ordered[lo]) * frac
    return round(float(val), 6)


def _safe_stats(values: Sequence[float]) -> dict[str, float | None]:
    if not values:
        return {"mean": None, "stddev": None, "p50": None, "p95": None, "min": None, "max": None}
    vals = [float(v) for v in values]
    return {
        "mean": round(mean(vals), 6),
        "stddev": (round(pstdev(vals), 6) if len(vals) > 1 else 0.0),
        "p50": _percentile(vals, 50.0),
        "p95": _percentile(vals, 95.0),
        "min": round(min(vals), 6),
        "max": round(max(vals), 6),
    }


def _path_matches_globs(path: Path, globs: Sequence[str]) -> bool:
    if not globs:
        return False
    posix = path.as_posix()
    lowered = posix.lower()
    name = path.name.lower()
    for raw in globs:
        pattern = str(raw or "").strip()
        if not pattern:
            continue
        p = pattern.replace("\\", "/")
        pl = p.lower()
        if fnmatch.fnmatch(posix, p) or fnmatch.fnmatch(lowered, pl):
            return True
        if fnmatch.fnmatch(path.name, p) or fnmatch.fnmatch(name, pl):
            return True
    return False


def _count_regex_hits(
    root_paths: Iterable[Path],
    patterns: Sequence[str],
    *,
    flags: int = re.IGNORECASE,
    ignore_globs: Sequence[str] | None = None,
) -> dict[str, int]:
    files_with_hits = 0
    total_hits = 0
    compiled = [re.compile(pattern, flags=flags) for pattern in patterns if str(pattern).strip()]
    ignored = [str(item).strip() for item in (ignore_globs or []) if str(item).strip()]
    if not compiled:
        return {"files_with_hits": 0, "total_hits": 0}
    for path in _iter_files(root_paths, suffixes=CODE_EXTENSIONS):
        if _path_matches_globs(path, ignored):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except (OSError, FileNotFoundError):
            continue
        file_hits = 0
        for regex in compiled:
            file_hits += len(regex.findall(text))
        if file_hits > 0:
            files_with_hits += 1
            total_hits += int(file_hits)
    return {"files_with_hits": int(files_with_hits), "total_hits": int(total_hits)}


def _run_probe_suite(
    agent: Mapping[str, Any],
    *,
    agent_root: Path,
    probe_key: str,
) -> dict[str, Any]:
    probes = list(agent.get(probe_key) or [])
    runs: list[dict[str, Any]] = []
    elapsed_values: list[float] = []
    throughput_values: list[float] = []
    extracted_values: dict[str, list[float]] = {}
    passed = 0
    failed = 0
    command_failures = 0
    assertion_failures = 0

    for raw in probes:
        if not isinstance(raw, dict):
            continue
        pid = str(raw.get("id") or "").strip() or f"{probe_key}_{len(runs) + 1:02d}"
        cmd = raw.get("command") or []
        if not isinstance(cmd, list) or not cmd:
            runs.append({"id": pid, "pass": False, "error": "missing command list"})
            failed += 1
            command_failures += 1
            continue

        repeat = int(raw.get("repeat") or 1)
        repeat = max(1, min(20, repeat))
        timeout_seconds = float(raw.get("timeout_seconds") or 90.0)
        expect_returncode = int(raw.get("expect_returncode") or 0)
        assertions = raw.get("assertions") or []
        throughput_path = str(raw.get("throughput_numerator_path") or "").strip()
        value_paths = [str(item).strip() for item in (raw.get("value_paths") or []) if str(item).strip()]

        for attempt in range(1, repeat + 1):
            run = _run_command([str(item) for item in cmd], cwd=agent_root, timeout_seconds=timeout_seconds)
            elapsed = float(run.get("elapsed_seconds") or 0.0)
            elapsed_values.append(elapsed)
            cmd_ok = int(run.get("returncode") or 0) == expect_returncode

            payload = None
            json_error = ""
            needs_json = bool(assertions or throughput_path or value_paths)
            if needs_json:
                try:
                    payload = json.loads(str(run.get("stdout") or ""))
                except Exception as exc:
                    json_error = f"{type(exc).__name__}: {exc}"

            assertion_rows: list[dict[str, Any]] = []
            assertions_ok = True
            if assertions:
                if json_error:
                    assertions_ok = False
                    assertion_failures += 1
                    assertion_rows.append(
                        {
                            "path": "",
                            "op": "json_parse",
                            "expected": "valid_json",
                            "actual": "",
                            "pass": False,
                            "error": json_error,
                        }
                    )
                else:
                    for item in assertions:
                        if not isinstance(item, dict):
                            continue
                        path = str(item.get("path") or "").strip()
                        op = str(item.get("op") or "eq").strip().lower()
                        expected = item.get("value")
                        actual: Any = None
                        path_error = ""
                        try:
                            actual = _resolve_path_value(payload, path)
                        except Exception as exc:
                            path_error = f"{type(exc).__name__}: {exc}"
                        ok = False if path_error else _assertion_ok(actual, op, expected)
                        if not ok:
                            assertions_ok = False
                            assertion_failures += 1
                        assertion_rows.append(
                            {
                                "path": path,
                                "op": op,
                                "expected": expected,
                                "actual": actual,
                                "pass": ok,
                                "error": path_error,
                            }
                        )

            throughput = None
            if throughput_path and payload is not None:
                try:
                    numerator = _resolve_path_value(payload, throughput_path)
                    nval = _safe_float(numerator)
                    if nval is not None and elapsed > 0:
                        throughput = float(nval) / elapsed
                        throughput_values.append(float(throughput))
                except (ValueError, TypeError):
                    throughput = None

            if payload is not None and value_paths:
                for path in value_paths:
                    try:
                        raw_val = _resolve_path_value(payload, path)
                    except (ValueError, TypeError):
                        continue
                    nval = _safe_float(raw_val)
                    if nval is None:
                        continue
                    extracted_values.setdefault(path, []).append(float(nval))

            passed_now = bool(cmd_ok and assertions_ok)
            if passed_now:
                passed += 1
            else:
                failed += 1
                if not cmd_ok:
                    command_failures += 1
            runs.append(
                {
                    "id": pid,
                    "attempt": attempt,
                    "pass": passed_now,
                    "command_ok": cmd_ok,
                    "returncode": (int(run.get("returncode")) if _is_number(run.get("returncode")) else -999),
                    "elapsed_seconds": elapsed,
                    "throughput": throughput,
                    "assertions": assertion_rows,
                    "command": list(run.get("command") or []),
                    "stdout_preview": str(run.get("stdout") or "")[:1000],
                    "stderr_preview": str(run.get("stderr") or "")[:1000],
                }
            )

    total = passed + failed
    elapsed_stats = _safe_stats(elapsed_values)
    throughput_stats = _safe_stats(throughput_values)
    extracted_stats = {key: _safe_stats(values) for key, values in extracted_values.items()}
    return {
        "total_runs": int(total),
        "passed_runs": int(passed),
        "failed_runs": int(failed),
        "pass_rate": (round(passed / total, 6) if total > 0 else None),
        "command_failures": int(command_failures),
        "assertion_failures": int(assertion_failures),
        "elapsed": elapsed_stats,
        "throughput": throughput_stats,
        "extracted": extracted_stats,
        "runs": runs,
    }


def _fallback_performance_probe(source_roots: Sequence[Path]) -> dict[str, Any]:
    code = _count_code(source_roots)
    extracted = {
        "code.files": _safe_stats([float(code.get("files") or 0)]),
        "code.loc": _safe_stats([float(code.get("loc") or 0)]),
    }
    runs = [{"id": "fallback_performance_scan", "attempt": 1, "pass": True, "elapsed_seconds": None}]
    return {
        "total_runs": 1,
        "passed_runs": 1,
        "failed_runs": 0,
        "pass_rate": 1.0,
        "command_failures": 0,
        "assertion_failures": 0,
        "elapsed": _safe_stats([]),
        "throughput": _safe_stats([]),
        "extracted": extracted,
        "runs": runs,
    }


def _fallback_resilience_probe(source_roots: Sequence[Path], *, repeats: int = 3) -> dict[str, Any]:
    runs: list[dict[str, Any]] = []
    expected: tuple[int, int] | None = None
    passed = 0
    failed = 0
    repeat_count = max(2, int(repeats))

    for idx in range(1, repeat_count + 1):
        code = _count_code(source_roots)
        snapshot = (int(code.get("files") or 0), int(code.get("loc") or 0))
        if expected is None:
            expected = snapshot
        ok = snapshot == expected
        if ok:
            passed += 1
        else:
            failed += 1
        runs.append(
            {
                "id": "fallback_resilience_scan",
                "attempt": idx,
                "pass": ok,
                "elapsed_seconds": None,
                "files": snapshot[0],
                "loc": snapshot[1],
            }
        )

    total = passed + failed
    return {
        "total_runs": int(total),
        "passed_runs": int(passed),
        "failed_runs": int(failed),
        "pass_rate": (round(passed / total, 6) if total > 0 else None),
        "command_failures": 0,
        "assertion_failures": int(failed),
        "elapsed": _safe_stats([]),
        "throughput": _safe_stats([]),
        "extracted": {},
        "runs": runs,
    }


def _fallback_security_probe(
    secret_hits: Mapping[str, int],
    risky_hits: Mapping[str, int],
) -> dict[str, Any]:
    secret_total = int(secret_hits.get("total_hits") or 0)
    risky_total = int(risky_hits.get("total_hits") or 0)
    return {
        "total_runs": 1,
        "passed_runs": 1,
        "failed_runs": 0,
        "pass_rate": 1.0,
        "command_failures": 0,
        "assertion_failures": 0,
        "elapsed": _safe_stats([]),
        "throughput": _safe_stats([]),
        "extracted": {
            "secret_like_hits": _safe_stats([float(secret_total)]),
            "risky_construct_hits": _safe_stats([float(risky_total)]),
        },
        "runs": [
            {
                "id": "fallback_security_static_scan",
                "attempt": 1,
                "pass": True,
                "secret_like_hits": secret_total,
                "risky_construct_hits": risky_total,
            }
        ],
    }


def _fallback_cost_probe(benchmark: Mapping[str, Any]) -> dict[str, Any]:
    rows = int(benchmark.get("raw_rows_count") or 0)
    ok = rows > 0
    elapsed_values: list[float] = []
    raw_elapsed = _safe_float(benchmark.get("raw_elapsed_seconds_mean"))
    if raw_elapsed is not None and raw_elapsed >= 0:
        elapsed_values.append(float(raw_elapsed))
    run = {"id": "fallback_cost_benchmark_presence", "attempt": 1, "pass": ok, "raw_rows_count": rows}
    return {
        "total_runs": 1,
        "passed_runs": (1 if ok else 0),
        "failed_runs": (0 if ok else 1),
        "pass_rate": (1.0 if ok else 0.0),
        "command_failures": (0 if ok else 1),
        "assertion_failures": 0,
        "elapsed": _safe_stats(elapsed_values),
        "throughput": _safe_stats([]),
        "extracted": {
            "raw_rows_count": _safe_stats([float(rows)]),
        },
        "runs": [run],
    }


def _collect_benchmark_summary(agent: Mapping[str, Any], *, suite_root: Path) -> dict[str, Any]:
    patterns = [str(item).strip() for item in (agent.get("benchmark_scorecard_globs") or []) if str(item).strip()]
    aliases = [str(item).strip().lower() for item in (agent.get("benchmark_aliases") or []) if str(item).strip()]
    seen: set[str] = set()
    scorecards: list[Path] = []
    for pattern in patterns:
        path = Path(pattern)
        if not path.is_absolute():
            path = (suite_root / pattern).resolve()
        matches = [Path(item) for item in sorted(glob.glob(str(path), recursive=True))]
        for match in matches:
            key = str(match.resolve())
            if key in seen:
                continue
            seen.add(key)
            scorecards.append(match)

    weighted_scores: list[float] = []
    success_rates: list[float] = []
    evidence_coverages: list[float] = []
    elapsed_means: list[float] = []
    credibility_scores: list[float] = []
    raw_row_elapsed: list[float] = []
    raw_row_tokens_prompt: list[float] = []
    raw_row_tokens_completion: list[float] = []
    raw_row_tokens_total: list[float] = []
    raw_row_tool_calls: list[float] = []
    raw_row_successes: list[float] = []
    used_files: list[str] = []
    errors: list[str] = []

    for scorecard in scorecards:
        try:
            payload = json.loads(scorecard.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"{scorecard}: {type(exc).__name__}: {exc}")
            continue
        summary = payload.get("summary") or {}
        competitors = summary.get("competitors") or {}
        if not isinstance(competitors, dict) or not competitors:
            continue

        selected: Mapping[str, Any] | None = None
        if aliases:
            lowered = {str(k).strip().lower(): v for k, v in competitors.items()}
            for alias in aliases:
                if alias in lowered:
                    selected = lowered[alias] if isinstance(lowered[alias], dict) else None
                    break
        if selected is None and len(competitors) == 1:
            maybe = next(iter(competitors.values()))
            if isinstance(maybe, dict):
                selected = maybe
        if selected is None and str(agent.get("id") or "").strip() in competitors:
            maybe = competitors[str(agent.get("id") or "").strip()]
            if isinstance(maybe, dict):
                selected = maybe
        if selected is None:
            continue

        ws = _safe_float(selected.get("weighted_score"))
        sr = _safe_float(selected.get("success_rate"))
        ec = _safe_float(selected.get("evidence_coverage"))
        em = _safe_float(selected.get("avg_elapsed_seconds"))
        cs = _safe_float(selected.get("credibility_weighted_score"))
        if ws is not None:
            weighted_scores.append(ws)
        if sr is not None:
            success_rates.append(sr)
        if ec is not None:
            evidence_coverages.append(ec)
        if em is not None:
            elapsed_means.append(em)
        if cs is not None:
            credibility_scores.append(cs)
        used_files.append(str(scorecard))

    raw_patterns = [str(item).strip() for item in (agent.get("benchmark_raw_globs") or []) if str(item).strip()]
    if not raw_patterns:
        raw_patterns = [pattern.replace("scorecard.json", "benchmark_results.raw.json") for pattern in patterns]

    raw_seen: set[str] = set()
    raw_files: list[Path] = []
    for pattern in raw_patterns:
        path = Path(pattern)
        if not path.is_absolute():
            path = (suite_root / pattern).resolve()
        matches = [Path(item) for item in sorted(glob.glob(str(path), recursive=True))]
        for match in matches:
            key = str(match.resolve())
            if key in raw_seen:
                continue
            raw_seen.add(key)
            raw_files.append(match)

    for raw_file in raw_files:
        try:
            payload = json.loads(raw_file.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"{raw_file}: {type(exc).__name__}: {exc}")
            continue
        if not isinstance(payload, list):
            continue
        selected_rows: list[Mapping[str, Any]] = []
        for row in payload:
            if not isinstance(row, dict):
                continue
            track = str(row.get("track") or "").strip().lower()
            if aliases and track in aliases:
                selected_rows.append(row)
                continue
            if not aliases and track:
                selected_rows.append(row)
                continue
            if not track and len(payload) == 1:
                selected_rows.append(row)
        if not selected_rows:
            continue

        for row in selected_rows:
            run = row.get("run") or {}
            if not isinstance(run, dict):
                run = {}
            usage = run.get("usage") or {}
            if not isinstance(usage, dict):
                usage = {}

            pt = _safe_float(usage.get("prompt_tokens"))
            ct = _safe_float(usage.get("completion_tokens"))
            tt = _safe_float(usage.get("total_tokens"))
            if tt is None and (pt is not None or ct is not None):
                tt = float((pt or 0.0) + (ct or 0.0))

            elapsed = _safe_float(run.get("elapsed_seconds"))
            tools = _safe_float(run.get("tool_calls"))
            success_value = row.get("success")
            if success_value is None and isinstance(row.get("checks"), dict):
                success_value = (row.get("checks") or {}).get("success")
            success_numeric = 1.0 if bool(success_value) else 0.0

            raw_row_successes.append(success_numeric)
            if pt is not None:
                raw_row_tokens_prompt.append(float(pt))
            if ct is not None:
                raw_row_tokens_completion.append(float(ct))
            if tt is not None:
                raw_row_tokens_total.append(float(tt))
            if elapsed is not None:
                raw_row_elapsed.append(float(elapsed))
            if tools is not None:
                raw_row_tool_calls.append(float(tools))

    ws_stats = _safe_stats(weighted_scores)
    sr_stats = _safe_stats(success_rates)
    em_stats = _safe_stats(elapsed_means)
    ec_stats = _safe_stats(evidence_coverages)
    cs_stats = _safe_stats(credibility_scores)
    raw_elapsed_stats = _safe_stats(raw_row_elapsed)
    raw_prompt_stats = _safe_stats(raw_row_tokens_prompt)
    raw_completion_stats = _safe_stats(raw_row_tokens_completion)
    raw_total_stats = _safe_stats(raw_row_tokens_total)
    raw_tools_stats = _safe_stats(raw_row_tool_calls)
    raw_success_stats = _safe_stats(raw_row_successes)

    total_tokens_sum = sum(raw_row_tokens_total) if raw_row_tokens_total else None
    success_count = sum(raw_row_successes) if raw_row_successes else None
    tokens_per_success = None
    if total_tokens_sum is not None and success_count is not None and success_count > 0:
        tokens_per_success = round(float(total_tokens_sum) / float(success_count), 6)
    tools_per_success = None
    if raw_row_tool_calls and success_count is not None and success_count > 0:
        tools_per_success = round(float(sum(raw_row_tool_calls)) / float(success_count), 6)

    return {
        "runs_count": len(used_files),
        "weighted_score_mean": ws_stats["mean"],
        "weighted_score_stddev": ws_stats["stddev"],
        "success_rate_mean": sr_stats["mean"],
        "success_rate_stddev": sr_stats["stddev"],
        "evidence_coverage_mean": ec_stats["mean"],
        "avg_elapsed_seconds_mean": em_stats["mean"],
        "avg_elapsed_seconds_stddev": em_stats["stddev"],
        "credibility_weighted_score_mean": cs_stats["mean"],
        "raw_rows_count": len(raw_row_successes),
        "raw_success_rate_mean": raw_success_stats["mean"],
        "raw_elapsed_seconds_mean": raw_elapsed_stats["mean"],
        "raw_elapsed_seconds_stddev": raw_elapsed_stats["stddev"],
        "raw_elapsed_seconds_p95": raw_elapsed_stats["p95"],
        "raw_prompt_tokens_mean": raw_prompt_stats["mean"],
        "raw_completion_tokens_mean": raw_completion_stats["mean"],
        "raw_total_tokens_mean": raw_total_stats["mean"],
        "raw_tool_calls_mean": raw_tools_stats["mean"],
        "raw_total_tokens_sum": (round(total_tokens_sum, 6) if total_tokens_sum is not None else None),
        "raw_success_count": (round(success_count, 6) if success_count is not None else None),
        "raw_tokens_per_success": tokens_per_success,
        "raw_tool_calls_per_success": tools_per_success,
        "scorecards_used": used_files,
        "raw_files_used": [str(p) for p in raw_files],
        "errors": errors,
    }


def _clamp01(value: Any) -> float | None:
    num = _safe_float(value)
    if num is None:
        return None
    return max(0.0, min(1.0, float(num)))


def _positive_float(value: Any) -> float | None:
    num = _safe_float(value)
    if num is None or num <= 0:
        return None
    return float(num)


def _compute_token_efficiency(
    *,
    benchmark: Mapping[str, Any],
    cost_probe: Mapping[str, Any],
) -> dict[str, Any]:
    tokens_per_success = _positive_float(benchmark.get("raw_tokens_per_success"))
    total_tokens_mean = _positive_float(benchmark.get("raw_total_tokens_mean"))
    prompt_tokens_mean = _positive_float(benchmark.get("raw_prompt_tokens_mean"))
    completion_tokens_mean = _positive_float(benchmark.get("raw_completion_tokens_mean"))

    if total_tokens_mean is None and (prompt_tokens_mean is not None or completion_tokens_mean is not None):
        total_tokens_mean = float(prompt_tokens_mean or 0.0) + float(completion_tokens_mean or 0.0)

    success_rate = _clamp01(benchmark.get("raw_success_rate_mean"))
    if success_rate is None:
        success_rate = _clamp01(benchmark.get("success_rate_mean"))
    cost_pass_rate = _clamp01(cost_probe.get("pass_rate"))

    effective_tokens_per_success = None
    source = ""
    if tokens_per_success is not None:
        effective_tokens_per_success = tokens_per_success
        source = "raw_tokens_per_success"
    elif total_tokens_mean is not None and success_rate is not None and success_rate > 0.0:
        effective_tokens_per_success = total_tokens_mean / max(float(success_rate), 0.05)
        source = "derived_total_tokens_mean_div_success_rate"
    elif total_tokens_mean is not None:
        effective_tokens_per_success = total_tokens_mean
        source = "fallback_total_tokens_mean"

    token_component = None
    if effective_tokens_per_success is not None:
        token_component = 100.0 / (1.0 + (float(effective_tokens_per_success) / 1500.0))

    density_component = None
    if total_tokens_mean is not None:
        density_component = 100.0 / (1.0 + (float(total_tokens_mean) / 1200.0))

    success_component = (float(success_rate) * 100.0) if success_rate is not None else None
    reliability_component = (float(cost_pass_rate) * 100.0) if cost_pass_rate is not None else None

    components = [
        (token_component, 0.6),
        (density_component, 0.15),
        (success_component, 0.15),
        (reliability_component, 0.1),
    ]
    available_weight = sum(weight for value, weight in components if value is not None)
    blended_score = (
        sum(float(value) * weight for value, weight in components if value is not None) / available_weight
        if available_weight > 0 and token_component is not None
        else None
    )

    token_signals = [
        tokens_per_success,
        total_tokens_mean,
        prompt_tokens_mean,
        completion_tokens_mean,
    ]
    token_signal_count = sum(1 for value in token_signals if value is not None)
    telemetry_coverage = round(token_signal_count / len(token_signals), 6)

    overall_score = None
    if blended_score is not None:
        overall_score = float(blended_score) * (0.65 + (0.35 * float(telemetry_coverage)))

    return {
        "overall_score": (round(float(overall_score), 6) if overall_score is not None else None),
        "telemetry_coverage": float(telemetry_coverage),
        "token_signal_count": int(token_signal_count),
        "token_signal_total": int(len(token_signals)),
        "effective_tokens_per_success": (
            round(float(effective_tokens_per_success), 6) if effective_tokens_per_success is not None else None
        ),
        "source": source,
        "components": {
            "token_component": (round(float(token_component), 6) if token_component is not None else None),
            "density_component": (round(float(density_component), 6) if density_component is not None else None),
            "success_component": (round(float(success_component), 6) if success_component is not None else None),
            "reliability_component": (
                round(float(reliability_component), 6) if reliability_component is not None else None
            ),
            "blended_score": (round(float(blended_score), 6) if blended_score is not None else None),
        },
    }


def _collect_benchmark_evidence(agent: Mapping[str, Any], *, suite_root: Path) -> dict[str, Any]:
    patterns = [str(item).strip() for item in (agent.get("benchmark_evidence_globs") or []) if str(item).strip()]
    aliases = [str(item).strip().lower() for item in (agent.get("benchmark_aliases") or []) if str(item).strip()]
    aid = str(agent.get("id") or "").strip().lower()
    if aid and aid not in aliases:
        aliases.append(aid)
    files_used: list[str] = []
    checks: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    if not patterns:
        return {"files_used": files_used, "checks": checks, "errors": errors}

    seen: set[str] = set()
    for pattern in patterns:
        path = Path(pattern)
        if not path.is_absolute():
            path = (suite_root / pattern).resolve()
        matches = [Path(item) for item in sorted(glob.glob(str(path), recursive=True))]
        for match in matches:
            key = str(match.resolve())
            if key in seen:
                continue
            seen.add(key)
            files_used.append(str(match))
            try:
                payload = json.loads(match.read_text(encoding="utf-8"))
            except Exception as exc:
                errors.append(f"{match}: {type(exc).__name__}: {exc}")
                continue
            if isinstance(payload, dict):
                raw_checks = payload.get("checks")
                if not isinstance(raw_checks, dict):
                    continue
                for cid, raw in raw_checks.items():
                    check_id = str(cid or "").strip()
                    if not check_id:
                        continue
                    row = dict(raw) if isinstance(raw, dict) else {"value": raw}
                    merged = dict(checks.get(check_id) or {})
                    for key_name in ["pass", "score", "value", "notes", "source", "updated_at_utc"]:
                        if key_name in row:
                            merged[key_name] = row[key_name]
                    checks[check_id] = merged
                continue
            if isinstance(payload, list):
                rows = [row for row in payload if isinstance(row, dict)]
                for row in rows:
                    track = str(row.get("track") or "").strip().lower()
                    if aliases:
                        if track and track not in aliases:
                            continue
                        if not track and len(rows) > 1:
                            continue
                    check_id = str(row.get("evidence_id") or row.get("task_id") or "").strip()
                    if not check_id:
                        continue
                    pass_value = row.get("pass")
                    if not isinstance(pass_value, bool):
                        pass_value = row.get("success")
                    if not isinstance(pass_value, bool):
                        check_summary = row.get("checks")
                        if isinstance(check_summary, dict) and isinstance(check_summary.get("success"), bool):
                            pass_value = bool(check_summary.get("success"))
                    score_value = _safe_float(row.get("score"))
                    if score_value is None:
                        score_value = _safe_float(row.get("quality_score"))
                    evidence_path = str(row.get("evidence") or "").strip()
                    merged = dict(checks.get(check_id) or {})
                    if isinstance(pass_value, bool):
                        merged["pass"] = bool(pass_value)
                    if score_value is not None:
                        merged["score"] = score_value
                    if evidence_path:
                        merged["source"] = evidence_path
                    checks[check_id] = merged
                continue
            errors.append(f"{match}: evidence payload must be an object or list")
    return {"files_used": files_used, "checks": checks, "errors": errors}


def _collect_cli_metrics(
    agent: Mapping[str, Any],
    *,
    tracked_commands: Sequence[str],
    agent_root: Path,
) -> dict[str, Any]:
    cli = dict(agent.get("cli") or {})
    command = cli.get("command") or []
    fixed_top = cli.get("fixed_top_level_commands")
    fixed_depth = dict(cli.get("fixed_subcommand_depth") or {})
    errors: list[str] = []

    top_level: int | None = None
    depth: dict[str, int | None] = {}

    if isinstance(command, list) and command:
        top_run = _run_command([*command, "--help"], cwd=agent_root, timeout_seconds=45.0)
        parsed_top = _parse_click_commands(str(top_run.get("stdout") or "") + "\n" + str(top_run.get("stderr") or ""))
        if parsed_top:
            top_level = len(parsed_top)
        elif _is_number(fixed_top):
            top_level = int(float(fixed_top))
            errors.append("top-level help parse failed; used fixed_top_level_commands fallback")
        else:
            errors.append("top-level help parse failed and no fixed fallback provided")

        for command_name in tracked_commands:
            sub_run = _run_command([*command, command_name, "--help"], cwd=agent_root, timeout_seconds=45.0)
            parsed = _parse_click_commands(str(sub_run.get("stdout") or "") + "\n" + str(sub_run.get("stderr") or ""))
            if parsed:
                depth[command_name] = len(parsed)
                continue
            if command_name in fixed_depth and _is_number(fixed_depth.get(command_name)):
                depth[command_name] = int(float(fixed_depth[command_name]))
                continue
            depth[command_name] = None
    else:
        if _is_number(fixed_top):
            top_level = int(float(fixed_top))
        for command_name in tracked_commands:
            if command_name in fixed_depth and _is_number(fixed_depth.get(command_name)):
                depth[command_name] = int(float(fixed_depth[command_name]))
            else:
                depth[command_name] = None

    depth_values = [int(v) for v in depth.values() if v is not None]
    depth_total = sum(depth_values) if depth_values else None
    return {
        "top_level_commands": top_level,
        "depth_total": depth_total,
        "depth_by_command": depth,
        "errors": errors,
    }


def _collect_agent_metrics(
    agent: Mapping[str, Any],
    *,
    tracked_commands: Sequence[str],
    suite_root: Path,
) -> dict[str, Any]:
    aid = str(agent.get("id") or "").strip()
    label = str(agent.get("label") or aid)
    root = _resolve(suite_root, str(agent.get("root") or "."))

    source_roots = [_resolve(root, rel) for rel in (agent.get("source_roots") or [])]
    if not source_roots:
        source_roots = [root]
    test_roots = [_resolve(root, rel) for rel in (agent.get("test_roots") or [])] or list(source_roots)
    test_dataset_roots = [_resolve(root, rel) for rel in (agent.get("test_dataset_roots") or [])]

    browser_roots = [_resolve(root, rel) for rel in (agent.get("browser_roots") or [])]
    plugin_roots = [_resolve(root, rel) for rel in (agent.get("plugin_roots") or [])]
    gateway_roots = [_resolve(root, rel) for rel in (agent.get("gateway_roots") or [])]
    cli_roots = [_resolve(root, rel) for rel in (agent.get("cli_roots") or [])]

    extensions_root_raw = str(agent.get("extensions_root") or "").strip()
    extensions_root = _resolve(root, extensions_root_raw) if extensions_root_raw else None
    mobile_roots = [str(item).strip() for item in (agent.get("mobile_roots") or [".", "apps"]) if str(item).strip()]
    required_paths = [_resolve(root, rel) for rel in (agent.get("required_paths") or [])]
    production_asset_roots = [_resolve(root, rel) for rel in (agent.get("production_asset_roots") or [])]
    security_scan_roots_raw = [
        str(item).strip() for item in (agent.get("security_scan_roots") or []) if str(item).strip()
    ]
    security_scan_roots = (
        [_resolve(root, rel) for rel in security_scan_roots_raw] if security_scan_roots_raw else list(source_roots)
    )
    security_scan_ignore_globs = [
        str(item).strip() for item in (agent.get("security_scan_ignore_globs") or []) if str(item).strip()
    ]

    errors: list[str] = []
    if not root.exists():
        errors.append(f"agent root does not exist: {root}")

    version_info = _collect_git_version_info(root, sync_cfg=dict(agent.get("repo_sync") or {}))
    errors.extend([str(item) for item in (version_info.get("errors") or [])])
    model_snapshot = _collect_model_snapshot(agent, agent_root=root)
    if bool(model_snapshot.get("required")) and not bool(model_snapshot.get("ok")):
        errors.append(
            f"required model snapshot unavailable for {aid}: {model_snapshot.get('error') or 'unknown error'}"
        )

    code = _count_code(source_roots)
    seen_test_files: set[str] = set()
    tests_named = _count_test_code(test_roots, seen_files=seen_test_files)
    tests_dataset = _count_test_code(test_dataset_roots, include_all=True, seen_files=seen_test_files)
    tests = {
        "files": int(tests_named["files"] + tests_dataset["files"]),
        "loc": int(tests_named["loc"] + tests_dataset["loc"]),
    }
    browser = _count_code(browser_roots)
    plugins = _count_code(plugin_roots)
    gateway = _count_code(gateway_roots)
    cli_code = _count_code(cli_roots)

    markdown_files = _count_files(source_roots, {".md"})
    config_files = _count_files(source_roots, {".json", ".toml", ".yaml", ".yml"})
    script_files = _count_files(source_roots, {".sh", ".ps1", ".bat"})
    python_files = _count_files(source_roots, {".py"})

    large_files = _count_large_code_files(source_roots, threshold=800)
    empty_code_files = _count_empty_code_files(source_roots)
    python_syntax_errors = _count_python_syntax_errors(source_roots)
    invalid_json_files = _count_invalid_json_files(source_roots)

    missing_required_paths = sum(1 for path in required_paths if not path.exists())
    empty_production_asset_files = _count_empty_files(production_asset_roots)

    extensions_dirs = _count_immediate_dirs(extensions_root) if extensions_root is not None else None
    mobile_dirs = _count_mobile_surface_dirs(root, mobile_roots)

    gateway_patterns = dict(DEFAULT_GATEWAY_PATTERNS)
    gateway_patterns.update(dict(agent.get("gateway_patterns") or {}))
    compat_metrics: dict[str, int] = {}
    for key, needle in gateway_patterns.items():
        counts = _count_text_occurrences(gateway_roots, str(needle))
        if key == "chat_completions":
            prefix = "gateway.openai_chat_completions"
        elif key == "responses":
            prefix = "gateway.responses"
        else:
            prefix = f"gateway.pattern.{key}"
        compat_metrics[f"{prefix}.files"] = int(counts["files_with_hits"])
        compat_metrics[f"{prefix}.occurrences"] = int(counts["occurrences"])

    cli = _collect_cli_metrics(agent, tracked_commands=tracked_commands, agent_root=root)
    errors.extend(list(cli.get("errors") or []))

    strict_checks = _run_strict_checks(agent, agent_root=root)
    benchmark = _collect_benchmark_summary(agent, suite_root=suite_root)
    benchmark_evidence = _collect_benchmark_evidence(agent, suite_root=suite_root)
    performance_probe = _run_probe_suite(agent, agent_root=root, probe_key="performance_probes")
    resilience_probe = _run_probe_suite(agent, agent_root=root, probe_key="resilience_probes")
    security_probe = _run_probe_suite(agent, agent_root=root, probe_key="security_probes")
    cost_probe = _run_probe_suite(agent, agent_root=root, probe_key="cost_probes")
    errors.extend([str(item) for item in (benchmark.get("errors") or [])])
    errors.extend([str(item) for item in (benchmark_evidence.get("errors") or [])])

    secret_patterns = [
        r"AKIA[0-9A-Z]{16}",
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
        r"(?i)(api[_-]?key|access[_-]?token|secret[_-]?key)\s*[:=]\s*[\"'][^\"']{16,}[\"']",
    ]
    risky_patterns = [
        r"\beval\s*\(",
        r"(?<!\.)\bexec\s*\(",
        r"pickle\.loads\s*\(",
        r"yaml\.load\s*\(",
        r"subprocess\.(?:run|Popen|call|check_output)\([^\\n]*shell\s*=\s*True",
    ]
    secret_hits = _count_regex_hits(
        security_scan_roots,
        secret_patterns,
        ignore_globs=security_scan_ignore_globs,
    )
    risky_hits = _count_regex_hits(
        security_scan_roots,
        risky_patterns,
        ignore_globs=security_scan_ignore_globs,
    )

    if int(performance_probe.get("total_runs") or 0) <= 0:
        performance_probe = _fallback_performance_probe(source_roots)
    if int(resilience_probe.get("total_runs") or 0) <= 0:
        resilience_probe = _fallback_resilience_probe(source_roots)
    if int(security_probe.get("total_runs") or 0) <= 0:
        security_probe = _fallback_security_probe(secret_hits, risky_hits)
    if int(cost_probe.get("total_runs") or 0) <= 0:
        cost_probe = _fallback_cost_probe(benchmark)
    token_efficiency = _compute_token_efficiency(benchmark=benchmark, cost_probe=cost_probe)

    metrics: dict[str, Any] = {}
    metrics["loc.total_files"] = int(code["files"])
    metrics["loc.total_loc"] = int(code["loc"])
    metrics["tests.files"] = int(tests["files"])
    metrics["tests.loc"] = int(tests["loc"])
    metrics["tests.dataset_files"] = int(tests_dataset["files"])
    metrics["tests.dataset_loc"] = int(tests_dataset["loc"])
    metrics["tests.loc_per_file"] = round((tests["loc"] / tests["files"]), 6) if tests["files"] > 0 else None
    metrics["tests.to_code_file_ratio"] = round((tests["files"] / code["files"]), 6) if code["files"] > 0 else None
    metrics["tests.to_code_loc_ratio"] = round((tests["loc"] / code["loc"]), 6) if code["loc"] > 0 else None

    metrics["code.python_files"] = int(python_files)
    metrics["code.non_python_files"] = int(max(0, int(code["files"]) - int(python_files)))
    metrics["docs.markdown_files"] = int(markdown_files)
    metrics["config.files"] = int(config_files)
    metrics["scripts.files"] = int(script_files)

    metrics["browser.files"] = int(browser["files"])
    metrics["browser.loc"] = int(browser["loc"])
    metrics["plugins.files"] = int(plugins["files"])
    metrics["plugins.loc"] = int(plugins["loc"])
    metrics["gateway.files"] = int(gateway["files"])
    metrics["gateway.loc"] = int(gateway["loc"])
    metrics["cli.files"] = int(cli_code["files"])
    metrics["cli.loc"] = int(cli_code["loc"])
    metrics["extensions.directories"] = int(extensions_dirs) if extensions_dirs is not None else None
    metrics["mobile_surface.directories"] = int(mobile_dirs)

    metrics["integrity.empty_code_files"] = int(empty_code_files)
    metrics["integrity.python_syntax_errors"] = int(python_syntax_errors)
    metrics["integrity.invalid_json_files"] = int(invalid_json_files)
    metrics["integrity.missing_required_paths"] = int(missing_required_paths)
    metrics["integrity.empty_production_asset_files"] = int(empty_production_asset_files)

    metrics["maintainability.large_code_files_over_800"] = (
        round((float(large_files) * 100000.0) / float(code["loc"]), 6) if int(code["loc"]) > 0 else None
    )
    metrics["maintainability.large_code_files_count_over_800"] = int(large_files)
    metrics["maintainability.avg_loc_per_code_file"] = (
        round((code["loc"] / code["files"]), 6) if code["files"] > 0 else None
    )

    metrics["security.secret_like_hits"] = int(secret_hits["total_hits"])
    metrics["security.secret_like_files"] = int(secret_hits["files_with_hits"])
    metrics["security.risky_construct_hits"] = (
        round((float(risky_hits["total_hits"]) * 100000.0) / float(code["loc"]), 6) if int(code["loc"]) > 0 else None
    )
    metrics["security.risky_construct_files"] = (
        round((float(risky_hits["files_with_hits"]) * 1000.0) / float(code["files"]), 6)
        if int(code["files"]) > 0
        else None
    )
    metrics["security.risky_construct_hits_count"] = int(risky_hits["total_hits"])
    metrics["security.risky_construct_files_count"] = int(risky_hits["files_with_hits"])

    metrics["cli.top_level_commands"] = cli.get("top_level_commands")
    metrics["cli.depth_total"] = cli.get("depth_total")
    for command_name, depth_value in dict(cli.get("depth_by_command") or {}).items():
        metrics[f"cli.depth.{command_name}"] = depth_value

    metrics.update(compat_metrics)

    metrics["production.strict_checks.total"] = int(strict_checks["total"])
    metrics["production.strict_checks.passed"] = int(strict_checks["passed"])
    metrics["production.strict_checks.failed"] = int(strict_checks["failed"])
    metrics["production.strict_checks.pass_rate"] = strict_checks["pass_rate"]
    metrics["production.strict_checks.avg_elapsed_seconds"] = strict_checks["avg_elapsed_seconds"]
    metrics["production.strict_checks.assertion_failures"] = int(strict_checks["assertion_failures"])
    metrics["production.strict_checks.command_failures"] = int(strict_checks["command_failures"])

    metrics["benchmark.runs_count"] = int(benchmark["runs_count"])
    metrics["benchmark.weighted_score_mean"] = benchmark["weighted_score_mean"]
    metrics["benchmark.weighted_score_stddev"] = benchmark["weighted_score_stddev"]
    metrics["benchmark.success_rate_mean"] = benchmark["success_rate_mean"]
    metrics["benchmark.success_rate_stddev"] = benchmark["success_rate_stddev"]
    metrics["benchmark.evidence_coverage_mean"] = benchmark["evidence_coverage_mean"]
    metrics["benchmark.avg_elapsed_seconds_mean"] = benchmark["avg_elapsed_seconds_mean"]
    metrics["benchmark.avg_elapsed_seconds_stddev"] = benchmark["avg_elapsed_seconds_stddev"]
    metrics["benchmark.credibility_weighted_score_mean"] = benchmark["credibility_weighted_score_mean"]
    metrics["benchmark.raw_rows_count"] = benchmark["raw_rows_count"]
    metrics["benchmark.raw_success_rate_mean"] = benchmark["raw_success_rate_mean"]
    metrics["benchmark.raw_elapsed_seconds_mean"] = benchmark["raw_elapsed_seconds_mean"]
    metrics["benchmark.raw_elapsed_seconds_stddev"] = benchmark["raw_elapsed_seconds_stddev"]
    metrics["benchmark.raw_elapsed_seconds_p95"] = benchmark["raw_elapsed_seconds_p95"]
    metrics["benchmark.raw_prompt_tokens_mean"] = benchmark["raw_prompt_tokens_mean"]
    metrics["benchmark.raw_completion_tokens_mean"] = benchmark["raw_completion_tokens_mean"]
    metrics["benchmark.raw_total_tokens_mean"] = benchmark["raw_total_tokens_mean"]
    metrics["benchmark.raw_tool_calls_mean"] = benchmark["raw_tool_calls_mean"]
    metrics["benchmark.raw_tokens_per_success"] = benchmark["raw_tokens_per_success"]
    metrics["benchmark.raw_tool_calls_per_success"] = benchmark["raw_tool_calls_per_success"]
    success_rate_mean = benchmark["success_rate_mean"]
    metrics["benchmark.failure_rate_mean"] = (
        round(1.0 - float(success_rate_mean), 6) if _is_number(success_rate_mean) else None
    )

    metrics["performance.load.total_runs"] = int(performance_probe["total_runs"])
    metrics["performance.load.passed_runs"] = int(performance_probe["passed_runs"])
    metrics["performance.load.failed_runs"] = int(performance_probe["failed_runs"])
    metrics["performance.load.pass_rate"] = performance_probe["pass_rate"]
    metrics["performance.load.avg_elapsed_seconds"] = (performance_probe.get("elapsed") or {}).get("mean")
    metrics["performance.load.p95_elapsed_seconds"] = (performance_probe.get("elapsed") or {}).get("p95")
    metrics["performance.load.avg_throughput"] = (performance_probe.get("throughput") or {}).get("mean")

    metrics["resilience.probes.total_runs"] = int(resilience_probe["total_runs"])
    metrics["resilience.probes.passed_runs"] = int(resilience_probe["passed_runs"])
    metrics["resilience.probes.failed_runs"] = int(resilience_probe["failed_runs"])
    metrics["resilience.probes.pass_rate"] = resilience_probe["pass_rate"]
    metrics["resilience.probes.avg_elapsed_seconds"] = (resilience_probe.get("elapsed") or {}).get("mean")
    metrics["resilience.probes.p95_elapsed_seconds"] = (resilience_probe.get("elapsed") or {}).get("p95")

    metrics["security.probes.total_runs"] = int(security_probe["total_runs"])
    metrics["security.probes.passed_runs"] = int(security_probe["passed_runs"])
    metrics["security.probes.failed_runs"] = int(security_probe["failed_runs"])
    metrics["security.probes.pass_rate"] = security_probe["pass_rate"]
    metrics["security.probes.avg_elapsed_seconds"] = (security_probe.get("elapsed") or {}).get("mean")

    metrics["cost.probes.total_runs"] = int(cost_probe["total_runs"])
    metrics["cost.probes.passed_runs"] = int(cost_probe["passed_runs"])
    metrics["cost.probes.failed_runs"] = int(cost_probe["failed_runs"])
    metrics["cost.probes.pass_rate"] = cost_probe["pass_rate"]
    metrics["cost.probes.avg_elapsed_seconds"] = (cost_probe.get("elapsed") or {}).get("mean")
    metrics["cost.benchmark_tokens_per_success"] = benchmark["raw_tokens_per_success"]
    metrics["cost.benchmark_tool_calls_per_success"] = benchmark["raw_tool_calls_per_success"]
    metrics["cost.benchmark_total_tokens_mean"] = benchmark["raw_total_tokens_mean"]
    metrics["cost.token_efficiency_score"] = token_efficiency["overall_score"]
    metrics["cost.token_efficiency_tokens_per_success_effective"] = token_efficiency["effective_tokens_per_success"]
    metrics["cost.token_efficiency_telemetry_coverage"] = token_efficiency["telemetry_coverage"]

    return {
        "id": aid,
        "label": label,
        "root": str(root),
        "metrics": metrics,
        "version_info": version_info,
        "model_snapshot": model_snapshot,
        "errors": errors,
        "strict_checks": strict_checks,
        "performance_probe": performance_probe,
        "resilience_probe": resilience_probe,
        "security_probe": security_probe,
        "cost_probe": cost_probe,
        "token_efficiency": token_efficiency,
        "benchmark_evidence": benchmark_evidence,
        "benchmark": benchmark,
    }


def _metric_weight(
    metric: str,
    *,
    category: str,
    category_weights: Mapping[str, Any],
    weight_overrides: Mapping[str, Any],
) -> float:
    if metric in weight_overrides and _is_number(weight_overrides[metric]):
        return float(weight_overrides[metric])
    if category in category_weights and _is_number(category_weights[category]):
        return float(category_weights[category])
    if category in DEFAULT_CATEGORY_WEIGHTS:
        return float(DEFAULT_CATEGORY_WEIGHTS[category])
    return 1.0


def _build_metric_specs(
    *,
    tracked_cli_commands: Sequence[str],
    gateway_pattern_keys: Sequence[str],
    category_weights: Mapping[str, Any],
    weight_overrides: Mapping[str, Any],
) -> dict[str, MetricSpec]:
    specs: dict[str, MetricSpec] = {}
    dynamic_categories = {
        "performance_load",
        "resilience",
        "security",
        "cost_efficiency",
        "production_readiness",
        "benchmark_execution",
        "reliability",
    }

    def add(metric: str, category: str, preference: str, rationale: str) -> None:
        mode = "dynamic" if category in dynamic_categories else "quick"
        specs[metric] = MetricSpec(
            metric=metric,
            category=category,
            preference=preference,
            weight=_metric_weight(
                metric,
                category=category,
                category_weights=category_weights,
                weight_overrides=weight_overrides,
            ),
            rationale=rationale,
            test_mode=mode,
        )

    add("loc.total_files", "code_surface", "higher_is_better", "Overall code surface breadth.")
    add("loc.total_loc", "code_surface", "higher_is_better", "Overall implementation depth.")
    add("code.python_files", "code_surface", "higher_is_better", "Python module breadth.")
    add("code.non_python_files", "code_surface", "higher_is_better", "Non-Python surface breadth.")
    add("docs.markdown_files", "code_surface", "higher_is_better", "Documentation surface breadth.")
    add("config.files", "code_surface", "higher_is_better", "Configuration surface breadth.")
    add("scripts.files", "code_surface", "higher_is_better", "Operational script breadth.")

    add("tests.files", "test_rigor", "higher_is_better", "Test file breadth.")
    add("tests.loc", "test_rigor", "higher_is_better", "Test implementation depth.")
    add(
        "tests.dataset_files",
        "test_rigor",
        "higher_is_better",
        "Structured evaluation dataset files counted as executable test assets.",
    )
    add(
        "tests.dataset_loc",
        "test_rigor",
        "higher_is_better",
        "Structured evaluation dataset LOC counted as executable test assets.",
    )
    add("tests.loc_per_file", "test_rigor", "higher_is_better", "Average depth per test file.")
    add("tests.to_code_file_ratio", "test_rigor", "higher_is_better", "Test-to-code file ratio.")
    add("tests.to_code_loc_ratio", "test_rigor", "higher_is_better", "Test-to-code LOC ratio.")

    add("browser.files", "code_surface", "higher_is_better", "Browser subsystem breadth.")
    add("browser.loc", "code_surface", "higher_is_better", "Browser subsystem depth.")
    add("plugins.files", "code_surface", "higher_is_better", "Plugin subsystem breadth.")
    add("plugins.loc", "code_surface", "higher_is_better", "Plugin subsystem depth.")
    add("extensions.directories", "code_surface", "higher_is_better", "Extension ecosystem breadth.")
    add("mobile_surface.directories", "code_surface", "higher_is_better", "Mobile platform presence.")

    add("cli.top_level_commands", "cli_surface", "higher_is_better", "Top-level operator entry points.")
    add("cli.depth_total", "cli_surface", "higher_is_better", "Total tracked CLI subcommand depth.")
    for command_name in sorted({str(name).strip() for name in tracked_cli_commands if str(name).strip()}):
        add(
            f"cli.depth.{command_name}",
            "cli_surface",
            "higher_is_better",
            f"CLI subcommand depth for `{command_name}` family.",
        )

    for key in sorted({str(item).strip() for item in gateway_pattern_keys if str(item).strip()}):
        if key == "chat_completions":
            prefix = "gateway.openai_chat_completions"
        elif key == "responses":
            prefix = "gateway.responses"
        else:
            prefix = f"gateway.pattern.{key}"
        add(f"{prefix}.files", "compatibility", "higher_is_better", f"File-level coverage for `{key}` compatibility.")
        add(
            f"{prefix}.occurrences",
            "compatibility",
            "higher_is_better",
            f"Occurrence-level wiring coverage for `{key}` compatibility.",
        )

    add("performance.load.total_runs", "performance_load", "higher_is_better", "Performance/load sample size.")
    add("performance.load.passed_runs", "performance_load", "higher_is_better", "Passing performance/load probes.")
    add("performance.load.failed_runs", "performance_load", "lower_is_better", "Failing performance/load probes.")
    add("performance.load.pass_rate", "performance_load", "higher_is_better", "Performance/load probe pass rate.")
    add(
        "performance.load.avg_elapsed_seconds",
        "performance_load",
        "lower_is_better",
        "Mean elapsed time across load probes.",
    )
    add(
        "performance.load.p95_elapsed_seconds",
        "performance_load",
        "lower_is_better",
        "P95 elapsed time across load probes.",
    )
    add("performance.load.avg_throughput", "performance_load", "higher_is_better", "Mean load throughput.")

    add("resilience.probes.total_runs", "resilience", "higher_is_better", "Resilience probe sample size.")
    add("resilience.probes.passed_runs", "resilience", "higher_is_better", "Passing resilience probes.")
    add("resilience.probes.failed_runs", "resilience", "lower_is_better", "Failing resilience probes.")
    add("resilience.probes.pass_rate", "resilience", "higher_is_better", "Resilience probe pass rate.")
    add(
        "resilience.probes.avg_elapsed_seconds",
        "resilience",
        "lower_is_better",
        "Mean elapsed time for resilience probes.",
    )
    add(
        "resilience.probes.p95_elapsed_seconds",
        "resilience",
        "lower_is_better",
        "P95 elapsed time for resilience probes.",
    )

    add("security.probes.total_runs", "security", "higher_is_better", "Security probe sample size.")
    add("security.probes.passed_runs", "security", "higher_is_better", "Passing security probes.")
    add("security.probes.failed_runs", "security", "lower_is_better", "Failing security probes.")
    add("security.probes.pass_rate", "security", "higher_is_better", "Security probe pass rate.")
    add(
        "security.probes.avg_elapsed_seconds",
        "security",
        "lower_is_better",
        "Mean elapsed time for security probes.",
    )
    add("security.secret_like_hits", "security", "lower_is_better", "Secret-like token pattern hits.")
    add("security.secret_like_files", "security", "lower_is_better", "Files containing secret-like patterns.")
    add(
        "security.risky_construct_hits",
        "security",
        "lower_is_better",
        "Potentially risky code-construct concentration (per 100k LOC).",
    )
    add(
        "security.risky_construct_files",
        "security",
        "lower_is_better",
        "Files containing risky constructs concentration (per 1k code files).",
    )

    add("cost.probes.total_runs", "cost_efficiency", "higher_is_better", "Cost-probe sample size.")
    add("cost.probes.passed_runs", "cost_efficiency", "higher_is_better", "Passing cost probes.")
    add("cost.probes.failed_runs", "cost_efficiency", "lower_is_better", "Failing cost probes.")
    add("cost.probes.pass_rate", "cost_efficiency", "higher_is_better", "Cost-probe pass rate.")
    add(
        "cost.probes.avg_elapsed_seconds",
        "cost_efficiency",
        "lower_is_better",
        "Mean elapsed time across cost probes.",
    )
    add(
        "cost.benchmark_tokens_per_success",
        "cost_efficiency",
        "lower_is_better",
        "Average benchmark tokens consumed per successful task.",
    )
    add(
        "cost.benchmark_tool_calls_per_success",
        "cost_efficiency",
        "lower_is_better",
        "Average benchmark tool calls per successful task.",
    )
    add(
        "cost.benchmark_total_tokens_mean",
        "cost_efficiency",
        "lower_is_better",
        "Mean benchmark total token usage.",
    )
    add(
        "cost.token_efficiency_tokens_per_success_effective",
        "cost_efficiency",
        "lower_is_better",
        "Effective token cost per success (direct or derived).",
    )
    add(
        "cost.token_efficiency_telemetry_coverage",
        "cost_efficiency",
        "higher_is_better",
        "Coverage of token telemetry signals used by efficiency scoring.",
    )
    add(
        "cost.token_efficiency_score",
        "cost_efficiency",
        "higher_is_better",
        "Blended token-efficiency score with telemetry-aware confidence weighting.",
    )

    add("integrity.empty_code_files", "integrity", "lower_is_better", "Empty code files indicate dead surface.")
    add("integrity.python_syntax_errors", "integrity", "lower_is_better", "Python syntax failures.")
    add("integrity.invalid_json_files", "integrity", "lower_is_better", "Invalid JSON artifacts.")
    add("integrity.missing_required_paths", "integrity", "lower_is_better", "Missing required production paths.")
    add(
        "integrity.empty_production_asset_files",
        "integrity",
        "lower_is_better",
        "Empty files inside declared production asset roots.",
    )

    add(
        "maintainability.large_code_files_over_800",
        "maintainability",
        "lower_is_better",
        "Large-file concentration (files >800 LOC per 100k LOC).",
    )
    add("production.strict_checks.total", "production_readiness", "higher_is_better", "Declared production checks.")
    add("production.strict_checks.passed", "production_readiness", "higher_is_better", "Passing production checks.")
    add("production.strict_checks.failed", "production_readiness", "lower_is_better", "Failing production checks.")
    add("production.strict_checks.pass_rate", "production_readiness", "higher_is_better", "Production check pass rate.")
    add(
        "production.strict_checks.avg_elapsed_seconds",
        "production_readiness",
        "lower_is_better",
        "Average strict check execution time.",
    )
    add(
        "production.strict_checks.assertion_failures",
        "production_readiness",
        "lower_is_better",
        "Strict-check assertion failures.",
    )
    add(
        "production.strict_checks.command_failures",
        "production_readiness",
        "lower_is_better",
        "Strict-check command execution failures.",
    )

    add("benchmark.runs_count", "benchmark_execution", "higher_is_better", "Benchmark sample size.")
    add("benchmark.weighted_score_mean", "benchmark_execution", "higher_is_better", "Mean benchmark weighted score.")
    add(
        "benchmark.credibility_weighted_score_mean",
        "benchmark_execution",
        "higher_is_better",
        "Mean benchmark evidence-weighted score.",
    )
    add("benchmark.success_rate_mean", "benchmark_execution", "higher_is_better", "Mean benchmark success rate.")
    add(
        "benchmark.evidence_coverage_mean",
        "benchmark_execution",
        "higher_is_better",
        "Mean benchmark evidence coverage.",
    )
    add(
        "benchmark.avg_elapsed_seconds_mean",
        "benchmark_execution",
        "lower_is_better",
        "Mean benchmark elapsed time.",
    )
    add("benchmark.raw_rows_count", "benchmark_execution", "higher_is_better", "Raw benchmark row sample size.")
    add("benchmark.raw_success_rate_mean", "benchmark_execution", "higher_is_better", "Raw benchmark success rate.")
    add(
        "benchmark.raw_elapsed_seconds_mean",
        "benchmark_execution",
        "lower_is_better",
        "Raw benchmark mean elapsed seconds.",
    )
    add(
        "benchmark.raw_elapsed_seconds_p95",
        "benchmark_execution",
        "lower_is_better",
        "Raw benchmark P95 elapsed seconds.",
    )

    add(
        "benchmark.weighted_score_stddev",
        "reliability",
        "lower_is_better",
        "Weighted-score stability across runs.",
    )
    add(
        "benchmark.success_rate_stddev",
        "reliability",
        "lower_is_better",
        "Success-rate stability across runs.",
    )
    add(
        "benchmark.avg_elapsed_seconds_stddev",
        "reliability",
        "lower_is_better",
        "Elapsed-time stability across runs.",
    )
    add(
        "benchmark.raw_elapsed_seconds_stddev",
        "reliability",
        "lower_is_better",
        "Raw elapsed-time stability across benchmark rows.",
    )
    add("benchmark.failure_rate_mean", "reliability", "lower_is_better", "Mean task failure rate.")

    return specs


def _build_metric_rows(
    *,
    metric_specs: Mapping[str, MetricSpec],
    agents: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    agent_ids = [str(agent.get("id") or "").strip() for agent in agents if str(agent.get("id") or "").strip()]
    rows: list[dict[str, Any]] = []
    for metric in sorted(metric_specs.keys()):
        spec = metric_specs[metric]
        values = {}
        for agent in agents:
            aid = str(agent.get("id") or "").strip()
            values[aid] = dict(agent.get("metrics") or {}).get(metric)

        participants = {aid: float(values[aid]) for aid in agent_ids if _is_number(values.get(aid))}
        missing = [aid for aid in agent_ids if aid not in participants]

        status = "no_data"
        winners: list[str] = []
        spread = None
        if len(participants) == 1:
            status = "single_agent"
            winners = list(participants.keys())
            spread = 0.0
        elif len(participants) >= 2:
            status = "ok"
            vals = list(participants.values())
            lo = min(vals)
            hi = max(vals)
            spread = round(hi - lo, 6)
            if spec.preference == "higher_is_better":
                best = hi
                winners = [aid for aid, value in participants.items() if abs(value - best) <= 1e-9]
            elif spec.preference == "lower_is_better":
                best = lo
                winners = [aid for aid, value in participants.items() if abs(value - best) <= 1e-9]
            else:
                raise ValueError(f"unsupported preference: {spec.preference}")

        normalized: dict[str, float] = {aid: 0.0 for aid in agent_ids}
        if participants:
            vals = list(participants.values())
            lo = min(vals)
            hi = max(vals)
            if abs(hi - lo) <= 1e-9:
                for aid in participants:
                    normalized[aid] = 1.0
            else:
                for aid, value in participants.items():
                    if spec.preference == "higher_is_better":
                        normalized[aid] = (value - lo) / (hi - lo)
                    else:
                        normalized[aid] = (hi - value) / (hi - lo)
        normalized = {aid: round(val, 6) for aid, val in normalized.items()}

        gap_to_best: dict[str, float | None] = {}
        if participants and winners:
            if spec.preference == "higher_is_better":
                best = max(participants.values())
                for aid in agent_ids:
                    gap_to_best[aid] = round(best - participants[aid], 6) if aid in participants else None
            else:
                best = min(participants.values())
                for aid in agent_ids:
                    gap_to_best[aid] = round(participants[aid] - best, 6) if aid in participants else None
        else:
            for aid in agent_ids:
                gap_to_best[aid] = None

        rows.append(
            {
                "metric": metric,
                "category": spec.category,
                "preference": spec.preference,
                "weight": round(float(spec.weight), 6),
                "rationale": spec.rationale,
                "test_mode": str(spec.test_mode or "quick"),
                "values": values,
                "participants": sorted(participants.keys()),
                "missing": missing,
                "status": status,
                "winners": sorted(winners),
                "spread": spread,
                "normalized": normalized,
                "gap_to_best": gap_to_best,
            }
        )
    return rows


def _build_scoreboard(rows: Sequence[Mapping[str, Any]], *, agents: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    agent_ids = [str(agent.get("id") or "").strip() for agent in agents if str(agent.get("id") or "").strip()]
    wins = {aid: 0 for aid in agent_ids}
    tie_metrics = 0
    measured_metrics = 0

    weighted_points = {aid: 0.0 for aid in agent_ids}
    measured_count = {aid: 0 for aid in agent_ids}
    comparable_measured_count = {aid: 0 for aid in agent_ids}
    max_weight = 0.0

    category_totals: dict[str, float] = {}
    category_points: dict[str, dict[str, float]] = {aid: {} for aid in agent_ids}
    category_measured_counts: dict[str, dict[str, int]] = {aid: {} for aid in agent_ids}
    category_comparable_measured_counts: dict[str, dict[str, int]] = {aid: {} for aid in agent_ids}

    for row in rows:
        participants = list(row.get("participants") or [])
        winners = list(row.get("winners") or [])
        weight = float(row.get("weight") or 0.0)
        category = str(row.get("category") or "uncategorized")
        normalized = dict(row.get("normalized") or {})
        values = dict(row.get("values") or {})

        comparable = len(participants) >= 2
        if comparable:
            measured_metrics += 1
            if len(winners) == 1:
                wins[winners[0]] += 1
            elif len(winners) > 1:
                tie_metrics += 1

        if comparable:
            max_weight += weight
            category_totals[category] = category_totals.get(category, 0.0) + weight
            for aid in agent_ids:
                weighted_points[aid] += float(normalized.get(aid) or 0.0) * weight
                category_points[aid][category] = (
                    float(category_points[aid].get(category) or 0.0) + float(normalized.get(aid) or 0.0) * weight
                )

        for aid in agent_ids:
            if _is_number(values.get(aid)):
                measured_count[aid] += 1
                category_measured_counts[aid][category] = int(category_measured_counts[aid].get(category) or 0) + 1
                if comparable:
                    comparable_measured_count[aid] += 1
                    category_comparable_measured_counts[aid][category] = (
                        int(category_comparable_measured_counts[aid].get(category) or 0) + 1
                    )

    total_metrics = len(rows)
    ranking: list[dict[str, Any]] = []
    for aid in agent_ids:
        composite = round((weighted_points[aid] / max_weight) * 100.0, 3) if max_weight > 0 else 0.0
        coverage = round((measured_count[aid] / total_metrics), 6) if total_metrics > 0 else 0.0
        comparable_coverage = (
            round((comparable_measured_count[aid] / measured_metrics), 6) if measured_metrics > 0 else 0.0
        )
        ranking.append(
            {
                "agent": aid,
                "weighted_points": round(weighted_points[aid], 6),
                "composite_score": composite,
                "coverage": coverage,
                "comparable_coverage": comparable_coverage,
                "wins": int(wins[aid]),
                "metrics_with_data": int(measured_count[aid]),
                "comparable_metrics_with_data": int(comparable_measured_count[aid]),
                "metrics_total": int(total_metrics),
                "comparable_metrics_total": int(measured_metrics),
            }
        )
    ranking.sort(key=lambda item: float(item["composite_score"]), reverse=True)
    for idx, row in enumerate(ranking, start=1):
        row["rank"] = idx

    category_scores: dict[str, dict[str, Any]] = {}
    for aid in agent_ids:
        category_scores[aid] = {}
        for category, category_weight_total in category_totals.items():
            points = float(category_points[aid].get(category) or 0.0)
            score = round((points / category_weight_total) * 100.0, 3) if category_weight_total > 0 else 0.0
            category_scores[aid][category] = {
                "score": score,
                "weighted_points": round(points, 6),
                "max_weight": round(float(category_weight_total), 6),
                "metrics_with_data": int(category_measured_counts[aid].get(category) or 0),
                "comparable_metrics_with_data": int(category_comparable_measured_counts[aid].get(category) or 0),
            }

    return {
        "total_metrics": total_metrics,
        "measured_metrics": measured_metrics,
        "tie_metrics": tie_metrics,
        "wins_by_agent": wins,
        "ranking": ranking,
        "max_weight_total": round(max_weight, 6),
        "category_scores": category_scores,
    }


def _focus_gaps(rows: Sequence[Mapping[str, Any]], *, focus_agent: str, top_n: int) -> list[dict[str, Any]]:
    focus = str(focus_agent or "").strip()
    gaps: list[dict[str, Any]] = []
    for row in rows:
        participants = set(row.get("participants") or [])
        if focus not in participants:
            continue
        if len(participants) < 2:
            continue
        winners = set(row.get("winners") or [])
        if focus in winners:
            continue
        gaps.append(
            {
                "metric": row.get("metric"),
                "category": row.get("category"),
                "weight": row.get("weight"),
                "preference": row.get("preference"),
                "values": row.get("values"),
                "winners": row.get("winners"),
                "gap_to_best": (row.get("gap_to_best") or {}).get(focus),
            }
        )
    gaps.sort(key=lambda item: (float(item.get("weight") or 0.0), float(item.get("gap_to_best") or 0.0)), reverse=True)
    return gaps[: max(0, int(top_n))]


def _build_competitor_pressure(
    *,
    rows: Sequence[Mapping[str, Any]],
    scoreboard: Mapping[str, Any],
    focus_agent: str,
) -> dict[str, Any]:
    focus = str(focus_agent or "").strip()
    ranking = [dict(item) for item in (scoreboard.get("ranking") or []) if isinstance(item, dict)]
    by_agent = {str(item.get("agent") or "").strip(): item for item in ranking if str(item.get("agent") or "").strip()}
    focus_score = _safe_float(dict(by_agent.get(focus) or {}).get("composite_score")) or 0.0
    pressure_rows: list[dict[str, Any]] = []
    for competitor, score_row in by_agent.items():
        if not competitor or competitor == focus:
            continue
        competitor_score = _safe_float(score_row.get("composite_score")) or 0.0
        competitor_wins = 0
        focus_wins = 0
        ties = 0
        comparable_metrics = 0
        for row in rows:
            participants = set(row.get("participants") or [])
            if focus not in participants or competitor not in participants:
                continue
            if len(participants) < 2:
                continue
            comparable_metrics += 1
            winners = set(row.get("winners") or [])
            if competitor in winners and focus not in winners:
                competitor_wins += 1
            elif focus in winners and competitor not in winners:
                focus_wins += 1
            else:
                ties += 1
        pressure_rows.append(
            {
                "competitor": competitor,
                "composite_score": round(competitor_score, 3),
                "composite_delta_vs_focus": round(competitor_score - focus_score, 3),
                "metrics_beating_focus": int(competitor_wins),
                "metrics_focus_beats": int(focus_wins),
                "metrics_tied": int(ties),
                "comparable_metrics": int(comparable_metrics),
                "threat_level": (
                    "high"
                    if (competitor_score > focus_score or competitor_wins > focus_wins)
                    else ("medium" if competitor_wins > 0 else "low")
                ),
            }
        )
    pressure_rows.sort(
        key=lambda item: (
            int(item.get("metrics_beating_focus") or 0),
            float(item.get("composite_delta_vs_focus") or 0.0),
        ),
        reverse=True,
    )
    threats = [row for row in pressure_rows if str(row.get("threat_level") or "") in {"high", "medium"}]
    return {
        "focus_agent": focus,
        "ranked_competitors": pressure_rows,
        "top_threats": threats,
    }


def load_suite_config(path: Path) -> dict[str, Any]:
    data = _read_json(path)
    agents = data.get("agents")
    if not isinstance(agents, list) or not agents:
        raise ValueError("suite config requires non-empty 'agents' list")
    normalized_agents: list[dict[str, Any]] = []
    for idx, raw in enumerate(agents, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"agents[{idx}] must be an object")
        aid = str(raw.get("id") or "").strip()
        if not aid:
            raise ValueError(f"agents[{idx}] is missing id")
        root = str(raw.get("root") or ".").strip()
        normalized = dict(raw)
        normalized["id"] = aid
        normalized["root"] = root
        normalized_agents.append(normalized)

    tracked_cli = [str(item).strip() for item in (data.get("tracked_cli_commands") or []) if str(item).strip()]
    if not tracked_cli:
        infer: list[str] = []
        for agent in normalized_agents:
            fixed_depth = dict((dict(agent.get("cli") or {})).get("fixed_subcommand_depth") or {})
            for name in fixed_depth:
                text = str(name).strip()
                if text and text not in infer:
                    infer.append(text)
        tracked_cli = sorted(infer)

    category_weights = dict(DEFAULT_CATEGORY_WEIGHTS)
    category_weights.update(dict(data.get("category_weights") or {}))
    metric_weight_overrides = dict(data.get("metric_weight_overrides") or {})
    competitor_catalog = [item for item in (data.get("competitor_catalog") or []) if isinstance(item, dict)]
    test_suite_contract_path = str(
        data.get("test_suite_contract_path") or str(DEFAULT_TEST_SUITE_CONTRACT_PATH)
    ).strip()
    execution_policy = dict(DEFAULT_EXECUTION_POLICY)
    execution_policy.update(dict(data.get("execution_policy") or {}))
    head_to_head_pair = [str(item).strip() for item in (data.get("head_to_head_pair") or []) if str(item).strip()]
    if len(head_to_head_pair) != 2:
        head_to_head_pair = []
    tie_policy = str(data.get("head_to_head_tie_policy") or "half_point").strip().lower()
    if tie_policy not in {"half_point", "exclude"}:
        tie_policy = "half_point"

    return {
        "id": str(data.get("id") or path.stem),
        "version": int(data.get("version") or 1),
        "description": str(data.get("description") or "").strip(),
        "tracked_cli_commands": tracked_cli,
        "category_weights": category_weights,
        "metric_weight_overrides": metric_weight_overrides,
        "competitor_catalog": competitor_catalog,
        "test_suite_contract_path": test_suite_contract_path,
        "execution_policy": execution_policy,
        "head_to_head_pair": head_to_head_pair,
        "head_to_head_tie_policy": tie_policy,
        "agents": normalized_agents,
    }


def build_suite_result(
    *,
    suite_config: Mapping[str, Any],
    suite_path: Path,
    focus_agent: str,
    top_gaps: int,
    head_to_head_pair: Sequence[str] | None = None,
    previous_registry_competitors: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    tracked_cli = list(suite_config.get("tracked_cli_commands") or [])
    category_weights = dict(suite_config.get("category_weights") or {})
    metric_weight_overrides = dict(suite_config.get("metric_weight_overrides") or {})
    execution_policy = dict(DEFAULT_EXECUTION_POLICY)
    execution_policy.update(dict(suite_config.get("execution_policy") or {}))
    suite_root = suite_path.parent.parent.parent.resolve()
    contract_path = Path(str(suite_config.get("test_suite_contract_path") or str(DEFAULT_TEST_SUITE_CONTRACT_PATH)))
    if not contract_path.is_absolute():
        contract_path = (suite_root / contract_path).resolve()
    contract = load_test_suite_contract(contract_path)
    prepared_agents, preparation = _materialize_competitor_catalog_agents(
        suite_config=suite_config,
        suite_root=suite_root,
    )

    agent_payloads: list[dict[str, Any]] = []
    gateway_keys: set[str] = set()
    for agent in prepared_agents:
        agent_payload = _collect_agent_metrics(
            agent,
            tracked_commands=tracked_cli,
            suite_root=suite_root,
        )
        agent_payloads.append(agent_payload)
        patterns = dict(DEFAULT_GATEWAY_PATTERNS)
        patterns.update(dict(agent.get("gateway_patterns") or {}))
        gateway_keys.update(patterns.keys())

    metric_specs = _build_metric_specs(
        tracked_cli_commands=tracked_cli,
        gateway_pattern_keys=sorted(gateway_keys),
        category_weights=category_weights,
        weight_overrides=metric_weight_overrides,
    )
    metric_rows = _build_metric_rows(metric_specs=metric_specs, agents=agent_payloads)
    scoreboard = _build_scoreboard(metric_rows, agents=agent_payloads)
    focus_gap_rows = _focus_gaps(metric_rows, focus_agent=focus_agent, top_n=top_gaps)
    competitor_pressure = _build_competitor_pressure(
        rows=metric_rows,
        scoreboard=scoreboard,
        focus_agent=focus_agent,
    )
    prediction_evo_scope = build_prediction_evo_scope(
        agents=agent_payloads,
        previous_registry_competitors=(previous_registry_competitors or {}),
        focus_agent=focus_agent,
    )

    result: dict[str, Any] = {
        "computed_at_utc": _now_iso(),
        "suite": {
            "id": str(suite_config.get("id") or ""),
            "version": int(suite_config.get("version") or 1),
            "description": str(suite_config.get("description") or ""),
            "config_path": str(suite_path),
            "test_suite_contract_path": str(contract_path),
            "execution_policy": execution_policy,
            "head_to_head_pair": list(head_to_head_pair or []),
            "head_to_head_tie_policy": str(suite_config.get("head_to_head_tie_policy") or "half_point"),
            "tracked_cli_commands": tracked_cli,
            "category_weights": category_weights,
            "metric_weight_overrides": metric_weight_overrides,
            "competitor_catalog_count": len(list(suite_config.get("competitor_catalog") or [])),
        },
        "preparation": preparation,
        "agents": agent_payloads,
        "metric_board": metric_rows,
        "scoreboard": scoreboard,
        "prediction_evo_scope": prediction_evo_scope,
        "focus": {
            "agent": str(focus_agent),
            "open_gaps": focus_gap_rows,
            "open_gap_count": len(focus_gap_rows),
            "competitor_pressure": competitor_pressure,
            "competitors_beating_focus": list(competitor_pressure.get("top_threats") or []),
        },
    }
    result["test_suite_contract"] = evaluate_test_suite_contract(
        contract=contract,
        result=result,
        focus_agent=focus_agent,
        head_to_head_pair=head_to_head_pair,
    )
    result["benchmark_program"] = evaluate_benchmark_program(
        contract=contract,
        result=result,
        contract_evaluation=dict(result.get("test_suite_contract") or {}),
    )
    contract_scores = list((dict(result.get("test_suite_contract") or {}).get("scores") or {}).get("agents") or [])
    score_map = {
        str(row.get("agent") or "").strip(): dict(row) for row in contract_scores if str(row.get("agent") or "").strip()
    }
    benchmark_rows = list(dict(result.get("benchmark_program") or {}).get("ranking") or [])
    benchmark_map = {
        str(row.get("agent") or "").strip(): dict(row) for row in benchmark_rows if str(row.get("agent") or "").strip()
    }
    ranking_rows = list((dict(result.get("scoreboard") or {})).get("ranking") or [])
    for row in ranking_rows:
        aid = str(row.get("agent") or "").strip()
        ext = dict(score_map.get(aid) or {})
        row["head_to_head_score"] = (
            round(float(ext.get("head_to_head_score")), 3) if _is_number(ext.get("head_to_head_score")) else None
        )
        row["head_to_head_decisive_score"] = (
            round(float(ext.get("head_to_head_decisive_score")), 3)
            if _is_number(ext.get("head_to_head_decisive_score"))
            else None
        )
        row["token_efficiency_score"] = (
            round(float(ext.get("token_efficiency_score")), 6)
            if _is_number(ext.get("token_efficiency_score"))
            else None
        )
        row["token_efficiency_tokens_per_success"] = (
            round(float(ext.get("token_efficiency_tokens_per_success")), 6)
            if _is_number(ext.get("token_efficiency_tokens_per_success"))
            else None
        )
        row["token_efficiency_telemetry_coverage"] = (
            round(float(ext.get("token_efficiency_telemetry_coverage")), 6)
            if _is_number(ext.get("token_efficiency_telemetry_coverage"))
            else 0.0
        )
        row["overall_suite_score"] = round(float(ext.get("overall_suite_score") or 0.0), 3)
        row["overall_suite_rank"] = int(ext.get("overall_rank") or 0)
        row["quick_suite_score"] = round(float(ext.get("quick_suite_score") or 0.0), 3)
        row["dynamic_suite_score"] = round(float(ext.get("dynamic_suite_score") or 0.0), 3)
        row["human_suite_score"] = round(float(ext.get("human_suite_score") or 0.0), 3)
        row["quick_suite_rank"] = int(ext.get("quick_suite_rank") or 0)
        row["dynamic_suite_rank"] = int(ext.get("dynamic_suite_rank") or 0)
        row["human_suite_rank"] = int(ext.get("human_suite_rank") or 0)
        bench = dict(benchmark_map.get(aid) or {})
        row["overall_benchmark_capability_score"] = round(
            float(bench.get("overall_benchmark_capability_score") or 0.0), 3
        )
        row["benchmark_program_rank"] = int(bench.get("rank") or 0)
        row["governance_verdict"] = str(bench.get("governance_verdict") or "NO_GO")
        lane_scores = dict(bench.get("lane_scores") or {})
        row["quick_lane_score"] = round(float(dict(lane_scores.get("quick") or {}).get("score") or 0.0), 3)
        row["dynamic_lane_score"] = round(float(dict(lane_scores.get("dynamic") or {}).get("score") or 0.0), 3)
    result["overall_suite_scoreboard"] = {
        "methodology": dict(dict(result.get("test_suite_contract") or {}).get("scoring_methodology") or {}),
        "ranking": sorted(
            [
                {
                    "agent": str(row.get("agent") or ""),
                    "head_to_head_score": (
                        round(float(row.get("head_to_head_score")), 3)
                        if _is_number(row.get("head_to_head_score"))
                        else None
                    ),
                    "head_to_head_decisive_score": (
                        round(float(row.get("head_to_head_decisive_score")), 3)
                        if _is_number(row.get("head_to_head_decisive_score"))
                        else None
                    ),
                    "token_efficiency_score": (
                        round(float(row.get("token_efficiency_score")), 6)
                        if _is_number(row.get("token_efficiency_score"))
                        else None
                    ),
                    "token_efficiency_tokens_per_success": (
                        round(float(row.get("token_efficiency_tokens_per_success")), 6)
                        if _is_number(row.get("token_efficiency_tokens_per_success"))
                        else None
                    ),
                    "token_efficiency_telemetry_coverage": round(
                        float(row.get("token_efficiency_telemetry_coverage") or 0.0), 6
                    ),
                    "overall_suite_score": round(float(row.get("overall_suite_score") or 0.0), 3),
                    "head_to_head_rank": int(row.get("rank") or 0),
                    "overall_suite_rank": int(row.get("overall_suite_rank") or 0),
                    "quick_suite_score": round(float(row.get("quick_suite_score") or 0.0), 3),
                    "dynamic_suite_score": round(float(row.get("dynamic_suite_score") or 0.0), 3),
                    "human_suite_score": round(float(row.get("human_suite_score") or 0.0), 3),
                    "quick_suite_rank": int(row.get("quick_suite_rank") or 0),
                    "dynamic_suite_rank": int(row.get("dynamic_suite_rank") or 0),
                    "human_suite_rank": int(row.get("human_suite_rank") or 0),
                    "overall_benchmark_capability_score": round(
                        float(row.get("overall_benchmark_capability_score") or 0.0), 3
                    ),
                    "benchmark_program_rank": int(row.get("benchmark_program_rank") or 0),
                    "governance_verdict": str(row.get("governance_verdict") or "NO_GO"),
                    "quick_lane_score": round(float(row.get("quick_lane_score") or 0.0), 3),
                    "dynamic_lane_score": round(float(row.get("dynamic_lane_score") or 0.0), 3),
                }
                for row in ranking_rows
            ],
            key=lambda item: int(item.get("overall_suite_rank") or 0)
            if int(item.get("overall_suite_rank") or 0) > 0
            else 9999,
        ),
    }
    return result


def _print_human(result: Mapping[str, Any]) -> None:
    suite = dict(result.get("suite") or {})
    scoreboard = dict(result.get("scoreboard") or {})
    runtime_ranking = list(scoreboard.get("ranking") or [])
    focus = dict(result.get("focus") or {})
    focus_gaps = list(focus.get("open_gaps") or [])
    pressure = dict(focus.get("competitor_pressure") or {})
    top_threats = list(pressure.get("top_threats") or [])
    prediction = dict(result.get("prediction_evo_scope") or {})
    contract = dict(result.get("test_suite_contract") or {})
    contract_summary = dict(contract.get("summary") or {})
    contract_runtime = dict(contract.get("runtime_metrics") or {})
    contract_catalog = dict((dict(contract.get("catalog") or {})).get("by_state") or {})
    dual_scoring = dict(result.get("overall_suite_scoreboard") or {})
    scoring_methodology = dict(dual_scoring.get("methodology") or {})
    ranking = list(dual_scoring.get("ranking") or [])
    runtime_map = {
        str(row.get("agent") or "").strip(): dict(row) for row in runtime_ranking if str(row.get("agent") or "").strip()
    }
    benchmark_program = dict(result.get("benchmark_program") or {})
    benchmark_ranking = list(benchmark_program.get("ranking") or [])
    h2h = dict(dict(contract.get("scores") or {}).get("head_to_head") or {})
    token_efficiency = dict(dict(contract.get("scores") or {}).get("token_efficiency") or {})
    token_h2h = dict(token_efficiency.get("head_to_head") or {})
    token_ranking = list(token_efficiency.get("overall_ranking") or [])

    print("Full Agent Comparison Suite")
    print(f"- suite: {suite.get('id')} v{suite.get('version')}")
    print(f"- computed at: {result.get('computed_at_utc')}")
    print(f"- config: {suite.get('config_path')}")
    policy = dict(suite.get("execution_policy") or {})
    if policy:
        print(
            f"- execution policy: quality_is_king={bool(policy.get('quality_is_king'))}, "
            f"cycle_limit_disabled={bool(policy.get('cycle_limit_disabled'))}"
        )
        if str(policy.get("stop_condition") or "").strip():
            print(f"- stop condition: {policy.get('stop_condition')}")
    print("")
    print("Ranking")
    if scoring_methodology:
        tie_policy = str(h2h.get("tie_policy") or "half_point")
        print(f"- head_to_head: {scoring_methodology.get('head_to_head_score')}")
        print(f"- token_efficiency: {scoring_methodology.get('token_efficiency_score')}")
        print(f"- overall_suite: {scoring_methodology.get('overall_suite_score')}")
        print(f"- lane_scores: {scoring_methodology.get('lane_suite_scores')}")
        print("- score math:")
        if tie_policy == "exclude":
            print("  - runtime head_to_head: winner=1, ties excluded, score=(points/counted_metrics)*100")
        else:
            print("  - runtime head_to_head: winner=1, tie=0.5, score=(points/counted_metrics)*100")
        print("  - head_to_head_decisive: winner=1, ties always excluded, score=(wins/non_tied_counted)*100")
        print("  - overall_suite: (runtime_passed + catalog_passed) / (runtime_applicable + catalog_applicable) * 100")
        print("  - lane_suite_scores: same formula as overall but mode-filtered by quick/dynamic/human tags")
        print("  - token_efficiency: separate token-only scoring block, emitted only with token telemetry evidence")
    for row in ranking:
        aid = str(row.get("agent") or "")
        runtime_row = dict(runtime_map.get(aid) or {})
        h2h_value = row.get("head_to_head_score")
        h2h_text = f"{h2h_value}" if _is_number(h2h_value) else "n/a"
        h2h_decisive_value = row.get("head_to_head_decisive_score")
        h2h_decisive_text = f"{h2h_decisive_value}" if _is_number(h2h_decisive_value) else "n/a"
        token_value = row.get("token_efficiency_score")
        token_text = f"{token_value}" if _is_number(token_value) else "n/a"
        print(
            f"- #{row.get('overall_suite_rank')} {row.get('agent')}: "
            f"overall_suite={row.get('overall_suite_score')} capability={row.get('overall_benchmark_capability_score')} "
            f"(quick={row.get('quick_suite_score')}, dynamic={row.get('dynamic_suite_score')}, human={row.get('human_suite_score')}), "
            f"(runtime_rank={runtime_row.get('rank')}, head_to_head={h2h_text}, decisive_h2h={h2h_decisive_text}, token_efficiency={token_text}), "
            f"verdict={row.get('governance_verdict')} "
            f"runtime_wins={runtime_row.get('wins')}, runtime_coverage={float(runtime_row.get('coverage') or 0.0) * 100:.1f}%"
        )
    print("")
    print("Head-to-Head (1v1)")
    if bool(h2h.get("enabled")):
        tie_policy = str(h2h.get("tie_policy") or "half_point")
        print(f"- pair: {h2h.get('agent_a')} vs {h2h.get('agent_b')}")
        print(
            f"- scores: {h2h.get('agent_a')}={h2h.get('agent_a_score')} "
            f"{h2h.get('agent_b')}={h2h.get('agent_b_score')} "
            f"(tie_policy={tie_policy}, counted_metrics={h2h.get('counted_metrics')}, "
            f"ties_counted={h2h.get('ties')}, ties_observed={h2h.get('ties_observed')})"
        )
        print(
            f"- decisive: {h2h.get('agent_a')}={h2h.get('decisive_agent_a_score')} "
            f"{h2h.get('agent_b')}={h2h.get('decisive_agent_b_score')} "
            f"(counted_metrics={h2h.get('decisive_counted_metrics')}, ties_excluded=True)"
        )
        h2h_by_mode = dict(h2h.get("by_mode") or {})
        for mode in ("quick", "dynamic", "human"):
            mode_row = dict(h2h_by_mode.get(mode) or {})
            counted = int(mode_row.get("counted_metrics") or 0)
            if counted <= 0:
                continue
            print(
                f"- by_mode.{mode}: {h2h.get('agent_a')}={mode_row.get('agent_a_score')} "
                f"{h2h.get('agent_b')}={mode_row.get('agent_b_score')} "
                f"(counted_metrics={counted}, ties_counted={mode_row.get('ties')}, "
                f"ties_observed={mode_row.get('ties_observed')})"
            )
    else:
        print("- not configured (use --h2h-a and --h2h-b for explicit 1v1).")
    print("")
    print("Token Efficiency")
    print(f"- method: {token_efficiency.get('methodology')}")
    if bool(token_h2h.get("enabled")):
        print(f"- pair: {token_h2h.get('agent_a')} vs {token_h2h.get('agent_b')}")
        print(
            f"- scores: {token_h2h.get('agent_a')}={token_h2h.get('agent_a_score')} "
            f"{token_h2h.get('agent_b')}={token_h2h.get('agent_b_score')} "
            f"(counted_metrics={token_h2h.get('counted_metrics')}, ties={token_h2h.get('ties')})"
        )
    else:
        print("- pair: not configured")
    for row in token_ranking[:6]:
        print(
            f"- #{row.get('token_efficiency_rank')} {row.get('agent')}: "
            f"score={row.get('token_efficiency_score')} "
            f"tokens_per_success={row.get('effective_tokens_per_success')} "
            f"coverage={row.get('telemetry_coverage')}"
        )
    print("")
    print("Benchmark Program")
    if benchmark_program:
        print(f"- id: {benchmark_program.get('id')}")
        lane_weights = dict(benchmark_program.get("lane_weights") or {})
        if lane_weights:
            joined = ", ".join(f"{k}={lane_weights[k]}" for k in sorted(lane_weights.keys()))
            print(f"- lane_weights: {joined}")
        verdict_counts = dict(benchmark_program.get("verdict_counts") or {})
        if verdict_counts:
            joined = ", ".join(f"{k}={verdict_counts[k]}" for k in sorted(verdict_counts.keys()))
            print(f"- verdict_counts: {joined}")
        for row in benchmark_ranking[:8]:
            print(
                f"- #{row.get('rank')} {row.get('agent')}: "
                f"capability={row.get('overall_benchmark_capability_score')} "
                f"quick={dict(row.get('lane_scores') or {}).get('quick', {}).get('score', 0.0)} "
                f"dynamic={dict(row.get('lane_scores') or {}).get('dynamic', {}).get('score', 0.0)} "
                f"verdict={row.get('governance_verdict')}"
            )
    print("")
    print("Metric Coverage")
    print(
        f"- total metrics: {scoreboard.get('total_metrics')} "
        f"(multi-agent measured: {scoreboard.get('measured_metrics')}, ties: {scoreboard.get('tie_metrics')})"
    )
    if contract:
        print("")
        print("Full Coverage Contract")
        print(
            f"- tracked checks: {contract_summary.get('tracked_total')} "
            f"(implemented={contract_summary.get('implemented_total')}, planned={contract_summary.get('planned_total')})"
        )
        print(
            f"- runtime metrics tracked: {contract_runtime.get('total')} "
            f"(focus data={contract_runtime.get('with_focus_data')}, comparable={contract_runtime.get('comparable')})"
        )
        if contract_catalog:
            states = ", ".join(f"{k}={contract_catalog[k]}" for k in sorted(contract_catalog.keys()))
            print(f"- catalog states: {states}")

    focus_agent = str(focus.get("agent") or "")
    if focus_agent:
        print("")
        print(f"Open Gaps For {focus_agent}")
        if not focus_gaps:
            print("- none")
        else:
            for row in focus_gaps:
                winners = ", ".join(list(row.get("winners") or []))
                print(
                    f"- {row.get('metric')}: winners={winners} "
                    f"gap={row.get('gap_to_best')} preference={row.get('preference')}"
                )

        print("")
        print(f"Competitors Beating {focus_agent} Most")
        if not top_threats:
            print("- none")
        else:
            for row in top_threats:
                print(
                    f"- {row.get('competitor')}: beat_metrics={row.get('metrics_beating_focus')} "
                    f"focus_beats={row.get('metrics_focus_beats')} "
                    f"composite_delta={row.get('composite_delta_vs_focus')}"
                )

    aggregate_focus = list(prediction.get("aggregate_predicted_focus") or [])
    aggregate_moves = list(prediction.get("aggregate_recommended_counter_moves") or [])
    print("")
    print("Prediction Evo Scope")
    if aggregate_focus:
        for row in aggregate_focus[:8]:
            print(f"- predicted area: {row.get('area')} (signals={row.get('count')})")
    else:
        print("- predicted area: none (not enough competitor version history yet)")
    if aggregate_moves:
        print("- recommended Thomas counter-moves:")
        for row in aggregate_moves[:8]:
            print(f"  - {row.get('move')} (signals={row.get('count')})")


def _render_markdown(result: Mapping[str, Any]) -> str:
    suite = dict(result.get("suite") or {})
    scoreboard = dict(result.get("scoreboard") or {})
    runtime_ranking = list(scoreboard.get("ranking") or [])
    focus = dict(result.get("focus") or {})
    gaps = list(focus.get("open_gaps") or [])
    pressure = dict(focus.get("competitor_pressure") or {})
    top_threats = list(pressure.get("top_threats") or [])
    prediction = dict(result.get("prediction_evo_scope") or {})
    contract = dict(result.get("test_suite_contract") or {})
    contract_summary = dict(contract.get("summary") or {})
    contract_runtime = dict(contract.get("runtime_metrics") or {})
    contract_catalog = dict((dict(contract.get("catalog") or {})).get("by_state") or {})
    dual_scoring = dict(result.get("overall_suite_scoreboard") or {})
    scoring_methodology = dict(dual_scoring.get("methodology") or {})
    ranking = list(dual_scoring.get("ranking") or [])
    runtime_map = {
        str(row.get("agent") or "").strip(): dict(row) for row in runtime_ranking if str(row.get("agent") or "").strip()
    }
    h2h = dict(dict(contract.get("scores") or {}).get("head_to_head") or {})
    token_efficiency = dict(dict(contract.get("scores") or {}).get("token_efficiency") or {})
    token_h2h = dict(token_efficiency.get("head_to_head") or {})
    token_ranking = list(token_efficiency.get("overall_ranking") or [])
    benchmark_program = dict(result.get("benchmark_program") or {})
    benchmark_ranking = list(benchmark_program.get("ranking") or [])
    agents = list(result.get("agents") or [])
    lines: list[str] = []
    lines.append(f"# Full Agent Comparison Suite ({suite.get('id')})")
    lines.append("")
    lines.append(f"- Computed at: `{result.get('computed_at_utc')}`")
    lines.append(f"- Config: `{suite.get('config_path')}`")
    policy = dict(suite.get("execution_policy") or {})
    if policy:
        lines.append(
            f"- Execution policy: quality_is_king=`{bool(policy.get('quality_is_king'))}`, "
            f"cycle_limit_disabled=`{bool(policy.get('cycle_limit_disabled'))}`"
        )
        if str(policy.get("stop_condition") or "").strip():
            lines.append(f"- Stop condition: `{policy.get('stop_condition')}`")
    lines.append("")
    lines.append("## Ranking")
    lines.append("")
    if scoring_methodology:
        tie_policy = str(h2h.get("tie_policy") or "half_point")
        lines.append(f"- Head-to-head method: `{scoring_methodology.get('head_to_head_score')}`")
        lines.append(f"- Token efficiency method: `{scoring_methodology.get('token_efficiency_score')}`")
        lines.append(f"- Overall suite method: `{scoring_methodology.get('overall_suite_score')}`")
        lines.append(f"- Lane suite method: `{scoring_methodology.get('lane_suite_scores')}`")
        lines.append("- Score math:")
        if tie_policy == "exclude":
            lines.append("- runtime head_to_head: `winner=1`, `ties_excluded`, `score=(points/counted_metrics)*100`")
        else:
            lines.append("- runtime head_to_head: `winner=1`, `tie=0.5`, `score=(points/counted_metrics)*100`")
        lines.append("- head_to_head_decisive: `winner=1`, `ties_excluded`, `score=(wins/non_tied_counted)*100`")
        lines.append(
            "- overall_suite: `(runtime_passed + catalog_passed) / (runtime_applicable + catalog_applicable) * 100`"
        )
        lines.append(
            "- lane_suite_scores: same formula as overall, filtered by `test_mode` (`quick`, `dynamic`, `human`)"
        )
        lines.append(
            "- token_efficiency: separate token-only scoring block, emitted only with token telemetry evidence"
        )
        lines.append("")
    for row in ranking:
        aid = str(row.get("agent") or "")
        runtime_row = dict(runtime_map.get(aid) or {})
        h2h_value = row.get("head_to_head_score")
        h2h_text = str(h2h_value) if _is_number(h2h_value) else "n/a"
        h2h_decisive_value = row.get("head_to_head_decisive_score")
        h2h_decisive_text = str(h2h_decisive_value) if _is_number(h2h_decisive_value) else "n/a"
        token_value = row.get("token_efficiency_score")
        token_text = str(token_value) if _is_number(token_value) else "n/a"
        lines.append(
            f"- #{row.get('overall_suite_rank')} `{row.get('agent')}`: overall_suite `{row.get('overall_suite_score')}`, capability `{row.get('overall_benchmark_capability_score')}`, "
            f"quick_suite `{row.get('quick_suite_score')}`, dynamic_suite `{row.get('dynamic_suite_score')}`, human_suite `{row.get('human_suite_score')}`, "
            f"runtime_rank `{runtime_row.get('rank')}`, head_to_head `{h2h_text}`, decisive_h2h `{h2h_decisive_text}`, token_efficiency `{token_text}`, "
            f"verdict `{row.get('governance_verdict')}`, runtime_wins `{runtime_row.get('wins')}`, "
            f"runtime_coverage `{round(float(runtime_row.get('coverage') or 0.0) * 100.0, 2)}%`"
        )
    lines.append("")
    lines.append("## Head-to-Head (1v1)")
    lines.append("")
    if bool(h2h.get("enabled")):
        tie_policy = str(h2h.get("tie_policy") or "half_point")
        lines.append(f"- Pair: `{h2h.get('agent_a')}` vs `{h2h.get('agent_b')}`")
        lines.append(
            f"- Scores: `{h2h.get('agent_a')}`=`{h2h.get('agent_a_score')}`, "
            f"`{h2h.get('agent_b')}`=`{h2h.get('agent_b_score')}` "
            f"(tie_policy `{tie_policy}`, counted_metrics `{h2h.get('counted_metrics')}`, "
            f"ties_counted `{h2h.get('ties')}`, ties_observed `{h2h.get('ties_observed')}`)"
        )
        lines.append(
            f"- Decisive (ties excluded): `{h2h.get('agent_a')}`=`{h2h.get('decisive_agent_a_score')}`, "
            f"`{h2h.get('agent_b')}`=`{h2h.get('decisive_agent_b_score')}` "
            f"(counted_metrics `{h2h.get('decisive_counted_metrics')}`)"
        )
        h2h_by_mode = dict(h2h.get("by_mode") or {})
        for mode in ("quick", "dynamic", "human"):
            mode_row = dict(h2h_by_mode.get(mode) or {})
            counted = int(mode_row.get("counted_metrics") or 0)
            if counted <= 0:
                continue
            lines.append(
                f"- By mode `{mode}`: `{h2h.get('agent_a')}`=`{mode_row.get('agent_a_score')}`, "
                f"`{h2h.get('agent_b')}`=`{mode_row.get('agent_b_score')}` "
                f"(counted_metrics `{counted}`, ties_counted `{mode_row.get('ties')}`, "
                f"ties_observed `{mode_row.get('ties_observed')}`)"
            )
    else:
        lines.append("- Not configured (use `--h2h-a` and `--h2h-b` for explicit 1v1).")
    lines.append("")
    lines.append("## Token Efficiency")
    lines.append("")
    lines.append(f"- Method: `{token_efficiency.get('methodology')}`")
    if bool(token_h2h.get("enabled")):
        lines.append(f"- Pair: `{token_h2h.get('agent_a')}` vs `{token_h2h.get('agent_b')}`")
        lines.append(
            f"- Scores: `{token_h2h.get('agent_a')}`=`{token_h2h.get('agent_a_score')}`, "
            f"`{token_h2h.get('agent_b')}`=`{token_h2h.get('agent_b_score')}` "
            f"(counted_metrics `{token_h2h.get('counted_metrics')}`, ties `{token_h2h.get('ties')}`)"
        )
    else:
        lines.append("- Pair: not configured.")
    for row in token_ranking[:6]:
        lines.append(
            f"- `#{row.get('token_efficiency_rank')}` `{row.get('agent')}`: "
            f"score `{row.get('token_efficiency_score')}`, "
            f"tokens_per_success `{row.get('effective_tokens_per_success')}`, "
            f"coverage `{row.get('telemetry_coverage')}`"
        )
    lines.append("")
    lines.append("## Benchmark Program")
    lines.append("")
    lines.append(f"- Program id: `{benchmark_program.get('id')}`")
    lane_weights = dict(benchmark_program.get("lane_weights") or {})
    if lane_weights:
        for lane in sorted(lane_weights.keys()):
            lines.append(f"- Lane weight `{lane}`: `{lane_weights[lane]}`")
    verdict_counts = dict(benchmark_program.get("verdict_counts") or {})
    if verdict_counts:
        for key in sorted(verdict_counts.keys()):
            lines.append(f"- Verdict `{key}`: `{verdict_counts[key]}`")
    for row in benchmark_ranking[:8]:
        lines.append(
            f"- `#{row.get('rank')}` `{row.get('agent')}`: capability `{row.get('overall_benchmark_capability_score')}`, "
            f"quick `{dict(row.get('lane_scores') or {}).get('quick', {}).get('score', 0.0)}`, "
            f"dynamic `{dict(row.get('lane_scores') or {}).get('dynamic', {}).get('score', 0.0)}`, "
            f"verdict `{row.get('governance_verdict')}`"
        )
    lines.append("")
    if contract:
        lines.append("## Full Coverage Contract")
        lines.append("")
        lines.append(
            f"- Tracked checks: `{contract_summary.get('tracked_total')}` "
            f"(implemented `{contract_summary.get('implemented_total')}`, planned `{contract_summary.get('planned_total')}`)"
        )
        lines.append(
            f"- Runtime metrics tracked: `{contract_runtime.get('total')}` "
            f"(focus data `{contract_runtime.get('with_focus_data')}`, comparable `{contract_runtime.get('comparable')}`)"
        )
        if contract_catalog:
            for key in sorted(contract_catalog.keys()):
                lines.append(f"- Catalog `{key}`: `{contract_catalog[key]}`")
        lines.append("")
    lines.append("## Agent Data Health")
    lines.append("")
    for agent in agents:
        errors = list(agent.get("errors") or [])
        version_info = dict(agent.get("version_info") or {})
        model_snapshot = dict(agent.get("model_snapshot") or {})
        lines.append(f"### {agent.get('id')}")
        lines.append(f"- Root: `{agent.get('root')}`")
        if version_info:
            head = str(version_info.get("local_head") or version_info.get("version") or "n/a")
            up = version_info.get("is_up_to_date")
            up_text = "yes" if up is True else ("no" if up is False else "unknown")
            lines.append(f"- Version: `{head}` (up_to_date={up_text})")
        if model_snapshot:
            model_value = str(model_snapshot.get("model") or model_snapshot.get("profile") or "n/a")
            lines.append(
                f"- Model snapshot: ok={bool(model_snapshot.get('ok'))}, day=`{model_snapshot.get('day_utc')}`, model=`{model_value}`"
            )
        lines.append(
            f"- Strict checks: {dict(agent.get('strict_checks') or {}).get('passed')} passed / {dict(agent.get('strict_checks') or {}).get('total')} total"
        )
        lines.append(f"- Benchmark runs used: {dict(agent.get('benchmark') or {}).get('runs_count')}")
        if errors:
            lines.append("- Errors:")
            for item in errors[:10]:
                lines.append(f"  - {item}")
        else:
            lines.append("- Errors: none")
        lines.append("")
    lines.append("## Focus Gaps")
    lines.append("")
    if not gaps:
        lines.append("- none")
    else:
        for row in gaps:
            winners = ", ".join(list(row.get("winners") or []))
            lines.append(
                f"- `{row.get('metric')}` ({row.get('category')}): winners `{winners}`, "
                f"gap `{row.get('gap_to_best')}`"
            )
    lines.append("")
    lines.append("## Competitor Pressure")
    lines.append("")
    if not top_threats:
        lines.append("- none")
    else:
        for row in top_threats:
            lines.append(
                f"- `{row.get('competitor')}`: beat_metrics `{row.get('metrics_beating_focus')}`, "
                f"focus_beats `{row.get('metrics_focus_beats')}`, "
                f"composite_delta `{row.get('composite_delta_vs_focus')}`"
            )
    lines.append("")
    lines.append("## Prediction Evo Scope")
    lines.append("")
    aggregate_focus = list(prediction.get("aggregate_predicted_focus") or [])
    aggregate_moves = list(prediction.get("aggregate_recommended_counter_moves") or [])
    if aggregate_focus:
        lines.append("### Predicted Next Competitor Focus")
        for row in aggregate_focus[:12]:
            lines.append(f"- `{row.get('area')}` ({row.get('count')} signals)")
    else:
        lines.append("- No competitor delta history yet.")
    lines.append("")
    if aggregate_moves:
        lines.append("### Recommended Thomas Counter-Moves")
        for row in aggregate_moves[:12]:
            lines.append(f"- {row.get('move')} ({row.get('count')} signals)")
    lines.append("")
    return "\n".join(lines)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a comprehensive multi-agent comparison suite.")
    parser.add_argument(
        "--suite-config", default=str(DEFAULT_SUITE_CONFIG), help=f"Suite config path (default: {DEFAULT_SUITE_CONFIG})"
    )
    parser.add_argument("--focus-agent", default="thomas", help="Agent id to show open-gap list for.")
    parser.add_argument("--h2h-a", default="", help="Head-to-head agent A id (explicit 1v1 mode).")
    parser.add_argument("--h2h-b", default="", help="Head-to-head agent B id (explicit 1v1 mode).")
    parser.add_argument("--top-gaps", type=int, default=25, help="Maximum focus gaps to include.")
    parser.add_argument("--json", action="store_true", help="Print JSON result.")
    parser.add_argument("--write", action="store_true", help=f"Write JSON artifact (default: {DEFAULT_WRITE_PATH}).")
    parser.add_argument(
        "--write-path",
        default=str(DEFAULT_WRITE_PATH),
        help=f"JSON output path for --write (default: {DEFAULT_WRITE_PATH})",
    )
    parser.add_argument(
        "--write-md", action="store_true", help=f"Write markdown report (default: {DEFAULT_WRITE_MD_PATH})."
    )
    parser.add_argument(
        "--write-md-path",
        default=str(DEFAULT_WRITE_MD_PATH),
        help=f"Markdown output path for --write-md (default: {DEFAULT_WRITE_MD_PATH})",
    )
    parser.add_argument(
        "--test-suite-contract-path",
        default="",
        help=f"Override full coverage contract path (default from config or {DEFAULT_TEST_SUITE_CONTRACT_PATH}).",
    )
    parser.add_argument(
        "--registry-path",
        default=str(DEFAULT_REGISTRY_PATH),
        help=f"Competitor registry JSON path (default: {DEFAULT_REGISTRY_PATH})",
    )
    parser.add_argument(
        "--registry-md-path",
        default=str(DEFAULT_REGISTRY_MD_PATH),
        help=f"Competitor registry markdown path (default: {DEFAULT_REGISTRY_MD_PATH})",
    )
    parser.add_argument(
        "--no-registry-write", action="store_true", help="Disable competitor registry updates for this run."
    )
    return parser.parse_args(argv)


def run(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    suite_path = Path(str(args.suite_config))
    if not suite_path.is_absolute():
        suite_path = (ROOT / suite_path).resolve()
    suite_config = load_suite_config(suite_path)
    if str(args.test_suite_contract_path or "").strip():
        suite_config = dict(suite_config)
        suite_config["test_suite_contract_path"] = str(args.test_suite_contract_path).strip()
    if str(args.h2h_a or "").strip() and str(args.h2h_b or "").strip():
        suite_config = dict(suite_config)
        suite_config["head_to_head_pair"] = [str(args.h2h_a).strip(), str(args.h2h_b).strip()]
    head_to_head_pair = [
        str(item).strip() for item in (suite_config.get("head_to_head_pair") or []) if str(item).strip()
    ]
    if len(head_to_head_pair) != 2:
        head_to_head_pair = []

    out_path = Path(str(args.write_path))
    if not out_path.is_absolute():
        out_path = (ROOT / out_path).resolve()
    out_md = Path(str(args.write_md_path))
    if not out_md.is_absolute():
        out_md = (ROOT / out_md).resolve()
    registry_path = Path(str(args.registry_path))
    if not registry_path.is_absolute():
        registry_path = (ROOT / registry_path).resolve()
    registry_md_path = Path(str(args.registry_md_path))
    if not registry_md_path.is_absolute():
        registry_md_path = (ROOT / registry_md_path).resolve()
    previous_registry = load_registry(registry_path)
    previous_competitors = dict(previous_registry.get("competitors") or {})

    result = build_suite_result(
        suite_config=suite_config,
        suite_path=suite_path,
        focus_agent=str(args.focus_agent or "").strip(),
        top_gaps=max(0, int(args.top_gaps)),
        head_to_head_pair=head_to_head_pair,
        previous_registry_competitors=previous_competitors,
    )
    required_model_failures: list[str] = []
    for agent in list(result.get("agents") or []):
        aid = str(agent.get("id") or "").strip()
        snapshot = dict(agent.get("model_snapshot") or {})
        if bool(snapshot.get("required")) and not bool(snapshot.get("ok")):
            required_model_failures.append(f"{aid}: {snapshot.get('error') or 'required model snapshot missing'}")
    result["validation"] = {"required_model_snapshot_failures": required_model_failures}

    if bool(args.write):
        _write_json(out_path, result)
    if bool(args.write_md):
        out_md.parent.mkdir(parents=True, exist_ok=True)
        out_md.write_text(_render_markdown(result), encoding="utf-8")

    if not bool(args.no_registry_write):
        _update_competitor_registry(
            result=result,
            registry_path=registry_path,
            registry_md_path=registry_md_path,
            result_json_path=(out_path if bool(args.write) else None),
            result_md_path=(out_md if bool(args.write_md) else None),
        )

    if bool(args.json):
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        _print_human(result)
        if required_model_failures:
            print("")
            print("Model Snapshot Validation")
            for row in required_model_failures:
                print(f"- {row}")

    return 2 if required_model_failures else 0


def main(argv: Sequence[str] | None = None) -> int:
    return run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
