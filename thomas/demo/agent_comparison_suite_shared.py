from __future__ import annotations

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

from thomas.plugins.competitor_intel_store import load_registry, render_registry_markdown

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
DEFAULT_BENCHMARK_EVIDENCE_GLOBS = ["demo/agentic-runs/*/benchmark_results.raw.json"]


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
    except (TypeError, ValueError, json.JSONDecodeError):
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


def _coerce_text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _dedupe_case_insensitive(values: Sequence[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        text = str(raw).strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _default_competitor_benchmark_aliases(cid: str) -> tuple[list[str], list[str]]:
    normalized = str(cid or "").strip().lower()
    if normalized == "thomas":
        return ["thomas", "thomas_os"], list(DEFAULT_BENCHMARK_EVIDENCE_GLOBS)
    if normalized == "openclaw":
        return ["openclaw"], list(DEFAULT_BENCHMARK_EVIDENCE_GLOBS)
    return ([str(cid).strip()] if str(cid or "").strip() else []), []


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
    default_aliases, default_evidence_globs = _default_competitor_benchmark_aliases(cid)
    aliases = _dedupe_case_insensitive(_coerce_text_list(entry.get("benchmark_aliases")))
    if not aliases:
        aliases = default_aliases
    elif str(cid).strip().lower() == "thomas" and all(item.lower() != "thomas_os" for item in aliases):
        aliases.append("thomas_os")
    benchmark_evidence_globs = _coerce_text_list(entry.get("benchmark_evidence_globs"))
    if not benchmark_evidence_globs:
        benchmark_evidence_globs = default_evidence_globs
    output = {
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
        "benchmark_evidence_globs": _dedupe_case_insensitive(benchmark_evidence_globs),
        "benchmark_aliases": _dedupe_case_insensitive(aliases),
        "repo_sync": {
            "enabled": True,
            "remote": str(entry.get("remote") or "origin"),
            "branch": str(entry.get("branch") or "main"),
            "fetch": bool(entry.get("fetch", True)),
            "pull_ff_only": bool(entry.get("pull_ff_only", True)),
        },
        "model_snapshot_required": False,
    }
    return output


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
            if not isinstance(agent.get("benchmark_aliases"), list) or not agent.get("benchmark_aliases"):
                agent["benchmark_aliases"] = _default_competitor_benchmark_aliases(cid)[0]
            if not isinstance(agent.get("benchmark_evidence_globs"), list) or not agent.get("benchmark_evidence_globs"):
                agent["benchmark_evidence_globs"] = _default_competitor_benchmark_aliases(cid)[1]
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


