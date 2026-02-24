from __future__ import annotations

import argparse
import json

import pytest

from thomas.cli.commands.browser import p010_browser_artifact_pdf_export as cli_mod


def test_standalone_parser_defaults() -> None:
    parser = cli_mod._build_standalone_parser()
    args = parser.parse_args(["artifact-123"])

    assert args.artifact_ref == "artifact-123"
    assert args.output is None
    assert args.overwrite is False
    assert args.page_size == "letter"
    assert args.artifacts_root is None
    assert args.format == "auto"
    assert args.zip_output is False
    assert args.include_images_in_zip is False
    assert args.json_output is False


def test_run_argparse_zip_flag_overrides_format(monkeypatch: pytest.MonkeyPatch) -> None:
    parser = cli_mod._build_standalone_parser()
    args = parser.parse_args(["artifact-123", "--format", "pdf", "--zip"])

    observed: dict[str, object] = {}

    def _fake_run_cli_common(**kwargs: object) -> int:
        observed.update(kwargs)
        return 0

    monkeypatch.setattr(cli_mod, "_run_cli_common", _fake_run_cli_common)
    exit_code = cli_mod._run_argparse(args)

    assert exit_code == 0
    assert observed["artifact_ref"] == "artifact-123"
    assert observed["output_format"] == "zip"


def test_run_argparse_forwards_boolean_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    parser = cli_mod._build_standalone_parser()
    args = parser.parse_args(
        [
            "artifact-123",
            "--overwrite",
            "--include-images",
            "--json",
            "--page-size",
            "a4",
            "--artifacts-root",
            "root-dir",
            "--output",
            "out.zip",
        ]
    )

    observed: dict[str, object] = {}

    def _fake_run_cli_common(**kwargs: object) -> int:
        observed.update(kwargs)
        return 0

    monkeypatch.setattr(cli_mod, "_run_cli_common", _fake_run_cli_common)
    exit_code = cli_mod._run_argparse(args)

    assert exit_code == 0
    assert observed["overwrite"] is True
    assert observed["include_images_in_zip"] is True
    assert observed["json_output"] is True
    assert observed["page_size"] == "a4"
    assert observed["artifacts_root"] == "root-dir"
    assert observed["output"] == "out.zip"


def test_register_adds_parser_with_handler() -> None:
    parser = argparse.ArgumentParser(prog="root")
    subparsers = parser.add_subparsers(dest="command")

    cli_mod.register(subparsers)
    args = parser.parse_args([cli_mod._COMMAND_NAME, "artifact-123"])

    assert callable(args.func)


def test_main_uses_run_argparse(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: dict[str, object] = {}

    def _fake_run_argparse(args: argparse.Namespace) -> int:
        observed["artifact_ref"] = args.artifact_ref
        observed["json_output"] = args.json_output
        return 7

    monkeypatch.setattr(cli_mod, "_run_argparse", _fake_run_argparse)
    exit_code = cli_mod.main(["artifact-123", "--json"])

    assert exit_code == 7
    assert observed["artifact_ref"] == "artifact-123"
    assert observed["json_output"] is True


def test_run_cli_common_json_success_emits_machine_readable_payload(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    expected = {
        "ok": True,
        "output_format": "zip",
        "output_path": "bundle.zip",
        "pages": 2,
        "images": 2,
        "sha256": "a" * 64,
    }

    def _fake_run_export(**_: object) -> dict[str, object]:
        return expected

    monkeypatch.setattr(cli_mod, "_run_export", _fake_run_export)

    exit_code = cli_mod._run_cli_common(
        artifact_ref="artifact-123",
        output=None,
        overwrite=False,
        page_size="letter",
        artifacts_root=None,
        output_format="auto",
        include_images_in_zip=False,
        json_output=True,
    )
    payload = json.loads(capsys.readouterr().out.strip())

    assert exit_code == 0
    assert payload == expected


def test_run_cli_common_human_error_includes_code(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class _KnownError(cli_mod.BrowserArtifactPdfExportError):
        code = "KNOWN_FAILURE"
        exit_code = 2

    def _fake_run_export(**_: object) -> dict[str, object]:
        raise _KnownError("expected boom")

    monkeypatch.setattr(cli_mod, "_run_export", _fake_run_export)

    exit_code = cli_mod._run_cli_common(
        artifact_ref="artifact-123",
        output=None,
        overwrite=False,
        page_size="letter",
        artifacts_root=None,
        output_format="auto",
        include_images_in_zip=False,
        json_output=False,
    )
    captured = capsys.readouterr()

    assert exit_code == 2
    assert "Error [KNOWN_FAILURE]: expected boom" in captured.err


def test_run_cli_common_json_unhandled_error_shape(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def _fake_run_export(**_: object) -> dict[str, object]:
        raise RuntimeError("unexpected")

    monkeypatch.setattr(cli_mod, "_run_export", _fake_run_export)

    exit_code = cli_mod._run_cli_common(
        artifact_ref="artifact-123",
        output=None,
        overwrite=False,
        page_size="letter",
        artifacts_root=None,
        output_format="auto",
        include_images_in_zip=False,
        json_output=True,
    )
    payload = json.loads(capsys.readouterr().out.strip())

    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["error"]["code"] == "UNHANDLED_ERROR"
    assert payload["error"]["message"] == "unexpected"
