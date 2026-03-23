from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from thomas.browser import p009_browser_artifact_screenshot as screenshot_mod
from thomas.browser.p009_browser_artifact_screenshot import (
    BrowserArtifactScreenshotError,
    BrowserArtifactScreenshotErrorCode,
    BrowserArtifactScreenshotRequest,
    take_artifact_screenshot,
)


def _write_min_png(path: Path) -> None:
    # A tiny, valid PNG header. Sufficient for "file exists" checks.
    path.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")


def test_take_artifact_screenshot_success_html(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.html"
    artifact.write_text("<html><body><h1>hello</h1></body></html>", encoding="utf-8")
    out = tmp_path / "shot.png"

    def fake_capture(**kwargs: Any) -> None:
        _write_min_png(Path(kwargs["output_path"]))

    monkeypatch.setattr(screenshot_mod, "_capture_with_playwright", fake_capture)

    req = BrowserArtifactScreenshotRequest(artifact=str(artifact), output=str(out))
    result = take_artifact_screenshot(req)

    assert Path(result.artifact_path) == artifact
    assert Path(result.screenshot_path) == out
    assert out.exists()
    assert result.renderer == "playwright"


def test_take_artifact_screenshot_success_image(tmp_path: Path) -> None:
    pytest.importorskip("PIL")
    from PIL import Image

    artifact = tmp_path / "photo.jpg"
    out = tmp_path / "photo.png"
    im = Image.new("RGB", (4, 4), (10, 20, 30))
    im.save(artifact, format="JPEG")

    req = BrowserArtifactScreenshotRequest(artifact=str(artifact), output=str(out))
    result = take_artifact_screenshot(req)

    assert Path(result.screenshot_path) == out
    assert out.exists()
    assert result.renderer == "pillow"
    assert out.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_take_artifact_screenshot_invalid_input_missing_file(tmp_path: Path) -> None:
    req = BrowserArtifactScreenshotRequest(
        artifact=str(tmp_path / "missing.html"),
        output=str(tmp_path / "out.png"),
    )

    with pytest.raises(BrowserArtifactScreenshotError) as exc:
        take_artifact_screenshot(req)

    assert exc.value.code == BrowserArtifactScreenshotErrorCode.INVALID_INPUT


def test_take_artifact_screenshot_invalid_output_extension(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.html"
    artifact.write_text("<html></html>", encoding="utf-8")

    req = BrowserArtifactScreenshotRequest(
        artifact=str(artifact),
        output=str(tmp_path / "out.jpg"),
    )

    with pytest.raises(BrowserArtifactScreenshotError) as exc:
        take_artifact_screenshot(req)

    assert exc.value.code == BrowserArtifactScreenshotErrorCode.INVALID_INPUT
    assert "must end with .png" in exc.value.message


def test_take_artifact_screenshot_missing_config_bad_artifact_root(tmp_path: Path) -> None:
    req = BrowserArtifactScreenshotRequest(
        artifact="some-id-or-relative-path.html",
        artifact_root=str(tmp_path / "does_not_exist"),
    )

    with pytest.raises(BrowserArtifactScreenshotError) as exc:
        take_artifact_screenshot(req)

    assert exc.value.code == BrowserArtifactScreenshotErrorCode.MISSING_CONFIG


def _load_cli_app() -> Any:
    import importlib

    main = importlib.import_module("thomas.cli.main")
    app = getattr(main, "app", None) or getattr(main, "cli", None)
    if app is not None:
        return app

    for fn_name in ("create_app", "build_app", "get_app"):
        fn = getattr(main, fn_name, None)
        if callable(fn):
            return fn()

    raise AssertionError("Expected thomas.cli.main to expose `app`/`cli` or a create/build function")


def test_cli_browser_artifact_screenshot_json_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.html"
    artifact.write_text("<html><body><h1>hello</h1></body></html>", encoding="utf-8")
    out = tmp_path / "shot.png"

    def fake_capture(**kwargs: Any) -> None:
        _write_min_png(Path(kwargs["output_path"]))

    monkeypatch.setattr(screenshot_mod, "_capture_with_playwright", fake_capture)

    app = _load_cli_app()

    # Ensure command is present even if the CLI loader is not used during this test.
    from thomas.cli.commands.browser import p009_browser_artifact_screenshot as cli_mod

    cli_mod.register(app)

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["browser", "artifact", "screenshot", str(artifact), "--out", str(out), "--json"],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["screenshot_path"] == str(out)
    assert out.exists()


def test_cli_browser_artifact_screenshot_json_failure(tmp_path: Path) -> None:
    app = _load_cli_app()

    from thomas.cli.commands.browser import p009_browser_artifact_screenshot as cli_mod

    cli_mod.register(app)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "browser",
            "artifact",
            "screenshot",
            str(tmp_path / "missing.html"),
            "--out",
            str(tmp_path / "out.png"),
            "--json",
        ],
    )
    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == BrowserArtifactScreenshotErrorCode.INVALID_INPUT.value
