"""Thomas actually playtests a browser game.

This is a real perception→decision→action loop, not a scripted mimic: each
turn Thomas SEES the game (a screenshot), DECIDES a move (a vision model
call), and PLAYS it (a real key/click into a real browser), then reports
back like a playtester — does it work, is it fun, what is broken.

The browser is Chrome driven over the DevTools Protocol, the same mechanism
``web_artifact_smoke`` already trusts on this machine (no Playwright
dependency). The model is whatever Code is configured to run; it must accept
vision input (the Codex Responses path converts ``image_url`` to
``input_image``). Honest limits: a screenshot→decide→act cycle is a few
seconds, so Thomas plays DELIBERATELY — excellent for turn-based, puzzle and
strategy games, and it plays a real-time game move-by-move rather than at
reflex speed. It says so in its report rather than pretending otherwise.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

import aiohttp

_CHROME_CANDIDATES = (
    "chrome",
    "google-chrome",
    "chromium",
    "msedge",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
)

# Chrome maps DOM key names to these; enough for games (arrows, WASD, space,
# enter). Anything outside the map still sends its literal text.
_KEY_INFO: dict[str, tuple[str, int]] = {
    "ArrowLeft": ("ArrowLeft", 37),
    "ArrowRight": ("ArrowRight", 39),
    "ArrowUp": ("ArrowUp", 38),
    "ArrowDown": ("ArrowDown", 40),
    " ": ("Space", 32),
    "Space": ("Space", 32),
    "Enter": ("Enter", 13),
    "Escape": ("Escape", 27),
    "w": ("KeyW", 87),
    "a": ("KeyA", 65),
    "s": ("KeyS", 83),
    "d": ("KeyD", 68),
}


def chrome_executable() -> str | None:
    for candidate in _CHROME_CANDIDATES:
        resolved = shutil.which(candidate) if "\\" not in candidate else candidate
        if resolved and Path(resolved).is_file():
            return str(resolved)
    return None


def _kill_process_tree(proc: subprocess.Popen[bytes]) -> None:
    """Kill a process AND its children. A leaked Chrome tree per playtest piles
    up until it exhausts memory and takes the server with it."""
    import sys

    pid = proc.pid
    if sys.platform.startswith("win"):
        with contextlib.suppress(Exception):
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
                check=False,
            )
    else:
        with contextlib.suppress(Exception):
            proc.terminate()
    with contextlib.suppress(Exception):
        proc.wait(timeout=5)
    with contextlib.suppress(Exception):
        if proc.poll() is None:
            proc.kill()


class CdpError(RuntimeError):
    """The browser could not be driven — distinct from the game misbehaving."""


class CdpBrowser:
    """A minimal DevTools-Protocol client: launch, navigate, screenshot, input."""

    def __init__(self, executable: str, *, width: int = 900, height: int = 600) -> None:
        self._executable = executable
        self._width = width
        self._height = height
        self._proc: subprocess.Popen[bytes] | None = None
        self._profile: tempfile.TemporaryDirectory[str] | None = None
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._msg_id = 0

    async def __aenter__(self) -> CdpBrowser:
        await self._launch()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    async def _launch(self) -> None:
        self._profile = tempfile.TemporaryDirectory(prefix="thomas_playtest_")
        args = [
            self._executable,
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            "--remote-debugging-port=0",
            # Modern headless Chrome refuses the DevTools websocket without an
            # allowed origin; the endpoint is loopback-only, so * is scoped here.
            "--remote-allow-origins=*",
            f"--user-data-dir={self._profile.name}",
            f"--window-size={self._width},{self._height}",
            "about:blank",
        ]
        self._proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        port = await self._read_devtools_port()
        self._session = aiohttp.ClientSession()
        # Attach to the page target Chrome already opened rather than minting a
        # new one (`/json/new` needs PUT + an allow-list on current Chrome).
        page_ws = await self._first_page_ws(port)
        self._ws = await self._session.ws_connect(page_ws, max_msg_size=64 * 1024 * 1024)
        await self._command("Page.enable")
        await self._command("Runtime.enable")

    async def _read_devtools_port(self) -> int:
        assert self._profile is not None
        port_file = Path(self._profile.name) / "DevToolsActivePort"
        deadline = time.time() + 15
        while time.time() < deadline:
            if port_file.is_file():
                lines = port_file.read_text(encoding="utf-8").splitlines()
                if lines and lines[0].strip().isdigit():
                    return int(lines[0].strip())
            if self._proc and self._proc.poll() is not None:
                raise CdpError("Chrome exited before it was ready to drive")
            await asyncio.sleep(0.1)
        raise CdpError("Chrome did not open a DevTools port in time")

    async def _first_page_ws(self, port: int) -> str:
        assert self._session is not None
        deadline = time.time() + 10
        while time.time() < deadline:
            with contextlib.suppress(aiohttp.ClientError, json.JSONDecodeError):
                async with self._session.get(f"http://127.0.0.1:{port}/json") as resp:
                    targets = await resp.json(content_type=None)
                for target in targets if isinstance(targets, list) else []:
                    if target.get("type") == "page" and target.get("webSocketDebuggerUrl"):
                        return str(target["webSocketDebuggerUrl"])
            await asyncio.sleep(0.15)
        raise CdpError("Chrome exposed no page target to drive")

    async def _command(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if self._ws is None:
            raise CdpError("browser is not connected")
        self._msg_id += 1
        msg_id = self._msg_id
        await self._ws.send_json({"id": msg_id, "method": method, "params": params or {}})
        # CDP interleaves events and command replies on one socket; read until ours.
        deadline = time.time() + 30
        while time.time() < deadline:
            msg = await self._ws.receive(timeout=30)
            if msg.type != aiohttp.WSMsgType.TEXT:
                raise CdpError(f"browser link closed during {method}")
            payload = json.loads(msg.data)
            if payload.get("id") == msg_id:
                if "error" in payload:
                    raise CdpError(f"{method}: {payload['error'].get('message')}")
                return payload.get("result", {})
        raise CdpError(f"{method} timed out")

    async def navigate(self, url: str) -> None:
        await self._command("Page.navigate", {"url": url})
        await asyncio.sleep(1.4)  # let first paint and scripts settle

    async def screenshot_b64(self) -> str:
        result = await self._command("Page.captureScreenshot", {"format": "png"})
        return str(result.get("data") or "")

    async def press_key(self, key: str) -> None:
        code, keycode = _KEY_INFO.get(key, ("", 0))
        base = {"key": key, "code": code or key, "windowsVirtualKeyCode": keycode, "nativeVirtualKeyCode": keycode}
        if len(key) == 1 and key.isprintable() and key not in _KEY_INFO:
            base["text"] = key
        await self._command("Input.dispatchKeyEvent", {"type": "keyDown", **base})
        await asyncio.sleep(0.05)
        await self._command("Input.dispatchKeyEvent", {"type": "keyUp", **base})

    async def click(self, x: float, y: float) -> None:
        for kind in ("mousePressed", "mouseReleased"):
            await self._command(
                "Input.dispatchMouseEvent",
                {"type": kind, "x": x, "y": y, "button": "left", "clickCount": 1},
            )
            await asyncio.sleep(0.03)

    async def smart_click(self, *, target: str, x: float, y: float, width: float, height: float) -> str:
        """Click a labelled control the way a person does, not a guessed pixel.

        A downscaled screenshot (detail:low, the speed win) blurs exact button
        coordinates, so a raw x,y often misses. When the game exposes real DOM
        buttons — the common case for start/restart/menu — click the one whose
        text matches what Thomas meant, or the most prominent one. Fall back to
        the raw pixel for canvas-drawn buttons so it still works for any game.
        Returns a short label of what was clicked (for the caption)."""
        expr = (
            "(() => {"
            "  const want = " + json.dumps((target or "").lower()) + ";"
            "  const els = [...document.querySelectorAll('button,[role=\"button\"],a,input[type=\"button\"],input[type=\"submit\"]')]"
            "    .filter(el => { const r = el.getBoundingClientRect(); return r.width > 8 && r.height > 8 && el.offsetParent !== null; });"
            "  if (!els.length) return null;"
            "  const score = el => {"
            "    const t = (el.textContent || el.value || '').trim().toLowerCase();"
            "    let s = 0;"
            "    if (want && t && (t.includes(want) || want.includes(t))) s += 100;"
            "    if (/\\b(start|run|play|begin|again|retry|restart|new game|go|continue|ok|yes)\\b/.test(t)) s += 20;"
            "    const r = el.getBoundingClientRect(); s += Math.min(20, (r.width * r.height) / 4000);"
            "    return s;"
            "  };"
            "  const best = els.map(el => ({ el, s: score(el) })).sort((a, b) => b.s - a.s)[0];"
            "  if (best.s <= 0) return null;"
            "  const r = best.el.getBoundingClientRect();"
            "  return { x: r.x + r.width / 2, y: r.y + r.height / 2, label: (best.el.textContent || best.el.value || 'button').trim().slice(0, 24) };"
            "})()"
        )
        found = await self.eval_js(expr)
        if isinstance(found, dict) and "x" in found:
            await self.click(float(found["x"]), float(found["y"]))
            return str(found.get("label") or "button")
        # Canvas / no DOM button: the model's pixel is the best we have. It was
        # given in the screenshot's own space, which matches the viewport.
        await self.click(x, y)
        return ""

    async def eval_js(self, expression: str) -> Any:
        result = await self._command(
            "Runtime.evaluate", {"expression": expression, "returnByValue": True}
        )
        return (result.get("result") or {}).get("value")

    async def close(self) -> None:
        with contextlib.suppress(Exception):
            if self._ws is not None:
                await self._ws.close()
        with contextlib.suppress(Exception):
            if self._session is not None:
                await self._session.close()
        if self._proc is not None:
            # Headless Chrome spawns renderer/gpu child processes; terminating
            # only the parent leaks them, and enough leaked Chromes crashed the
            # server (7 orphans measured, 2026-08-10). Kill the whole tree.
            _kill_process_tree(self._proc)
        if self._profile is not None:
            with contextlib.suppress(Exception):
                self._profile.cleanup()


@dataclass
class PlaytestEvent:
    kind: str  # "observation" | "action" | "note" | "report" | "error"
    text: str = ""
    data: dict[str, Any] = field(default_factory=dict)


PlaytestSink = Callable[[PlaytestEvent], Awaitable[None]]


_MOVE_SYSTEM = (
    "You are Thomas, playtesting a browser game to see if it actually works and "
    "is any fun. Each turn you get a screenshot of the live game. Decide ONE "
    "action to play well and be fast and decisive. Reply STRICT JSON only: "
    '{"see": "<=12 words on the current screen>", '
    '"action": {"type": "key|click|wait", "key": "ArrowLeft|ArrowRight|ArrowUp|ArrowDown|Space|Enter|w|a|s|d", '
    '"target": "<button text if clicking, e.g. START RUN>", "x": <int>, "y": <int>}, '
    '"note": "<a bug or how it feels, empty if nothing>"}. '
    "Use key for gameplay (arrows/WASD/Space). To press a menu button use click "
    "with its label in target AND its pixel in x,y. wait only mid-animation."
)

_REPORT_SYSTEM = (
    "You just playtested this in a real browser for several moves. Write an "
    "honest, short report as strict JSON: "
    '{"works": true|false, "verdict": "<one line: does it work / play?>", '
    '"fun": "<one line: is it any good, honestly>", '
    '"difficulty": "<too easy|about right|too hard|n/a>", '
    '"bugs": ["<each real problem you hit, empty list if none>"], '
    '"summary": "<2-3 sentences a developer can act on>", '
    '"recommendations": [{"label": "<=4 words, an action button, e.g. Make it more forgiving>", '
    '"prompt": "<the exact instruction to carry out that fix, one sentence>"}]}. '
    "Give 1-3 recommendations, best first — concrete changes that would most "
    "improve it based on what you saw. If it is already good, recommend a small "
    "polish. Judge only what you actually observed. If it never started, say so."
)


def _extract_json(text: str) -> dict[str, Any]:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return {}
    with contextlib.suppress(json.JSONDecodeError):
        return json.loads(text[start : end + 1])
    return {}


async def playtest_game(
    *,
    game_url: str,
    llm: Any,
    game_title: str,
    on_event: PlaytestSink,
    max_moves: int = 10,
    width: int = 900,
    height: int = 600,
) -> dict[str, Any]:
    """Play ``game_url`` for up to ``max_moves`` and return a playtest report.

    ``llm`` is any object with an async ``chat(messages)`` returning
    ``{"text": ...}`` and accepting vision ``image_url`` parts.
    """
    executable = chrome_executable()
    if executable is None:
        await on_event(PlaytestEvent("error", "No Chrome or Edge is installed, so Thomas cannot open the game to play it."))
        return {"works": False, "summary": "No browser available to play the game."}

    transcript: list[dict[str, Any]] = []
    await on_event(PlaytestEvent("note", f"Opening {game_title} to play it…"))
    try:
        async with CdpBrowser(executable, width=width, height=height) as browser:
            await browser.navigate(game_url)
            opening = await browser.screenshot_b64()
            if opening:
                await on_event(PlaytestEvent("frame", "Looking at the game…", {"image": opening}))
            for move in range(1, max_moves + 1):
                shot = await browser.screenshot_b64()
                if not shot:
                    await on_event(PlaytestEvent("error", "The game did not render, so there was nothing to play."))
                    break
                await on_event(PlaytestEvent("frame", "Thinking about the next move…", {"image": shot}))
                messages = [
                    {"role": "system", "content": _MOVE_SYSTEM},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": f"Game: {game_title}. The screen is {width}x{height} pixels. Move {move} of {max_moves}. What do you see, and what is your move?"},
                            # detail:low downscales to ~512px server-side — a big
                            # latency win; button precision is recovered by the
                            # DOM-aware smart_click below.
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{shot}", "detail": "low"}},
                        ],
                    },
                ]
                # The game keeps animating while Thomas thinks: pump live frames
                # during the ~3s decision so the viewer never sees a frozen
                # screen (a perceived-speed win on top of the real latency cut).
                async def _pump_during_think() -> None:
                    with contextlib.suppress(Exception):
                        while True:
                            await asyncio.sleep(0.22)
                            live = await browser.screenshot_b64()
                            if live:
                                await on_event(PlaytestEvent("frame", "Thinking…", {"image": live}))

                pump = asyncio.ensure_future(_pump_during_think())
                try:
                    reply = await llm.chat(messages)
                finally:
                    pump.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await pump
                decision = _extract_json(str(reply.get("text") or ""))
                see = str(decision.get("see") or "").strip()
                action = decision.get("action") if isinstance(decision.get("action"), dict) else {}
                note = str(decision.get("note") or "").strip()
                if see:
                    await on_event(PlaytestEvent("observation", see, {"move": move}))
                transcript.append({"move": move, "see": see, "action": action, "note": note})

                act_type = str(action.get("type") or "wait").lower()
                if act_type == "key":
                    key = str(action.get("key") or "").strip() or "ArrowRight"
                    caption = f"Pressed {key}"
                    await on_event(PlaytestEvent("action", caption, {"type": "key", "key": key}))
                    await browser.press_key(key)
                elif act_type == "click":
                    x = float(action.get("x") or width / 2)
                    y = float(action.get("y") or height / 2)
                    target = str(action.get("target") or "").strip()
                    label = await browser.smart_click(target=target, x=x, y=y, width=width, height=height)
                    caption = f"Clicked {label}" if label else "Clicked"
                    await on_event(PlaytestEvent("action", caption, {"type": "click", "x": x, "y": y}))
                else:
                    caption = "Watching the screen"
                    await on_event(PlaytestEvent("action", caption, {"type": "wait"}))
                if note:
                    await on_event(PlaytestEvent("note", note, {"move": move}))
                # Stream the game AS IT REACTS: a short burst of real frames so
                # the viewer WATCHES Thomas play rather than reading about it.
                for _ in range(6):
                    frame = await browser.screenshot_b64()
                    if frame:
                        await on_event(PlaytestEvent("frame", caption, {"image": frame, "see": see}))
                    await asyncio.sleep(0.16)

            final_shot = await browser.screenshot_b64()
    except CdpError as exc:
        await on_event(PlaytestEvent("error", f"Thomas could not drive the game: {exc}"))
        return {"works": False, "summary": f"Could not play the game: {exc}"}

    # The report, grounded in what actually happened.
    report_messages = [
        {"role": "system", "content": _REPORT_SYSTEM},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": f"Game: {game_title}. Here is your move-by-move log:\n{json.dumps(transcript, ensure_ascii=False)[:4000]}\nAnd the final screen is attached. Write the report."},
                *([{"type": "image_url", "image_url": {"url": f"data:image/png;base64,{final_shot}"}}] if final_shot else []),
            ],
        },
    ]
    report_reply = await llm.chat(report_messages)
    report = _extract_json(str(report_reply.get("text") or ""))
    if not report:
        report = {"works": True, "summary": "Thomas played the game but could not summarize the run."}
    await on_event(PlaytestEvent("report", report.get("summary", ""), report))
    return report
