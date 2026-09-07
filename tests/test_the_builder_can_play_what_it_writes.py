"""The Build worker can play the page it wrote, and report what it saw (2026-09-05).

On the Mario Kart build Thomas wrote, in his own words, that he was "not
claiming the game is verified fixed because this workspace gave me no
browser-control tool". He was right: the edit-only toolset had nothing that
could press START and hold accelerate. The engine's smoke check presses one
button and looks for paint; it passed a race that ended in three seconds with
every kart at 0:00.00, and passed the next version where the circuit had
vanished. Nobody in the loop could drive.

``web.playtest`` runs a scripted session in a real headless browser against
the workspace: the page and its own web assets are served from the folder
through the same allowlist the smoke uses, every other host is refused, and
each step returns the text observed, page errors, and how much of the canvas
is painted. Screenshots land under the workspace's ``.thomas/playtest`` folder.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest

from thomas.tools import web_playtest

pytestmark = pytest.mark.skipif(
    not web_playtest.playtest_available(), reason="playwright with chromium is not installed"
)

PAGE = """<!doctype html><html><head><title>Kart</title><link rel="stylesheet" href="styles.css"></head>
<body><h1 id="title">Garage</h1><button id="start">START RACE</button>
<canvas id="c" width="200" height="100"></canvas><div id="hud">LAP 0/3</div>
<script>
const ctx = document.getElementById('c').getContext('2d');
let laps = 0, held = 0;
document.getElementById('start').onclick = () => { document.getElementById('title').textContent = 'Racing'; };
window.addEventListener('keydown', (e) => { if (e.key === 'w') { held++; ctx.fillStyle = '#f04452'; ctx.fillRect(0, 0, 200, 100);
  if (held % 10 === 0) { laps++; document.getElementById('hud').textContent = 'LAP ' + laps + '/3'; } } });
fetch('https://example.com/data.json').then(r => { document.getElementById('hud').dataset.net = 'reached'; }).catch(() => { document.getElementById('hud').dataset.net = 'blocked'; });
</script></body></html>"""


def _workspace(tmp_path: Path) -> Path:
    (tmp_path / "index.html").write_text(PAGE, encoding="utf-8")
    (tmp_path / "styles.css").write_text("body{background:#123456}", encoding="utf-8")
    (tmp_path / "secrets.env").write_text("TOKEN=abc", encoding="utf-8")
    return tmp_path


def _run(tool, args):
    return asyncio.run(tool.execute(args))


def test_a_click_and_a_held_key_change_what_the_page_shows(tmp_path: Path) -> None:
    tool = web_playtest.WebPlaytestTool(_workspace(tmp_path))
    result = _run(
        tool,
        {
            "page": "index.html",
            "steps": [
                {"observe": "#title"},
                {"click": "START RACE"},
                {"observe": "#title"},
                {"hold": "w", "seconds": 1.0},
                {"observe": "#hud"},
                {"screenshot": "after-race"},
            ],
        },
    )
    assert result.ok, result.error
    text = str(result.data)
    assert "Garage" in text and "Racing" in text, text
    assert "LAP 1/3" in text or "LAP 2/3" in text or "LAP 3/3" in text, text
    painted = [int(m) for m in re.findall(r"canvas painted: #c (\d+) px", text)]
    assert painted and painted[0] == 0 and painted[-1] > 0, text  # blank before the hold, painted after
    assert "errors: none" in text, text  # the blocked example.com fetch is a note, not an error
    shots = list((tmp_path / ".thomas" / "playtest").rglob("*.png"))
    assert shots, "no screenshot was written"
    assert str(shots[0]) in text or shots[0].name in text


def test_the_page_can_load_its_own_stylesheet_but_not_the_internet_or_secrets(tmp_path: Path) -> None:
    tool = web_playtest.WebPlaytestTool(_workspace(tmp_path))
    result = _run(
        tool,
        {
            "page": "index.html",
            "steps": [
                {"wait": 0.8},
                {"observe": "#hud"},
                {"eval": "getComputedStyle(document.body).backgroundColor"},
                {"eval": "document.getElementById('hud').dataset.net"},
                {"eval": "fetch('/secrets.env').then(r => r.status)"},
            ],
        },
    )
    assert result.ok, result.error
    text = str(result.data)
    assert "rgb(18, 52, 86)" in text, text  # styles.css was served
    assert "blocked" in text, text  # example.com was not
    assert "404" in text, text  # secrets.env is refused by the allowlist


def test_a_page_error_is_reported_not_hidden(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    (root / "broken.html").write_text("<script>throw new Error('boom at boot')</script><p>hi</p>", encoding="utf-8")
    result = _run(web_playtest.WebPlaytestTool(root), {"page": "broken.html", "steps": [{"observe": "body"}]})
    assert result.ok, result.error
    assert "boom at boot" in str(result.data)


def test_a_bad_step_is_refused_before_a_browser_starts(tmp_path: Path) -> None:
    result = _run(
        web_playtest.WebPlaytestTool(_workspace(tmp_path)), {"page": "index.html", "steps": [{"launch": "x"}]}
    )
    assert not result.ok
    assert "launch" in str(result.error)


def test_a_page_outside_the_workspace_is_refused(tmp_path: Path) -> None:
    result = _run(web_playtest.WebPlaytestTool(_workspace(tmp_path)), {"page": "../index.html", "steps": []})
    assert not result.ok


HIDDEN_TWIN = """<!doctype html><html><body>
<button id="quit" style="display:none">QUIT TO GARAGE</button>
<button id="garage" onclick="document.getElementById('where').textContent='in the garage'">GARAGE</button>
<div id="where">on the results screen</div></body></html>"""


def test_a_click_by_text_prefers_the_visible_exact_match(tmp_path: Path) -> None:
    """Live: "GARAGE" matched the hidden pause-menu "QUIT TO GARAGE" first and the click
    waited five seconds for a button that was never visible."""
    (tmp_path / "index.html").write_text(HIDDEN_TWIN, encoding="utf-8")
    result = _run(
        web_playtest.WebPlaytestTool(tmp_path),
        {"page": "index.html", "steps": [{"click": "GARAGE"}, {"observe": "#where"}]},
    )
    assert result.ok, result.error
    assert "in the garage" in str(result.data), result.data


def test_a_failed_step_keeps_what_the_earlier_steps_saw(tmp_path: Path) -> None:
    """One failed click used to throw the whole session away, including the HUD text
    the model needed; now the report stops at the failed step and says so."""
    (tmp_path / "index.html").write_text(HIDDEN_TWIN, encoding="utf-8")
    result = _run(
        web_playtest.WebPlaytestTool(tmp_path),
        {"page": "index.html", "steps": [{"observe": "#where"}, {"click": "NO SUCH BUTTON"}, {"observe": "#where"}]},
    )
    assert result.ok, result.error
    text = str(result.data)
    assert "on the results screen" in text
    assert "FAILED" in text and "NO SUCH BUTTON" in text, text
    assert "stopped at step 2" in text, text
    assert text.count("observe") == 1  # the step after the failure did not run


def test_old_playtest_sessions_are_pruned_to_the_newest_twenty(tmp_path: Path) -> None:
    """Every session writes its screenshots under .thomas/playtest/<stamp>; a
    build that plays itself dozens of times a day would otherwise keep them all."""
    root = _workspace(tmp_path)
    store = root / ".thomas" / "playtest"
    import os
    import time

    stale = time.time() - 3 * 86400  # old enough to prune; a session from the last day never is
    for i in range(25):
        (store / f"20260901T{i:06d}").mkdir(parents=True)
        (store / f"20260901T{i:06d}" / "01-old.png").write_bytes(b"x")
        os.utime(store / f"20260901T{i:06d}", (stale, stale))
    result = _run(web_playtest.WebPlaytestTool(root), {"page": "index.html", "steps": [{"screenshot": "now"}]})
    assert result.ok, result.error
    sessions = sorted(p.name for p in store.iterdir() if p.is_dir())
    assert len(sessions) == 20, len(sessions)
    assert sessions[-1] > "20260901T000024"  # the newest session is the one just written
    assert "20260901T000000" not in sessions and "20260901T000024" in sessions


# Generation 9 of the Mario Kart build (2026-09-05): the judge's own playtest
# asked to hold "w+ArrowUp", the way the worker had described it, and the step
# failed with an unsupported key name; and the judge quoted the worker's recorded
# session from a 2000-character preview that ended before the sixth finisher.


def test_a_combined_key_string_holds_every_key_in_it() -> None:
    assert web_playtest.hold_keys("w+ArrowUp") == ["w", "ArrowUp"]
    assert web_playtest.hold_keys(["w", "ArrowUp"]) == ["w", "ArrowUp"]
    assert web_playtest.hold_keys("Shift+W") == ["Shift", "W"]
    assert web_playtest.hold_keys("+") == ["+"]


def test_the_full_report_is_saved_beside_the_screenshots(tmp_path: Path) -> None:
    tool = web_playtest.WebPlaytestTool(_workspace(tmp_path))
    result = _run(
        tool,
        {
            "page": "index.html",
            "steps": [{"observe": "#title"}, {"hold": "w+ArrowUp", "seconds": 0.3}, {"observe": "#hud"}],
        },
    )
    assert result.ok, result.error
    assert "hold w+ArrowUp" in str(result.data), result.data
    reports = list((tmp_path / ".thomas" / "playtest").glob("*/report.txt"))
    assert len(reports) == 1, reports
    assert reports[0].read_text(encoding="utf-8") == str(result.data)
    assert web_playtest.recent_reports(tmp_path, limit=3) == [str(result.data)]


# The Minecraft build (2026-09-05, project "Code task 2026-08-14 1413"): main.js
# checked navigator.webdriver and the user agent for Headless/Playwright/Puppeteer
# and never activated its renderer under automation ("used to make smoke checks
# fail"), so every playtest, Thomas's, the judge's and mine, saw a HUD over a
# void and could not tell. The player the tool is must look like a person's
# browser, and a WebGL canvas must be measured too.

HONEST_PAGE = """<!doctype html><html><body><pre id="who"></pre>
<canvas id="gl" width="200" height="100"></canvas><canvas id="blank" width="200" height="100"></canvas>
<script>
document.getElementById('who').textContent = JSON.stringify({webdriver: navigator.webdriver, headless: /HeadlessChrome/.test(navigator.userAgent)});
const gl = document.getElementById('gl').getContext('webgl');
if (gl) { gl.clearColor(0.2, 0.5, 0.9, 1); gl.clear(gl.COLOR_BUFFER_BIT); gl.enable(gl.SCISSOR_TEST); gl.scissor(0, 0, 100, 100); gl.clearColor(0.9, 0.2, 0.1, 1); gl.clear(gl.COLOR_BUFFER_BIT); }
</script></body></html>"""


def test_the_page_cannot_tell_it_is_being_played_by_a_tool(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text(HONEST_PAGE, encoding="utf-8")
    result = _run(web_playtest.WebPlaytestTool(tmp_path), {"page": "index.html", "steps": [{"observe": "#who"}]})
    assert result.ok, result.error
    assert '"webdriver":false' in str(result.data).replace(" ", "") or '"webdriver":null' in str(result.data).replace(
        " ", ""
    ), result.data
    assert '"headless":false' in str(result.data).replace(" ", ""), result.data


def test_a_webgl_canvas_is_measured_from_what_it_shows(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text(HONEST_PAGE, encoding="utf-8")
    result = _run(web_playtest.WebPlaytestTool(tmp_path), {"page": "index.html", "steps": [{"wait": 0.5}]})
    assert result.ok, result.error
    text = str(result.data)
    gl = re.search(r"#gl (\d+)% of the canvas differs from its dominant colour", text)
    blank = re.search(r"#blank no context yet", text)  # never asked for a context, so never given one
    assert gl and 30 <= int(gl.group(1)) <= 70, text  # half the canvas is the second colour
    assert blank, text


# The Minecraft run (2026-09-05, transcript-b3b0589bccfaad14): the paint probe
# called getContext('2d') on the world canvas before the game had claimed it,
# which made it a 2D canvas, and three.js then failed with "A WebGL context could
# not be created ... Canvas has an existing context of a different type". The
# tool broke the game it was measuring. Measuring must never claim a canvas.

LATE_GL_PAGE = """<!doctype html><html><body><button id="go">ENTER</button><pre id="out"></pre>
<canvas id="world" width="200" height="100"></canvas>
<script>
document.getElementById('go').onclick = () => {
  const c = document.getElementById('world');
  const gl = c.getContext('webgl');
  document.getElementById('out').textContent = gl ? 'gl ok' : 'gl failed';
  if (gl) { gl.clearColor(0.1, 0.6, 0.2, 1); gl.clear(gl.COLOR_BUFFER_BIT); }
};
</script></body></html>"""


def test_measuring_a_canvas_never_claims_it(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text(LATE_GL_PAGE, encoding="utf-8")
    result = _run(
        web_playtest.WebPlaytestTool(tmp_path),
        {"page": "index.html", "steps": [{"observe": "#out"}, {"click": "#go"}, {"wait": 0.3}, {"observe": "#out"}]},
    )
    assert result.ok, result.error
    text = str(result.data)
    assert "gl ok" in text and "gl failed" not in text, text
    assert "#world no context yet" in text.split("2. click")[0], text
    assert "differs from its dominant colour" in text.split("4. observe")[-1], text


# Pass 3 of the Minecraft feature run: an eval that set three flags with
# semicolons failed with "Unexpected token ';'" because the tool wrapped it as
# one expression. Statements run, and the last expression is the value.


def test_an_eval_may_hold_statements_and_returns_the_last_expression(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text(
        "<!doctype html><html><body><div id='x'>1</div></body></html>", encoding="utf-8"
    )
    result = _run(
        web_playtest.WebPlaytestTool(tmp_path),
        {
            "page": "index.html",
            "steps": [
                {
                    "eval": "window.flag = 7; document.getElementById('x').textContent = 'set'; document.getElementById('x').textContent"
                },
                {"eval": "({flag: window.flag})"},
                {"eval": "this is not javascript"},
            ],
        },
    )
    assert result.ok, result.error
    text = str(result.data)
    assert '1. eval -> "set"' in text, text
    assert '2. eval -> {"flag": 7}' in text, text
    assert "3. eval" in text and "FAILED" in text and "SyntaxError" in text, text


# "playtest exceeded 240s" three times in one evening, each time with every
# earlier step's report thrown away: the clock was checked before a step, and a
# step that began just under the limit ran past the outer timeout's 30-second
# grace. The grace covers the longest single step, and a session that ends on
# its clock still returns what it saw.


def test_a_session_that_reaches_its_clock_keeps_its_report(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "index.html").write_text(
        "<!doctype html><html><body><p id='p'>hello</p></body></html>", encoding="utf-8"
    )
    monkeypatch.setattr(web_playtest, "SESSION_SECONDS", 1.0)
    result = _run(
        web_playtest.WebPlaytestTool(tmp_path),
        {"page": "index.html", "steps": [{"observe": "#p"}, {"wait": 3}, {"observe": "#p"}]},
    )
    assert result.ok, result.error
    text = str(result.data)
    assert '1. observe "#p" -> "hello"' in text, text
    assert "2. wait 3s -> ok" in text, text
    assert "3. stopped: session wall clock of 1s reached" in text, text


# The judge held the Minecraft proof run because the screenshot the proof page
# cited for the 54-block feature was gone: retention kept twenty session
# folders and pruned it while the record still pointed at it. A session from
# the last day is evidence in use and is never pruned; only older ones beyond
# the keep count go.


def test_recent_sessions_are_never_pruned(tmp_path: Path) -> None:
    import os
    import time

    store = tmp_path / ".thomas" / "playtest"
    for i in range(30):
        (store / f"2026090{i // 10}T{i % 10:02d}0000").mkdir(parents=True)
    old = time.time() - 3 * 86400
    stale = sorted(p for p in store.iterdir())[:8]
    for p in stale:
        os.utime(p, (old, old))
    current = store / "current"
    current.mkdir()
    web_playtest._prune_old_sessions(store, keep=20, current=current)
    left = sorted(p.name for p in store.iterdir())
    assert len(left) == 31 - 8 + 0 or len(left) >= 23, left  # the 22 recent ones and current survive
    assert all(p.name not in left for p in stale), left


def _serve(directory: Path):
    """A throwaway loopback server for the directory, like the Thomas server Thomas verifies against."""
    import http.server
    import threading

    handler = type("H", (http.server.SimpleHTTPRequestHandler,), {"log_message": lambda *a, **k: None})
    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), lambda *a, **k: handler(*a, directory=str(directory), **k)
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def test_a_page_on_a_loopback_server_can_be_played_by_url(tmp_path: Path) -> None:
    """A self-edit run on the Thomas checkout was told to verify against the
    running server and could not: the tool only took a file inside the project,
    so Thomas wrote scratch pages into the product folder to get a verdict.
    A loopback URL is the running server; it is played as itself."""
    root = _workspace(tmp_path)
    # The server serves a DIFFERENT page than the one in the project folder, so
    # a pass can only come from the live server, never from folding the URL
    # into a project path and playing the file.
    served = tmp_path / "served"
    served.mkdir()
    (served / "index.html").write_text(
        """<!doctype html><title>Live</title><h1 id="title">LIVE PAGE</h1>"""
        """<button id="go" onclick="document.getElementById('title').textContent='LIVE CLICKED'">GO</button>""",
        encoding="utf-8",
    )
    server, origin = _serve(served)
    try:
        tool = web_playtest.WebPlaytestTool(root)
        result = _run(
            tool,
            {"page": f"{origin}/index.html", "steps": [{"observe": "#title"}, {"click": "GO"}, {"observe": "#title"}]},
        )
        assert result.ok, result.error
        assert "LIVE PAGE" in result.data and "LIVE CLICKED" in result.data, result.data
        assert "Garage" not in result.data
        assert "errors: none" in result.data
    finally:
        server.shutdown()


def test_a_page_on_someone_elses_server_is_still_refused(tmp_path: Path) -> None:
    tool = web_playtest.WebPlaytestTool(_workspace(tmp_path))
    result = _run(tool, {"page": "https://example.com/index.html", "steps": [{"observe": "body"}]})
    assert not result.ok and "this machine" in result.error
