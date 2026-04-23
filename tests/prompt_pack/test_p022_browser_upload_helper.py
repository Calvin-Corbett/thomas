import json
import hashlib
from pathlib import Path
import sys

import pytest

# pytest may run with import-mode=importlib, which does not automatically add the
# project root to sys.path. Make the import deterministic for this prompt-pack test.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from thomas.browser.p022_browser_upload_helper import (  # noqa: E402
    BrowserUploadExternalFailureError,
    BrowserUploadInvalidInputError,
    BrowserUploadMissingConfigError,
    BrowserUploadRequest,
    stage_file_for_browser,
)
from thomas.cli.commands.browser import p022_browser_upload_helper as cli  # noqa: E402


def test_stage_file_success_copies_and_hashes(tmp_path: Path) -> None:
    src = tmp_path / "src.bin"
    payload = b"hello upload helper\n" * 3
    src.write_bytes(payload)

    dest_dir = tmp_path / "uploads"
    req = BrowserUploadRequest(source_path=src, destination_dir=dest_dir, compute_sha256=True)
    res = stage_file_for_browser(req)

    assert res.source_path == src
    assert res.staged_path == dest_dir / "src.bin"
    assert res.staged_path.exists()
    assert res.staged_path.read_bytes() == payload
    assert res.bytes_copied == len(payload)

    expected_sha = hashlib.sha256(payload).hexdigest()
    assert res.sha256 == expected_sha


def test_stage_file_destination_exists_without_overwrite_is_deterministic(tmp_path: Path) -> None:
    src = tmp_path / "src.txt"
    src.write_text("hello")

    dest_dir = tmp_path / "uploads"
    first = stage_file_for_browser(BrowserUploadRequest(source_path=src, destination_dir=dest_dir))
    assert first.staged_path.exists()

    with pytest.raises(BrowserUploadExternalFailureError) as exc_info:
        stage_file_for_browser(BrowserUploadRequest(source_path=src, destination_dir=dest_dir, overwrite=False))

    assert exc_info.value.code == "destination_exists"


def test_stage_file_invalid_destination_name_is_deterministic(tmp_path: Path) -> None:
    src = tmp_path / "src.txt"
    src.write_text("hello")

    dest_dir = tmp_path / "uploads"
    with pytest.raises(BrowserUploadInvalidInputError) as exc_info:
        stage_file_for_browser(
            BrowserUploadRequest(
                source_path=src,
                destination_dir=dest_dir,
                destination_name="../nope.txt",
            )
        )

    assert exc_info.value.code == "invalid_destination_name"


def test_stage_file_invalid_source_is_deterministic(tmp_path: Path) -> None:
    missing = tmp_path / "missing.txt"
    req = BrowserUploadRequest(source_path=missing, destination_dir=tmp_path / "uploads")

    with pytest.raises(BrowserUploadInvalidInputError) as exc_info:
        stage_file_for_browser(req)

    err = exc_info.value
    assert err.code == "source_not_found"
    assert "does not exist" in err.message
    assert err.details.get("source_path") == str(missing)


def test_stage_file_missing_config_errors_when_dest_unset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = tmp_path / "src.txt"
    src.write_text("x")

    # Make sure no env keys are present.
    for key in [
        "THOMAS_BROWSER_UPLOAD_DIR",
        "THOMAS_BROWSER_UPLOAD_ROOT",
        "THOMAS_WORKSPACE",
        "THOMAS_PROJECT_ROOT",
        "THOMAS_HOME",
    ]:
        monkeypatch.delenv(key, raising=False)

    req = BrowserUploadRequest(source_path=src, destination_dir=None)

    with pytest.raises(BrowserUploadMissingConfigError) as exc_info:
        stage_file_for_browser(req)

    assert exc_info.value.code == "missing_upload_directory"


def test_cli_json_output_success(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    src = tmp_path / "src.txt"
    src.write_text("hello")

    dest = tmp_path / "uploads"
    exit_code = cli.main([str(src), "--dest", str(dest), "--json"])
    assert exit_code == 0

    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload["ok"] is True
    assert payload["result"]["staged_path"].endswith("uploads/src.txt")


def test_cli_json_output_failure_missing_config(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    src = tmp_path / "src.txt"
    src.write_text("hello")

    for key in [
        "THOMAS_BROWSER_UPLOAD_DIR",
        "THOMAS_BROWSER_UPLOAD_ROOT",
        "THOMAS_WORKSPACE",
        "THOMAS_PROJECT_ROOT",
        "THOMAS_HOME",
    ]:
        monkeypatch.delenv(key, raising=False)

    exit_code = cli.main([str(src), "--json"])
    assert exit_code == 1

    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "missing_upload_directory"


def test_cli_schema_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # tmp_path is unused but keeps signature uniform and may help if capsys is flaky.
    exit_code = cli.main(["--schema"])
    assert exit_code == 0

    out = capsys.readouterr().out.strip()
    schema = json.loads(out)
    assert schema["type"] == "object"
    assert "ok" in schema["required"]


def test_cli_missing_source_json(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = cli.main(["--json"])
    assert exit_code == 2

    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "missing_source"
