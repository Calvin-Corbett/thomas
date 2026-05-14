from __future__ import annotations

from typing import Any

import fnmatch
import glob
import io
import json
import math
import re
import tokenize
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from statistics import mean, pstdev

from thomas.demo.agent_comparison_suite_shared import (
    CODE_EXTENSIONS,
    _assertion_ok,
    _count_code,
    _is_number,
    _iter_files,
    _resolve_path_value,
    _run_command,
    _safe_float,
)


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
        if path.suffix == ".py":
            text = _strip_python_comments_and_strings(text)
        file_hits = 0
        for regex in compiled:
            file_hits += len(regex.findall(text))
        if file_hits > 0:
            files_with_hits += 1
            total_hits += int(file_hits)
    return {"files_with_hits": int(files_with_hits), "total_hits": int(total_hits)}


def _strip_python_comments_and_strings(text: str) -> str:
    lines = text.splitlines(keepends=True)
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type not in (tokenize.STRING, tokenize.COMMENT):
                continue
            start_row, start_col = tok.start
            end_row, end_col = tok.end
            if start_row == end_row:
                line = lines[start_row - 1]
                lines[start_row - 1] = line[:start_col] + (" " * max(0, end_col - start_col)) + line[end_col:]
                continue

            first = lines[start_row - 1]
            lines[start_row - 1] = first[:start_col] + (" " * max(0, len(first) - start_col))
            for row in range(start_row, end_row - 1):
                lines[row] = " " * len(lines[row])
            last = lines[end_row - 1]
            lines[end_row - 1] = (" " * end_col) + last[end_col:]
    except (IndentationError, SyntaxError, tokenize.TokenError):
        return text
    return "".join(lines)


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
    evidence_files: list[Path] = []
    for pattern in patterns:
        path = Path(pattern)
        if not path.is_absolute():
            path = (suite_root / pattern).resolve()
        matches = [Path(item) for item in sorted(glob.glob(str(path), recursive=True))]
        for match in matches:
            if not match.is_file():
                continue
            evidence_files.append(match)
            if match.name == "benchmark_results.raw.json":
                prog_match = match.with_name("benchmark_results.prog_evidence.json")
                if prog_match.is_file():
                    evidence_files.append(prog_match)
            elif match.name == "benchmark_results.prog_evidence.json":
                raw_match = match.with_name("benchmark_results.raw.json")
                if raw_match.is_file():
                    evidence_files.append(raw_match)

    for match in evidence_files:
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
