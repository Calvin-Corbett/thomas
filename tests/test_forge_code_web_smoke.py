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


def test_a_page_may_load_the_data_file_it_ships_with(tmp_path) -> None:
    """A self-contained page that reads its own CSV is not reaching the network.

    The smoke server's allowlist carried `.json` but no other data format, so a
    page that `fetch`ed a `sales.csv` sitting beside it got a 404 from the
    harness -- and then correctly reported itself blank, because nothing had
    any data to draw.

    Measured on a real Code run: the goal was a canvas revenue chart reading
    `sales.csv`. Thomas wrote both files, the page is correct -- served where
    the CSV is reachable it prints the grand total `$623,001.25`, which matches
    the CSV summed independently, and paints 80,236 non-transparent pixels --
    and verification still returned `BROWSER_SMOKE_FAILED ... Could not load
    sales.csv (HTTP 404) ... nothing was ever drawn to the canvas`. The run then
    burned its whole ten-pass fix budget trying to repair a page that was
    already right, and finished `failed`.

    A false failure is the same defect as a false pass wearing the other face:
    the verdict was decided by something that never examined the page.
    """

    (tmp_path / "sales.csv").write_text("region,revenue\nNorth,1\n", encoding="utf-8")
    (tmp_path / "data.tsv").write_text("region\trevenue\nNorth\t1\n", encoding="utf-8")
    (tmp_path / "feed.xml").write_text("<rows><row/></rows>", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("plain text", encoding="utf-8")

    assert smoke._safe_web_path(tmp_path, "/sales.csv") == tmp_path / "sales.csv"
    assert smoke._safe_web_path(tmp_path, "/data.tsv") == tmp_path / "data.tsv"
    assert smoke._safe_web_path(tmp_path, "/feed.xml") == tmp_path / "feed.xml"
    assert smoke._safe_web_path(tmp_path, "/notes.txt") == tmp_path / "notes.txt"


def test_widening_the_data_formats_did_not_open_the_source_boundary(tmp_path) -> None:
    """The other direction: the allowlist is still a boundary, not a formality.

    Data files are inert -- the browser parses them as text, never executes
    them -- which is why `.json` was always served. Source, secrets and
    dotfiles must stay refused, or verification becomes a way to read the
    project's private files out of a page it just generated.
    """

    for name, body in (
        (".env", "SECRET=value"),
        ("server.py", "TOKEN = 'value'"),
        ("id_rsa", "-----BEGIN PRIVATE KEY-----"),
        ("db.sqlite3", "SQLite format 3"),
        ("notes.yaml", "token: value"),
    ):
        (tmp_path / name).write_text(body, encoding="utf-8")
        assert smoke._safe_web_path(tmp_path, f"/{name}") is None, f"{name} must not be served"


@pytest.mark.skipif(smoke._browser_executable() is None, reason="Chrome or Edge is not installed")
def test_real_browser_smoke_passes_a_page_that_charts_its_own_csv(tmp_path) -> None:
    """End to end, in a real browser: the shape that used to fail wrongly."""

    (tmp_path / "sales.csv").write_text(
        "region,revenue\nNorth,100\nSouth,50\nNorth,25\n", encoding="utf-8"
    )
    (tmp_path / "report.html").write_text(
        "<!doctype html><html><head><title>Revenue</title></head><body>"
        "<p id='total'>loading</p><canvas id='chart' width='200' height='100'></canvas>"
        "<script>"
        "fetch('sales.csv').then(r=>{if(!r.ok)throw new Error('HTTP '+r.status);return r.text();})"
        # String.fromCharCode(10) rather than a newline escape: this JS lives
        # inside a Python string inside a test, and an escape here has to
        # survive both layers intact. It did not -- one backslash was lost in
        # transit, Python turned the survivor into a real newline, and the page
        # under test failed with "Uncaught SyntaxError: Invalid or unexpected
        # token" while the allowlist it was written to check was already fixed.
        ".then(t=>{const rows=t.trim().split(String.fromCharCode(10)).slice(1).map(l=>l.split(','));"
        "let sum=0; rows.forEach(r=>sum+=Number(r[1]));"
        "document.getElementById('total').textContent='TOTAL '+sum;"
        "const ctx=document.getElementById('chart').getContext('2d');"
        "ctx.fillStyle='#2a6'; rows.forEach((r,i)=>ctx.fillRect(i*40+5,10,30,Number(r[1])/2));});"
        "</script></body></html>",
        encoding="utf-8",
    )

    result = smoke.smoke_html_artifacts(tmp_path, ["report.html"], timeout=30)

    assert result.attempted is True
    assert result.ok is True, result.summary
    # The failure this test exists for named the fetch and then the blank canvas.
    assert "404" not in result.summary
    assert "blank picture area" not in result.summary


@pytest.mark.skipif(smoke._browser_executable() is None, reason="Chrome or Edge is not installed")
def test_a_page_asking_for_a_file_that_is_not_there_does_not_pass(tmp_path) -> None:
    """A deliverable missing its own data file must not verify clean.

    Caught on a real Code run, and it is the exact failure this whole harness
    exists to prevent. Thomas was asked for a canvas chart reading `sales.csv`,
    wrote `report.html` and **did not write the CSV**. Opened, the page reads
    "GRAND TOTAL Unavailable -- Could not load sales.csv (HTTP 404)" and its
    canvas has zero non-transparent pixels. Verification returned
    `BROWSER_SMOKE_OK: browser boot clean; boot only`, outcome `completed`,
    rubric `met`.

    Three separate checks each had a good reason to say nothing:

    * `fetch` 404 is an ordinary response, not an `error` event, so
      `resource_errors` never sees it -- that list only catches `<script src>`
      and `<img>` style failures.
    * the page CAUGHT its own failure and displayed a tidy message, so there was
      no uncaught error either.
    * `paintState` returns `unverifiable` unless the page called `getContext`,
      deliberately, so a decorative canvas on a working page is not called a
      failed render. This page never reached `getContext` -- it failed earlier --
      so a canvas that was genuinely never drawn looked exactly like decoration.

    The reliable signal is not in the DOM at all: the harness's own server
    returned that 404 and can simply say so. That is a fact about the
    deliverable, not a guess about intent.
    """

    (tmp_path / "report.html").write_text(
        "<!doctype html><html><head><title>Revenue</title></head><body>"
        "<p id='total'>loading</p><canvas id='chart' width='300' height='150'></canvas>"
        "<script>"
        "fetch('sales.csv').then(r=>{if(!r.ok)throw new Error('HTTP '+r.status);return r.text();})"
        ".then(t=>{document.getElementById('total').textContent='ok';})"
        ".catch(e=>{document.getElementById('total').textContent='Unavailable: '+e.message;});"
        "</script></body></html>",
        encoding="utf-8",
    )

    result = smoke.smoke_html_artifacts(tmp_path, ["report.html"], timeout=30)

    assert result.ok is False, f"a page missing its own data file passed: {result.summary}"
    assert "sales.csv" in result.summary, result.summary


@pytest.mark.skipif(smoke._browser_executable() is None, reason="Chrome or Edge is not installed")
def test_the_missing_asset_check_ignores_the_browser_s_own_favicon_request(tmp_path) -> None:
    """The other direction, and the one that would have broken everything.

    Chromium requests `/favicon.ico` on its own for every page. Counting that as
    a missing asset would fail every deliverable that does not ship an icon --
    a new false negative in place of the false pass, which is the trade this
    change must not make. Verified by observing the actual request log during a
    smoke run: the browser asked for `/p.html`, `/sales.csv` and `/favicon.ico`,
    and only the middle one was authored by the page.
    """

    (tmp_path / "index.html").write_text(
        "<!doctype html><html><head><title>Plain</title></head><body>"
        "<p>Nothing fetched here, and no icon shipped.</p>"
        "</body></html>",
        encoding="utf-8",
    )

    result = smoke.smoke_html_artifacts(tmp_path, ["index.html"], timeout=30)

    assert result.ok is True, result.summary
    assert "favicon" not in result.summary.lower()


@pytest.mark.skipif(smoke._browser_executable() is None, reason="Chrome or Edge is not installed")
def test_a_page_whose_navigation_does_nothing_says_so(tmp_path) -> None:
    """A convincing shell is the shape a generated app actually fails in.

    The delivered "calculator for ideas" shipped a five-item workspace sidebar
    -- Calculator, Conversions, Graph studio, History, Saved formulas -- where
    the script never mentions "conversions" or "graph" at all and not one of
    the five carries a handler. Every check passed it, correctly by its own
    terms: the page boots, raises no errors, and its keypad genuinely works.
    Verification was "boot only", so it clicked nothing, and nobody found out
    until a person clicked a tab.

    Recorded as a NOTE and never a failure, for the same reason the start and
    pause probes are notes: which control is navigation is guessed from its
    position and wording, and a tab that is ALREADY the open one correctly
    changes nothing when clicked. It states the numbers and lets a reader weigh
    them.
    """

    (tmp_path / "index.html").write_text(
        "<!doctype html><html><head><title>Shell</title></head><body>"
        "<aside>"
        "<button>Calculator</button><button>Conversions</button>"
        "<button>Graph studio</button><button>History</button>"
        "</aside>"
        "<section class='main'><h1>It looks finished</h1></section>"
        "</body></html>",
        encoding="utf-8",
    )

    result = smoke.smoke_html_artifacts(tmp_path, ["index.html"], timeout=30)

    # Still passes: the page boots and this is an observation, not a verdict.
    assert result.ok is True, result.summary
    assert "decoration" in result.summary, result.summary


@pytest.mark.skipif(smoke._browser_executable() is None, reason="Chrome or Edge is not installed")
def test_navigation_that_works_is_not_called_decoration(tmp_path) -> None:
    """The other direction, and the one that would make this useless noise.

    Flagging a page whose tabs genuinely switch would train people to ignore
    the line -- worse than never printing it. Working controls are recorded as
    real interactions instead.
    """

    (tmp_path / "index.html").write_text(
        "<!doctype html><html><head><title>Real</title></head><body>"
        "<aside><button data-v='a'>Overview</button><button data-v='b'>Details</button>"
        "<button data-v='c'>Settings</button><button data-v='d'>About</button></aside>"
        "<section class='main'><h1 id='view'>Overview</h1></section>"
        "<script>"
        "const names={a:'Overview',b:'Details',c:'Settings',d:'About'};"
        "document.querySelector('aside').addEventListener('click',e=>{"
        "const b=e.target.closest('button'); if(!b) return;"
        "document.getElementById('view').textContent=names[b.dataset.v];});"
        "</script></body></html>",
        encoding="utf-8",
    )

    result = smoke.smoke_html_artifacts(tmp_path, ["index.html"], timeout=30)

    assert result.ok is True, result.summary
    assert "decoration" not in result.summary, result.summary
    assert "nav:Details" in result.summary, result.summary
