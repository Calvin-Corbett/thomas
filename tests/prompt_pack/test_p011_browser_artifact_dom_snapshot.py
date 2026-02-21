import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from thomas.browser.p011_browser_artifact_dom_snapshot import (
    BrowserArtifactDomSnapshotInput,
    BrowserDomSnapshotError,
    browser_artifact_dom_snapshot,
)
from thomas.cli.commands.browser import p011_browser_artifact_dom_snapshot as cli_mod


class StubBrowserWithMethod:
    def dom_snapshot(self, timeout_ms: int = 0):
        return {"hello": "world", "timeout_ms": timeout_ms}


class StubPage:
    def __init__(self, html: str):
        self._html = html

    def content(self):
        return self._html


class StubBrowserWithPage:
    def __init__(self, html: str):
        self.page = StubPage(html)


def test_dom_snapshot_writes_json_artifact(tmp_path: Path):
    browser = StubBrowserWithMethod()
    req = BrowserArtifactDomSnapshotInput(artifacts_dir=str(tmp_path), base_name="test", timeout_ms=123)
    out = browser_artifact_dom_snapshot(browser, req)

    assert out.content_type == "application/json"
    assert out.capture_method == "browser_method"

    p = Path(out.artifact_path)
    assert p.exists()
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["hello"] == "world"
    assert data["timeout_ms"] == 123


def test_dom_snapshot_falls_back_to_html(tmp_path: Path):
    browser = StubBrowserWithPage("<html><body>hi</body></html>")
    req = BrowserArtifactDomSnapshotInput(artifacts_dir=str(tmp_path), prefer_cdp=False)
    out = browser_artifact_dom_snapshot(browser, req)

    assert out.content_type == "text/html"
    assert out.capture_method == "html"

    p = Path(out.artifact_path)
    assert p.suffix == ".html"
    assert "<body>hi</body>" in p.read_text(encoding="utf-8")


def test_output_path_takes_precedence(tmp_path: Path):
    browser = StubBrowserWithMethod()
    out_file = tmp_path / "snapshot-output"  # no suffix on purpose
    req = BrowserArtifactDomSnapshotInput(output_path=str(out_file))
    out = browser_artifact_dom_snapshot(browser, req)

    p = Path(out.artifact_path)
    assert p == out_file.with_suffix(".json")
    assert p.exists()


def test_missing_browser_raises_deterministic_error(tmp_path: Path):
    req = BrowserArtifactDomSnapshotInput(artifacts_dir=str(tmp_path))
    with pytest.raises(BrowserDomSnapshotError) as ei:
        browser_artifact_dom_snapshot(None, req)

    assert ei.value.code == "THOMAS_BROWSER_DOM_SNAPSHOT_MISSING_CONFIG"
    assert ei.value.category == "missing_config"


def test_invalid_input_both_output_and_dir(tmp_path: Path):
    browser = StubBrowserWithMethod()
    req = BrowserArtifactDomSnapshotInput(artifacts_dir=str(tmp_path), output_path=str(tmp_path / "x.json"))
    with pytest.raises(BrowserDomSnapshotError) as ei:
        browser_artifact_dom_snapshot(browser, req)

    assert ei.value.code == "THOMAS_BROWSER_DOM_SNAPSHOT_INVALID_INPUT"


def test_invalid_input_timeout_ms(tmp_path: Path):
    browser = StubBrowserWithMethod()
    req = BrowserArtifactDomSnapshotInput(artifacts_dir=str(tmp_path), timeout_ms=0)
    with pytest.raises(BrowserDomSnapshotError) as ei:
        browser_artifact_dom_snapshot(browser, req)

    assert ei.value.code == "THOMAS_BROWSER_DOM_SNAPSHOT_INVALID_INPUT"


def test_missing_config_no_default_artifacts_dir(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("THOMAS_ARTIFACTS_DIR", raising=False)
    monkeypatch.delenv("THOMAS_ARTIFACT_DIR", raising=False)

    browser = StubBrowserWithMethod()
    req = BrowserArtifactDomSnapshotInput(artifacts_dir=None)

    with pytest.raises(BrowserDomSnapshotError) as ei:
        browser_artifact_dom_snapshot(browser, req)

    assert ei.value.code == "THOMAS_BROWSER_DOM_SNAPSHOT_MISSING_CONFIG"


def test_cli_json_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(cli_mod, "_resolve_active_browser", lambda: StubBrowserWithMethod())

    runner = CliRunner()
    result = runner.invoke(
        cli_mod.app,
        [
            "--artifacts-dir",
            str(tmp_path),
            "--json",
        ],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout.strip())
    assert payload["ok"] is True
    assert Path(payload["artifact_path"]).exists()


def test_cli_json_failure_missing_browser(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def _boom():
        raise cli_mod.BrowserDomSnapshotError(
            code="THOMAS_BROWSER_DOM_SNAPSHOT_MISSING_CONFIG",
            category="missing_config",
            message="No browser",
        )

    monkeypatch.setattr(cli_mod, "_resolve_active_browser", _boom)

    runner = CliRunner()
    result = runner.invoke(
        cli_mod.app,
        [
            "--artifacts-dir",
            str(tmp_path),
            "--json",
        ],
    )
    assert result.exit_code != 0
    payload = json.loads(result.stdout.strip())
    assert payload["ok"] is False
    assert payload["error_code"] == "THOMAS_BROWSER_DOM_SNAPSHOT_MISSING_CONFIG"
