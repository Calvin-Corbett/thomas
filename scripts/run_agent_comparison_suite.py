from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

from thomas.demo import agent_comparison_suite as _suite


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SUITE_CONFIG = ROOT / "demo" / "baselines" / "agent_comparison_suite.current.json"
DEFAULT_ARTIFACT_PATHS_REL = {
    "latest_json": "docs/openclaw_gap_runs/latest_full_suite_compare.json",
    "latest_markdown": "docs/openclaw_gap_runs/latest_full_suite_compare.md",
    "latest_legacy_json": "docs/openclaw_gap_runs/latest_compare.json",
    "registry_json": "docs/openclaw_gap_runs/competitor_registry.json",
    "registry_markdown": "docs/openclaw_gap_runs/competitor_registry.md",
}
BENCHMARK_GLOB_KEYS: dict[str, tuple[str, ...]] = {
    "benchmark_scorecard_globs": (
        "benchmark_scorecard_globs",
        "benchmark_scorecard_glob",
        "scorecard_globs",
        "scorecard_glob",
    ),
    "benchmark_raw_globs": (
        "benchmark_raw_globs",
        "benchmark_raw_glob",
        "raw_globs",
        "benchmark_results_raw_globs",
        "benchmark_results_globs",
    ),
    "benchmark_evidence_globs": (
        "benchmark_evidence_globs",
        "benchmark_evidence_glob",
        "evidence_globs",
        "benchmark_checks_globs",
    ),
}
BENCHMARK_ALIAS_KEYS = (
    "benchmark_aliases",
    "benchmark_alias",
    "benchmark_tracks",
    "track_aliases",
)


def _resolve_repo_path(repo_root: Path, raw_path: str | None, *, fallback_rel: str) -> Path:
    value = str(raw_path or "").strip() or fallback_rel
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = (repo_root / path).resolve()
    return path


def _dedupe_keep_order(items: Sequence[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in items:
        text = str(raw or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _coerce_string_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    values: list[str] = []
    if isinstance(raw, str):
        values = [raw]
    elif isinstance(raw, Mapping):
        for key in ("glob", "path", "pattern", "value"):
            if key in raw:
                values = [str(raw.get(key) or "")]
                break
    elif isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
        for item in raw:
            if isinstance(item, Mapping):
                for key in ("glob", "path", "pattern", "value"):
                    if key in item:
                        values.append(str(item.get(key) or ""))
                        break
                else:
                    values.append(str(item))
            else:
                values.append(str(item))
    else:
        values = [str(raw)]
    return _dedupe_keep_order(values)


def _first_present_string_list(payload: Mapping[str, Any], keys: Sequence[str]) -> list[str]:
    for key in keys:
        values = _coerce_string_list(payload.get(key))
        if values:
            return values
    return []


def _normalize_agent_benchmark_config(agent: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
    normalized = dict(agent)
    changed = False

    aid = str(normalized.get("id") or "").strip()
    aliases: list[str] = []
    for key in BENCHMARK_ALIAS_KEYS:
        aliases.extend(_coerce_string_list(normalized.get(key)))
    if aid:
        aliases.append(aid)
    aliases = _dedupe_keep_order(aliases)
    if normalized.get("benchmark_aliases") != aliases:
        normalized["benchmark_aliases"] = aliases
        changed = True

    for canonical, candidates in BENCHMARK_GLOB_KEYS.items():
        values = _first_present_string_list(normalized, candidates)
        if canonical == "benchmark_evidence_globs" and not values:
            values = _first_present_string_list(normalized, BENCHMARK_GLOB_KEYS["benchmark_raw_globs"])
        if normalized.get(canonical) != values:
            normalized[canonical] = values
            changed = True

    return normalized, changed


def _normalize_suite_config_payload(payload: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
    normalized = dict(payload)
    agents = normalized.get("agents")
    if not isinstance(agents, list):
        return normalized, False

    changed = False
    out_agents: list[Any] = []
    for item in agents:
        if not isinstance(item, Mapping):
            out_agents.append(item)
            continue
        normalized_agent, agent_changed = _normalize_agent_benchmark_config(item)
        out_agents.append(normalized_agent)
        changed = changed or agent_changed

    if changed:
        normalized["agents"] = out_agents
    return normalized, changed


def _prepare_suite_config_for_run(
    suite_config_path: str | Path | None,
    *,
    repo_root: Path = ROOT,
) -> tuple[Path, Path | None]:
    config_path = Path(suite_config_path or DEFAULT_SUITE_CONFIG).expanduser()
    if not config_path.is_absolute():
        config_path = (repo_root / config_path).resolve()

    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return config_path, None
    if not isinstance(payload, Mapping):
        return config_path, None

    normalized_payload, changed = _normalize_suite_config_payload(payload)
    if not changed:
        return config_path, None

    fd, raw_path = tempfile.mkstemp(prefix="agent-suite-normalized-", suffix=".json")
    temp_path = Path(raw_path)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(normalized_payload, handle, indent=2)
        handle.write("\n")
    return temp_path, temp_path


def _inject_suite_config(argv: Sequence[str], *, suite_config_path: Path) -> list[str]:
    forwarded: list[str] = []
    skip_next = False
    for token in argv:
        if skip_next:
            skip_next = False
            continue
        text = str(token)
        if text == "--suite-config":
            skip_next = True
            continue
        if text.startswith("--suite-config="):
            continue
        forwarded.append(text)
    forwarded += ["--suite-config", str(suite_config_path)]
    return forwarded


def load_artifact_paths(
    suite_config_path: str | Path | None = None,
    *,
    repo_root: Path = ROOT,
) -> dict[str, Path]:
    config_path = Path(suite_config_path or DEFAULT_SUITE_CONFIG).expanduser()
    if not config_path.is_absolute():
        config_path = (repo_root / config_path).resolve()

    artifact_paths_cfg: dict[str, Any] = {}
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and isinstance(payload.get("artifact_paths"), dict):
            artifact_paths_cfg = dict(payload["artifact_paths"])
    except Exception:
        artifact_paths_cfg = {}

    resolved: dict[str, Path] = {}
    for key, rel_path in DEFAULT_ARTIFACT_PATHS_REL.items():
        resolved[key] = _resolve_repo_path(
            repo_root,
            str(artifact_paths_cfg.get(key) or ""),
            fallback_rel=rel_path,
        )
    return resolved


def _parse_wrapper_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--suite-config", default=None)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--write-path", default=None)
    parser.add_argument("--write-md", action="store_true")
    parser.add_argument("--write-md-path", default=None)
    parser.add_argument("--registry-path", default=None)
    parser.add_argument("--registry-md-path", default=None)
    parser.add_argument("--no-registry-write", action="store_true")
    args, _ = parser.parse_known_args(list(argv))
    return args


def _inject_default_paths(argv: Sequence[str], *, artifact_paths: dict[str, Path]) -> list[str]:
    parsed = _parse_wrapper_args(argv)
    forwarded = list(argv)

    if parsed.write and parsed.write_path is None:
        forwarded += ["--write-path", str(artifact_paths["latest_json"])]
    if parsed.write_md and parsed.write_md_path is None:
        forwarded += ["--write-md-path", str(artifact_paths["latest_markdown"])]
    if (not parsed.no_registry_write) and parsed.registry_path is None:
        forwarded += ["--registry-path", str(artifact_paths["registry_json"])]
    if (not parsed.no_registry_write) and parsed.registry_md_path is None:
        forwarded += ["--registry-md-path", str(artifact_paths["registry_markdown"])]

    return forwarded


def _effective_write_path(parsed: argparse.Namespace) -> Path | None:
    if not bool(parsed.write):
        return None
    return _resolve_repo_path(
        ROOT,
        str(parsed.write_path or ""),
        fallback_rel=DEFAULT_ARTIFACT_PATHS_REL["latest_json"],
    )


def _mirror_legacy_json(
    *,
    source_path: Path,
    canonical_path: Path,
    legacy_path: Path,
) -> None:
    if not source_path.exists():
        return

    source = source_path.resolve()
    canonical = canonical_path.resolve()
    legacy = legacy_path.resolve()
    if canonical == legacy:
        return

    destination: Path | None = None
    if source == canonical:
        destination = legacy_path
    elif source == legacy:
        destination = canonical_path
    if destination is None:
        return

    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_path, destination)


def run(argv: Sequence[str] | None = None) -> int:
    raw_argv = list(argv) if argv is not None else list(sys.argv[1:])
    parsed = _parse_wrapper_args(raw_argv)
    suite_config_path, temp_config_path = _prepare_suite_config_for_run(parsed.suite_config or DEFAULT_SUITE_CONFIG)
    artifact_paths = load_artifact_paths(suite_config_path)
    forwarded_argv = _inject_default_paths(raw_argv, artifact_paths=artifact_paths)
    forwarded_argv = _inject_suite_config(forwarded_argv, suite_config_path=suite_config_path)

    try:
        rc = _suite.main(forwarded_argv)
        rc = int(rc) if rc is not None else 0
        if rc != 0:
            return rc

        forwarded_parsed = _parse_wrapper_args(forwarded_argv)
        write_path = _effective_write_path(forwarded_parsed)
        if write_path is not None:
            _mirror_legacy_json(
                source_path=write_path,
                canonical_path=artifact_paths["latest_json"],
                legacy_path=artifact_paths["latest_legacy_json"],
            )
        return 0
    finally:
        if temp_config_path is not None:
            temp_config_path.unlink(missing_ok=True)


def main(argv: Sequence[str] | None = None) -> int:
    return run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
