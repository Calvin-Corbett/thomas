#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence


ROOT = Path(__file__).resolve().parents[1]
PROOF_FILE = "apps/site/verification/ui-proof.json"
REQUIRED_RUNTIME_REPORT_PATH = "apps/site/verification/runtime-report.json"
EXPECTED_GENERATOR_SCRIPT = "scripts/refresh_site_visual_proof.py"
EXPECTED_RUNTIME_VERIFIER = "scripts/verify_site_visual_runtime.mjs"
REQUIRED_SCREENSHOT_KEYS = ("full_page", "footer_focus")
REQUIRED_ASSERTIONS = (
    "core_layout_present",
    "no_console_runtime_errors",
    "no_broken_images",
    "pixel_diff_within_threshold",
    "nav_persistent_all_routes",
    "unknown_route_theme_integrity",
    "band_on_footer_border",
    "no_band_strip_height",
    "riders_mounted_on_back",
    "riders_seat_contact_stable",
    "riders_centered_on_saddle",
    "riders_robot_clearly_visible",
    "no_horizontal_drag_overflow",
)
UI_PATH_PREFIXES = ("apps/site/src/app/", "apps/site/src/components/")
UI_PATH_SUFFIXES = (".css", ".scss", ".ts", ".tsx", ".js", ".jsx")


def _normalize(path: str) -> str:
    return str(path or "").strip().replace("\\", "/")


def _run_git(repo_root: Path, args: Sequence[str]) -> list[str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"git {' '.join(args)} failed")
    out: list[str] = []
    for raw in proc.stdout.splitlines():
        path = _normalize(raw)
        if path:
            out.append(path)
    return out


def _git_changed_paths_range(repo_root: Path, *, base: str, head: str) -> list[str]:
    spec = f"{base}...{head}"
    return sorted(set(_run_git(repo_root, ["diff", "--name-only", spec])))


def _git_local_changed_paths(repo_root: Path) -> list[str]:
    paths = set(_run_git(repo_root, ["diff", "--name-only"]))
    paths.update(_run_git(repo_root, ["diff", "--name-only", "--cached"]))
    paths.update(_run_git(repo_root, ["ls-files", "--others", "--exclude-standard"]))
    return sorted(paths)


def _is_ui_change(path: str) -> bool:
    p = _normalize(path)
    if not p:
        return False
    if not any(p.startswith(prefix) for prefix in UI_PATH_PREFIXES):
        return False
    return p.lower().endswith(UI_PATH_SUFFIXES)


def _parse_timestamp(raw: Any) -> bool:
    text = str(raw or "").strip()
    if not text:
        return False
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
        return True
    except Exception:
        return False


def _is_hex_sha256(raw: Any) -> bool:
    text = str(raw or "").strip().lower()
    return bool(re.fullmatch(r"[0-9a-f]{64}", text))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _read_number(container: dict[str, Any], key: str, errors: list[str], *, label: str) -> float | None:
    if key not in container:
        errors.append(f"missing numeric field: {label}.{key}")
        return None
    raw = container.get(key)
    if isinstance(raw, bool):
        errors.append(f"field must be numeric, got bool: {label}.{key}")
        return None
    try:
        return float(raw)
    except Exception:
        errors.append(f"field must be numeric: {label}.{key}")
        return None


def _validate_proof_payload(
    payload: Any,
    repo_root: Path,
    *,
    ui_changes: Sequence[str],
) -> tuple[list[str], list[str], str]:
    errors: list[str] = []
    screenshot_paths: list[str] = []
    runtime_report_path = ""
    runtime_report_path = ""
    runtime_report_payload: dict[str, Any] | None = None

    if not isinstance(payload, dict):
        return (["visual proof payload must be a JSON object"], screenshot_paths, runtime_report_path)

    rule_version = payload.get("rule_version")
    try:
        parsed_rule_version = int(rule_version)
    except Exception:
        parsed_rule_version = None
    if parsed_rule_version != 2:
        errors.append("rule_version must be 2")

    if not _parse_timestamp(payload.get("captured_at_utc")):
        errors.append("captured_at_utc must be a valid ISO-8601 timestamp")

    target_url = str(payload.get("target_url") or "").strip()
    if not target_url or not (target_url.startswith("http://") or target_url.startswith("https://")):
        errors.append("target_url must be a non-empty http(s) URL")

    generator = payload.get("generator")
    if not isinstance(generator, dict):
        errors.append("generator must be an object")
    else:
        script = _normalize(str(generator.get("script") or ""))
        runtime_verifier = _normalize(str(generator.get("runtime_verifier") or ""))
        if script != EXPECTED_GENERATOR_SCRIPT:
            errors.append(f"generator.script must be {EXPECTED_GENERATOR_SCRIPT}")
        if runtime_verifier != EXPECTED_RUNTIME_VERIFIER:
            errors.append(f"generator.runtime_verifier must be {EXPECTED_RUNTIME_VERIFIER}")
        if not _parse_timestamp(generator.get("generated_at_utc")):
            errors.append("generator.generated_at_utc must be a valid ISO-8601 timestamp")

    git_info = payload.get("git")
    if not isinstance(git_info, dict):
        errors.append("git must be an object")
    else:
        head_sha = str(git_info.get("head_sha") or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{7,40}", head_sha):
            errors.append("git.head_sha must be a valid commit SHA")
        listed_ui = git_info.get("ui_changed_paths")
        if not isinstance(listed_ui, list):
            errors.append("git.ui_changed_paths must be a list")
        else:
            normalized_listed = [_normalize(str(raw)) for raw in listed_ui if _normalize(str(raw))]
            bad_listed = [path for path in normalized_listed if not _is_ui_change(path)]
            if bad_listed:
                errors.append(
                    "git.ui_changed_paths contains non-UI path(s): " + ", ".join(sorted(set(bad_listed)))
                )
            missing_ui = sorted(set(ui_changes) - set(normalized_listed))
            if missing_ui:
                errors.append(
                    "git.ui_changed_paths is missing detected UI change(s): "
                    + ", ".join(missing_ui)
                )

    runtime = payload.get("runtime_report")
    if not isinstance(runtime, dict):
        errors.append("runtime_report must be an object")
    else:
        runtime_path = _normalize(str(runtime.get("path") or ""))
        runtime_hash = str(runtime.get("sha256") or "").strip().lower()
        if not runtime_path:
            errors.append("runtime_report.path is required")
        else:
            runtime_report_path = runtime_path
            if runtime_path != REQUIRED_RUNTIME_REPORT_PATH:
                errors.append(f"runtime_report.path must be {REQUIRED_RUNTIME_REPORT_PATH}")
            if not runtime_path.startswith("apps/site/verification/"):
                errors.append("runtime_report.path must live under apps/site/verification/")
            if Path(runtime_path).suffix.lower() != ".json":
                errors.append("runtime_report.path must be a .json file")
            runtime_abs = (repo_root / runtime_path).resolve()
            if not runtime_abs.exists():
                errors.append(f"runtime report file does not exist: {runtime_path}")
            elif runtime_abs.stat().st_size <= 0:
                errors.append(f"runtime report file is empty: {runtime_path}")
            else:
                if not _is_hex_sha256(runtime_hash):
                    errors.append("runtime_report.sha256 must be a 64-char hex sha256")
                else:
                    actual_runtime_hash = _sha256_file(runtime_abs)
                    if actual_runtime_hash != runtime_hash:
                        errors.append(
                            "runtime_report.sha256 mismatch: "
                            f"expected {runtime_hash}, got {actual_runtime_hash}"
                        )
                try:
                    loaded_runtime = json.loads(runtime_abs.read_text(encoding="utf-8"))
                    if isinstance(loaded_runtime, dict):
                        runtime_report_payload = loaded_runtime
                    else:
                        errors.append("runtime report JSON must be an object")
                except Exception as exc:
                    errors.append(f"failed to parse runtime report JSON ({runtime_path}): {exc}")

    shots = payload.get("screenshots")
    if not isinstance(shots, dict):
        errors.append("screenshots must be an object")
    else:
        for key in REQUIRED_SCREENSHOT_KEYS:
            raw_entry = shots.get(key)
            if not isinstance(raw_entry, dict):
                errors.append(f"screenshots.{key} must be an object with path and sha256")
                continue
            raw_path = _normalize(str(raw_entry.get("path") or ""))
            raw_hash = str(raw_entry.get("sha256") or "").strip().lower()
            if not raw_path:
                errors.append(f"screenshots.{key}.path is required")
                continue
            if not _is_hex_sha256(raw_hash):
                errors.append(f"screenshots.{key}.sha256 must be a 64-char hex sha256")
            if not raw_path.startswith("apps/site/verification/screenshots/"):
                errors.append(f"screenshots.{key}.path must live under apps/site/verification/screenshots/")
            proof_ext = Path(raw_path).suffix.lower()
            if proof_ext not in (".png", ".jpg", ".jpeg"):
                errors.append(f"screenshots.{key}.path must be .png/.jpg/.jpeg")
            disk_path = (repo_root / raw_path).resolve()
            if not disk_path.exists():
                errors.append(f"screenshot file does not exist: {raw_path}")
            elif disk_path.stat().st_size <= 0:
                errors.append(f"screenshot file is empty: {raw_path}")
            else:
                if _is_hex_sha256(raw_hash):
                    actual_hash = _sha256_file(disk_path)
                    if actual_hash != raw_hash:
                        errors.append(
                            f"screenshots.{key}.sha256 mismatch: expected {raw_hash}, got {actual_hash}"
                        )
            screenshot_paths.append(raw_path)

    metrics = payload.get("metrics")
    if not isinstance(metrics, dict):
        errors.append("metrics must be an object")
        return (errors, screenshot_paths, runtime_report_path)

    footer_top = _read_number(metrics, "footer_top", errors, label="metrics")
    band_top = _read_number(metrics, "band_top", errors, label="metrics")
    band_height = _read_number(metrics, "band_height", errors, label="metrics")
    viewport_width = _read_number(metrics, "viewport_width", errors, label="metrics")
    root_scroll_width = _read_number(metrics, "root_scroll_width", errors, label="metrics")
    console_error_count = _read_number(metrics, "console_error_count", errors, label="metrics")
    broken_image_count = _read_number(metrics, "broken_image_count", errors, label="metrics")
    pixel_diff_threshold_ratio = _read_number(metrics, "pixel_diff_threshold_ratio", errors, label="metrics")
    pixel_diff_full_page_ratio = _read_number(metrics, "pixel_diff_full_page_ratio", errors, label="metrics")
    pixel_diff_footer_focus_ratio = _read_number(metrics, "pixel_diff_footer_focus_ratio", errors, label="metrics")
    pixel_diff_max_ratio = _read_number(metrics, "pixel_diff_max_ratio", errors, label="metrics")
    pixel_diff_size_mismatch_count = _read_number(metrics, "pixel_diff_size_mismatch_count", errors, label="metrics")

    has_nav = metrics.get("has_nav")
    has_main = metrics.get("has_main")
    has_footer = metrics.get("has_footer")
    if not isinstance(has_nav, bool):
        errors.append("metrics.has_nav must be a boolean")
    if not isinstance(has_main, bool):
        errors.append("metrics.has_main must be a boolean")
    if not isinstance(has_footer, bool):
        errors.append("metrics.has_footer must be a boolean")

    riders = metrics.get("riders")
    if not isinstance(riders, list) or not riders:
        errors.append("metrics.riders must be a non-empty list")
    else:
        for index, raw_rider in enumerate(riders):
            if not isinstance(raw_rider, dict):
                errors.append(f"metrics.riders[{index}] must be an object")
                continue
            robot_top = _read_number(raw_rider, "robot_top", errors, label=f"metrics.riders[{index}]")
            robot_bottom = _read_number(raw_rider, "robot_bottom", errors, label=f"metrics.riders[{index}]")
            robot_width = _read_number(raw_rider, "robot_width", errors, label=f"metrics.riders[{index}]")
            robot_height = _read_number(raw_rider, "robot_height", errors, label=f"metrics.riders[{index}]")
            robot_left = _read_number(raw_rider, "robot_left", errors, label=f"metrics.riders[{index}]")
            robot_right = _read_number(raw_rider, "robot_right", errors, label=f"metrics.riders[{index}]")
            robot_center_x = _read_number(raw_rider, "robot_center_x", errors, label=f"metrics.riders[{index}]")
            robot_body_top = _read_number(raw_rider, "robot_body_top", errors, label=f"metrics.riders[{index}]")
            robot_body_bottom = _read_number(raw_rider, "robot_body_bottom", errors, label=f"metrics.riders[{index}]")
            robot_body_left = _read_number(raw_rider, "robot_body_left", errors, label=f"metrics.riders[{index}]")
            robot_body_right = _read_number(raw_rider, "robot_body_right", errors, label=f"metrics.riders[{index}]")
            robot_body_center_x = _read_number(raw_rider, "robot_body_center_x", errors, label=f"metrics.riders[{index}]")
            track_top = _read_number(raw_rider, "track_top", errors, label=f"metrics.riders[{index}]")
            track_bottom = _read_number(raw_rider, "track_bottom", errors, label=f"metrics.riders[{index}]")
            saddle_top = _read_number(raw_rider, "saddle_top", errors, label=f"metrics.riders[{index}]")
            saddle_bottom = _read_number(raw_rider, "saddle_bottom", errors, label=f"metrics.riders[{index}]")
            saddle_left = _read_number(raw_rider, "saddle_left", errors, label=f"metrics.riders[{index}]")
            saddle_right = _read_number(raw_rider, "saddle_right", errors, label=f"metrics.riders[{index}]")
            if (
                robot_body_top is not None
                and saddle_top is not None
                and saddle_bottom is not None
            ):
                if robot_body_top < saddle_top - 2 or robot_body_top > saddle_bottom + 4:
                    errors.append(
                        f"metrics.riders[{index}] mount check failed: robot_body_top ({robot_body_top:.2f}) "
                        f"must be within saddle band [{saddle_top - 2:.2f}, {saddle_bottom + 4:.2f}]"
                    )
            if robot_body_bottom is not None and saddle_top is not None:
                bottom_offset = robot_body_bottom - saddle_top
                if bottom_offset < -6 or bottom_offset > 16:
                    errors.append(
                        f"metrics.riders[{index}] seat contact failed: robot_body_bottom-saddle_top "
                        f"must be in [-6, 16] (got {bottom_offset:.2f})"
                    )
            if (
                robot_body_left is not None
                and robot_body_right is not None
                and
                robot_body_center_x is not None
                and saddle_left is not None
                and saddle_right is not None
            ):
                saddle_center_x = saddle_left + (saddle_right - saddle_left) / 2
                centered = abs(robot_body_center_x - saddle_center_x) <= 4
                overlaps_saddle = (
                    robot_body_right >= saddle_left + 1 and robot_body_left <= saddle_right - 1
                )
                if not (centered and overlaps_saddle):
                    errors.append(
                        f"metrics.riders[{index}] horizontal mount failed: robot_body_center_x "
                        f"({robot_body_center_x:.2f}) must be within +/-4px of saddle center ({saddle_center_x:.2f}) "
                        f"and overlap saddle span [{saddle_left + 1:.2f}, {saddle_right - 1:.2f}] "
                        f"(robot body span [{robot_body_left:.2f}, {robot_body_right:.2f}])"
                    )
            if robot_width is not None and robot_width < 12:
                errors.append(
                    f"metrics.riders[{index}] visibility failed: robot_width must be >= 12 (got {robot_width:.2f})"
                )
            if robot_height is not None and robot_height < 10:
                errors.append(
                    f"metrics.riders[{index}] visibility failed: robot_height must be >= 10 (got {robot_height:.2f})"
                )
            if (
                robot_top is not None
                and robot_bottom is not None
                and track_top is not None
                and track_bottom is not None
                and not (robot_bottom > track_top + 1 and robot_top < track_bottom - 1)
            ):
                errors.append(
                    f"metrics.riders[{index}] visibility failed: robot bounds [{robot_top:.2f}, {robot_bottom:.2f}] "
                    f"must intersect track [{track_top:.2f}, {track_bottom:.2f}]"
                )

    route_matrix = metrics.get("route_matrix")
    if not isinstance(route_matrix, list) or not route_matrix:
        errors.append("metrics.route_matrix must be a non-empty list")
    else:
        saw_probe_route = False
        for index, raw_route in enumerate(route_matrix):
            if not isinstance(raw_route, dict):
                errors.append(f"metrics.route_matrix[{index}] must be an object")
                continue
            route_path = _normalize(str(raw_route.get("route") or ""))
            if not route_path.startswith("/"):
                errors.append(f"metrics.route_matrix[{index}].route must start with '/'")
            if route_path == "/__ui-route-smoke__":
                saw_probe_route = True
            nav_position = _normalize(str(raw_route.get("nav_position") or "")).lower()
            if nav_position not in {"fixed", "sticky"}:
                errors.append(
                    f"metrics.route_matrix[{index}].nav_position must be fixed or sticky "
                    f"(got {nav_position or 'missing'})"
                )
            nav_top = _read_number(raw_route, "nav_top", errors, label=f"metrics.route_matrix[{index}]")
            nav_top_after_scroll = _read_number(
                raw_route,
                "nav_top_after_scroll",
                errors,
                label=f"metrics.route_matrix[{index}]",
            )
            route_viewport_width = _read_number(
                raw_route,
                "viewport_width",
                errors,
                label=f"metrics.route_matrix[{index}]",
            )
            route_root_scroll_width = _read_number(
                raw_route,
                "root_scroll_width",
                errors,
                label=f"metrics.route_matrix[{index}]",
            )
            route_broken_images = _read_number(
                raw_route,
                "broken_image_count",
                errors,
                label=f"metrics.route_matrix[{index}]",
            )
            if nav_top is not None and abs(nav_top) > 2:
                errors.append(
                    f"metrics.route_matrix[{index}] nav top drift too high at load "
                    f"(got {nav_top:.2f}, expected <= 2px)"
                )
            if nav_top_after_scroll is not None and abs(nav_top_after_scroll) > 2:
                errors.append(
                    f"metrics.route_matrix[{index}] nav top drift too high after scroll "
                    f"(got {nav_top_after_scroll:.2f}, expected <= 2px)"
                )
            if (
                route_viewport_width is not None
                and route_root_scroll_width is not None
                and route_root_scroll_width > route_viewport_width + 1
            ):
                errors.append(
                    f"metrics.route_matrix[{index}] horizontal overflow: root_scroll_width must be <= viewport_width + 1 "
                    f"(got {route_root_scroll_width:.2f} vs {route_viewport_width:.2f})"
                )
            if route_broken_images is not None and route_broken_images > 0:
                errors.append(
                    f"metrics.route_matrix[{index}] broken_image_count must be 0 "
                    f"(got {route_broken_images:.2f})"
                )
        if not saw_probe_route:
            errors.append("metrics.route_matrix must include /__ui-route-smoke__ route entry")

    assertions = payload.get("assertions")
    if not isinstance(assertions, dict):
        errors.append("assertions must be an object")
    else:
        for key in REQUIRED_ASSERTIONS:
            if assertions.get(key) is not True:
                errors.append(f"assertions.{key} must be true")

    if runtime_report_payload is not None:
        runtime_metrics = runtime_report_payload.get("metrics")
        runtime_assertions = runtime_report_payload.get("assertions")
        runtime_target_url = str(runtime_report_payload.get("target_url") or "").strip()
        runtime_pixel_diff = runtime_report_payload.get("pixel_diff")
        if runtime_metrics != metrics:
            errors.append("metrics must exactly match runtime_report.metrics")
        if runtime_assertions != assertions:
            errors.append("assertions must exactly match runtime_report.assertions")
        if runtime_target_url and runtime_target_url != target_url:
            errors.append("target_url must match runtime_report.target_url")
        if not isinstance(runtime_pixel_diff, dict):
            errors.append("runtime report must include pixel_diff object")
        else:
            comparisons = runtime_pixel_diff.get("comparisons")
            if not isinstance(comparisons, dict):
                errors.append("runtime report pixel_diff.comparisons must be an object")
            else:
                for key in ("full_page", "footer_focus"):
                    entry = comparisons.get(key)
                    if not isinstance(entry, dict):
                        errors.append(f"runtime report pixel_diff.comparisons.{key} must be an object")
                        continue
                    for path_key, prefix in (
                        ("baseline_path", "apps/site/verification/baselines/"),
                        ("current_path", "apps/site/verification/screenshots/"),
                        ("diff_path", "apps/site/verification/diffs/"),
                    ):
                        rel = _normalize(str(entry.get(path_key) or ""))
                        if not rel:
                            errors.append(
                                f"runtime report pixel_diff.comparisons.{key}.{path_key} is required"
                            )
                            continue
                        if not rel.startswith(prefix):
                            errors.append(
                                f"runtime report pixel_diff.comparisons.{key}.{path_key} must live under {prefix}"
                            )
                            continue
                        abs_path = (repo_root / rel).resolve()
                        if not abs_path.exists():
                            errors.append(
                                f"runtime report pixel_diff.comparisons.{key}.{path_key} file does not exist: {rel}"
                            )
                            continue
                        hash_key = path_key.replace("_path", "_sha256")
                        raw_hash = str(entry.get(hash_key) or "").strip().lower()
                        if not _is_hex_sha256(raw_hash):
                            errors.append(
                                f"runtime report pixel_diff.comparisons.{key}.{hash_key} must be a 64-char hex sha256"
                            )
                            continue
                        actual_hash = _sha256_file(abs_path)
                        if raw_hash != actual_hash:
                            errors.append(
                                f"runtime report pixel_diff.comparisons.{key}.{hash_key} mismatch: "
                                f"expected {raw_hash}, got {actual_hash}"
                            )

    if footer_top is not None and band_top is not None and abs(band_top - footer_top) > 3:
        errors.append(
            f"metrics border alignment failed: |band_top - footer_top| must be <= 3 "
            f"(got |{band_top:.2f} - {footer_top:.2f}|)"
        )
    if band_height is not None and int(round(band_height)) != 0:
        errors.append(f"metrics.band_height must be 0 (got {band_height:.2f})")
    if viewport_width is not None and root_scroll_width is not None and root_scroll_width > viewport_width + 1:
        errors.append(
            "metrics horizontal overflow failed: root_scroll_width must be <= viewport_width + 1 "
            f"(got {root_scroll_width:.2f} vs {viewport_width:.2f})"
        )
    if isinstance(has_nav, bool) and not has_nav:
        errors.append("metrics.has_nav must be true")
    if isinstance(has_main, bool) and not has_main:
        errors.append("metrics.has_main must be true")
    if isinstance(has_footer, bool) and not has_footer:
        errors.append("metrics.has_footer must be true")
    if console_error_count is not None and console_error_count > 0:
        errors.append(f"metrics.console_error_count must be 0 (got {console_error_count:.2f})")
    if broken_image_count is not None and broken_image_count > 0:
        errors.append(f"metrics.broken_image_count must be 0 (got {broken_image_count:.2f})")
    if pixel_diff_threshold_ratio is not None:
        if pixel_diff_threshold_ratio < 0 or pixel_diff_threshold_ratio > 1:
            errors.append(
                "metrics.pixel_diff_threshold_ratio must be in [0, 1] "
                f"(got {pixel_diff_threshold_ratio:.6f})"
            )
    if pixel_diff_full_page_ratio is not None:
        if pixel_diff_full_page_ratio < 0 or pixel_diff_full_page_ratio > 1:
            errors.append(
                "metrics.pixel_diff_full_page_ratio must be in [0, 1] "
                f"(got {pixel_diff_full_page_ratio:.6f})"
            )
    if pixel_diff_footer_focus_ratio is not None:
        if pixel_diff_footer_focus_ratio < 0 or pixel_diff_footer_focus_ratio > 1:
            errors.append(
                "metrics.pixel_diff_footer_focus_ratio must be in [0, 1] "
                f"(got {pixel_diff_footer_focus_ratio:.6f})"
            )
    if pixel_diff_max_ratio is not None:
        if pixel_diff_max_ratio < 0 or pixel_diff_max_ratio > 1:
            errors.append(
                "metrics.pixel_diff_max_ratio must be in [0, 1] "
                f"(got {pixel_diff_max_ratio:.6f})"
            )
    if pixel_diff_size_mismatch_count is not None and pixel_diff_size_mismatch_count != 0:
        errors.append(
            "metrics.pixel_diff_size_mismatch_count must be 0 "
            f"(got {pixel_diff_size_mismatch_count:.2f})"
        )
    if (
        pixel_diff_threshold_ratio is not None
        and pixel_diff_max_ratio is not None
        and pixel_diff_max_ratio > pixel_diff_threshold_ratio
    ):
        errors.append(
            "metrics pixel diff threshold failed: pixel_diff_max_ratio must be <= "
            f"pixel_diff_threshold_ratio (got {pixel_diff_max_ratio:.6f} > {pixel_diff_threshold_ratio:.6f})"
        )

    return (errors, screenshot_paths, runtime_report_path)


def _sample(paths: Iterable[str], *, limit: int = 6) -> str:
    items = [str(p) for p in paths]
    if not items:
        return ""
    shown = ", ".join(items[:limit])
    if len(items) > limit:
        shown += f", ... (+{len(items) - limit} more)"
    return shown


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Enforce visual verification proof for website UI changes."
    )
    parser.add_argument("--repo-root", default=None, help="Repository root (default: inferred).")
    parser.add_argument("--base", default="", help="Git base ref/SHA for change detection.")
    parser.add_argument("--head", default="HEAD", help="Git head ref/SHA for change detection.")
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve() if args.repo_root else ROOT
    base = str(args.base or "").strip()
    head = str(args.head or "").strip() or "HEAD"
    errors: list[str] = []

    try:
        if base:
            changed_paths = _git_changed_paths_range(repo_root, base=base, head=head)
            source_mode = f"range:{base}...{head}"
        else:
            changed_paths = _git_local_changed_paths(repo_root)
            source_mode = "local"
    except Exception as exc:
        print(f"site visual proof gate failed: {exc}")
        return 1

    changed_set = {_normalize(path) for path in changed_paths if _normalize(path)}
    ui_changes = sorted(path for path in changed_set if _is_ui_change(path))

    proof_path = _normalize(PROOF_FILE)
    proof_abs = (repo_root / proof_path).resolve()
    screenshot_paths: list[str] = []
    runtime_report_path = ""

    if ui_changes:
        if not proof_abs.exists():
            errors.append(f"missing required proof file: {proof_path}")
        else:
            try:
                payload = json.loads(proof_abs.read_text(encoding="utf-8"))
            except Exception as exc:
                errors.append(f"failed to parse {proof_path}: {exc}")
            else:
                validation_errors, payload_screens, payload_runtime = _validate_proof_payload(
                    payload,
                    repo_root,
                    ui_changes=ui_changes,
                )
                errors.extend(validation_errors)
                screenshot_paths.extend(_normalize(path) for path in payload_screens if _normalize(path))
                runtime_report_path = _normalize(payload_runtime)

        must_change = [proof_path, *screenshot_paths]
        must_change.append(runtime_report_path or REQUIRED_RUNTIME_REPORT_PATH)
        missing_updates = [path for path in must_change if path not in changed_set]
        if missing_updates:
            errors.append(
                "UI changes require fresh visual proof updates. Missing changed proof artifact(s): "
                f"{', '.join(missing_updates)}"
            )

    result = {
        "ok": not errors,
        "mode": source_mode,
        "changed_count": len(changed_set),
        "ui_change_count": len(ui_changes),
        "ui_changes": ui_changes,
        "proof_file": proof_path,
        "proof_screenshots": screenshot_paths,
        "proof_runtime_report": runtime_report_path,
        "errors": errors,
    }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif errors:
        print("Site visual proof gate: FAIL")
        print(f"- mode: {source_mode}")
        print(f"- ui changes ({len(ui_changes)}): {_sample(ui_changes)}")
        for err in errors:
            print(f"- {err}")
    elif ui_changes:
        print("Site visual proof gate: PASS")
        print(f"- mode: {source_mode}")
        print(f"- ui changes ({len(ui_changes)}): {_sample(ui_changes)}")
        print(f"- proof file: {proof_path}")
        if screenshot_paths:
            print(f"- proof screenshots: {_sample(screenshot_paths)}")
        if runtime_report_path:
            print(f"- proof runtime report: {runtime_report_path}")
    else:
        print("Site visual proof gate: PASS (no website UI changes detected)")
        print(f"- mode: {source_mode}")

    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(run())
