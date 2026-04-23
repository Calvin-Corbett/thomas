import json
import zipfile
from pathlib import Path

import pytest

import thomas.browser.p016_browser_data_cookies_export_and_import as cookies_mod
from thomas.browser.p016_browser_data_cookies_export_and_import import (
    CookiesExportRequest,
    CookiesImportRequest,
    ExternalFailureError,
    InvalidInputError,
    MissingConfigError,
    export_cookies,
    import_cookies,
)


class InMemoryBackend:
    def __init__(self, cookies=None, *, fail_list=False, fail_add=False):
        self._cookies = cookies or []
        self.fail_list = fail_list
        self.fail_add = fail_add
        self.added = []

    def list_cookies(self, url=None):
        if self.fail_list:
            raise RuntimeError("boom")
        return list(self._cookies)

    def add_cookies(self, cookies):
        if self.fail_add:
            raise RuntimeError("boom")
        self.added.extend(list(cookies))


def test_export_success_writes_versioned_file(tmp_path: Path) -> None:
    backend = InMemoryBackend(
        cookies=[
            {
                "name": "session",
                "value": "abc",
                "domain": ".example.com",
                "path": "/",
                "secure": True,
                "httpOnly": True,
            },
            {
                "name": "prefs",
                "value": "dark",
                "domain": "example.com",
                "path": "/",
                "secure": False,
            },
        ]
    )

    out = tmp_path / "cookies.json"
    res = export_cookies(CookiesExportRequest(output_file=out), backend=backend)

    assert res.cookie_count == 2
    assert res.output_format == "json"
    assert out.exists()

    payload = json.loads(out.read_text("utf-8"))
    assert payload["schema"].startswith("thomas.browser.cookies")
    assert isinstance(payload["cookies"], list)
    assert len(payload["cookies"]) == 2


def test_export_zip_success_writes_archive(tmp_path: Path) -> None:
    backend = InMemoryBackend(
        cookies=[
            {
                "name": "a",
                "value": "1",
                "domain": "example.com",
                "path": "/",
                "secure": True,
            }
        ]
    )

    out = tmp_path / "cookies.zip"
    res = export_cookies(CookiesExportRequest(output_file=out), backend=backend)

    assert res.cookie_count == 1
    assert res.output_format == "zip"
    assert out.exists()

    with zipfile.ZipFile(out, "r") as zf:
        raw = zf.read("cookies.json").decode("utf-8")
    payload = json.loads(raw)
    assert payload["schema"] == "thomas.browser.cookies.v1"
    assert len(payload["cookies"]) == 1


def test_import_success_reads_list_or_wrapped_schema(tmp_path: Path) -> None:
    inp = tmp_path / "cookies_in.json"
    inp.write_text(
        json.dumps(
            [
                {
                    "name": "a",
                    "value": "1",
                    "domain": "example.com",
                    "path": "/",
                    "secure": True,
                }
            ]
        ),
        "utf-8",
    )

    backend = InMemoryBackend()
    res = import_cookies(CookiesImportRequest(input_file=inp), backend=backend)

    assert res.cookie_count == 1
    assert res.input_format == "json"
    assert backend.added
    assert backend.added[0]["url"].startswith("https://")


def test_import_zip_success_reads_archive(tmp_path: Path) -> None:
    inp = tmp_path / "cookies_in.zip"
    payload = {
        "schema": "thomas.browser.cookies.v1",
        "exported_at": "2026-02-21T00:00:00+00:00",
        "cookies": [
            {"name": "a", "value": "1", "domain": "example.com", "path": "/", "secure": True},
        ],
    }
    with zipfile.ZipFile(inp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("cookies.json", json.dumps(payload))

    backend = InMemoryBackend()
    res = import_cookies(CookiesImportRequest(input_file=inp), backend=backend)

    assert res.cookie_count == 1
    assert res.input_format == "zip"
    assert res.archive_member == "cookies.json"
    assert backend.added
    assert backend.added[0]["url"].startswith("https://")


def test_import_zip_missing_json_is_deterministic(tmp_path: Path) -> None:
    inp = tmp_path / "bad.zip"
    with zipfile.ZipFile(inp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("README.txt", "no cookies here")

    with pytest.raises(InvalidInputError) as ei:
        import_cookies(CookiesImportRequest(input_file=inp), backend=InMemoryBackend())

    assert ei.value.code == "INVALID_INPUT"


def test_import_invalid_json_is_deterministic(tmp_path: Path) -> None:
    inp = tmp_path / "bad.json"
    inp.write_text("not json", "utf-8")

    with pytest.raises(InvalidInputError) as ei:
        import_cookies(CookiesImportRequest(input_file=inp), backend=InMemoryBackend())

    assert ei.value.code == "INVALID_INPUT"


def test_export_backend_failure_wraps_as_external_failure(tmp_path: Path) -> None:
    backend = InMemoryBackend(fail_list=True)
    out = tmp_path / "cookies.json"

    with pytest.raises(ExternalFailureError) as ei:
        export_cookies(CookiesExportRequest(output_file=out), backend=backend)

    assert ei.value.code == "EXTERNAL_FAILURE"


def test_missing_config_is_deterministic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("THOMAS_BROWSER_PROFILE_DIR", raising=False)

    # Prevent best-effort imports from discovering a default profile dir.
    def _boom(_name: str):
        raise ImportError("blocked for deterministic test")

    monkeypatch.setattr(cookies_mod.importlib, "import_module", _boom)

    with pytest.raises(MissingConfigError) as ei:
        export_cookies(CookiesExportRequest(output_file=tmp_path / "x.json"), backend=None)

    assert ei.value.code == "MISSING_CONFIG"
