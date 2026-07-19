from __future__ import annotations

import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from thomas.forge.anvil import web_artifact_smoke as smoke


def test_instrumentation_precedes_application_scripts_and_receipt_round_trips() -> None:
    source = "<!doctype html><html><head><script>window.appBooted = true;</script></head><body>Ready</body></html>"

    instrumented = smoke._instrument_html(source)

    assert instrumented.index("thomas-browser-smoke-harness") < instrumented.index("window.appBooted")
    payload = {"dom_ready": True, "errors": [], "title": "Ready"}
    encoded = base64.b64encode(json.dumps(payload).encode()).decode()
    assert smoke._receipt_from_dom(f'<html data-thomas-smoke="{encoded}"></html>') == payload


def test_safe_asset_boundary_rejects_dotfiles_and_non_web_source(tmp_path) -> None:
    (tmp_path / ".env").write_text("SECRET=value", encoding="utf-8")
    (tmp_path / "server.py").write_text("TOKEN = 'value'", encoding="utf-8")
    (tmp_path / "app.js").write_text("window.ready = true", encoding="utf-8")

    assert smoke._safe_web_path(tmp_path, "/.env") is None
    assert smoke._safe_web_path(tmp_path, "/server.py") is None
    assert smoke._safe_web_path(tmp_path, "/../app.js") is None
    assert smoke._safe_web_path(tmp_path, "/app.js") == tmp_path / "app.js"
    assert smoke._allowed_proxy_path(f"{smoke._SMOKE_ORIGIN}/app.js") == "/app.js"
    assert smoke._allowed_proxy_path("/styles.css", smoke._SMOKE_HOST) == "/styles.css"
    assert smoke._allowed_proxy_path("/styles.css", "127.0.0.1:8908") is None
    assert smoke._allowed_proxy_path("http://127.0.0.1:8908/app.js") is None


@pytest.mark.skipif(smoke._browser_executable() is None, reason="Chrome or Edge is not installed")
def test_real_browser_smoke_starts_and_interacts_with_canvas_app(tmp_path) -> None:
    (tmp_path / "index.html").write_text(
        "<!doctype html><html><head><title>Signal QA</title></head><body>"
        "<button id='start'>Start game</button><canvas id='game' width='320' height='180'></canvas>"
        "<script>"
        "const events=[]; window.events=events;"
        "start.onclick=()=>{events.push('start');start.hidden=true;};"
        "const ctx=game.getContext('2d');"
        "game.addEventListener('keydown',e=>{events.push(e.key);ctx.fillStyle='red';ctx.fillRect(1,1,12,12);});"
        "game.addEventListener('pointermove',()=>{events.push('pointer');ctx.fillStyle='blue';ctx.fillRect(20,1,12,12);});"
        "</script></body></html>",
        encoding="utf-8",
    )

    result = smoke.smoke_html_artifacts(tmp_path, ["index.html"], timeout=20)

    assert result.attempted is True
    assert result.ok is True
    assert "clicked:Start game" in result.summary
    assert "keyboard:ArrowRight" in result.summary
    assert "pointer:canvas" in result.summary


@pytest.mark.skipif(smoke._browser_executable() is None, reason="Chrome or Edge is not installed")
def test_real_browser_smoke_does_not_claim_unhandled_canvas_inputs(tmp_path) -> None:
    (tmp_path / "index.html").write_text(
        "<!doctype html><p>Static canvas</p><canvas width='320' height='180'></canvas>",
        encoding="utf-8",
    )

    result = smoke.smoke_html_artifacts(tmp_path, ["index.html"], timeout=20)

    assert result.ok is True
    assert "keyboard:ArrowRight" not in result.summary
    assert "pointer:canvas" not in result.summary


@pytest.mark.skipif(smoke._browser_executable() is None, reason="Chrome or Edge is not installed")
def test_real_browser_smoke_rejects_noop_resume_control(tmp_path) -> None:
    (tmp_path / "index.html").write_text(
        "<!doctype html><button id='start'>Start game</button>"
        "<button id='pause' aria-label='Pause game' disabled>Pause</button>"
        "<section id='pause-screen' hidden><button id='resume'>Resume</button></section>"
        "<canvas width='320' height='180'></canvas><script>"
        "start.onclick=()=>{start.hidden=true;pause.disabled=false;};"
        "document.addEventListener('keydown',event=>{if(event.key==='p'){pauseScreen.hidden=false;}});"
        "const pauseScreen=document.getElementById('pause-screen');"
        "</script>",
        encoding="utf-8",
    )

    result = smoke.smoke_html_artifacts(tmp_path, ["index.html"], timeout=20)

    assert result.attempted is True
    assert result.ok is False
    assert "Resume control did not return to play" in result.summary


@pytest.mark.skipif(smoke._browser_executable() is None, reason="Chrome or Edge is not installed")
def test_real_browser_smoke_loads_local_linked_css_and_javascript(tmp_path) -> None:
    (tmp_path / "index.html").write_text(
        "<!doctype html><html><head><title>Linked assets</title>"
        "<link rel='stylesheet' href='styles.css'></head>"
        "<body><main id='status'>Loading</main><script src='app.js'></script></body></html>",
        encoding="utf-8",
    )
    (tmp_path / "styles.css").write_text(
        "@import url('data:text/css,'); body { color: rgb(10, 20, 30); }", encoding="utf-8"
    )
    (tmp_path / "app.js").write_text(
        "document.getElementById('status').textContent = 'Linked assets loaded';",
        encoding="utf-8",
    )

    result = smoke.smoke_html_artifacts(tmp_path, ["index.html", "styles.css", "app.js"], timeout=20)

    assert result.attempted is True
    assert result.ok is True
    assert result.receipts[0]["body_text_chars"] == len("Linked assets loaded")


@pytest.mark.skipif(smoke._browser_executable() is None, reason="Chrome or Edge is not installed")
def test_real_browser_smoke_fails_on_runtime_error_and_missing_asset(tmp_path) -> None:
    (tmp_path / "runtime-error.html").write_text(
        "<!doctype html><main>Before</main><script>"
        "addEventListener('DOMContentLoaded',()=>{throw new Error('runtime boom')});"
        "</script>",
        encoding="utf-8",
    )
    (tmp_path / "missing-asset.html").write_text(
        "<!doctype html><main>Before</main><script src='missing.js'></script>",
        encoding="utf-8",
    )

    runtime = smoke.smoke_html_artifacts(tmp_path, ["runtime-error.html"], timeout=20)
    missing = smoke.smoke_html_artifacts(tmp_path, ["missing-asset.html"], timeout=20)

    assert runtime.attempted is True and runtime.ok is False
    assert "runtime boom" in runtime.summary
    assert missing.attempted is True and missing.ok is False
    assert "missing.js" in missing.summary


@pytest.mark.skipif(smoke._browser_executable() is None, reason="Chrome or Edge is not installed")
def test_real_browser_smoke_proxy_cannot_reach_another_localhost_service(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    victim_hits: list[str] = []
    monkeypatch.setattr(smoke, "_SMOKE_CSP", "default-src * 'unsafe-inline' data: blob:")

    class VictimHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
            victim_hits.append(self.path)
            self.send_response(204)
            self.end_headers()

        def log_message(self, _format: str, *_args: object) -> None:
            return

    victim = ThreadingHTTPServer(("127.0.0.1", 0), VictimHandler)
    victim.daemon_threads = True
    thread = threading.Thread(target=victim.serve_forever, name="thomas-smoke-victim", daemon=True)
    thread.start()
    try:
        (tmp_path / "localhost-probe.html").write_text(
            "<!doctype html><main>Network boundary</main>"
            f"<img src='http://127.0.0.1:{victim.server_port}/sensitive-action'>",
            encoding="utf-8",
        )

        result = smoke.smoke_html_artifacts(tmp_path, ["localhost-probe.html"], timeout=20)
    finally:
        victim.shutdown()
        victim.server_close()
        thread.join(timeout=2)

    assert result.attempted is True
    assert result.ok is False
    assert victim_hits == []
