from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from thomas.demo.agent_comparison_suite_shared import (
    DEFAULT_GATEWAY_PATTERNS,
    MetricSpec,
    _collect_git_version_info,
    _collect_model_snapshot,
    _count_code,
    _count_empty_code_files,
    _count_empty_files,
    _count_files,
    _count_immediate_dirs,
    _count_invalid_json_files,
    _count_large_code_files,
    _count_mobile_surface_dirs,
    _count_non_test_code,
    _count_python_syntax_errors,
    _count_test_code,
    _count_text_occurrences,
    _is_number,
    _parse_click_commands,
    _resolve,
    _run_command,
)
from thomas.demo.agent_comparison_suite_strict_checks import (
    _collect_benchmark_evidence,
    _collect_benchmark_summary,
    _compute_token_efficiency,
    _count_regex_hits,
    _fallback_cost_probe,
    _fallback_performance_probe,
    _fallback_resilience_probe,
    _fallback_security_probe,
    _run_probe_suite,
    _run_strict_checks,
)


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
    code_without_tests = _count_non_test_code(source_roots, excluded_files=seen_test_files)
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
    metrics["tests.to_code_file_ratio"] = (
        round((tests["files"] / code_without_tests["files"]), 6) if code_without_tests["files"] > 0 else None
    )
    metrics["tests.to_code_loc_ratio"] = (
        round((tests["loc"] / code_without_tests["loc"]), 6) if code_without_tests["loc"] > 0 else None
    )

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
