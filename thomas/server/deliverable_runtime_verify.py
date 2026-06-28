"""Runtime smoke-load verification for generated web deliverables.

Static verification (`deliverable_verify`) confirms files EXIST and references
resolve. But an app can have every file present and still render blank — a JS
error on load, a canvas that never draws, a runtime 404. Claude Code's defining
discipline is to actually OPEN the thing and watch it run; this is that step.

It serves the deliverable over a throwaway loopback HTTP server (so sub-resources
load exactly as a browser would fetch them) and loads the entry in headless
Chromium, capturing uncaught page errors and confirming the page rendered real
content (visible text, a drawn canvas, or a non-trivial DOM). It is best-effort
and time-boxed: if a browser is unavailable or the check itself errors, it returns
``skipped`` and never blocks the finalize path.

This is the capability that would have caught the football game's blank screen had
the cause been a JS crash rather than a header (and catches that whole class now).
"""

from __future__ import annotations

import functools
import http.server
import re
import socket
import threading
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class RuntimeResult:
    ok: bool
    skipped: bool = False
    reason: str = ""
    entry: str = ""
    page_errors: list[str] = field(default_factory=list)
    console_errors: list[str] = field(default_factory=list)
    rendered_chars: int = 0
    canvas_drawn: bool = False
    dom_nodes: int = 0

    def summary(self) -> str:
        if self.skipped:
            return f"runtime check skipped ({self.reason})"
        if self.ok:
            return f"runtime OK: {self.entry} rendered ({self.rendered_chars} chars / canvas={self.canvas_drawn}), 0 errors"
        if self.page_errors:
            return f"runtime FAILED: JS error on load — {self.page_errors[0][:160]}"
        return f"runtime FAILED: {self.reason or 'app rendered blank'}"


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args: object) -> None:  # silence access logs
        return


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = int(s.getsockname()[1])
    s.close()
    return port


_RENDER_PROBE_JS = """
() => {
  const rgb = (s) => { const m = (s||'').match(/rgba?\\(([^)]+)\\)/); if (!m) return null;
    const p = m[1].split(',').map(x => parseFloat(x)); return {r:p[0],g:p[1],b:p[2],a:p[3]===undefined?1:p[3]}; };
  const effBg = (el) => { let e = el; while (e) { const c = rgb(getComputedStyle(e).backgroundColor);
    if (c && c.a > 0.05) return c; e = e.parentElement; } return {r:255,g:255,b:255,a:1}; };
  const visibleEl = (el) => { const s = getComputedStyle(el);
    return !(s.display==='none' || s.visibility==='hidden' || parseFloat(s.opacity)===0); };
  const root = document.body || document.documentElement;
  let visText = 0, allText = '';
  if (root) {
    const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let node;
    while (node = w.nextNode()) {
      const t = (node.textContent || '').trim(); if (!t) continue;
      const el = node.parentElement; if (!el || !visibleEl(el)) continue;
      const fg = rgb(getComputedStyle(el).color) || {r:0,g:0,b:0,a:1};
      const bg = effBg(el);
      const diff = Math.abs(fg.r-bg.r) + Math.abs(fg.g-bg.g) + Math.abs(fg.b-bg.b);
      if (fg.a > 0.05 && diff > 30) { visText += t.length; allText += t + ' '; }   // skip invisible / no-contrast
    }
  }
  const loadingOnly = visText > 0 &&
    /^(loading|please wait|initial\\w*|starting|booting|spinner|one moment|fetching)\\b/i.test(allText.trim());
  const hasApp = !!(root && root.querySelector('canvas,svg,video,audio,form,input,button,select,textarea,table,img[src]'));
  let canvasDrawn = false;
  for (const c of (root ? root.querySelectorAll('canvas') : [])) {
    try {
      const ctx = c.getContext('2d');
      if (!ctx) { canvasDrawn = true; break; }
      const w = Math.min(c.width, 200), h = Math.min(c.height, 200);
      if (w < 1 || h < 1) continue;
      const d = ctx.getImageData(0, 0, w, h).data;
      const first = d[0] + ',' + d[1] + ',' + d[2] + ',' + d[3];
      for (let i = 0; i < d.length; i += 64) {   // dense sample (~every 16px) so small fills are caught
        if ((d[i] + ',' + d[i+1] + ',' + d[i+2] + ',' + d[i+3]) !== first) { canvasDrawn = true; break; }
      }
      if (canvasDrawn) break;
    } catch (e) { canvasDrawn = true; break; }
  }
  const dom = root ? root.querySelectorAll('*').length : 0;
  return { visText, loadingOnly, hasApp, canvasDrawn, dom };
}
"""


def runtime_smoke_load(root: str | Path, entry: str = "index.html", *, timeout_ms: int = 6000) -> RuntimeResult:
    """Load a web deliverable in headless Chromium and confirm it runs.

    Fails when the entry raises an uncaught JS error on load, or renders blank
    (no visible text, no drawn canvas, trivial DOM). Skips cleanly when Playwright
    or a browser is unavailable.
    """
    root = Path(root)
    entry_path = root / entry
    if not entry_path.is_file():
        htmls = sorted(root.glob("*.html"))
        if not htmls:
            return RuntimeResult(ok=False, entry=entry, reason=f"no entry document ({entry})")
        entry_path = htmls[0]
        entry = entry_path.name

    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:  # noqa: BLE001
        return RuntimeResult(ok=True, skipped=True, entry=entry, reason=f"playwright unavailable: {e}")

    port = _free_port()
    handler = functools.partial(_QuietHandler, directory=str(root))
    try:
        httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    except OSError as e:
        return RuntimeResult(ok=True, skipped=True, entry=entry, reason=f"could not bind server: {e}")

    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    page_errors: list[str] = []
    console_errors: list[str] = []
    failed_assets: list[str] = []
    base = f"http://127.0.0.1:{port}"

    def _on_response(resp) -> None:
        try:
            if resp.status >= 400 and resp.url.startswith(base):
                failed_assets.append(f"{resp.status} {resp.url[len(base) :]}")
        except Exception:  # noqa: BLE001
            pass

    sig: dict = {}
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.on("pageerror", lambda exc: page_errors.append(str(exc)))
                page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
                page.on("response", _on_response)
                page.goto(f"{base}/{entry}", wait_until="load", timeout=timeout_ms)
                # Poll across a settle WINDOW (not a single 800ms sample): catch content
                # that renders late (fetch/async) AND crashes that fire seconds after load.
                best = {"visText": 0, "loadingOnly": True, "hasApp": False, "canvasDrawn": False, "dom": 0}
                waited, window_ms, step = 0, 3000, 500
                while waited < window_ms and not page_errors:
                    page.wait_for_timeout(step)
                    waited += step
                    s = page.evaluate(_RENDER_PROBE_JS)
                    better = (
                        (int(s.get("visText", 0) or 0) > int(best["visText"]))
                        or (s.get("canvasDrawn") and not best["canvasDrawn"])
                        or (s.get("hasApp") and not best["hasApp"])
                    )
                    if better:
                        best = s
                sig = best
            finally:
                browser.close()
    except Exception as e:  # noqa: BLE001 — a check failure must never block finalize
        return RuntimeResult(ok=True, skipped=True, entry=entry, reason=f"runtime check error: {type(e).__name__}: {e}")
    finally:
        httpd.shutdown()

    rendered_chars = int(sig.get("visText", 0) or 0)
    dom_nodes = int(sig.get("dom", 0) or 0)
    canvas_drawn = bool(sig.get("canvasDrawn", False))
    loading_only = bool(sig.get("loadingOnly", False))
    has_app = bool(sig.get("hasApp", False))

    def _result(ok: bool, reason: str = "") -> RuntimeResult:
        return RuntimeResult(
            ok=ok,
            entry=entry,
            page_errors=page_errors,
            console_errors=console_errors,
            rendered_chars=rendered_chars,
            canvas_drawn=canvas_drawn,
            dom_nodes=dom_nodes,
            reason=reason,
        )

    # An uncaught JS error ANY time in the window means the app crashed -> not runnable.
    if page_errors:
        return _result(False, "uncaught JS error during load/run")
    # A 404 on a first-party script/style/data file -> the app is missing a load-bearing
    # asset (a perpetual "Loading…" skeleton would otherwise pass).
    _broken = [a for a in failed_assets if re.search(r"\.(?:m?js|css|json|wasm)(?:\?|$)", a, re.I)]
    if _broken:
        return _result(False, f"failed to load required asset(s): {', '.join(_broken[:3])}")
    # Real, visible content? (loading spinners, invisible text, and empty scaffolding
    # do NOT count.)
    has_real_content = (rendered_chars >= 1 and not loading_only) or canvas_drawn or (has_app and dom_nodes >= 5)
    if not has_real_content:
        why = "still showing a loading placeholder" if loading_only else "no visible content (blank/invisible render)"
        return _result(False, f"app rendered nothing usable — {why}")
    return _result(True)
