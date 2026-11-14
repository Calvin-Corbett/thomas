"""Build's composer: Send / Pause / Resume / Stop, and the queue stack above it.

The Build redesign (screen 3a) makes the composer's round button Pause while a
run is going, Resume after a pause, and Send the moment anything is typed; a
message sent mid-run waits above the composer card with its own Steer and ✕,
under one status line ("Wirer is adding the corner toggle ... Step 4 of 5 ·
1m 12s").

Two halves, because neither covers the other:

* ``tests/web_node/build_composer_controls.mjs`` runs the shipped
  ``unified_code_composer.js`` with the two places that use it --
  ``syncDynamic`` in ``chat_message_view.js`` and the ``#tc-send`` click in
  ``chat_shell_bindings.js`` -- under Node: the state rule, what each state
  draws, Chat getting its button back, escaping, and that an empty-composer
  click in Build reaches the run and never falls through to a stop.
* ``test_the_stack_patches_in_place_in_a_real_page`` loads the module and its
  stylesheet into Chromium. Build re-renders on every live event and on a 1 s
  clock; if each render rebuilt the queue, a click whose mousedown landed on
  the old Steer button would be lost and the status dot's pulse would restart
  every second. Only a real DOM can show the nodes survive, focus moves to a
  sensible place when a row leaves, and the computed colours and glyphs are
  the design's. It skips where Chromium cannot launch.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "thomas" / "server" / "web"
HARNESS = ROOT / "tests" / "web_node" / "build_composer_controls.mjs"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from web_fixtures.thomas_chat_fixture import browser_ok  # noqa: E402


def test_the_composer_controls_hold_under_node() -> None:
    result = subprocess.run(
        ["node", str(HARNESS), str(WEB / "chat.html")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    checks = json.loads(result.stdout)
    failed = [name for name, ok in checks.items() if not ok]
    assert not failed, f"composer checks failed: {failed}"
    assert len(checks) >= 16


# The composer as chat.html lays it out in Build: the stack is the rail's
# sibling inside the composer wrapper, directly above it.
PAGE = """<!doctype html>
<html data-theme="dark" data-thomas-theme="dark"><head><meta charset="utf-8">
<link rel="stylesheet" href="/static/css/tokens.css">
<link rel="stylesheet" href="/static/css/unified_code_mode.css">
<link rel="stylesheet" href="/static/css/unified_code_composer.css">
<link rel="stylesheet" href="/static/css/chat_shell.css">
<script src="/static/js/unified_code_composer.js"></script>
</head>
<body style="margin:0">
<div id="tc-shell" data-surface-mode="code"
     style="width:900px;height:640px;font-family:var(--font-sans);color:var(--c-text);background:var(--c-bg);">
  <div style="height:420px"></div>
  <div data-ui-id="chat.composer" style="flex:0 0 auto;padding:6px 0 18px;">
    <div id="tc-code-composer-extras" hidden></div>
    <div id="tc-composer-rail" class="tc-rail">
      <div id="card" style="display:flex;align-items:center;gap:8px;background:var(--c-composer-bg);
           border:1px solid var(--c-border-2);border-radius:12px;padding:10px 10px 10px 14px;">
        <textarea id="tc-input" rows="1" style="flex:1;background:transparent;border:0;color:var(--c-text)"></textarea>
        <button id="tc-send" title="Send" style="width:34px;height:34px;border-radius:8px;border:0;
                background:var(--send-bg, var(--c-surface-2));color:var(--send-ink, var(--c-muted));
                opacity:var(--send-op, .85);display:grid;place-items:center;"><i id="tc-send-icon"
                class="ph ph-arrow-up" style="font-size:19px;font-weight:700;"></i></button>
      </div>
    </div>
  </div>
</div>
</body></html>"""

SCENARIO = """() => {
  const composer = window.ThomasCodeComposer;
  const root = document.getElementById('tc-code-composer-extras');
  const shell = document.getElementById('tc-shell');
  const out = {};
  const queued = [
    { id: 'q1', message: 'make the toggle a sun and moon icon' },
    { id: 'q2', message: 'also keep it in the top right' },
  ];
  const working = { words: 'Wirer is adding the corner toggle', tone: 'working', stepText: 'Step 4 of 5', elapsed: 72000 };
  // The page's one escaper is handed in (unified_code_mode.js owns it).
  const esc = value => String(value == null ? '' : value).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const clicks = [];
  composer.bind(root, { onSteer: id => clicks.push(['steer', id]), onRemove: id => clicks.push(['remove', id]) });

  out.shown = composer.render(root, { esc, queued, status: working });
  out.rootHidden = root.hidden;
  const items = root.querySelectorAll('.tc-code-queue-item');
  out.items = items.length;
  out.itemHeight = items[0].getBoundingClientRect().height;
  const steer = root.querySelector('[data-code-queue-steer="q1"]');
  const steerStyle = getComputedStyle(steer);
  out.steerBg = steerStyle.backgroundColor;
  out.steerInk = steerStyle.color;
  out.steerHeight = steer.getBoundingClientRect().height;
  out.label = getComputedStyle(root.querySelector('.tc-code-queue-label')).textTransform;
  const dot = root.querySelector('.tc-code-status-dot');
  out.dotAnimation = getComputedStyle(dot).animationName;
  out.dotBg = getComputedStyle(dot).backgroundColor;
  out.meta = root.querySelector('[data-code-status-meta]').textContent;
  const card = document.getElementById('card').getBoundingClientRect();
  const stack = root.getBoundingClientRect();
  const firstItem = items[0].getBoundingClientRect();
  out.edges = [firstItem.left - card.left, firstItem.right - card.right, card.top - stack.bottom];

  // The clock ticks and the words change: same nodes, new text.
  composer.render(root, { esc, queued, status: { ...working, words: 'Wirer is wiring the toggle', elapsed: 73000 } });
  out.sameSteer = root.querySelector('[data-code-queue-steer="q1"]') === steer;
  out.sameDot = root.querySelector('.tc-code-status-dot') === dot;
  out.metaAfter = root.querySelector('[data-code-status-meta]').textContent;
  out.wordsAfter = root.querySelector('[data-code-status-words]').textContent;

  composer.render(root, { esc, queued, status: { ...working, tone: 'paused', words: 'Paused. Agents hold after their current step.' } });
  out.pausedBg = getComputedStyle(dot).backgroundColor;
  out.pausedAnimation = getComputedStyle(dot).animationName;
  out.sameDotPaused = root.querySelector('.tc-code-status-dot') === dot;

  // Clicks come back by id.
  root.querySelector('[data-code-queue-steer="q2"]').click();
  root.querySelector('[data-code-queue-remove="q1"]').click();
  out.clicks = clicks.slice();

  // Removing the focused row puts focus on the row that took its place.
  root.querySelector('[data-code-queue-remove="q1"]').focus();
  composer.render(root, { esc, queued: [queued[1]], status: working });
  out.focusAfterRemove = document.activeElement.getAttribute('data-code-queue-remove');
  out.queueReplaced = root.querySelector('[data-code-queue-steer="q1"]') === null;

  // The last row leaves and nothing is left to say: the stack goes, and you
  // are back where you type.
  composer.render(root, { esc, queued: [], status: null });
  out.emptyHidden = root.hidden;
  out.emptyDisplay = getComputedStyle(root).display;
  out.focusWhenEmpty = document.activeElement.id;

  // Steer never passes focus to the next Steer -- a second Enter would send
  // a message nobody chose -- whether its row goes busy or leaves.
  composer.render(root, { esc, queued, status: working });
  root.querySelector('[data-code-queue-steer="q1"]').focus();
  composer.render(root, { esc, queued: [{ ...queued[0], busy: true }, queued[1]], status: working });
  out.focusAfterSteerBusy = document.activeElement.id;
  root.querySelector('[data-code-queue-steer="q2"]').focus();
  composer.render(root, { esc, queued: [queued[0]], status: working });
  out.focusAfterSteerLeft = document.activeElement.id;

  // Never above Chat's composer, whatever its hidden flag says.
  composer.render(root, { esc, queued, status: working });
  shell.dataset.surfaceMode = 'chat';
  out.chatDisplay = getComputedStyle(root).display;
  shell.dataset.surfaceMode = 'code';

  // The status line has no Stop: the primary button is the control.
  composer.render(root, { esc, queued: [], status: { ...working, tone: 'paused', stoppable: true } });
  out.stopButtons = root.querySelectorAll('[data-code-stop], .tc-code-status-stop, .tc-code-status button').length;

  // The primary button.
  const send = document.getElementById('tc-send');
  const icon = document.getElementById('tc-send-icon');
  // Each state's icon is the design's SVG drawn as a mask: [mask, width].
  const drawn = () => {
    const before = getComputedStyle(icon, '::before');
    return [String(before.webkitMaskImage || before.maskImage || ''), before.width, before.content];
  };
  const ctx = { running: true, paused: false, canPause: true, hasText: false };
  composer.applyPrimary(send, icon, composer.primaryState(ctx), ctx);
  out.pauseIcon = drawn();
  out.pauseBg = getComputedStyle(send).backgroundColor;
  out.pauseName = send.getAttribute('aria-label');
  const typed = { ...ctx, hasText: true };
  composer.applyPrimary(send, icon, composer.primaryState(typed), typed);
  out.sendIcon = drawn();
  out.sendBg = getComputedStyle(send).backgroundColor;
  const paused = { ...ctx, paused: true };
  composer.applyPrimary(send, icon, composer.primaryState(paused), paused);
  out.resumeIcon = drawn();
  const noPause = { ...ctx, canPause: false };
  composer.applyPrimary(send, icon, composer.primaryState(noPause), noPause);
  out.stopIcon = drawn();
  // Off Build the icon map's own glyphs are untouched (Work's pause button).
  composer.clearPrimary(send);
  icon.className = 'ph ph-pause';
  out.mapPauseIcon = drawn();
  out.clearedTitle = send.getAttribute('title');
  return out;
}"""


def _serve_static(route) -> None:
    """The page's /static tree, from the shipped files (tokens.css @imports a sibling)."""
    relative = route.request.url.split("/static/", 1)[1].split("?", 1)[0]
    path = (WEB / relative).resolve()
    if WEB.resolve() not in path.parents or not path.is_file():
        route.fulfill(status=404, body="")
        return
    kind = "text/css" if path.suffix == ".css" else "text/javascript"
    route.fulfill(status=200, content_type=kind, body=path.read_bytes())


def test_the_stack_patches_in_place_in_a_real_page() -> None:
    if not browser_ok():
        pytest.skip("Chromium cannot launch here")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 900, "height": 640})
            errors: list[str] = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.route("http://thomas.test/static/**", _serve_static)
            page.route(
                "http://thomas.test/",
                lambda route: route.fulfill(status=200, content_type="text/html", body=PAGE),
            )
            page.goto("http://thomas.test/", wait_until="load")
            out = page.evaluate(SCENARIO)
        finally:
            browser.close()

    assert not errors, errors
    assert out["shown"] is True and out["rootHidden"] is False
    assert out["items"] == 2
    # Design: 6px padding around a 26px Steer, 1px border -> a 40px row.
    assert 39 <= out["itemHeight"] <= 41, out["itemHeight"]
    assert out["steerHeight"] == 26
    assert out["steerBg"] == "rgb(110, 155, 255)", "Steer is the accent fill"
    assert out["steerInk"] == "rgb(11, 16, 32)"
    assert out["label"] == "none"
    assert out["dotAnimation"] == "tc-code-status-pulse"
    assert out["dotBg"] == "rgb(110, 155, 255)"
    assert out["meta"] == "Step 4 of 5 · 1m 12s"
    # The stack sits on the card's own edges, 6px above it.
    left, right, gap = out["edges"]
    assert abs(left) <= 1 and abs(right) <= 1, out["edges"]
    assert abs(gap - 6) <= 1, out["edges"]

    assert out["sameSteer"], "a clock tick rebuilt the Steer button under the pointer"
    assert out["sameDot"], "a clock tick restarted the status dot's pulse"
    assert out["metaAfter"] == "Step 4 of 5 · 1m 13s"
    assert out["wordsAfter"] == "Wirer is wiring the toggle"
    assert out["pausedBg"] == "rgb(226, 178, 95)", "paused is the warn dot"
    assert out["pausedAnimation"] == "none"
    assert out["sameDotPaused"]
    # No Stop on the status line; the primary button is Pause / Resume (Stop only when a run cannot pause).
    assert out["stopButtons"] == 0

    assert out["clicks"] == [["steer", "q2"], ["remove", "q1"]]
    assert out["queueReplaced"]
    assert out["focusAfterRemove"] == "q2"
    assert out["emptyHidden"] is True and out["emptyDisplay"] == "none"
    assert out["focusWhenEmpty"] == "tc-input"
    assert out["focusAfterSteerBusy"] == "tc-input"
    assert out["focusAfterSteerLeft"] == "tc-input"
    assert out["chatDisplay"] == "none"

    assert out["pauseName"] == "Pause"
    assert out["pauseBg"] == "rgba(255, 255, 255, 0.07)", "Pause is the neutral fill"
    assert out["sendBg"] == "rgb(110, 155, 255)", "Send with text is the accent fill"
    # The design's own shapes, at the design's sizes: two bars, the arrow's
    # stroke path, a triangle, a square -- never the bullet a missing glyph is.
    icons = {name: out[f"{name}Icon"] for name in ("pause", "send", "resume", "stop")}
    for name, (mask, width, content) in icons.items():
        assert "data:image/svg+xml" in mask, f"{name} is not drawn: {mask!r}"
        assert content == '""', f"{name} still prints a glyph over its drawing"
    assert icons["pause"][0].count("rect") == 2 and icons["pause"][1] == "14px"
    assert "M12 19V5" in icons["send"][0] and icons["send"][1] == "16px"
    assert "M7 5v14l12-7z" in icons["resume"][0] and icons["resume"][1] == "14px"
    assert "rect" in icons["stop"][0] and icons["stop"][1] == "14px"
    mask, _width, content = out["mapPauseIcon"]
    assert content == '"‖"' and mask in ("", "none"), "the icon map's pause is untouched outside Build"
    assert out["clearedTitle"] == "Send"
