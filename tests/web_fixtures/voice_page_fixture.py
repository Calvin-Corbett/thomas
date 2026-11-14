"""The real chat page in Chromium with a fake microphone and a stand-in for the voice routes.

``open_voice_page`` serves the fixture Thomas from ``thomas_chat_fixture`` with the ``/api/voice`` routes added (or
answering 404, the way a server with the plugin off does), stands in for Voice Studio's live listening on the
``/api/voice/live`` websocket (half a second of microphone sound in, then the words of one pause back), opens the page on its own so it is either Chat or Code, and
swaps the two things a headless browser cannot do for recorders: the browser's voice and the playing of a sound.
Everything the page says aloud, plays, records and sends is read back from ``window`` afterwards.
"""

from __future__ import annotations

import json
import struct
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from tests.web_fixtures import thomas_chat_fixture as base

REAL_HANDLER = base._handler

MIC_FLAGS = [
    "--use-fake-device-for-media-stream",
    "--use-fake-ui-for-media-stream",
    "--autoplay-policy=no-user-gesture-required",
]
SMALL = {"profile": "local", "id": "fixture-mini", "label": "Fixture mini"}
MODELS = {
    "profiles": [
        {
            "name": "local",
            "provider": "local",
            "has_api_key": True,
            "models": [{"id": "fixture-1", "label": "Fixture model"}, {"id": "fixture-mini", "label": "Fixture mini"}],
        }
    ],
    "preferences": {"active_profile": "local"},
    "default": "local",
}
WAV = (
    b"RIFF"
    + struct.pack("<I", 36)
    + b"WAVEfmt "
    + struct.pack("<IHHIIHH", 16, 1, 1, 8000, 16000, 2, 16)
    + b"data\0\0\0\0"
)
# Replaces what a headless browser cannot do. Read back through window.__voice.
INIT = """
window.__voice = { spoken: [], played: [], chat: [], code: [], paused: 0 };
const realFetch = window.fetch.bind(window);
window.fetch = function (url, init) {
  try {
    const body = init && typeof init.body === 'string' ? JSON.parse(init.body) : null;
    if (body && String(url).startsWith('/api/v2/chat') && init.method === 'POST') window.__voice.chat.push(body);
    if (body && String(url).startsWith('/api/evolve/agent/send')) window.__voice.code.push(body);
    if (body && String(url).startsWith('/api/voice/speak')) {
      const thread = document.getElementById('tc-thread');
      window.__voice.speakWhileWriting = window.__voice.speakWhileWriting || [];
      window.__voice.speakWhileWriting.push(!(thread && thread.innerText.includes('piece 19')));
    }
  } catch (e) { /* not JSON */ }
  return realFetch(url, init);
};
Object.defineProperty(window, 'speechSynthesis', { configurable: true, value: {
  speak(u) { window.__voice.spoken.push({ text: u.text, voice: u.voice && u.voice.name }); setTimeout(() => u.onend && u.onend(), 20); },
  cancel() {}, getVoices() { return [{ name: 'Test Voice A' }, { name: 'Test Voice B' }]; },
} });
window.SpeechSynthesisUtterance = function (text) { this.text = text; };
HTMLMediaElement.prototype.pause = function () { window.__voice.paused += 1; };
HTMLMediaElement.prototype.play = function () {
  const el = this;
  window.__voice.played.push(String(el.src).slice(0, 5));
  if (!window.__voice.hold) setTimeout(() => el.dispatchEvent(new Event('ended')), 20);
  return Promise.resolve();
};
"""
# The browser's own hearing: it hears one sentence a moment after it starts (live talk), or when it is stopped
# (the microphone's dictation), whichever comes first, and never twice.
HEARD = """
window.SpeechRecognition = function () {
  const self = this;
  function hear() {
    if (self.said) return;
    self.said = true;
    const e = { resultIndex: 0, results: [Object.assign([{ transcript: 'what the browser heard' }], { isFinal: true })] };
    if (self.onresult) self.onresult(e);
  }
  this.start = function () { self.running = true; setTimeout(hear, 300); };
  this.stop = function () { hear(); setTimeout(() => self.onend && self.onend(), 10); };
  this.abort = function () { self.said = true; };
};
"""
NO_EARS = "delete window.webkitSpeechRecognition; window.SpeechRecognition = undefined;"


@dataclass
class Voice:
    """What the stand-in voice routes answer, and what they were asked."""

    row_on: bool = True
    studio_running: bool = True
    transcript: str = "what time is it"
    live_model: str | None = "sherpa-fixture"
    live_why: str = ""
    utterances: list[str] = field(default_factory=lambda: ["what time is it"])
    frames: int = 0
    sockets: list[Any] = field(default_factory=list)
    fast_model: dict[str, str] | None = field(default_factory=lambda: dict(SMALL))
    settings: dict[str, str] = field(
        default_factory=lambda: {"engine": "auto", "voice": "default", "fast_model": "auto", "studio_url": "x"}
    )
    asked: list[tuple[str, str]] = field(default_factory=list)
    heard: list[int] = field(default_factory=list)
    said: list[dict[str, Any]] = field(default_factory=list)
    saved: list[dict[str, Any]] = field(default_factory=list)
    # Thomas's own ears: True when his listening model still has to be set up. Set up now goes through ``setup_steps``
    # (one per look at its progress), then stops with ``setup_fails`` or, when that is '', is done.
    needs_setup: bool = False
    setup_started: int = 0
    setup_steps: list[dict[str, Any]] = field(
        default_factory=lambda: [{"state": "working", "step": "model", "done": 335_000_000, "total": 670_000_000}]
    )
    setup_fails: str = ""
    progress: dict[str, Any] = field(
        default_factory=lambda: {"state": "idle", "done": 0, "total": 670_000_000, "step": "", "error": ""}
    )

    def setup(self) -> dict[str, Any] | None:
        """What GET /api/voice/setup and the status say: None once Thomas can listen by himself."""
        if not self.needs_setup:
            return None
        return {
            "model": "parakeet-fixture",
            "name": "Parakeet Fixture",
            "about": "Writes down what you say.",
            "licence": "CC-BY-4.0",
            "credit": "Fixture credit",
            "bytes": 670_000_000,
            "engine": True,
            "progress": dict(self.progress),
        }

    def advance(self) -> None:
        """One look at a set-up that has started moves it on a step."""
        if not self.setup_started or not self.needs_setup:
            return
        if self.setup_steps:
            self.progress.update(self.setup_steps.pop(0))
        elif self.setup_fails:
            self.progress.update(state="failed", error=self.setup_fails)
        else:
            self.needs_setup = False

    def status(self) -> dict[str, Any]:
        who = "voicestudio" if self.studio_running and self.settings["engine"] != "browser" else "browser"
        return {
            "ok": True,
            "settings": self.settings,
            "studio": {"running": self.studio_running, "url": "x"},
            "speaker": who,
            "listener": who,
            "fast_model": self.fast_model,
            "setup": self.setup(),
            "live": {
                "model": self.live_model
                if (who == "voicestudio" or self.setup_started) and not self.needs_setup
                else None,
                "why": self.live_why,
                "by": "thomas" if self.setup_started and not self.needs_setup else "",
            },
        }

    def hear(self, text: str, *, final: bool = True) -> None:
        """Voice Studio's live listening sends what it heard to the page that is listening now."""
        self.sockets[-1].send(
            json.dumps({"type": "final" if final else "partial", "text": text, "final_kind": "utterance"})
        )

    def live(self, socket: Any) -> None:
        """The /api/voice/live websocket: started, then each utterance after half a second (5 frames) of sound."""
        self.sockets.append(socket)
        waiting = list(self.utterances)
        if not self.row_on:
            socket.close(code=1008)
            return
        if not self.live_model:
            socket.send(json.dumps({"type": "error", "kind": "no_live_model", "message": self.live_why}))
            socket.close()
            return
        socket.send(json.dumps({"type": "live.started", "model": self.live_model}))

        def got(message: Any) -> None:
            if isinstance(message, (bytes, bytearray)):
                self.frames += 1
                if waiting and self.frames % 5 == 0:
                    text = waiting.pop(0)
                    socket.send(json.dumps({"type": "partial", "text": text.split(" ")[0]}))
                    socket.send(json.dumps({"type": "final", "text": text, "final_kind": "utterance"}))

        # Playwright 1.62 raises inside its own listener when the page closes a routed websocket (KeyError 'code'), so
        # no close handler is set; the tests read the page's own socket instead.
        socket.on_message(got)


def _handler(fixture: base.ThomasFixture, voice: Voice):
    parent = REAL_HANDLER(fixture)

    class Handler(parent):  # type: ignore[valid-type, misc]
        def _voice(self, method: str) -> bool:
            path = self.path.split("?", 1)[0]
            if not path.startswith("/api/voice/"):
                return False
            voice.asked.append((method, self.path))
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            if not voice.row_on:
                self._send(404, b"404: Not Found", "text/plain; charset=utf-8")
            elif (method, path) == ("GET", "/api/voice/status"):
                self._json(voice.status())
            elif (method, path) == ("GET", "/api/voice/setup"):
                voice.advance()
                self._json({"ok": True, "setup": voice.setup()})
            elif (method, path) == ("POST", "/api/voice/setup"):
                assert json.loads(body)["model"] == "parakeet-fixture", body
                voice.setup_started += 1
                voice.progress.update(state="working", step="starting")
                self._json({"ok": True, "setup": voice.setup()})
            elif (method, path) == ("GET", "/api/voice/voices"):
                self._json({"ok": True, "voices": [{"id": "alloy", "name": "Alloy"}, {"id": "p1", "name": "Mine"}]})
            elif (method, path) == ("PUT", "/api/voice/settings"):
                voice.saved.append(json.loads(body))
                voice.settings.update(voice.saved[-1])
                self._json({"ok": True, "settings": voice.settings})
            elif (method, path) == ("POST", "/api/voice/transcribe"):
                voice.heard.append(len(body))
                self._json({"ok": True, "text": voice.transcript})
            elif (method, path) == ("POST", "/api/voice/speak"):
                voice.said.append(json.loads(body))
                self._send(200, WAV, "audio/wav")
            else:
                self._send(404, b"404: Not Found", "text/plain; charset=utf-8")
            return True

        def do_GET(self) -> None:  # noqa: N802
            if not self._voice("GET"):
                super().do_GET()

        def do_POST(self) -> None:  # noqa: N802
            if not self._voice("POST"):
                super().do_POST()

        def do_PUT(self) -> None:  # noqa: N802
            if not self._voice("PUT"):
                self._send(404, b"", "text/plain")

    return Handler


CODE_REPLY = "Here is the answer from Code."
EVENT_END = "\n\n"


def answer_code_runs(page: Any, reply: str = CODE_REPLY) -> None:
    """Make Code finish any task at once, with a saved turn that holds ``reply``, the way a real finished run does."""

    def answer(route: Any, body: dict[str, Any]) -> None:
        route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

    turns = [
        {"role": "user", "text": "asked"},
        {"role": "agent", "run_id": "r1", "ok": True, "transcript": json.dumps({"fc": "final", "text": reply})},
    ]
    done = {"type": "done", "run_id": "r1", "ok": True, "persistence_confirmed": True, "text": reply}
    page.route(
        "**/api/evolve/agent/send",
        lambda r: answer(r, {"ok": True, "run_id": "r1", "conversation_id": "c1", "project_root": "C:/project"}),
    )
    page.route(
        "**/api/evolve/agent/stream?run_id=r1*",
        lambda r: r.fulfill(status=200, content_type="text/event-stream", body="data: " + json.dumps(done) + EVENT_END),
    )
    page.route(
        "**/api/evolve/agent/conversations/c1",
        lambda r: answer(r, {"ok": True, "conversation": {"id": "c1", "title": "T", "turns": turns}}),
    )
    page.route("**/api/evolve/agent/conversations/c1/tree", lambda r: answer(r, {"ok": True, "entries": []}))
    page.route(
        "**/api/evolve/agent/conversations",
        lambda r: answer(r, {"conversations": [{"id": "c1", "title": "T", "turn_count": 2}]}),
    )


@dataclass
class VoicePage:
    page: Any
    fixture: base.ThomasFixture
    voice: Voice
    errors: list[str]

    def value(self, expression: str) -> Any:
        return self.page.evaluate(f"() => {expression}")

    def asked(self, prefix: str = "/api/voice/") -> list[tuple[str, str]]:
        return [row for row in self.voice.asked if row[1].startswith(prefix)]


@contextmanager
def open_voice_page(
    voice: Voice | None = None,
    *,
    mode: str = "chat",
    recognition: bool = False,
    no_ears: bool = False,
    wait_for_button: bool = True,
) -> Iterator[VoicePage]:
    """The chat page in ``mode`` ("chat" or "code") with a fake microphone."""
    from playwright.sync_api import sync_playwright

    voice = voice or Voice()
    base._handler = lambda fixture: _handler(fixture, voice)
    saved_models = base.STUBS["/api/models"]
    base.STUBS["/api/models"] = MODELS
    try:
        with base.serve() as fixture, sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=MIC_FLAGS)
            context = browser.new_context(viewport={"width": 1440, "height": 900}, permissions=["microphone"])
            page = context.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
            page.route("**/*", lambda r: r.continue_() if r.request.url.startswith(fixture.url) else r.abort())
            page.add_init_script(INIT + (HEARD if recognition else "") + (NO_EARS if no_ears else ""))
            page.route_web_socket("**/api/voice/live", voice.live)
            suffix = "&tab_mode=code" if mode == "code" else ""
            page.goto(fixture.url + "/?embed=1&browser=0" + suffix, wait_until="load")
            page.wait_for_selector("#tc-mic-btn", timeout=20000)
            if wait_for_button and voice.row_on:
                page.wait_for_selector("#tc-voice-btn", state="attached", timeout=10000)
            page.wait_for_timeout(500)
            try:
                yield VoicePage(page=page, fixture=fixture, voice=voice, errors=errors)
            finally:
                browser.close()
    finally:
        base._handler = REAL_HANDLER
        base.STUBS["/api/models"] = saved_models
