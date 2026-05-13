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

from PIL import Image, ImageChops

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


def _pixel_diff_stats(*, baseline_path: Path, current_path: Path, diff_out_path: Path) -> dict[str, Any]:
    with Image.open(baseline_path) as baseline_raw:
        baseline_image = baseline_raw.convert("RGBA")
    with Image.open(current_path) as current_raw:
        current_image = current_raw.convert("RGBA")

    size_mismatch = baseline_image.size != current_image.size
    if size_mismatch:
        target_size = (
            max(baseline_image.width, current_image.width),
            max(baseline_image.height, current_image.height),
        )
        padded_baseline = Image.new("RGBA", target_size, (0, 0, 0, 0))
        padded_current = Image.new("RGBA", target_size, (0, 0, 0, 0))
        padded_baseline.paste(baseline_image, (0, 0))
        padded_current.paste(current_image, (0, 0))
        baseline_image = padded_baseline
        current_image = padded_current

    diff_image = ImageChops.difference(current_image, baseline_image)
    total_pixels = diff_image.width * diff_image.height
    changed_pixels = 0
    if total_pixels > 0:
        raw = memoryview(diff_image.tobytes())
        for idx in range(0, len(raw), 4):
            if raw[idx] or raw[idx + 1] or raw[idx + 2] or raw[idx + 3]:
                changed_pixels += 1

    diff_ratio = (changed_pixels / total_pixels) if total_pixels else 0.0

    # Persist an overlay-style diff that highlights changed pixels in red.
    mask = diff_image.convert("L").point(lambda value: 255 if value else 0)
    overlay = Image.new("RGBA", current_image.size, (255, 48, 48, 188))
    preview = baseline_image.copy()
    preview.paste(overlay, (0, 0), mask)
    diff_out_path.parent.mkdir(parents=True, exist_ok=True)
    preview.save(diff_out_path)

    return {
        "changed_pixels": int(changed_pixels),
        "total_pixels": int(total_pixels),
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
                "pixel baseline is missing: "
                f"{_rel_to_root(baseline_abs)} (run refresh with --init-pixel-baseline once)"
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
    parser.add_argument("--no-post-check", action="store_true", help="Skip running check_site_visual_proof at end.")
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
