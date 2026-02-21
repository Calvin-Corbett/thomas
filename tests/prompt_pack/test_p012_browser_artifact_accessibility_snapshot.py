from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import pytest

from thomas.browser.p012_browser_artifact_accessibility_snapshot import (
    AccessibilitySnapshotRequest,
    BrowserArtifactError,
    capture_accessibility_snapshot_artifact,
)


class _StubPage:
    def __init__(self, snap: Mapping[str, Any] | None = None, *, raise_exc: Exception | None = None):
        self._snap = snap or {"role": "WebArea", "name": "stub", "children": []}
        self._raise_exc = raise_exc

    def accessibility_snapshot(self, *, root: Any | None = None, interesting_only: bool = True) -> Mapping[str, Any]:
        if self._raise_exc is not None:
            raise self._raise_exc
        # Prove we threaded the args through.
        assert interesting_only is True
        assert root is None
        return self._snap


def test_capture_accessibility_snapshot_writes_artifact(tmp_path: Path) -> None:
    req = AccessibilitySnapshotRequest(source=_StubPage(), artifact_dir=tmp_path, artifact_name="ax")

    result = capture_accessibility_snapshot_artifact(req)

    assert result.artifact_path.exists()
    assert result.artifact_path.name == "ax.json"

    payload = json.loads(result.artifact_path.read_text(encoding="utf-8"))
    assert payload["type"] == "accessibility_snapshot"
    assert payload["snapshot"]["role"] == "WebArea"
    assert payload["schema_version"] == 1


def test_missing_artifact_dir_is_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("THOMAS_ARTIFACT_DIR", raising=False)

    req = AccessibilitySnapshotRequest(source=_StubPage(), artifact_dir=None)

    with pytest.raises(BrowserArtifactError) as ei:
        capture_accessibility_snapshot_artifact(req)

    err = ei.value
    assert err.code == "missing_config"


def test_invalid_source_is_deterministic(tmp_path: Path) -> None:
    req = AccessibilitySnapshotRequest(source=object(), artifact_dir=tmp_path)

    with pytest.raises(BrowserArtifactError) as ei:
        capture_accessibility_snapshot_artifact(req)

    assert ei.value.code == "invalid_input"


def test_external_failure_is_deterministic(tmp_path: Path) -> None:
    req = AccessibilitySnapshotRequest(
        source=_StubPage(raise_exc=RuntimeError("boom")),
        artifact_dir=tmp_path,
    )

    with pytest.raises(BrowserArtifactError) as ei:
        capture_accessibility_snapshot_artifact(req)

    assert ei.value.code == "external_failure"


def test_cli_json_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    from thomas.cli.commands.browser import p012_browser_artifact_accessibility_snapshot as cli_mod

    monkeypatch.setattr(cli_mod, "_resolve_browser_source", lambda: _StubPage())

    code = cli_mod.run_accessibility_snapshot(
        artifact_dir=tmp_path,
        name="ax_cli",
        interesting_only=True,
        json_mode=True,
    )
    assert code == 0

    out = capsys.readouterr().out.strip()
    payload = json.loads(out)

    assert payload["ok"] is True
    assert payload["artifact_path"].endswith("ax_cli.json")
    assert Path(payload["artifact_path"]).exists()
    assert payload["snapshot"]["role"] == "WebArea"


def test_cli_json_missing_config_exit_code(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    from thomas.cli.commands.browser import p012_browser_artifact_accessibility_snapshot as cli_mod

    def _boom() -> Any:
        raise BrowserArtifactError("missing_config", "no browser")

    monkeypatch.setattr(cli_mod, "_resolve_browser_source", _boom)

    code = cli_mod.run_accessibility_snapshot(
        artifact_dir=None,
        name="ax",
        interesting_only=True,
        json_mode=True,
    )
    assert code == 3

    out = capsys.readouterr().out.strip()
    payload = json.loads(out)

    assert payload["ok"] is False
    assert payload["error"]["code"] == "missing_config"
