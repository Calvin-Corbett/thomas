from __future__ import annotations

import base64
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

pytest.importorskip("thomas")
pytest.importorskip("reportlab")

from thomas.browser.p010_browser_artifact_pdf_export import (
    ArtifactNoImagesError,
    ArtifactNotFoundError,
    BrowserArtifactPdfExportRequest,
    export_browser_artifact_to_pdf,
)

# A tiny valid 1x1 PNG (red pixel).
_PNG_1X1_RED = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR42mP8z/CfHgAGgwJ/lw1V9QAAAABJRU5ErkJggg=="
)


def _make_png(path: Path) -> None:
    path.write_bytes(_PNG_1X1_RED)


def test_export_browser_artifact_to_pdf_success(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "artifact"
    artifact_dir.mkdir()
    _make_png(artifact_dir / "step_1.png")
    _make_png(artifact_dir / "step_2.png")

    out_pdf = tmp_path / "out.pdf"
    result = export_browser_artifact_to_pdf(
        BrowserArtifactPdfExportRequest(
            artifact_ref=str(artifact_dir),
            output_path=str(out_pdf),
            output_format="pdf",
        )
    )

    assert out_pdf.exists()
    assert out_pdf.read_bytes().startswith(b"%PDF")
    assert result.output_format == "pdf"
    assert result.pdf_path == str(out_pdf)
    assert result.zip_path is None
    assert result.pages == 2
    assert result.images == 2


def test_export_browser_artifact_to_zip_success(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "artifact"
    artifact_dir.mkdir()
    _make_png(artifact_dir / "step_1.png")
    _make_png(artifact_dir / "step_2.png")

    out_zip = tmp_path / "bundle.zip"
    result = export_browser_artifact_to_pdf(
        BrowserArtifactPdfExportRequest(
            artifact_ref=str(artifact_dir),
            output_path=str(out_zip),
            output_format="zip",
            include_images_in_zip=True,
        )
    )

    assert out_zip.exists()
    assert result.output_format == "zip"
    assert result.zip_path == str(out_zip)
    assert result.pdf_path is None
    assert result.pdf_name_in_zip is not None
    assert result.manifest_name_in_zip == "manifest.json"

    with zipfile.ZipFile(out_zip, "r") as zf:
        names = set(zf.namelist())
        assert result.pdf_name_in_zip in names
        assert "manifest.json" in names
        assert "images/step_1.png" in names
        assert "images/step_2.png" in names

        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        assert manifest["pages"] == 2
        assert manifest["images"] == 2
        assert manifest["include_images"] is True


def test_export_browser_artifact_to_pdf_missing_artifact(tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist"
    with pytest.raises(ArtifactNotFoundError) as exc:
        export_browser_artifact_to_pdf(BrowserArtifactPdfExportRequest(artifact_ref=str(missing)))
    assert exc.value.code == "ARTIFACT_NOT_FOUND"


def test_export_browser_artifact_to_pdf_no_images(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "empty_artifact"
    artifact_dir.mkdir()

    with pytest.raises(ArtifactNoImagesError) as exc:
        export_browser_artifact_to_pdf(BrowserArtifactPdfExportRequest(artifact_ref=str(artifact_dir)))
    assert exc.value.code == "NO_IMAGES_FOUND"


def _invoke_cli(args: list[str]) -> tuple[int, str]:
    """
    Invoke the Thomas CLI in the most compatible way available.
    Returns: (exit_code, stdout)
    """
    # Prefer in-process Typer invocation if available (fast, stable).
    try:
        from typer.testing import CliRunner  # type: ignore
        from thomas.cli.main import app as cli_app  # type: ignore

        runner = CliRunner()
        result = runner.invoke(cli_app, args)
        return result.exit_code, result.output
    except Exception:
        proc = subprocess.run(
            [sys.executable, "-m", "thomas", *args],
            check=False,
            capture_output=True,
            text=True,
        )
        return proc.returncode, proc.stdout


def test_cli_json_success_zip(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "artifact"
    artifact_dir.mkdir()
    _make_png(artifact_dir / "step_1.png")
    _make_png(artifact_dir / "step_2.png")
    out_zip = tmp_path / "cli_bundle.zip"

    exit_code, stdout = _invoke_cli(
        [
            "browser",
            "artifact-pdf-export",
            str(artifact_dir),
            "--output",
            str(out_zip),
            "--zip",
            "--include-images",
            "--json",
        ]
    )
    assert exit_code == 0
    payload = json.loads(stdout)
    assert payload["ok"] is True
    assert payload["output_format"] == "zip"
    assert Path(payload["output_path"]).exists()


def test_cli_json_failure(tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist.pdf"
    exit_code, stdout = _invoke_cli(["browser", "artifact-pdf-export", str(missing), "--json"])
    assert exit_code != 0
    payload = json.loads(stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "ARTIFACT_NOT_FOUND"


