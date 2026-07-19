"""The deliverable ranker must surface the user's real output, not a build script.

A worker that writes ``build_cookie_pdf.py`` + ``cookies.pdf`` must present the PDF,
and one that writes ``index.html`` + ``scripts/forge/gates/monolith_guard.py`` must
present the web page — never the script. ``deliverable_kind`` must classify the entry
so the UI knows whether to open a right-side live preview (web) vs. inline (pdf/image/
text) vs. download (file). These had no unit coverage (adversarial review 2026-06-17).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from aiohttp import ClientConnectionError, ClientSession, CookieJar
from aiohttp.test_utils import TestClient, TestServer

from thomas.server import chat_delegation_deliverable_postprocess as postprocess
from thomas.server import deliverable_runtime_verify, deliverable_verify
from thomas.server.routes import deliverable_aiohttp as da


def _make_workspace(monkeypatch: pytest.MonkeyPatch, base: Path, exec_id: str, files: dict[str, str]) -> str:
    """Create a fake workspace under a monkeypatched base and return the exec id."""
    monkeypatch.setattr(da, "_WORKSPACES_BASE", base)
    wd = base / exec_id
    for rel, content in files.items():
        target = wd / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return exec_id


def test_rank_prefers_real_deliverable_over_build_script() -> None:
    pdf = da._deliverable_rank(Path("cookies.pdf"))
    script = da._deliverable_rank(Path("build_cookie_pdf.py"))
    assert pdf < script, "a produced PDF must outrank the script that built it"


def test_rank_prefers_web_then_pdf_then_image() -> None:
    html = da._deliverable_rank(Path("index.html"))
    pdf = da._deliverable_rank(Path("doc.pdf"))
    png = da._deliverable_rank(Path("shot.png"))
    assert html < pdf < png


def test_rank_build_filenames_lose_to_real_output() -> None:
    real = da._deliverable_rank(Path("index.html"))
    reqs = da._deliverable_rank(Path("requirements.txt"))
    assert real < reqs


def test_static_verifier_exception_is_visible(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog) -> None:
    (tmp_path / "index.html").write_text("<main>ready</main>", encoding="utf-8")

    def fail_verify(*_args, **_kwargs):
        raise RuntimeError("verifier unavailable")

    monkeypatch.setattr(deliverable_verify, "verify_web_deliverable", fail_verify)
    warning = postprocess.executability_warning(tmp_path, ["index.html"])

    assert "could not verify" in warning
    assert "Static deliverable verification failed" in caplog.text


def test_runtime_verifier_exception_is_visible(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog) -> None:
    (tmp_path / "index.html").write_text("<main>ready</main>", encoding="utf-8")
    monkeypatch.setenv("THOMAS_RUNTIME_VERIFY", "1")

    def fail_runtime(*_args, **_kwargs):
        raise RuntimeError("browser unavailable")

    monkeypatch.setattr(deliverable_runtime_verify, "runtime_smoke_load", fail_runtime)
    warning = postprocess.runtime_executability_warning(tmp_path, ["index.html"])

    assert "could not complete the browser verification" in warning
    assert "Runtime deliverable verification failed" in caplog.text


def test_entry_picks_pdf_over_build_script(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    eid = _make_workspace(
        monkeypatch,
        tmp_path,
        "exec-pdfcase",
        {"build_cookie_pdf.py": "print('x')", "cookies.pdf": "%PDF-1.4 fake"},
    )
    assert da.deliverable_entry(eid) == "cookies.pdf"
    assert da.deliverable_kind(eid) == "pdf"


def test_entry_picks_html_over_offtask_script(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The real Pong/Starfield scenario: worker wrote index.html AND an off-task gate script."""
    eid = _make_workspace(
        monkeypatch,
        tmp_path,
        "exec-webcase",
        {
            "index.html": "<title>Game</title><canvas></canvas>",
            "scripts/forge/gates/monolith_guard.py": "# off-task scaffolding",
        },
    )
    assert da.deliverable_entry(eid) == "index.html"
    assert da.deliverable_kind(eid) == "web"


def test_kind_classifies_each_family(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cases = {
        "exec-web": ({"index.html": "x"}, "web"),
        "exec-img": ({"chart.png": "x"}, "image"),
        "exec-txt": ({"notes.md": "x"}, "text"),
        "exec-bin": ({"report.docx": "x"}, "file"),
    }
    for eid, (files, expected) in cases.items():
        _make_workspace(monkeypatch, tmp_path, eid, files)
        assert da.deliverable_kind(eid) == expected, f"{eid} should classify as {expected}"


def test_empty_workspace_has_no_entry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(da, "_WORKSPACES_BASE", tmp_path)
    (tmp_path / "exec-empty").mkdir(parents=True)
    assert da.deliverable_entry("exec-empty") is None
    assert da.deliverable_kind("exec-empty") == ""


def test_deliverable_in_subdir_beats_root_build_script(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A real deliverable in a build-output subdir must still beat a root build script
    (regression: the old dotfile filter hid it and surfaced the script)."""
    eid = _make_workspace(
        monkeypatch,
        tmp_path,
        "exec-subdir",
        {"dist/index.html": "<title>app</title>", "build_site.py": "print(1)"},
    )
    assert da.deliverable_entry(eid) == "dist/index.html"
    assert da.deliverable_kind(eid) == "web"


def test_junk_dir_files_are_ignored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    eid = _make_workspace(
        monkeypatch,
        tmp_path,
        "exec-junk",
        {"index.html": "<title>x</title>", ".git/config": "noise", "node_modules/p/i.js": "noise"},
    )
    assert da.deliverable_entry(eid) == "index.html"


def test_lone_output_in_dotdir_is_not_reported_as_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """If the only content sits under a junk dir, fall back to it rather than report
    'nothing to show' for a build that did produce a file."""
    eid = _make_workspace(monkeypatch, tmp_path, "exec-fallback", {".cache/report.pdf": "%PDF-1.4"})
    # .cache is not in _JUNK_DIRS, so it's surfaced directly; either way it must not be None.
    assert da.deliverable_entry(eid) is not None
    assert da.deliverable_kind(eid) == "pdf"


def test_entry_preference_is_case_insensitive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A worker that wrote 'Index.html' must resolve on Linux CI and Windows alike."""
    eid = _make_workspace(monkeypatch, tmp_path, "exec-case", {"Index.html": "<title>x</title>"})
    assert da.deliverable_entry(eid) == "Index.html"
    assert da.deliverable_kind(eid) == "web"


def test_entry_prefers_successful_attempt_artifact_over_stale_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A later successful attempt must not open an old preferred index.html."""
    eid = _make_workspace(
        monkeypatch,
        tmp_path,
        "exec-attempt-boundary",
        {
            "index.html": "<title>broken stale attempt</title>",
            "game-v2.html": "<title>successful retry</title><canvas></canvas>",
        },
    )
    monkeypatch.setattr(
        da.task_bot_runtime,
        "get_execution",
        lambda execution_id: {
            "execution_id": execution_id,
            "proof": {"artifacts": [{"path": "game-v2.html", "type": "html"}]},
        },
    )

    assert da.deliverable_entry(eid) == "game-v2.html"
    assert da.deliverable_kind(eid) == "web"
    assert da.deliverable_url(eid) == "/deliverable/exec-attempt-boundary/game-v2.html"


@pytest.mark.asyncio
async def test_route_default_serves_successful_attempt_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    eid = _make_workspace(
        monkeypatch,
        tmp_path,
        "exec-route-attempt",
        {
            "index.html": "<title>stale</title>",
            "game-v2.html": "<title>fresh</title>",
        },
    )
    monkeypatch.setattr(
        da.task_bot_runtime,
        "get_execution",
        lambda execution_id: {"proof": {"artifacts": [{"path": "game-v2.html"}]}},
    )
    served: list[Path] = []

    def _file_response(path: Path):
        served.append(Path(path))
        return da.web.Response(text="ok")

    class _Transport:
        def get_extra_info(self, name: str):
            return ("127.0.0.1", 12345) if name == "peername" else None

    class _Request:
        transport = _Transport()
        match_info = {"execution_id": eid, "tail": ""}

    monkeypatch.setattr(da.web, "FileResponse", _file_response)

    response = await da.handle_deliverable(_Request())

    # HTML deliverables are served via web.Response with an in-memory storage shim
    # injected (so sandboxed games/apps using localStorage don't crash on init), NOT
    # FileResponse. Verify the SUCCESSFUL attempt's artifact is the one served.
    body = response.text or ""
    assert "fresh" in body and "stale" not in body  # served game-v2.html, not stale index.html
    assert "localStorage" in body  # storage shim injected
    assert 'rel="icon" href="data:image/svg+xml' in body  # opaque sandbox must not request the host favicon
    assert response.headers["Content-Security-Policy"] == "sandbox allow-scripts allow-forms"


@pytest.mark.asyncio
async def test_download_returns_exact_pdf_bytes_and_attachment_filename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"%PDF-1.4\nTHOMAS-PDF-PROOF\n%%EOF"
    monkeypatch.setattr(da, "_WORKSPACES_BASE", tmp_path)
    workspace = tmp_path / "exec-download"
    workspace.mkdir(parents=True)
    (workspace / "quarterly-report.pdf").write_bytes(payload)

    app = da.web.Application()
    da.register_deliverable_routes(app, require_api_access=lambda _request: None)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        response = await client.get("/deliverable/exec-download/quarterly-report.pdf?download=1")
        assert response.status == 200
        assert await response.read() == payload
        assert response.content_type == "application/pdf"
        assert response.headers["Content-Disposition"] == 'attachment; filename="quarterly-report.pdf"'
        assert response.headers["X-Content-Type-Options"] == "nosniff"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_html_preview_redirects_to_expiring_execution_capability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    eid = _make_workspace(
        monkeypatch,
        tmp_path,
        "exec-0123456789ab",
        {
            "index.html": '<link rel="stylesheet" href="/assets/styles.css"><script type="module" src="/src/main.js"></script>',
            "assets/styles.css": "body{color:rgb(1,2,3)}",
            "src/main.js": "fetch('/data.json'); new Worker('/worker.js', {type: 'module'});",
            "data.json": '{"ok":true}',
            "worker.js": "self.postMessage('ready')",
        },
    )

    app = da.web.Application()
    service = da.register_deliverable_routes(app, require_api_access=lambda _request: None)
    client = TestClient(TestServer(app))
    await client.start_server()
    main_origin = str(client.make_url("/")).rstrip("/")
    service.configure(main_origin=main_origin)
    preview_client = ClientSession(cookie_jar=CookieJar(unsafe=True))
    try:
        entry = await client.get(f"/deliverable/{eid}/index.html", allow_redirects=False)
        assert entry.status == 302
        location = str(entry.headers.get("Location") or "")
        parsed_entry = urlsplit(location)
        assert parsed_entry.scheme == "http"
        assert parsed_entry.hostname == "127.0.0.1"
        assert parsed_entry.port != urlsplit(main_origin).port
        entry_parts = parsed_entry.path.strip("/").split("/")
        assert entry_parts[0] == "__enter"
        assert da._PREVIEW_CAPABILITY_RE.fullmatch(entry_parts[1])
        assert entry_parts[2:] == ["index.html"]

        preview_origin = f"{parsed_entry.scheme}://{parsed_entry.hostname}:{parsed_entry.port}"
        handshake = await preview_client.get(location, allow_redirects=False)
        assert handshake.status == 302
        assert handshake.headers["Location"] == "/index.html"
        assert handshake.headers["Referrer-Policy"] == "no-referrer"
        assert handshake.headers["Clear-Site-Data"] == '"cache", "storage"'
        assert "no-store" in handshake.headers["Cache-Control"]
        assert "HttpOnly" in handshake.headers["Set-Cookie"]
        assert "SameSite=Strict" in handshake.headers["Set-Cookie"]

        preview = await preview_client.get(preview_origin + handshake.headers["Location"])
        assert preview.status == 200
        assert 'type="module"' in await preview.text()
        assert str(preview.url) == f"{preview_origin}/index.html"
        assert preview.headers["Cache-Control"] == "private, no-store, max-age=0"
        assert preview.headers["Cross-Origin-Resource-Policy"] == "same-origin"
        assert "Access-Control-Allow-Origin" not in preview.headers
        assert "X-Frame-Options" not in preview.headers
        csp = preview.headers["Content-Security-Policy"]
        assert "sandbox allow-scripts allow-forms allow-same-origin" in csp
        assert "worker-src 'self' blob:" in csp
        assert f"frame-ancestors {main_origin}" in csp

        expected_assets = {
            "/assets/styles.css": "body{color:rgb(1,2,3)}",
            "/src/main.js": "new Worker",
            "/worker.js": "postMessage",
        }
        for path, marker in expected_assets.items():
            asset = await preview_client.get(preview_origin + path)
            assert asset.status == 200
            assert marker in await asset.text()
        data = await preview_client.get(preview_origin + "/data.json")
        assert data.status == 200
        assert await data.json() == {"ok": True}

        api = await preview_client.get(preview_origin + "/api/models")
        assert api.status == 404
        service_worker = await preview_client.get(
            preview_origin + "/worker.js",
            headers={"Service-Worker": "script", "Sec-Fetch-Dest": "serviceworker"},
        )
        assert service_worker.status == 404
        async with ClientSession() as no_cookie_client:
            missing_handshake = await no_cookie_client.get(preview_origin + "/index.html")
            assert missing_handshake.status == 404

            invalid_capability = location.replace(entry_parts[1], "a" * 52)
            denied_capability = await no_cookie_client.get(invalid_capability, allow_redirects=False)
            assert denied_capability.status == 404

            traversal = await no_cookie_client.get(preview_origin + "/%2e%2e/secret.txt")
            assert traversal.status == 404
    finally:
        await preview_client.close()
        await client.close()
        await service.stop()


@pytest.mark.asyncio
async def test_preview_grant_expires_and_releases_its_socket_without_another_request(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "preview"
    workspace.mkdir()
    (workspace / "index.html").write_text("<main>temporary</main>", encoding="utf-8")
    service = da.DeliverablePreviewService(ttl_seconds=1)
    service.configure(main_origin="http://127.0.0.1:8899")
    client = ClientSession(cookie_jar=CookieJar(unsafe=True))
    try:
        location = await service.preview_directory_url(
            subject_id="expiry-proof",
            workspace=workspace,
            tail="index.html",
        )
        preview_origin = location.split("/__enter/", 1)[0]
        assert service._grants

        await asyncio.sleep(1.1)

        assert service._grants == {}
        with pytest.raises(ClientConnectionError):
            await client.get(preview_origin + "/index.html")
    finally:
        await client.close()
        await service.stop()


@pytest.mark.asyncio
async def test_preview_service_bounds_active_grants(tmp_path: Path) -> None:
    service = da.DeliverablePreviewService(ttl_seconds=60, max_grants=1)
    service.configure(main_origin="http://127.0.0.1:8899")
    client = ClientSession()
    try:
        locations: list[str] = []
        for index in range(2):
            workspace = tmp_path / f"preview-{index}"
            workspace.mkdir()
            (workspace / "index.html").write_text(f"<main>{index}</main>", encoding="utf-8")
            locations.append(
                await service.preview_directory_url(
                    subject_id=f"bounded-{index}",
                    workspace=workspace,
                    tail="index.html",
                )
            )

        assert len(service._grants) == 1
        with pytest.raises(ClientConnectionError):
            await client.get(locations[0])
    finally:
        await client.close()
        await service.stop()


def test_deliverable_registration_requires_access_guard() -> None:
    with pytest.raises(TypeError):
        da.register_deliverable_routes(da.web.Application())  # type: ignore[call-arg]
    with pytest.raises(TypeError, match="require_api_access must be callable"):
        da.register_deliverable_routes(da.web.Application(), require_api_access=None)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_registered_download_requires_configured_api_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"private-thomas-result"
    monkeypatch.setattr(da, "_WORKSPACES_BASE", tmp_path)
    workspace = tmp_path / "exec-private"
    workspace.mkdir(parents=True)
    (workspace / "secret.pdf").write_bytes(payload)

    def require_token(request: da.web.Request) -> None:
        if request.headers.get("Authorization") != "Bearer test-token":
            raise da.web.HTTPUnauthorized(text="API token required")

    app = da.web.Application()
    da.register_deliverable_routes(app, require_api_access=require_token)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        denied = await client.get("/deliverable/exec-private/secret.pdf?download=1")
        assert denied.status == 401
        assert await denied.read() != payload

        allowed = await client.get(
            "/deliverable/exec-private/secret.pdf?download=1",
            headers={"Authorization": "Bearer test-token"},
        )
        assert allowed.status == 200
        assert await allowed.read() == payload
    finally:
        await client.close()
