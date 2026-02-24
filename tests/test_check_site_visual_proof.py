from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import scripts.check_site_visual_proof as mod


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _write_proof(
    repo_root: Path,
    *,
    ui_changed_paths: list[str],
    robot_top: float = 632.0,
    robot_bottom: float = 649.0,
    robot_width: float = 12.0,
    robot_height: float = 10.0,
    robot_body_top: float | None = None,
    robot_body_bottom: float | None = None,
    robot_body_center_x: float | None = None,
    robot_body_half_width: float = 5.0,
    saddle_top: float = 636.0,
    saddle_left: float = 700.0,
    saddle_right: float = 716.0,
    robot_center_x: float = 708.0,
    pixel_diff_threshold_ratio: float = 0.02,
    pixel_diff_full_page_ratio: float = 0.0,
    pixel_diff_footer_focus_ratio: float = 0.0,
    pixel_diff_max_ratio: float = 0.0,
    pixel_diff_size_mismatch_count: float = 0.0,
) -> None:
    if robot_body_top is None:
        robot_body_top = robot_top + 3.0
    if robot_body_bottom is None:
        robot_body_bottom = robot_body_top + 8.0
    if robot_body_center_x is None:
        robot_body_center_x = robot_center_x

    screenshots_dir = repo_root / "apps" / "site" / "verification" / "screenshots"
    baselines_dir = repo_root / "apps" / "site" / "verification" / "baselines"
    diffs_dir = repo_root / "apps" / "site" / "verification" / "diffs"
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    baselines_dir.mkdir(parents=True, exist_ok=True)
    diffs_dir.mkdir(parents=True, exist_ok=True)
    full_page = screenshots_dir / "full-page.png"
    footer_focus = screenshots_dir / "footer-focus.png"
    full_page.write_bytes(b"\x89PNG\r\n\x1a\nproof-full")
    footer_focus.write_bytes(b"\x89PNG\r\n\x1a\nproof-footer")
    baseline_full_page = baselines_dir / "full-page.png"
    baseline_footer_focus = baselines_dir / "footer-focus.png"
    diff_full_page = diffs_dir / "full-page-diff.png"
    diff_footer_focus = diffs_dir / "footer-focus-diff.png"
    baseline_full_page.write_bytes(full_page.read_bytes())
    baseline_footer_focus.write_bytes(footer_focus.read_bytes())
    diff_full_page.write_bytes(b"\x89PNG\r\n\x1a\ndiff-full")
    diff_footer_focus.write_bytes(b"\x89PNG\r\n\x1a\ndiff-footer")

    runtime_report_path = repo_root / "apps" / "site" / "verification" / "runtime-report.json"
    runtime_report_path.parent.mkdir(parents=True, exist_ok=True)
    runtime_report_payload = {
        "captured_at_utc": "2026-02-23T16:34:16Z",
        "target_url": "https://thomas-site.thomasdevhub.workers.dev/",
                "metrics": {
                    "has_nav": True,
                    "has_main": True,
                    "has_footer": True,
                    "console_error_count": 0,
                    "broken_image_count": 0,
                    "pixel_diff_threshold_ratio": pixel_diff_threshold_ratio,
                    "pixel_diff_full_page_ratio": pixel_diff_full_page_ratio,
                    "pixel_diff_footer_focus_ratio": pixel_diff_footer_focus_ratio,
                    "pixel_diff_max_ratio": pixel_diff_max_ratio,
                    "pixel_diff_size_mismatch_count": pixel_diff_size_mismatch_count,
                    "viewport_width": 1424,
                    "root_scroll_width": 1424,
                    "footer_top": 640,
            "band_top": 641,
            "band_height": 0,
            "riders": [
                {
                    "track_top": 616,
                    "track_bottom": 672,
                    "sprite_bottom": 672,
                    "saddle_top": saddle_top,
                    "saddle_bottom": saddle_top + 5,
                    "saddle_left": saddle_left,
                    "saddle_right": saddle_right,
                    "robot_top": robot_top,
                    "robot_bottom": robot_bottom,
                    "robot_left": robot_center_x - 4,
                    "robot_right": robot_center_x + 4,
                    "robot_center_x": robot_center_x,
                    "robot_width": robot_width,
                    "robot_height": robot_height,
                    "robot_body_top": robot_body_top,
                    "robot_body_bottom": robot_body_bottom,
                    "robot_body_left": robot_body_center_x - robot_body_half_width,
                    "robot_body_right": robot_body_center_x + robot_body_half_width,
                    "robot_body_center_x": robot_body_center_x,
                    "robot_body_width": robot_body_half_width * 2,
                    "robot_body_height": robot_body_bottom - robot_body_top,
                }
            ],
        },
        "assertions": {
            "core_layout_present": True,
            "no_console_runtime_errors": True,
            "no_broken_images": True,
            "pixel_diff_within_threshold": True,
            "band_on_footer_border": True,
            "no_band_strip_height": True,
            "riders_mounted_on_back": True,
            "riders_seat_contact_stable": True,
            "riders_centered_on_saddle": True,
            "riders_robot_clearly_visible": True,
            "no_horizontal_drag_overflow": True,
        },
        "pixel_diff": {
            "threshold_ratio": pixel_diff_threshold_ratio,
            "comparisons": {
                "full_page": {
                    "changed_pixels": 0,
                    "total_pixels": 1,
                    "diff_ratio": pixel_diff_full_page_ratio,
                    "size_mismatch": False,
                    "width": 1,
                    "height": 1,
                    "baseline_path": "apps/site/verification/baselines/full-page.png",
                    "current_path": "apps/site/verification/screenshots/full-page.png",
                    "diff_path": "apps/site/verification/diffs/full-page-diff.png",
                    "baseline_sha256": _sha256(baseline_full_page),
                    "current_sha256": _sha256(full_page),
                    "diff_sha256": _sha256(diff_full_page),
                },
                "footer_focus": {
                    "changed_pixels": 0,
                    "total_pixels": 1,
                    "diff_ratio": pixel_diff_footer_focus_ratio,
                    "size_mismatch": False,
                    "width": 1,
                    "height": 1,
                    "baseline_path": "apps/site/verification/baselines/footer-focus.png",
                    "current_path": "apps/site/verification/screenshots/footer-focus.png",
                    "diff_path": "apps/site/verification/diffs/footer-focus-diff.png",
                    "baseline_sha256": _sha256(baseline_footer_focus),
                    "current_sha256": _sha256(footer_focus),
                    "diff_sha256": _sha256(diff_footer_focus),
                },
            },
        },
    }
    runtime_report_path.write_text(json.dumps(runtime_report_payload, indent=2), encoding="utf-8")

    payload = {
        "rule_version": 2,
        "captured_at_utc": "2026-02-23T16:34:16Z",
        "target_url": "https://thomas-site.thomasdevhub.workers.dev/",
        "generator": {
            "script": "scripts/refresh_site_visual_proof.py",
            "runtime_verifier": "scripts/verify_site_visual_runtime.mjs",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        },
        "git": {
            "head_sha": "a1b2c3d4",
            "ui_changed_paths": ui_changed_paths,
        },
        "runtime_report": {
            "path": "apps/site/verification/runtime-report.json",
            "sha256": _sha256(runtime_report_path),
        },
        "screenshots": {
            "full_page": {
                "path": "apps/site/verification/screenshots/full-page.png",
                "sha256": _sha256(full_page),
            },
            "footer_focus": {
                "path": "apps/site/verification/screenshots/footer-focus.png",
                "sha256": _sha256(footer_focus),
            },
        },
        "metrics": runtime_report_payload["metrics"],
        "assertions": runtime_report_payload["assertions"],
    }
    proof_path = repo_root / "apps" / "site" / "verification" / "ui-proof.json"
    proof_path.parent.mkdir(parents=True, exist_ok=True)
    proof_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_site_visual_proof_gate_passes_when_no_ui_changes(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(mod, "_git_local_changed_paths", lambda _repo: ["README.md"])
    rc = mod.run(["--repo-root", str(tmp_path)])
    out = capsys.readouterr().out

    assert rc == 0
    assert "PASS (no website UI changes detected)" in out


def test_site_visual_proof_gate_fails_when_ui_changes_without_proof(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(mod, "_git_local_changed_paths", lambda _repo: ["apps/site/src/app/page.tsx"])
    rc = mod.run(["--repo-root", str(tmp_path)])
    out = capsys.readouterr().out

    assert rc == 1
    assert "missing required proof file: apps/site/verification/ui-proof.json" in out


def test_site_visual_proof_gate_passes_with_valid_proof_bundle(monkeypatch, tmp_path, capsys) -> None:
    ui_file = "apps/site/src/app/page.tsx"
    _write_proof(tmp_path, ui_changed_paths=[ui_file])
    changed = [
        ui_file,
        "apps/site/verification/ui-proof.json",
        "apps/site/verification/screenshots/full-page.png",
        "apps/site/verification/screenshots/footer-focus.png",
        "apps/site/verification/runtime-report.json",
    ]
    monkeypatch.setattr(mod, "_git_local_changed_paths", lambda _repo: changed)

    rc = mod.run(["--repo-root", str(tmp_path)])
    out = capsys.readouterr().out

    assert rc == 0
    assert "Site visual proof gate: PASS" in out


def test_site_visual_proof_gate_fails_mount_check(monkeypatch, tmp_path, capsys) -> None:
    ui_file = "apps/site/src/components/footer.tsx"
    _write_proof(
        tmp_path,
        ui_changed_paths=[ui_file],
        robot_body_top=648.0,
        saddle_top=633.0,
    )
    changed = [
        ui_file,
        "apps/site/verification/ui-proof.json",
        "apps/site/verification/screenshots/full-page.png",
        "apps/site/verification/screenshots/footer-focus.png",
        "apps/site/verification/runtime-report.json",
    ]
    monkeypatch.setattr(mod, "_git_local_changed_paths", lambda _repo: changed)

    rc = mod.run(["--repo-root", str(tmp_path)])
    out = capsys.readouterr().out

    assert rc == 1
    assert "mount check failed" in out


def test_site_visual_proof_gate_fails_seat_contact_check(monkeypatch, tmp_path, capsys) -> None:
    ui_file = "apps/site/src/components/footer.tsx"
    _write_proof(
        tmp_path,
        ui_changed_paths=[ui_file],
        saddle_top=633.0,
        robot_body_top=625.0,
        robot_body_bottom=654.0,
    )
    changed = [
        ui_file,
        "apps/site/verification/ui-proof.json",
        "apps/site/verification/screenshots/full-page.png",
        "apps/site/verification/screenshots/footer-focus.png",
        "apps/site/verification/runtime-report.json",
    ]
    monkeypatch.setattr(mod, "_git_local_changed_paths", lambda _repo: changed)

    rc = mod.run(["--repo-root", str(tmp_path)])
    out = capsys.readouterr().out

    assert rc == 1
    assert "seat contact failed" in out


def test_site_visual_proof_gate_fails_horizontal_mount_check(monkeypatch, tmp_path, capsys) -> None:
    ui_file = "apps/site/src/components/footer.tsx"
    _write_proof(
        tmp_path,
        ui_changed_paths=[ui_file],
        saddle_left=700.0,
        saddle_right=716.0,
        robot_body_center_x=730.0,
    )
    changed = [
        ui_file,
        "apps/site/verification/ui-proof.json",
        "apps/site/verification/screenshots/full-page.png",
        "apps/site/verification/screenshots/footer-focus.png",
        "apps/site/verification/runtime-report.json",
    ]
    monkeypatch.setattr(mod, "_git_local_changed_paths", lambda _repo: changed)

    rc = mod.run(["--repo-root", str(tmp_path)])
    out = capsys.readouterr().out

    assert rc == 1
    assert "horizontal mount failed" in out


def test_site_visual_proof_gate_fails_robot_visibility_check(monkeypatch, tmp_path, capsys) -> None:
    ui_file = "apps/site/src/components/footer.tsx"
    _write_proof(
        tmp_path,
        ui_changed_paths=[ui_file],
        robot_width=6.0,
        robot_height=6.0,
    )
    changed = [
        ui_file,
        "apps/site/verification/ui-proof.json",
        "apps/site/verification/screenshots/full-page.png",
        "apps/site/verification/screenshots/footer-focus.png",
        "apps/site/verification/runtime-report.json",
    ]
    monkeypatch.setattr(mod, "_git_local_changed_paths", lambda _repo: changed)

    rc = mod.run(["--repo-root", str(tmp_path)])
    out = capsys.readouterr().out

    assert rc == 1
    assert "visibility failed: robot_width" in out


def test_site_visual_proof_gate_fails_pixel_diff_threshold(monkeypatch, tmp_path, capsys) -> None:
    ui_file = "apps/site/src/components/footer.tsx"
    _write_proof(
        tmp_path,
        ui_changed_paths=[ui_file],
        pixel_diff_threshold_ratio=0.02,
        pixel_diff_full_page_ratio=0.03,
        pixel_diff_footer_focus_ratio=0.01,
        pixel_diff_max_ratio=0.03,
    )
    changed = [
        ui_file,
        "apps/site/verification/ui-proof.json",
        "apps/site/verification/screenshots/full-page.png",
        "apps/site/verification/screenshots/footer-focus.png",
        "apps/site/verification/runtime-report.json",
    ]
    monkeypatch.setattr(mod, "_git_local_changed_paths", lambda _repo: changed)

    rc = mod.run(["--repo-root", str(tmp_path)])
    out = capsys.readouterr().out

    assert rc == 1
    assert "pixel diff threshold failed" in out


def test_site_visual_proof_gate_fails_screenshot_hash_mismatch(monkeypatch, tmp_path, capsys) -> None:
    ui_file = "apps/site/src/components/dino-riders.tsx"
    _write_proof(tmp_path, ui_changed_paths=[ui_file])
    full_page = tmp_path / "apps" / "site" / "verification" / "screenshots" / "full-page.png"
    full_page.write_bytes(b"\x89PNG\r\n\x1a\ntampered")

    changed = [
        ui_file,
        "apps/site/verification/ui-proof.json",
        "apps/site/verification/screenshots/full-page.png",
        "apps/site/verification/screenshots/footer-focus.png",
        "apps/site/verification/runtime-report.json",
    ]
    monkeypatch.setattr(mod, "_git_local_changed_paths", lambda _repo: changed)

    rc = mod.run(["--repo-root", str(tmp_path)])
    out = capsys.readouterr().out

    assert rc == 1
    assert "screenshots.full_page.sha256 mismatch" in out


def test_site_visual_proof_gate_fails_when_git_ui_paths_stale(monkeypatch, tmp_path, capsys) -> None:
    _write_proof(tmp_path, ui_changed_paths=["apps/site/src/app/page.tsx"])
    changed = [
        "apps/site/src/components/dino-riders.tsx",
        "apps/site/verification/ui-proof.json",
        "apps/site/verification/screenshots/full-page.png",
        "apps/site/verification/screenshots/footer-focus.png",
        "apps/site/verification/runtime-report.json",
    ]
    monkeypatch.setattr(mod, "_git_local_changed_paths", lambda _repo: changed)

    rc = mod.run(["--repo-root", str(tmp_path)])
    out = capsys.readouterr().out

    assert rc == 1
    assert "git.ui_changed_paths is missing detected UI change(s)" in out
