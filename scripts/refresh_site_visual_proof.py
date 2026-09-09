#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "output" / "site-visual-proof"
RUNTIME_REPORT_OUTPUT = OUTPUT_DIR / "runtime-report.json"
PROOF_DIR = ROOT / "apps" / "site" / "verification"
PROOF_SHOTS_DIR = PROOF_DIR / "screenshots"
PROOF_BASELINES_DIR = PROOF_DIR / "baselines"
PROOF_DIFFS_DIR = PROOF_DIR / "diffs"
PROOF_FILE = PROOF_DIR / "ui-proof.json"
PROOF_RUNTIME_REPORT = PROOF_DIR / "runtime-report.json"
DEFAULT_PIXEL_DIFF_THRESHOLD_RATIO = 0.02

# Pixel comparison: symmetric, anti-aliasing-tolerant, two-tier.
#
# site-visual-proof-baseline-drift-2026-08-26, round 1: two independent
# Playwright captures of the *identical* rendered page disagreed on ~59% of
# footer-focus pixels under a naive exact-byte comparison. Forensics traced
# it to two real, fixed capture bugs (see verify_site_visual_runtime.mjs):
# document.fonts.ready was not awaited before scrollHeight was read, and the
# scroll-to-bottom call raced globals.css's `scroll-behavior: smooth`
# against a fixed wait. Both are fixed at the capture layer now. Measured
# after both fixes: 5 independent same-tree captures are BYTE-IDENTICAL
# (0 pixels differ, any channel, at any threshold) -- footer-focus capture
# is provably deterministic today, not merely "usually low-diff".
#
# Round 1 (radius=2, tolerance=32, single-direction) shipped anyway with a
# real defect an adversarial review caught: current-pixel-vs-baseline-
# neighbourhood matching is directionless, so REMOVED content always finds
# background to match against -- blanking a third of the footer scored
# 0.073% (measured), an unbounded blind spot regardless of tolerance. T=32
# was also convenience-sized, not measured: 16-32x the actual 1-2/255 noise
# this was meant to absorb, so a uniform recolor up to 32/255 (an obviously
# wrong color) was invisible too, and radius=2 masked shifts up to 6px --
# the incident's own visual signature.
#
# Round 2 fixes both, keeping the gate strict rather than widening it:
#
# 1. SYMMETRIC (Chamfer-style) matching. For each direction (current vs
#    baseline, baseline vs current) a pixel passes if it is within
#    _PIXEL_STRICT_TOLERANCE of the same coordinate in the other image, OR
#    -- only where a real anti-aliased edge is plausible -- within
#    _PIXEL_EDGE_TOLERANCE of its best match in a
#    _PIXEL_AA_NEIGHBORHOOD_RADIUS neighbourhood. A pixel is "changed" if
#    EITHER direction fails. This closes the deletion blind spot: a deleted
#    glyph's baseline pixel has no matching current pixel in its
#    neighbourhood (there is nothing there to match, at any radius that
#    does not also swallow real regressions), so the baseline-vs-current
#    direction fails even though the current-vs-baseline direction (a
#    background pixel finding background nearby) would not have.
# 2. TWO-TIER tolerance, not one loose global number. The neighbourhood
#    escape only applies where local contrast (max-min over the same
#    neighbourhood, in EITHER image -- an edge can be flat-turned-edge or
#    edge-turned-flat under a 1px shift) reaches _PIXEL_EDGE_CONTRAST,
#    i.e. only pixels plausibly ON an anti-aliased boundary. Flat pixels
#    (backgrounds, solid fills, gradients) must match within
#    _PIXEL_STRICT_TOLERANCE at their exact coordinate -- no neighbourhood
#    rescue -- so a uniform recolor or opacity/contrast regression across a
#    flat region is caught immediately, not absorbed by an edge-only escape.
#
# Values (measured, not chosen for convenience):
#   _PIXEL_STRICT_TOLERANCE = 8: with capture now byte-identical run to run,
#     the honest measured noise floor is 0. 8 is kept as headroom for
#     cross-session drift this run could not observe (a different day, a
#     Chromium/OS update) -- a small multiple of the historically observed
#     1-2/255 flat-region noise, not 16-32x it.
#   _PIXEL_AA_NEIGHBORHOOD_RADIUS = 1: with the scroll-behavior race fixed,
#     the residual glyph-edge anti-aliasing jitter measured on 10 pairwise
#     real captures was absorbed at radius=1; radius=2 was sized to the
#     *pre-fix* scroll bug and is no longer needed, so it is removed --
#     radius=1 also means a 2px+ real shift cannot be neighbourhood-matched
#     away, unlike round 1's radius=2 (which masked shifts up to 6px).
#   _PIXEL_EDGE_TOLERANCE = 24, _PIXEL_EDGE_CONTRAST = 24: sized so a
#     uniform recolor as small as +16/255 is still caught (measured: CAUGHT
#     at 92.9%) while genuine 1px AA jitter at real glyph edges still
#     passes (measured: 0% on 5 real same-tree captures).
# Verified on the real reproduction pair plus synthetic attacks (see
# tests/test_site_visual_proof_pixel_diff_teeth.py, which pins these
# numbers): bottom-third-of-footer deletion CAUGHT (3.7%, was 0.073%
# SILENT under round 1), uniform recolor +16 CAUGHT (92.9%, was 0.000%
# SILENT up to +32 under round 1), a 2px vertical shift CAUGHT (3.0%, was
# SILENT up to 6px under round 1), a 1px shift (true AA-scale jitter) still
# PASSES (0.07%).
_PIXEL_STRICT_TOLERANCE = 8
_PIXEL_AA_NEIGHBORHOOD_RADIUS = 1
_PIXEL_EDGE_TOLERANCE = 24
_PIXEL_EDGE_CONTRAST = 24


def _normalize(path: str) -> str:
    return str(path or "").strip().replace("\\", "/")


def _rel_to_root(path: Path) -> str:
    return _normalize(str(path.resolve().relative_to(ROOT.resolve())))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _run(command: Sequence[str], *, cwd: Path) -> None:
    proc = subprocess.run(
        list(command),
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0:
        return
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    detail = "\n".join(part for part in (out, err) if part)
    if detail:
        raise RuntimeError(f"command failed ({' '.join(command)}):\n{detail}")
    raise RuntimeError(f"command failed ({' '.join(command)})")


def _run_git(args: Sequence[str]) -> list[str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"git {' '.join(args)} failed")
    lines: list[str] = []
    for raw in proc.stdout.splitlines():
        path = _normalize(raw)
        if path:
            lines.append(path)
    return lines


def _local_changed_paths() -> list[str]:
    paths = set(_run_git(["diff", "--name-only"]))
    paths.update(_run_git(["diff", "--name-only", "--cached"]))
    paths.update(_run_git(["ls-files", "--others", "--exclude-standard"]))
    return sorted(paths)


def _ui_paths(paths: list[str]) -> list[str]:
    prefixes = ("apps/site/src/app/", "apps/site/src/components/")
    suffixes = (".css", ".scss", ".ts", ".tsx", ".js", ".jsx")
    out: list[str] = []
    for raw in paths:
        p = _normalize(raw)
        if not p:
            continue
        if not any(p.startswith(prefix) for prefix in prefixes):
            continue
        if not p.lower().endswith(suffixes):
            continue
        out.append(p)
    return sorted(set(out))


def _runtime_verify_command(*, skip_build: bool, host: str, port: int, timeout_ms: int) -> list[str]:
    command = [
        "node",
        str(ROOT / "scripts" / "verify_site_visual_runtime.mjs"),
        "--host",
        host,
        "--port",
        str(port),
        "--timeout-ms",
        str(timeout_ms),
        "--output-dir",
        str(OUTPUT_DIR),
        "--report",
        str(RUNTIME_REPORT_OUTPUT),
    ]
    if skip_build:
        command.append("--skip-build")
    return command


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _copy_required_screenshots(runtime_report: dict[str, Any]) -> dict[str, dict[str, str]]:
    shots = runtime_report.get("screenshots")
    if not isinstance(shots, dict):
        raise RuntimeError("runtime report is missing screenshots object")

    PROOF_SHOTS_DIR.mkdir(parents=True, exist_ok=True)
    mapping = {
        "full_page": PROOF_SHOTS_DIR / "full-page.png",
        "footer_focus": PROOF_SHOTS_DIR / "footer-focus.png",
    }
    out: dict[str, dict[str, str]] = {}
    for key, dest in mapping.items():
        raw = _normalize(str(shots.get(key) or ""))
        if not raw:
            raise RuntimeError(f"runtime report missing screenshots.{key}")
        src = (ROOT / raw).resolve()
        if not src.exists():
            raise RuntimeError(f"runtime screenshot not found: {raw}")
        shutil.copy2(src, dest)
        out[key] = {
            "path": _rel_to_root(dest),
            "sha256": _sha256(dest),
        }
    return out


def _local_contrast(arr: np.ndarray, radius: int) -> np.ndarray:
    """Max-min spread over a (2*radius+1)-square window, per pixel, maxed
    across channels: a proxy for "this pixel sits on or next to a real
    edge" (glyph stroke, border, high-contrast boundary) versus "this pixel
    is inside a flat fill/gradient"."""
    lo = arr.copy()
    hi = arr.copy()
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            if dy == 0 and dx == 0:
                continue
            shifted = np.roll(np.roll(arr, dy, axis=0), dx, axis=1)
            lo = np.minimum(lo, shifted)
            hi = np.maximum(hi, shifted)
    return np.max(hi - lo, axis=2)


def _directional_mismatch(src: np.ndarray, dst: np.ndarray, *, radius: int) -> np.ndarray:
    """For every src pixel: does it have an acceptable match in dst? A pixel
    passes if it is within _PIXEL_STRICT_TOLERANCE of the SAME coordinate in
    dst, or -- only if src or dst shows real local contrast there (a
    plausible anti-aliased edge) -- within _PIXEL_EDGE_TOLERANCE of its best
    match anywhere in the `radius` neighbourhood. Returns a boolean mismatch
    mask indexed like src (True = no acceptable match found).

    Deliberately one-directional: content REMOVED from dst relative to src
    only shows up by calling this twice with src/dst swapped and taking the
    union (see _pixel_diff_stats) -- a src pixel with real content always
    has *something* nearby in a same-content dst, but calling this the other
    way round asks the opposite direction's own question ("does removed
    content have a match in the pixel-poorer image?") and fails it there
    instead.
    """
    exact_diff = np.max(np.abs(src - dst), axis=2)
    near_edge = (_local_contrast(src, radius) >= _PIXEL_EDGE_CONTRAST) | (
        _local_contrast(dst, radius) >= _PIXEL_EDGE_CONTRAST
    )
    best_diff = None
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            shifted = np.roll(np.roll(dst, dy, axis=0), dx, axis=1)
            channel_diff = np.max(np.abs(src - shifted), axis=2)
            best_diff = channel_diff if best_diff is None else np.minimum(best_diff, channel_diff)
    passed = (exact_diff <= _PIXEL_STRICT_TOLERANCE) | (near_edge & (best_diff <= _PIXEL_EDGE_TOLERANCE))
    return ~passed


def _pixel_diff_stats(*, baseline_path: Path, current_path: Path, diff_out_path: Path) -> dict[str, Any]:
    with Image.open(baseline_path) as baseline_raw:
        baseline_image = baseline_raw.convert("RGB")
    with Image.open(current_path) as current_raw:
        current_image = current_raw.convert("RGB")

    size_mismatch = baseline_image.size != current_image.size
    if size_mismatch:
        target_size = (
            max(baseline_image.width, current_image.width),
            max(baseline_image.height, current_image.height),
        )
        padded_baseline = Image.new("RGB", target_size, (0, 0, 0))
        padded_current = Image.new("RGB", target_size, (0, 0, 0))
        padded_baseline.paste(baseline_image, (0, 0))
        padded_current.paste(current_image, (0, 0))
        baseline_image = padded_baseline
        current_image = padded_current

    baseline_arr = np.asarray(baseline_image, dtype=np.int16)
    current_arr = np.asarray(current_image, dtype=np.int16)
    radius = _PIXEL_AA_NEIGHBORHOOD_RADIUS

    # Symmetric (Chamfer-style) comparison: a pixel counts as changed if
    # EITHER direction fails to find an acceptable match. current-vs-baseline
    # alone catches ADDITIONS but is structurally blind to DELETIONS (a
    # background pixel where content used to be always finds background
    # nearby); baseline-vs-current alone would be blind the other way. The
    # union closes both.
    forward_mismatch = _directional_mismatch(current_arr, baseline_arr, radius=radius)
    backward_mismatch = _directional_mismatch(baseline_arr, current_arr, radius=radius)
    changed_mask = forward_mismatch | backward_mismatch

    total_pixels = int(changed_mask.size)
    changed_pixels = int(np.count_nonzero(changed_mask))
    diff_ratio = (changed_pixels / total_pixels) if total_pixels else 0.0

    # Persist an overlay-style diff that highlights changed pixels in red.
    mask = Image.fromarray((changed_mask.astype(np.uint8) * 255), mode="L")
    overlay = Image.new("RGBA", current_image.size, (255, 48, 48, 188))
    preview = baseline_image.convert("RGBA")
    preview.paste(overlay, (0, 0), mask)
    diff_out_path.parent.mkdir(parents=True, exist_ok=True)
    preview.save(diff_out_path)

    return {
        "changed_pixels": changed_pixels,
        "total_pixels": total_pixels,
        "diff_ratio": float(diff_ratio),
        "size_mismatch": bool(size_mismatch),
        "width": int(current_image.width),
        "height": int(current_image.height),
    }


def _apply_pixel_diff_gate(
    runtime_report: dict[str, Any],
    screenshots: dict[str, dict[str, str]],
    *,
    init_pixel_baseline: bool,
    threshold_ratio: float,
) -> None:
    mapping = {
        "full_page": "full-page.png",
        "footer_focus": "footer-focus.png",
    }
    PROOF_BASELINES_DIR.mkdir(parents=True, exist_ok=True)
    PROOF_DIFFS_DIR.mkdir(parents=True, exist_ok=True)

    if init_pixel_baseline:
        for key, filename in mapping.items():
            current_rel = screenshots.get(key, {}).get("path")
            if not current_rel:
                raise RuntimeError(f"missing screenshots.{key}.path for baseline init")
            current_abs = (ROOT / _normalize(str(current_rel))).resolve()
            baseline_abs = (PROOF_BASELINES_DIR / filename).resolve()
            shutil.copy2(current_abs, baseline_abs)

    metrics = runtime_report.get("metrics")
    assertions = runtime_report.get("assertions")
    if not isinstance(metrics, dict):
        raise RuntimeError("runtime report missing metrics object")
    if not isinstance(assertions, dict):
        raise RuntimeError("runtime report missing assertions object")

    comparisons: dict[str, Any] = {}
    max_ratio = 0.0
    size_mismatch_count = 0
    for key, filename in mapping.items():
        current_rel = screenshots.get(key, {}).get("path")
        if not current_rel:
            raise RuntimeError(f"missing screenshots.{key}.path for pixel diff gate")
        current_abs = (ROOT / _normalize(str(current_rel))).resolve()
        baseline_abs = (PROOF_BASELINES_DIR / filename).resolve()
        if not baseline_abs.exists():
            raise RuntimeError(
                f"pixel baseline is missing: {_rel_to_root(baseline_abs)} (run refresh with --init-pixel-baseline once)"
            )
        diff_abs = (PROOF_DIFFS_DIR / f"{Path(filename).stem}-diff.png").resolve()
        stats = _pixel_diff_stats(
            baseline_path=baseline_abs,
            current_path=current_abs,
            diff_out_path=diff_abs,
        )
        comparisons[key] = {
            **stats,
            "baseline_path": _rel_to_root(baseline_abs),
            "current_path": _rel_to_root(current_abs),
            "diff_path": _rel_to_root(diff_abs),
            "baseline_sha256": _sha256(baseline_abs),
            "current_sha256": _sha256(current_abs),
            "diff_sha256": _sha256(diff_abs),
        }
        max_ratio = max(max_ratio, float(stats["diff_ratio"]))
        if bool(stats["size_mismatch"]):
            size_mismatch_count += 1

    metrics["pixel_diff_threshold_ratio"] = float(threshold_ratio)
    metrics["pixel_diff_full_page_ratio"] = float(comparisons["full_page"]["diff_ratio"])
    metrics["pixel_diff_footer_focus_ratio"] = float(comparisons["footer_focus"]["diff_ratio"])
    metrics["pixel_diff_max_ratio"] = float(max_ratio)
    metrics["pixel_diff_size_mismatch_count"] = int(size_mismatch_count)
    assertions["pixel_diff_within_threshold"] = max_ratio <= float(threshold_ratio) and size_mismatch_count == 0

    runtime_report["pixel_diff"] = {
        "threshold_ratio": float(threshold_ratio),
        "comparisons": comparisons,
    }


def _write_proof(
    runtime_report: dict[str, Any],
    screenshots: dict[str, dict[str, str]],
    *,
    command: Sequence[str],
) -> dict[str, Any]:
    metrics = runtime_report.get("metrics")
    assertions = runtime_report.get("assertions")
    target_url = str(runtime_report.get("target_url") or "").strip()
    if not isinstance(metrics, dict):
        raise RuntimeError("runtime report missing metrics object")
    if not isinstance(assertions, dict):
        raise RuntimeError("runtime report missing assertions object")
    if not target_url:
        raise RuntimeError("runtime report missing target_url")

    PROOF_DIR.mkdir(parents=True, exist_ok=True)
    PROOF_RUNTIME_REPORT.write_text(
        f"{json.dumps(runtime_report, ensure_ascii=False, indent=2)}\n",
        encoding="utf-8",
    )

    changed = _local_changed_paths()
    payload = {
        "rule_version": 2,
        "captured_at_utc": str(runtime_report.get("captured_at_utc") or datetime.now(timezone.utc).isoformat()),
        "target_url": target_url,
        "generator": {
            "script": "scripts/refresh_site_visual_proof.py",
            "runtime_verifier": "scripts/verify_site_visual_runtime.mjs",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        },
        "git": {
            "head_sha": _run_git(["rev-parse", "HEAD"])[0],
            "ui_changed_paths": _ui_paths(changed),
        },
        "runtime_report": {
            "path": _rel_to_root(PROOF_RUNTIME_REPORT),
            "sha256": _sha256(PROOF_RUNTIME_REPORT),
        },
        "screenshots": screenshots,
        "metrics": metrics,
        "assertions": assertions,
        "commands": [" ".join(command), "python scripts/forge/gates/site_visual_proof.py"],
    }

    PROOF_FILE.write_text(f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n", encoding="utf-8")
    return payload


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Refresh apps/site visual proof bundle from runtime verification output.",
    )
    parser.add_argument("--skip-build", action="store_true", help="Skip Next.js build before runtime verify.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=3108)
    parser.add_argument("--timeout-ms", type=int, default=180000)
    parser.add_argument(
        "--pixel-threshold-ratio",
        type=float,
        default=DEFAULT_PIXEL_DIFF_THRESHOLD_RATIO,
        help="Maximum allowed changed-pixel ratio per screenshot.",
    )
    parser.add_argument(
        "--init-pixel-baseline",
        action="store_true",
        help="Seed apps/site/verification/baselines from the current screenshots.",
    )
    parser.add_argument("--no-post-check", action="store_true", help="Skip running site_visual_proof gate at end.")
    args = parser.parse_args(argv)

    verify_command = _runtime_verify_command(
        skip_build=bool(args.skip_build),
        host=str(args.host),
        port=int(args.port),
        timeout_ms=int(args.timeout_ms),
    )
    _run(verify_command, cwd=ROOT)

    if not RUNTIME_REPORT_OUTPUT.exists():
        raise RuntimeError(f"runtime report not found: {_rel_to_root(RUNTIME_REPORT_OUTPUT)}")
    runtime_report = _load_json(RUNTIME_REPORT_OUTPUT)
    if not isinstance(runtime_report, dict):
        raise RuntimeError("runtime report must be a JSON object")

    screenshots = _copy_required_screenshots(runtime_report)
    _apply_pixel_diff_gate(
        runtime_report,
        screenshots,
        init_pixel_baseline=bool(args.init_pixel_baseline),
        threshold_ratio=float(args.pixel_threshold_ratio),
    )
    payload = _write_proof(runtime_report, screenshots, command=verify_command)

    if not args.no_post_check:
        _run([sys.executable, "scripts/forge/gates/site_visual_proof.py"], cwd=ROOT)

    print("Site visual proof refresh: PASS")
    print(f"- proof file: {_rel_to_root(PROOF_FILE)}")
    print(f"- runtime report: {_rel_to_root(PROOF_RUNTIME_REPORT)}")
    for key in ("full_page", "footer_focus"):
        shot = payload["screenshots"][key]
        print(f"- screenshot {key}: {shot['path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
