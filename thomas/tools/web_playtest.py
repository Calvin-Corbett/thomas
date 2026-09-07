"""``web.playtest``: play the page you wrote, in a real browser, and read back what happened.

Why this exists: on the Mario Kart build Thomas wrote "I'm not claiming the game
is verified fixed because this workspace gave me no browser-control tool." He
was right. The edit-only toolset could not press START or hold accelerate, the
engine's smoke check presses one control and looks for paint, and it passed a
race that ended three seconds after GO with every kart at 0:00.00, then passed
the next version where the circuit had vanished. Nobody in the loop could drive.

The session is offline and bounded: the page and its own web assets are served
from the workspace through the shared allowlist (``thomas.core.web_asset_policy``),
every other host is refused, steps are capped, and the whole session has a
wall clock. Each step reports the text observed, page errors since the last
step, and how much of every canvas is painted. Screenshots land under the
workspace's ``.thomas/playtest`` folder so a person can look too.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import mimetypes
import os
import re
import time
from pathlib import Path
from typing import Any

from thomas.core.web_asset_policy import safe_web_path
from thomas.tools.base import Tool, ToolResult
from thomas.tools.web_preflight import first_unresolved_root_link

try:  # the browser driver is optional; without it the tool says how to install it
    from playwright.async_api import Error as PlaywrightError
except ImportError:  # pragma: no cover - exercised only where playwright is absent

    class PlaywrightError(Exception):
        """Stand-in so the except clauses below stay specific without the driver."""


# What a headless session can raise: the driver's own errors, the OS refusing
# to launch, the session's own clock, and a step that names a bad value.
_PLAYTEST_ERRORS = (PlaywrightError, OSError, RuntimeError, ValueError, TypeError, asyncio.TimeoutError)

ORIGIN_HOST = "thomas-playtest.invalid"
ORIGIN = f"http://{ORIGIN_HOST}"
# A page served by a server on this machine, played as itself.
_LOOPBACK_URL = re.compile(r"^https?://(127\.0\.0\.1|localhost)(:\d{1,5})?(/.*)?$", re.IGNORECASE)


def _origin_of(url: str) -> str:
    match = re.match(r"^(https?://[^/]+)", url, re.IGNORECASE)
    return match.group(1) if match else ""


MAX_STEPS = 80  # a race script with an observe after every hold ran past 40 on its first live use
MAX_HOLD_SECONDS = 60.0
MAX_WAIT_SECONDS = 60.0
SESSION_SECONDS = 480.0  # a full race or a creative-mode tour ran past 240 s three times on 2026-09-05
KEEP_SESSIONS = 20  # screenshot folders kept under .thomas/playtest beyond the last day
RECENT_SESSION_SECONDS = 86400.0  # a session from the last day is never pruned
OBSERVE_CHARS = 1500
STEP_KINDS = ("click", "press", "hold", "type", "wait", "observe", "eval", "screenshot")

# Alpha > 0 pixels, sampled every 4th pixel in each direction, per canvas. A
# WebGL canvas without preserveDrawingBuffer reads back blank; say so rather
# than call it unpainted.
_CANVAS_JS = """() => Array.from(document.querySelectorAll('canvas')).map((c) => {
  const id = c.id ? '#' + c.id : 'canvas';
  try {
    const kind = c.__thomasContext;
    if (!kind) { return { id, kind: 'none', note: 'no context yet' }; }
    if (kind !== '2d') { return { id, kind: 'webgl', note: 'not readable (WebGL); use observe on the HUD instead' }; }
    const ctx = c.getContext('2d');
    const w = c.width, h = c.height; if (!w || !h) { return { id, painted: 0, total: 0 }; }
    const data = ctx.getImageData(0, 0, w, h).data; let painted = 0, total = 0;
    for (let y = 0; y < h; y += 4) { for (let x = 0; x < w; x += 4) { total++; if (data[(y * w + x) * 4 + 3] > 0) painted++; } }
    return { id, painted: painted * 16, total: total * 16 };
  } catch (e) { return { id, note: 'unreadable: ' + String(e) }; }
})"""


_HONEST_ARGS = (
    "--disable-blink-features=AutomationControlled",
    "--use-gl=angle",
    "--use-angle=swiftshader",
    "--enable-unsafe-swiftshader",
)
_PERSON_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)
_HIDE_WEBDRIVER_JS = "Object.defineProperty(navigator, 'webdriver', { get: () => false, configurable: true });"
# Measuring must never claim a canvas: asking a context-less canvas for '2d'
# makes it a 2D canvas, and the game's later WebGL request fails ("Canvas has an
# existing context of a different type"). The page's own getContext calls are
# recorded instead, and the probe reads the record.
_TRACK_CONTEXT_JS = """(() => {
  const original = HTMLCanvasElement.prototype.getContext;
  HTMLCanvasElement.prototype.getContext = function (kind, ...rest) {
    const ctx = original.call(this, kind, ...rest);
    if (ctx && !this.__thomasContext) { this.__thomasContext = String(kind); }
    return ctx;
  };
})();"""


def _browsers_dir() -> Path:
    env = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "").strip()
    if env:
        return Path(env).expanduser()
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "ms-playwright"
    if os.uname().sysname == "Darwin":  # pragma: no cover - platform specific
        return Path.home() / "Library" / "Caches" / "ms-playwright"
    return Path.home() / ".cache" / "ms-playwright"


def playtest_available() -> bool:
    """Playwright is importable and a Chromium it can launch is installed."""
    if importlib.util.find_spec("playwright") is None:
        return False
    try:
        return any(p.is_dir() and p.name.startswith("chromium") for p in _browsers_dir().iterdir())
    except OSError:
        return False


def _validate_steps(raw: Any) -> list[dict[str, Any]] | str:
    if not isinstance(raw, list):
        return "steps must be a list of step objects"
    if len(raw) > MAX_STEPS:
        return (
            f"at most {MAX_STEPS} steps per session ({len(raw)} given): merge consecutive holds into one longer "
            "hold and observe less often, or split the script across two calls"
        )
    steps: list[dict[str, Any]] = []
    for index, step in enumerate(raw, 1):
        if not isinstance(step, dict) or not step:
            return f"step {index} must be an object with one action"
        kinds = [k for k in step if k in STEP_KINDS]
        if len(kinds) != 1:
            unknown = ", ".join(sorted(k for k in step if k not in {"seconds", "into", "exact"}))
            return f"step {index} names no known action ({unknown}); use one of {', '.join(STEP_KINDS)}"
        steps.append(step)
    return steps


class WebPlaytestTool(Tool):
    name = "web.playtest"
    category = "web"
    description = (
        "Play an HTML page from this project in a real headless browser and read back what happened. "
        'Steps run in order: {"click": "button text or CSS selector"}, {"press": "Enter"}, '
        '{"hold": "w" or ["w", "ArrowUp"], "seconds": 5}, {"type": "text", "into": "CSS"}, '
        '{"wait": 2}, {"observe": "CSS selector or body"}, {"eval": "JS expression"}, '
        '{"screenshot": "name"}. Every step reports the text it saw, page errors, and how much of each '
        "canvas is painted. The page's own files are served; the internet is not. Use it to prove a game "
        "or app actually works before saying so."
    )
    parameters = {
        "type": "object",
        "properties": {
            "page": {
                "type": "string",
                "description": "HTML file relative to the project root (e.g. index.html), or the URL of a page on a server running on this machine (http://127.0.0.1:<port>/...)",
            },
            "steps": {"type": "array", "items": {"type": "object"}, "description": "Actions to perform in order"},
            "viewport": {
                "type": "object",
                "properties": {"width": {"type": "integer"}, "height": {"type": "integer"}},
                "description": "Browser size (default 1280x720)",
            },
        },
        "required": ["page", "steps"],
    }

    def __init__(self, root: Path):
        self._root = Path(root).resolve()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        page_rel = str(args.get("page") or "").strip().replace("\\", "/")
        # A server on this machine is played as itself: a self-edit run on the
        # Thomas checkout was told to verify against the running server and
        # could not, so it wrote scratch pages into the product folder instead.
        live_url = page_rel if _LOOPBACK_URL.match(page_rel) else ""
        if not live_url and re.match(r"^https?://", page_rel, re.IGNORECASE):
            return ToolResult(
                ok=False,
                error=f"only a server on this machine (127.0.0.1 or localhost) can be played by URL: {page_rel}",
            )
        target = None if live_url else (safe_web_path(self._root, page_rel) if page_rel else None)
        if not live_url and (target is None or target.suffix.lower() not in {".html", ".htm"}):
            return ToolResult(ok=False, error=f"page must be an HTML file inside the project: {page_rel or '(empty)'}")
        # A served page (root-absolute links that resolve nowhere on disk, like
        # Thomas's own chat.html and its /static/ modules) can only be played
        # on the server that mounts it. Played from disk it fails for reasons
        # unrelated to the change, and a run then "fixes" the page for the
        # scratch server. Refuse before a browser starts and say what to do.
        if target is not None:
            missing = first_unresolved_root_link(self._root, target)
            if missing:
                return ToolResult(
                    ok=False,
                    error=(
                        f"{page_rel} is a served page: it links {missing}, which exists only when a server mounts it, "
                        "so it cannot be played from disk. Play the running server instead: pass page as its loopback "
                        "URL, e.g. page=http://127.0.0.1:<port>/ (the brief names the port)."
                    ),
                )
        steps = _validate_steps(args.get("steps") if args.get("steps") is not None else [])
        if isinstance(steps, str):
            return ToolResult(ok=False, error=steps)
        if not playtest_available():
            return ToolResult(
                ok=False,
                error="web.playtest needs the playwright package and its Chromium: pip install playwright && playwright install chromium",
            )
        viewport = args.get("viewport") if isinstance(args.get("viewport"), dict) else {}
        width = int(viewport.get("width") or 1280)
        height = int(viewport.get("height") or 720)
        started = time.monotonic()
        self._partial: list[str] = []
        # The grace past the session clock covers the browser launch and the
        # longest single step: a hold that began just under the limit used to
        # run into the outer timeout, and every earlier step's report was lost.
        grace = MAX_HOLD_SECONDS + MAX_WAIT_SECONDS + 60
        try:
            data = await asyncio.wait_for(
                self._session(target, steps, width, height, started, live_url=live_url), timeout=SESSION_SECONDS + grace
            )
        except asyncio.TimeoutError:
            seen = "\n".join(self._partial)
            return ToolResult(
                ok=False,
                error=f"playtest exceeded {int(SESSION_SECONDS)}s and was cut off; what it saw before that:\n{seen}",
            )
        except _PLAYTEST_ERRORS as exc:  # the browser's failure is the result
            return ToolResult(ok=False, error=f"playtest could not run: {type(exc).__name__}: {exc}")
        return ToolResult(ok=True, data=data, duration_ms=(time.monotonic() - started) * 1000.0)

    async def _session(
        self,
        target: Path | None,
        steps: list[dict[str, Any]],
        width: int,
        height: int,
        started: float,
        *,
        live_url: str = "",
    ) -> str:
        from playwright.async_api import async_playwright

        root = self._root
        errors: list[str] = []
        blocked: list[str] = []
        live_origin = _origin_of(live_url) if live_url else ""
        shown = live_url if live_url else target.relative_to(root).as_posix()
        lines: list[str] = [f"web.playtest {shown} (viewport {width}x{height})"]
        self._partial = lines
        shot_dir = root / ".thomas" / "playtest" / time.strftime("%Y%m%dT%H%M%S")

        async def route(route_obj: Any, request: Any) -> None:
            url = str(request.url)
            if live_origin and (url == live_origin or url.startswith(live_origin + "/")):
                await route_obj.continue_()  # the running server answers for its own pages
                return
            if not url.startswith(ORIGIN + "/") and url != ORIGIN:
                await route_obj.abort("blockedbyclient")
                return
            served = safe_web_path(root, url[len(ORIGIN) :])
            if served is None:
                await route_obj.fulfill(status=404, body="not served")
                return
            content_type = mimetypes.guess_type(str(served))[0] or "application/octet-stream"
            await route_obj.fulfill(status=200, body=served.read_bytes(), content_type=content_type)

        async with async_playwright() as pw:
            # The player looks like a person's browser. The Minecraft build read
            # navigator.webdriver and "HeadlessChrome" and never started its
            # renderer under automation: a void for every verifier, a world for
            # a person. A page must not be able to tell who is playing.
            browser = await pw.chromium.launch(headless=True, args=list(_HONEST_ARGS))
            try:
                context = await browser.new_context(viewport={"width": width, "height": height}, user_agent=_PERSON_UA)
                await context.add_init_script(_HIDE_WEBDRIVER_JS)
                await context.add_init_script(_TRACK_CONTEXT_JS)
                await context.route("**/*", route)
                page = await context.new_page()
                page.on("pageerror", lambda e: errors.append(f"page error: {e}"))
                # A request this sandbox refused is a note, not the page's error:
                # the page may handle it fine, and calling it an error sends the
                # model off to "fix" a fetch that only fails offline.
                page.on(
                    "console",
                    lambda m: (
                        errors.append(f"console.{m.type}: {m.text}")
                        if m.type == "error" and "ERR_BLOCKED_BY_CLIENT" not in m.text
                        else None
                    ),
                )
                page.on(
                    "requestfailed",
                    lambda r: (
                        blocked.append(str(r.url)[:200])
                        if "BLOCKED_BY_CLIENT" in str(getattr(r, "failure", "") or "")
                        else None
                    ),
                )
                await page.goto(live_url or f"{ORIGIN}/{target.relative_to(root).as_posix()}", wait_until="load")
                await page.wait_for_timeout(300)
                reported = 0
                clock = time.monotonic()  # the session's budget starts once the page is up, not at browser launch
                for index, step in enumerate(steps, 1):
                    if time.monotonic() - clock > SESSION_SECONDS:
                        lines.append(f"{index}. stopped: session wall clock of {int(SESSION_SECONDS)}s reached")
                        break
                    try:
                        outcome = await self._run_step(page, step, shot_dir, index)
                    except _PLAYTEST_ERRORS as exc:
                        # The step's failure is a fact about the page; the steps
                        # before it saw real things, and one failed click must
                        # not throw them away.
                        kind = next(k for k in step if k in STEP_KINDS)
                        reason = str(exc).strip().splitlines()[0][:300] if str(exc).strip() else type(exc).__name__
                        lines.append(f"{index}. {kind} {json.dumps(step[kind])[:120]} -> FAILED: {reason}")
                        lines.append(f"stopped at step {index}; later steps did not run")
                        break
                    lines.append(f"{index}. {outcome}")
                    if len(errors) > reported:
                        lines.extend(f"   {e[:400]}" for e in errors[reported:])
                        reported = len(errors)
                    paint = await self._paint_line(page)
                    if paint:
                        lines.append(f"   {paint}")
            finally:
                await browser.close()
        lines.append("errors: " + (f"{len(errors)} (listed above)" if errors else "none"))
        if blocked:
            unique = list(dict.fromkeys(blocked))[:8]
            lines.append(
                f"blocked by the offline sandbox (not an error of the page): {len(unique)} request(s): "
                + ", ".join(unique)
            )
        report = "\n".join(lines)
        # The full report lives with the session: a judge reading a truncated
        # tool preview ruled "inconclusive" on a race whose sixth finisher was
        # past the 2000th character.
        try:
            shot_dir.mkdir(parents=True, exist_ok=True)
            _prune_old_sessions(shot_dir.parent, keep=KEEP_SESSIONS, current=shot_dir)
            (shot_dir / "report.txt").write_text(report, encoding="utf-8")
        except OSError:  # a report that cannot be saved is still returned to the caller
            pass
        return report

    async def _run_step(self, page: Any, step: dict[str, Any], shot_dir: Path, index: int) -> str:
        kind = next(k for k in step if k in STEP_KINDS)
        value = step[kind]
        if kind == "click":
            selector = str(value)
            if _looks_like_css(selector):
                await page.locator(selector).first.click(timeout=5000)
                return f'click "{selector}" -> ok'
            # Text: the visible exact match first, then a visible partial match.
            # Live, "GARAGE" resolved to the hidden pause-menu "QUIT TO GARAGE"
            # and the click waited five seconds for a button that never showed.
            for exact in (True, False):
                candidates = page.get_by_text(selector, exact=exact)
                for index in range(min(await candidates.count(), 12)):
                    candidate = candidates.nth(index)
                    if await candidate.is_visible():
                        await candidate.click(timeout=5000)
                        return f'click "{selector}" -> ok' + ("" if exact else " (partial text match)")
            await page.get_by_text(selector).first.click(timeout=5000)  # let the driver say why
            return f'click "{selector}" -> ok'
        if kind == "press":
            await page.keyboard.press(str(value))
            return f"press {value} -> ok"
        if kind == "hold":
            keys = hold_keys(value)
            seconds = min(MAX_HOLD_SECONDS, max(0.05, float(step.get("seconds") or 1.0)))
            for key in keys:
                await page.keyboard.down(key)
            # Keep the key event stream alive for pages that read keydown
            # rather than a held-state map; one repeat every 50 ms like a keyboard.
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                await page.wait_for_timeout(50)
                for key in keys:
                    await page.keyboard.down(key)
            for key in keys:
                await page.keyboard.up(key)
            return f"hold {'+'.join(keys)} {seconds:g}s -> ok"
        if kind == "type":
            into = str(step.get("into") or "")
            if into:
                await page.locator(into).first.fill(str(value), timeout=5000)
            else:
                await page.keyboard.type(str(value))
            return f'type into "{into or "focused element"}" -> ok'
        if kind == "wait":
            seconds = min(MAX_WAIT_SECONDS, max(0.0, float(value)))
            await page.wait_for_timeout(int(seconds * 1000))
            return f"wait {seconds:g}s -> ok"
        if kind == "observe":
            selector = str(value or "body")
            text = await page.evaluate(
                "(sel) => { const el = document.querySelector(sel); return el ? (el.innerText || el.textContent || '') : null; }",
                selector,
            )
            if text is None:
                return f'observe "{selector}" -> no such element'
            text = re.sub(r"\s+", " ", str(text)).strip()
            return f'observe "{selector}" -> "{text[:OBSERVE_CHARS]}"' + (" ..." if len(text) > OBSERVE_CHARS else "")
        if kind == "eval":
            result = await page.evaluate(_eval_source(str(value)))
            return f"eval -> {json.dumps(result, default=str)[:OBSERVE_CHARS]}"
        if kind == "screenshot":
            shot_dir.mkdir(parents=True, exist_ok=True)
            _prune_old_sessions(shot_dir.parent, keep=KEEP_SESSIONS, current=shot_dir)
            name = re.sub(r"[^A-Za-z0-9_-]+", "-", str(value or "shot")).strip("-") or "shot"
            path = shot_dir / f"{index:02d}-{name}.png"
            await page.screenshot(path=str(path))
            return f"screenshot -> {path}"
        return f"{kind} -> unsupported"

    async def _paint_line(self, page: Any) -> str:
        try:
            stats = await page.evaluate(_CANVAS_JS)
        except _PLAYTEST_ERRORS:  # a page mid-navigation has no canvases to read
            return ""
        parts = []
        for row in stats or []:
            if "painted" in row:
                total = int(row.get("total") or 0)
                painted = int(row.get("painted") or 0)
                pct = (100 * painted // total) if total else 0
                parts.append(f"{row.get('id')} {painted} px of {total} ({pct}%)")
            elif row.get("kind") == "none":
                parts.append(f"{row.get('id')} no context yet")
            elif row.get("kind") == "webgl":
                # A WebGL canvas cannot be read back; what it shows can be
                # photographed. A world that never renders is a flat colour.
                parts.append(f"{row.get('id')} {await self._shown_line(page, str(row.get('id')))}")
            else:
                parts.append(f"{row.get('id')} {row.get('note')}")
        return f"canvas painted: {'; '.join(parts)}" if parts else ""

    async def _shown_line(self, page: Any, canvas_id: str) -> str:
        try:
            from PIL import Image
        except ImportError:
            return "not readable (WebGL); pillow is not installed, so use observe on the HUD instead"
        import io

        try:
            png = await page.locator(canvas_id).first.screenshot(timeout=5000)
            image = Image.open(io.BytesIO(png)).convert("RGB")
        except _PLAYTEST_ERRORS + (OSError,):
            return "not readable (WebGL); the canvas could not be photographed"
        small = image.resize((max(1, image.width // 4), max(1, image.height // 4)))
        colours = small.getcolors(small.width * small.height) or []
        if not colours:
            return "0% of the canvas differs from its dominant colour"
        dominant = max(count for count, _ in colours)
        differing = 100 - (100 * dominant // (small.width * small.height))
        return f"{differing}% of the canvas differs from its dominant colour"


def _eval_source(value: str) -> str:
    """The page function for an ``eval`` step. One expression is returned as it
    is; a script with statements runs them and returns its last expression
    ("window.flag = 7; ...; document.title" gave "Unexpected token ';'" when the
    whole thing was wrapped as one expression)."""
    text = value.strip().rstrip(";").strip()
    head, sep, tail = text.rpartition(";")
    if sep and tail.strip() and not tail.strip().startswith(("return ", "return(")):
        return f"async () => {{ {head}; return ({tail.strip()}); }}"
    if sep:
        return f"async () => {{ {text}; }}"
    return f"async () => ({text})"


def hold_keys(value: Any) -> list[str]:
    """The keys a ``hold`` step presses together: a list, or one string joined
    with ``+`` the way people write chords ("w+ArrowUp", "Shift+W"); a lone
    ``+`` is the plus key."""

    if isinstance(value, list):
        keys = [str(k) for k in value if str(k)]
    else:
        text = str(value)
        keys = [k for k in text.split("+") if k] if len(text) > 1 else [text]
    return keys[:4]


def recent_reports(root: Path, *, limit: int = 3) -> list[str]:
    """The newest saved session reports under ``.thomas/playtest``, oldest first."""

    store = Path(root) / ".thomas" / "playtest"
    try:
        sessions = sorted(p for p in store.iterdir() if p.is_dir())
    except OSError:
        return []
    out: list[str] = []
    for session in sessions[-max(0, int(limit)) :]:
        try:
            out.append((session / "report.txt").read_text(encoding="utf-8"))
        except OSError:
            continue
    return out


def _prune_old_sessions(store: Path, *, keep: int, current: Path) -> None:
    """Keep the newest ``keep`` session folders under the playtest store, and
    every folder from the last day whatever the count. A session is evidence in
    use: the judge held a run because the screenshot its proof page cited had
    been pruned from under it while the record still pointed at it."""
    import shutil

    try:
        sessions = sorted(p for p in store.iterdir() if p.is_dir() and p != current)
    except OSError:
        return
    cutoff = time.time() - RECENT_SESSION_SECONDS
    for old in sessions[: max(0, len(sessions) - (keep - 1))]:
        try:
            if old.stat().st_mtime >= cutoff:
                continue  # evidence from the last day stays, however many there are
        except OSError:
            continue
        shutil.rmtree(old, ignore_errors=True)


def _looks_like_css(selector: str) -> bool:
    return (
        bool(re.match(r"^[#.\[]|^[a-z][a-z0-9-]*([#.\[:>\s]|$)", selector.strip())) and " " not in selector.strip()[:1]
    )


def register_web_playtest_tool(registry: Any, root: Path) -> None:
    registry.register(WebPlaytestTool(root))
