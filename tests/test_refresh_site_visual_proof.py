from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image

import scripts.refresh_site_visual_proof as mod


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def test_refresh_site_visual_proof_writes_strict_bundle(monkeypatch, tmp_path) -> None:
    root = tmp_path
    output_dir = root / "output" / "site-visual-proof"
    output_dir.mkdir(parents=True, exist_ok=True)
    runtime_report_output = output_dir / "runtime-report.json"
    full_src = output_dir / "full-page.png"
    footer_src = output_dir / "footer-focus.png"
    Image.new("RGBA", (64, 48), (20, 30, 40, 255)).save(full_src)
    Image.new("RGBA", (64, 48), (22, 31, 41, 255)).save(footer_src)
    runtime_report_output.write_text(
        json.dumps(
            {
                "captured_at_utc": "2026-02-23T19:05:00Z",
                "target_url": "http://127.0.0.1:3108",
                "screenshots": {
                    "full_page": "output/site-visual-proof/full-page.png",
                    "footer_focus": "output/site-visual-proof/footer-focus.png",
                },
                "metrics": {
                    "has_nav": True,
                    "has_main": True,
                    "has_footer": True,
                    "console_error_count": 0,
                    "broken_image_count": 0,
                    "pixel_diff_threshold_ratio": 0.02,
                    "pixel_diff_full_page_ratio": 0.0,
                    "pixel_diff_footer_focus_ratio": 0.0,
                    "pixel_diff_max_ratio": 0.0,
                    "pixel_diff_size_mismatch_count": 0,
                    "viewport_width": 1424,
                    "root_scroll_width": 1424,
                    "footer_top": 640,
                    "band_top": 641,
                    "band_height": 0,
                    "riders": [
                        {
                            "track_top": 610,
                            "track_bottom": 670,
                            "saddle_top": 635,
                            "saddle_bottom": 640,
                            "saddle_left": 700,
                            "saddle_right": 716,
                            "robot_top": 625,
                            "robot_bottom": 645,
                            "robot_left": 704,
                            "robot_right": 712,
                            "robot_center_x": 708,
                            "robot_width": 12,
                            "robot_height": 10,
                            "robot_body_top": 628,
                            "robot_body_bottom": 636,
                            "robot_body_left": 703,
                            "robot_body_right": 713,
                            "robot_body_center_x": 708,
                            "robot_body_width": 10,
                            "robot_body_height": 8,
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
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(mod, "ROOT", root)
    monkeypatch.setattr(mod, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(mod, "RUNTIME_REPORT_OUTPUT", runtime_report_output)
    monkeypatch.setattr(mod, "PROOF_DIR", root / "apps" / "site" / "verification")
    monkeypatch.setattr(mod, "PROOF_SHOTS_DIR", root / "apps" / "site" / "verification" / "screenshots")
    monkeypatch.setattr(mod, "PROOF_BASELINES_DIR", root / "apps" / "site" / "verification" / "baselines")
    monkeypatch.setattr(mod, "PROOF_DIFFS_DIR", root / "apps" / "site" / "verification" / "diffs")
    monkeypatch.setattr(mod, "PROOF_FILE", root / "apps" / "site" / "verification" / "ui-proof.json")
    monkeypatch.setattr(mod, "PROOF_RUNTIME_REPORT", root / "apps" / "site" / "verification" / "runtime-report.json")
    monkeypatch.setattr(mod, "_run", lambda command, cwd: None)

    def _fake_git(args: list[str]) -> list[str]:
        if args == ["rev-parse", "HEAD"]:
            return ["abc1234"]
        if args == ["diff", "--name-only"]:
            return ["apps/site/src/components/dino-riders.tsx"]
        if args == ["diff", "--name-only", "--cached"]:
            return []
        if args == ["ls-files", "--others", "--exclude-standard"]:
            return []
        raise AssertionError(f"unexpected git args: {args}")

    monkeypatch.setattr(mod, "_run_git", _fake_git)

    rc = mod.run(["--skip-build", "--init-pixel-baseline"])
    assert rc == 0

    proof_path = root / "apps" / "site" / "verification" / "ui-proof.json"
    payload = json.loads(proof_path.read_text(encoding="utf-8"))
    assert payload["rule_version"] == 2
    assert payload["generator"]["script"] == "scripts/refresh_site_visual_proof.py"
    assert payload["generator"]["runtime_verifier"] == "scripts/verify_site_visual_runtime.mjs"
    assert payload["git"]["head_sha"] == "abc1234"
    assert payload["git"]["ui_changed_paths"] == ["apps/site/src/components/dino-riders.tsx"]
    assert payload["runtime_report"]["path"] == "apps/site/verification/runtime-report.json"
    assert payload["runtime_report"]["sha256"] == _sha256(
        root / "apps" / "site" / "verification" / "runtime-report.json"
    )
    assert payload["screenshots"]["full_page"]["path"] == "apps/site/verification/screenshots/full-page.png"
    assert payload["screenshots"]["footer_focus"]["path"] == "apps/site/verification/screenshots/footer-focus.png"
    assert payload["screenshots"]["full_page"]["sha256"] == _sha256(
        root / "apps" / "site" / "verification" / "screenshots" / "full-page.png"
    )
    assert payload["screenshots"]["footer_focus"]["sha256"] == _sha256(
        root / "apps" / "site" / "verification" / "screenshots" / "footer-focus.png"
    )
    assert payload["assertions"]["pixel_diff_within_threshold"] is True
    assert payload["metrics"]["pixel_diff_max_ratio"] == 0.0
    assert (root / "apps" / "site" / "verification" / "baselines" / "full-page.png").exists()
    assert (root / "apps" / "site" / "verification" / "baselines" / "footer-focus.png").exists()
